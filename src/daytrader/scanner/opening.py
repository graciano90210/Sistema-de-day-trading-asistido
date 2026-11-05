"""Primera vela de 5 minutos de la sesión regular (09:30–09:35 ET) para un universo amplio.

Insumo de "stocks in play" (ronda 2, H1): volumen relativo de la vela de apertura.
La vela 09:30 está disponible a las 09:35 (available_at = ts + 5 min).
Descarga reanudable por día, con varios días en paralelo (latencia del API domina).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, time, timedelta

import polars as pl

from daytrader.data.adjust import adjust_for_splits
from daytrader.data.alpaca_client import MultiFetcher
from daytrader.data.store import Store
from daytrader.market_calendar import et_to_utc_naive
from daytrader.scanner.universe import eligible_symbols, previous_sessions

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS opening_bars (
    symbol VARCHAR NOT NULL, session_date DATE NOT NULL,
    ts_utc TIMESTAMP NOT NULL, available_at TIMESTAMP NOT NULL,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, vwap DOUBLE,
    PRIMARY KEY (symbol, session_date)
);
CREATE TABLE IF NOT EXISTS opening_log (session_date DATE PRIMARY KEY, n_requested INTEGER, n_bars INTEGER);
"""


def broad_universe(
    store: Store, d: date, min_price=5.0, min_avg_volume=1_000_000, min_atr=0.5, lookback=14
) -> list[str]:
    """Acciones comunes con precio, volumen medio y ATR mínimos usando SOLO sesiones < d (ajustado por split)."""
    f = daily_features(store, d, lookback)
    f = f.filter((pl.col("c") >= min_price) & (pl.col("v") >= min_avg_volume) & (pl.col("atr") >= min_atr))
    return sorted(f["symbol"].to_list())


def daily_features(store: Store, d: date, lookback: int = 14) -> pl.DataFrame:
    """Por símbolo: último cierre (c), volumen medio (v) y ATR (media simple del TR) de las `lookback` sesiones < d."""
    prev = previous_sessions(d, lookback + 1)
    bars = store.query(
        "SELECT symbol, session_date, high, low, close, volume FROM bars_1d WHERE session_date BETWEEN ? AND ?",
        [prev[0], prev[-1]],
    )
    elig = set(eligible_symbols(store, ["NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"], True))
    bars = adjust_for_splits(bars.filter(pl.col("symbol").is_in(elig)), store.query("SELECT * FROM splits"), d,
                             price_cols=("high", "low", "close"))  # fmt: skip
    bars = bars.sort("symbol", "session_date").with_columns(pl.col("close").shift(1).over("symbol").alias("pc"))
    bars = bars.with_columns(
        pl.max_horizontal(
            pl.col("high") - pl.col("low"), (pl.col("high") - pl.col("pc")).abs(), (pl.col("low") - pl.col("pc")).abs()
        ).alias("tr")  # fmt: skip
    )
    f = bars.group_by("symbol").agg(
        pl.col("close").last().alias("c"), pl.col("session_date").last().alias("last"),
        pl.col("volume").tail(lookback).mean().alias("v"), pl.col("tr").tail(lookback).mean().alias("atr"),
    )  # fmt: skip
    return f.filter(pl.col("last") == prev[-1])


def select_stocks_in_play(
    store: Store, d: date, top_n: int = 20, min_rvol: float = 1.0, lookback: int = 14, min_history: int = 10,
    min_open: float = 5.0, min_avg_volume: float = 1_000_000, min_atr: float = 0.5,
) -> pl.DataFrame:  # fmt: skip
    """Regla del paper (Zarattini, Barbon y Aziz 2024, §4), decidida a las 09:35 ET de d.

    RVOL = volumen de la vela 09:30–09:35 de d / media de esa vela en las `lookback` sesiones previas
    (se exigen al menos `min_history` sesiones con dato). Filtros: apertura > $5, volumen medio 14 d >= 1M,
    ATR 14 d > $0,50, RVOL >= 1. Top N por RVOL; la dirección la da la vela (doji = sin orden, pero ocupa puesto).
    """
    prev = previous_sessions(d, lookback)
    ob = store.query(
        "SELECT symbol, session_date, open, high, low, close, volume FROM opening_bars WHERE session_date BETWEEN ? AND ?",
        [prev[0], d],
    )
    today = ob.filter(pl.col("session_date") == d)
    past = adjust_for_splits(ob.filter(pl.col("session_date") < d), store.query("SELECT * FROM splits"), d,
                             price_cols=(), volume_cols=("volume",))  # fmt: skip
    hist = past.group_by("symbol").agg(pl.col("volume").mean().alias("orv_avg"), pl.len().alias("n_hist"))
    feats = daily_features(store, d, lookback).select("symbol", pl.col("c").alias("prev_close"),
                                                      pl.col("v").alias("avg_volume"), pl.col("atr").alias("atr14"))  # fmt: skip
    df = (
        today.join(hist, on="symbol", how="inner")
        .join(feats, on="symbol", how="inner")
        .filter(
            (pl.col("n_hist") >= min_history)
            & (pl.col("orv_avg") > 0)
            & (pl.col("open") > min_open)
            & (pl.col("avg_volume") >= min_avg_volume)
            & (pl.col("atr14") > min_atr)
        )  # fmt: skip
        .with_columns((pl.col("volume") / pl.col("orv_avg")).alias("rvol"))
        .filter(pl.col("rvol") >= min_rvol)
        .sort("rvol", descending=True)
        .head(top_n)
        .with_row_index("rank", offset=1)
        .with_columns(
            pl.when(pl.col("close") > pl.col("open"))
            .then(1)
            .when(pl.col("close") < pl.col("open"))
            .then(-1)
            .otherwise(0)
            .alias("side")
        )  # fmt: skip
    )
    return df.select(
        pl.lit(d).alias("session_date"), pl.col("rank").cast(pl.Int32), "symbol", "rvol", pl.col("side").cast(pl.Int32),
        pl.col("open").alias("or_open"), pl.col("high").alias("or_high"), pl.col("low").alias("or_low"),
        pl.col("close").alias("or_close"), "atr14", "avg_volume", "prev_close",
    )  # fmt: skip


def _fetch_day(fetch_many: MultiFetcher, d: date, symbols: list[str], batch: int = 1000) -> pl.DataFrame:
    t0 = et_to_utc_naive(d, time(9, 30))
    out = []
    for i in range(0, len(symbols), batch):
        raw = fetch_many(symbols[i : i + batch], "5m", t0, t0)  # Alpaca incluye la barra que empieza en `end`
        out.append(raw.filter(pl.col("ts_utc") == t0))
    df = pl.concat(out) if out else pl.DataFrame()
    if df.is_empty():
        return df
    return df.with_columns(
        pl.lit(d).alias("session_date"), (pl.col("ts_utc") + timedelta(minutes=5)).alias("available_at")
    )


def ensure_opening_bars(
    store: Store,
    fetch_factory: Callable[[], MultiFetcher],
    days: list[date],
    workers: int = 4,
    on_day: Callable[[date, int], None] | None = None,
) -> None:
    store.con.execute(DDL)
    done = set(store.query("SELECT session_date FROM opening_log")["session_date"].to_list())
    todo = [(d, broad_universe(store, d)) for d in days if d not in done]
    fetchers = [fetch_factory() for _ in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_day, fetchers[k % workers], d, syms): (d, syms) for k, (d, syms) in enumerate(todo)}
        for fut in as_completed(futs):
            d, syms = futs[fut]
            try:
                df = fut.result()
            except Exception as exc:  # se reintenta en la próxima ejecución
                log.error("Apertura %s falló: %s", d, exc)
                continue
            cols = [
                "symbol",
                "session_date",
                "ts_utc",
                "available_at",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "vwap",
            ]
            if not df.is_empty():
                store.upsert("opening_bars", df.select(cols))
            store.upsert(
                "opening_log", pl.DataFrame({"session_date": [d], "n_requested": [len(syms)], "n_bars": [df.height]})
            )
            if on_day:
                on_day(d, df.height)
