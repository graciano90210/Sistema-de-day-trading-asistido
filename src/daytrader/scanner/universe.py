"""Etapa 1: universo líquido de acciones comunes, calculado con sesiones ANTERIORES a D."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

import polars as pl

from daytrader.data.access import get_bars
from daytrader.data.adjust import adjust_for_splits
from daytrader.data.alpaca_client import MultiFetcher
from daytrader.data.ingest import prepare_bars
from daytrader.data.store import Store
from daytrader.market_calendar import et_to_utc_naive, sessions

log = logging.getLogger(__name__)

# Nombres que delatan productos que no son acciones comunes.
_EXCLUDE = re.compile(
    r"\b(ETF|ETN|ETP|Fund|Trust|Warrants?|Rights?|Units?|Preferred|Pfd|Notes?|Debentures?|Bonds?|"
    r"Index|Leveraged|Inverse|ProShares|Direxion|iShares|SPDR|Invesco|Vanguard|Acquisition|Partnership|"
    r"Depositary Shares? Representing)\b|%",
    re.IGNORECASE,
)


def is_common_stock(name: str) -> bool:
    return bool(name) and not _EXCLUDE.search(name)


def refresh_assets(store: Store, assets: pl.DataFrame) -> int:
    df = assets.with_columns(
        pl.col("name").map_elements(is_common_stock, return_dtype=pl.Boolean).alias("is_common"),
        pl.lit(datetime.now()).alias("fetched_at"),
    )
    return store.upsert("assets", df)


def eligible_symbols(store: Store, exchanges: list[str], include_inactive: bool) -> list[str]:
    sql = f"SELECT symbol FROM assets WHERE is_common AND exchange IN ({','.join('?' * len(exchanges))})"
    if not include_inactive:
        sql += " AND status = 'active'"
    syms = store.query(sql, list(exchanges))["symbol"].to_list()
    return [s for s in syms if VALID_SYMBOL.match(s)]  # descarta CUSIPs y códigos raros que Alpaca rechaza


VALID_SYMBOL = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")


def ingest_universe_daily(
    store: Store,
    fetch_many: MultiFetcher,
    symbols: list[str],
    start: date,
    end: date,
    feed: str,
    batch_size: int = 200,
    on_batch: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    """Barras diarias [start, end) para muchos símbolos, INCREMENTAL: cada símbolo descarga solo desde
    el final de lo que ya tiene (ingest_log '1d' ok) hasta `end`. La primera vez, el rango completo."""
    have = store.query(
        "SELECT symbol, max(chunk_end) AS until FROM ingest_log WHERE timeframe = '1d' AND status = 'ok' "
        "AND chunk_start <= ? GROUP BY 1",
        [start],
    )
    covered: dict[str, date] = dict(have.iter_rows())
    # Agrupar por fecha de inicio de descarga (casi todos comparten la misma: el último día ya cubierto)
    groups: dict[date, list[str]] = {}
    for s in symbols:
        frm = max(start, covered.get(s, start))
        if frm < end:
            groups.setdefault(frm, []).append(s)
    total = sum(len(v) for v in groups.values())
    rows = errors = done = 0
    for frm, syms in sorted(groups.items()):
        for i in range(0, len(syms), batch_size):
            batch = syms[i : i + batch_size]
            try:
                raw = fetch_many(batch, "1d", et_to_utc_naive(frm, time(0)), et_to_utc_naive(end, time(0)))
                df = prepare_bars(raw, "1d", feed).filter(
                    pl.col("session_date").is_between(frm, end - timedelta(days=1))
                )
                rows += store.upsert_bars(df, "1d")
                counts = dict(df.group_by("symbol").len().iter_rows())
                for s in batch:
                    store.log_chunk(s, "1d", frm, end, counts.get(s, 0), "ok")
            except Exception as exc:
                log.error("Lote %s/%d falló: %s", frm, i, exc)
                errors += 1
                for s in batch:
                    store.log_chunk(s, "1d", frm, end, 0, "error", str(exc)[:300])
            done += len(batch)
            if on_batch:
                on_batch(done, total)
    return rows, errors


def previous_sessions(d: date, n: int) -> list[date]:
    """Las n sesiones NYSE estrictamente anteriores a d (orden ascendente)."""
    s = sessions(d - timedelta(days=int(n * 1.6) + 15), d - timedelta(days=1))["session_date"].to_list()
    return s[-n:]


def stage1(store: Store, d: date, cfg: dict, as_of: datetime) -> tuple[pl.DataFrame, list[tuple[str, int]]]:
    """Features diarias por símbolo usando solo barras con available_at <= as_of y sesiones < d.

    Devuelve (universo filtrado, embudo [(paso, n)]).
    """
    lookback = int(cfg["lookback_sessions"])
    prev = previous_sessions(d, max(lookback, 14) + 1)
    bars = get_bars(store, None, as_of, start=et_to_utc_naive(prev[0], time(0)), timeframe="1d")
    bars = bars.filter(pl.col("session_date") < d)  # redundante con available_at; explícito
    eligible = eligible_symbols(store, cfg["exchanges"], cfg["include_inactive"])
    bars = bars.filter(pl.col("symbol").is_in(eligible))
    bars = adjust_for_splits(bars, store.query("SELECT * FROM splits"), d)

    bars = bars.sort("symbol", "session_date").with_columns(pl.col("close").shift(1).over("symbol").alias("prev_c"))
    bars = bars.with_columns(
        pl.max_horizontal(
            pl.col("high") - pl.col("low"),
            (pl.col("high") - pl.col("prev_c")).abs(),
            (pl.col("low") - pl.col("prev_c")).abs(),
        ).alias("tr")
    )
    feats = (
        bars.group_by("symbol")
        .agg(
            pl.col("close").last().alias("prev_close"),
            pl.col("session_date").last().alias("prev_date"),
            pl.len().alias("n_sessions"),
            pl.col("tr").tail(14).mean().alias("atr14"),
            (pl.col("close") * pl.col("volume")).tail(lookback).mean().alias("adv_usd"),
            pl.col("volume").tail(lookback).mean().alias("avg_volume"),
        )
        .with_columns((pl.col("atr14") / pl.col("prev_close")).alias("atr_pct"))
    )

    funnel = [("acciones comunes con barras diarias", feats.height)]
    steps = [
        ("cotizó la sesión anterior", pl.col("prev_date") == prev[-1]),
        ("historia suficiente", pl.col("n_sessions") >= int(cfg["min_history"])),
        ("precio en rango", pl.col("prev_close").is_between(cfg["min_price"], cfg["max_price"])),
        ("liquidez (ADV $)", pl.col("adv_usd") >= cfg["min_adv_usd"]),
        ("ATR mínimo", (pl.col("atr14") >= cfg["min_atr"]) & (pl.col("atr_pct") >= cfg["min_atr_pct"])),
    ]
    for name, cond in steps:
        feats = feats.filter(cond)
        funnel.append((name, feats.height))
    return feats.sort("adv_usd", descending=True), funnel
