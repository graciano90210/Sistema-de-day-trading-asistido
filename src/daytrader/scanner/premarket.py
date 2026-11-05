"""Resúmenes de pre-market point-in-time: solo barras de 1 min con available_at <= cutoff."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

import polars as pl

from daytrader.data.alpaca_client import MultiFetcher
from daytrader.data.store import Store
from daytrader.market_calendar import et_to_utc_naive

log = logging.getLogger(__name__)
ONE_MIN = timedelta(minutes=1)

SNAP_SCHEMA = {
    "symbol": pl.Utf8,
    "session_date": pl.Date,
    "cutoff_utc": pl.Datetime("us"),
    "last": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "volume": pl.Float64,
    "dollar_volume": pl.Float64,
    "n_bars": pl.Int64,
    "last_bar_ts": pl.Datetime("us"),
}


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def summarize_premarket(
    raw: pl.DataFrame,
    symbols: list[str],
    d: date,
    start_utc: datetime,
    cutoff_utc: datetime,
    bar_minutes: int = 1,
) -> pl.DataFrame:
    """Una fila por símbolo pedido (volumen 0 si no hubo operaciones).

    Una barra de `bar_minutes` que empieza en t está disponible en t + bar_minutes.
    """
    span = timedelta(minutes=bar_minutes)
    bars = raw.filter(
        (pl.col("ts_utc") >= start_utc) & ((pl.col("ts_utc") + span) <= cutoff_utc)  # available_at <= cutoff
    ).sort("symbol", "ts_utc")
    agg = bars.group_by("symbol").agg(
        pl.col("close").last().alias("last"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("volume").sum().alias("volume"),
        (pl.coalesce("vwap", "close") * pl.col("volume")).sum().alias("dollar_volume"),
        pl.len().cast(pl.Int64).alias("n_bars"),
        pl.col("ts_utc").last().alias("last_bar_ts"),
    )
    base = pl.DataFrame({"symbol": symbols}, schema={"symbol": pl.Utf8})
    out = base.join(agg, on="symbol", how="left").with_columns(
        pl.lit(d).alias("session_date"),
        pl.lit(cutoff_utc).cast(pl.Datetime("us")).alias("cutoff_utc"),
        pl.col("volume").fill_null(0.0),
        pl.col("dollar_volume").fill_null(0.0),
        pl.col("n_bars").fill_null(0),
    )
    return out.select(list(SNAP_SCHEMA)).cast(SNAP_SCHEMA)


def ensure_snapshots(
    store: Store,
    fetch_many: MultiFetcher,
    symbols: list[str],
    dates: list[date],
    start_et: time,
    cutoff_et: time,
    batch_size: int = 1000,  # la latencia por request domina: lotes grandes rinden ~4× más
    bar_minutes: int = 5,
) -> int:
    """Descarga y resume el pre-market de (símbolo, fecha) que aún no estén en caché.

    Usa barras de `bar_minutes` (5 por defecto: 5× menos datos que 1 min y mismo resultado si el
    cutoff y el inicio están alineados a múltiplos de 5 minutos).
    """
    if (start_et.minute % bar_minutes) or (cutoff_et.minute % bar_minutes):
        raise ValueError(f"inicio y cutoff deben estar alineados a {bar_minutes} min")
    tf = {1: "1m", 5: "5m"}[bar_minutes]
    span = timedelta(minutes=bar_minutes)
    fetched = 0
    for d in dates:
        start_utc, cutoff_utc = et_to_utc_naive(d, start_et), et_to_utc_naive(d, cutoff_et)
        have = set(
            store.query("SELECT symbol FROM premarket_snap WHERE session_date = ? AND cutoff_utc = ?", [d, cutoff_utc])[
                "symbol"
            ].to_list()
        )
        missing = [s for s in symbols if s not in have]
        for i in range(0, len(missing), batch_size):
            batch = missing[i : i + batch_size]
            # Alpaca incluye la barra que EMPIEZA en `end`: pedimos hasta la última con available_at <= cutoff.
            raw = fetch_many(batch, tf, start_utc, cutoff_utc - span)
            store.upsert("premarket_snap", summarize_premarket(raw, batch, d, start_utc, cutoff_utc, bar_minutes))
            fetched += len(batch)
    return fetched


def load_snapshots(store: Store, symbols: list[str], dates: list[date], cutoff_et: time) -> pl.DataFrame:
    if not symbols or not dates:
        return pl.DataFrame(schema=SNAP_SCHEMA)
    cutoffs = [et_to_utc_naive(d, cutoff_et) for d in dates]
    df = store.query(
        f"SELECT * FROM premarket_snap WHERE cutoff_utc IN ({','.join('?' * len(cutoffs))}) "
        f"AND symbol IN ({','.join('?' * len(symbols))})",
        [*cutoffs, *symbols],
    )
    return df
