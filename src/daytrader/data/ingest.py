"""Ingesta incremental y reanudable de barras a DuckDB.

Unidad de trabajo: (símbolo, timeframe, bloque [inicio, fin) en fechas ET).
Un bloque marcado 'ok' en ingest_log no se vuelve a descargar.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, time, timedelta

import polars as pl

from daytrader.data.alpaca_client import Fetcher
from daytrader.data.store import Store
from daytrader.market_calendar import ET_NAME, classify_sessions, et_date_expr, et_to_utc_naive

log = logging.getLogger(__name__)

ONE_MINUTE = timedelta(minutes=1)
DAILY_AVAILABLE_ET_HOUR = 20  # barra diaria visible a las 20:00 ET de su sesión


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Divide [start, end) en bloques por mes calendario."""
    chunks = []
    cur = start
    while cur < end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        chunks.append((cur, min(nxt, end)))
        cur = nxt
    return chunks


def prepare_bars(raw: pl.DataFrame, timeframe: str, feed: str) -> pl.DataFrame:
    """Añade available_at, session_date y session a barras crudas."""
    if timeframe == "1m":
        df = classify_sessions(raw).with_columns((pl.col("ts_utc") + ONE_MINUTE).alias("available_at"))
    elif timeframe == "1d":
        df = raw.with_columns(et_date_expr("ts_utc").alias("session_date"), pl.lit("day").alias("session"))
        df = df.with_columns(
            (pl.col("session_date").cast(pl.Datetime("us")) + pl.duration(hours=DAILY_AVAILABLE_ET_HOUR))
            .dt.replace_time_zone(ET_NAME, ambiguous="earliest")
            .dt.convert_time_zone("UTC")
            .dt.replace_time_zone(None)
            .alias("available_at")
        )
    else:
        raise ValueError(f"timeframe no soportado: {timeframe}")
    return df.with_columns(pl.lit(feed).alias("feed"))


@dataclass
class IngestSummary:
    chunks_done: int = 0
    chunks_skipped: int = 0
    rows: int = 0
    errors: list[tuple[str, date, str]] = field(default_factory=list)


def ingest(
    store: Store,
    fetch: Fetcher,
    symbols: list[str],
    start: date,
    end: date,
    timeframe: str,
    feed: str,
    on_chunk: Callable[[str, date, date, int], None] | None = None,
) -> IngestSummary:
    """Descarga [start, end) para cada símbolo. `end` es exclusivo (fecha ET)."""
    summary = IngestSummary()
    chunks = month_chunks(start, end) if timeframe == "1m" else [(start, end)]
    for symbol in symbols:
        done = store.completed_chunks(symbol, timeframe)
        for c_start, c_end in chunks:
            if (c_start, c_end) in done:
                summary.chunks_skipped += 1
                continue
            try:
                raw = fetch(symbol, timeframe, et_to_utc_naive(c_start, time(0)), et_to_utc_naive(c_end, time(0)))
                df = prepare_bars(raw, timeframe, feed)
                # Defensivo: solo filas dentro del bloque pedido.
                df = df.filter(pl.col("session_date").is_between(c_start, c_end - timedelta(days=1)))
                n = store.upsert_bars(df, timeframe)
                store.log_chunk(symbol, timeframe, c_start, c_end, n, "ok")
                summary.chunks_done += 1
                summary.rows += n
            except Exception as exc:
                log.error("Error %s %s %s: %s", symbol, timeframe, c_start, exc)
                store.log_chunk(symbol, timeframe, c_start, c_end, 0, "error", str(exc)[:500])
                summary.errors.append((symbol, c_start, str(exc)[:200]))
                n = 0
            if on_chunk:
                on_chunk(symbol, c_start, c_end, n)
    return summary
