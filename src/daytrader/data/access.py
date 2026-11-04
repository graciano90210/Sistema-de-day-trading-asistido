"""Acceso point-in-time a barras. ÚNICA vía permitida para que estrategias lean datos.

Garantía: nada devuelto aquí tiene `available_at > as_of`.
- 1m: barra con inicio 09:30 → disponible 09:31.
- Resample N min: el bucket solo existe cuando ha cerrado completo.
- 1d: la barra de la sesión D es visible desde D 20:00 ET.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from daytrader.data.store import TABLES, Store


def _as_list(symbols: str | list[str]) -> list[str]:
    return [symbols] if isinstance(symbols, str) else list(symbols)


def get_bars(
    store: Store,
    symbols: str | list[str],
    as_of: datetime,
    start: datetime | None = None,
    timeframe: str = "1m",
    sessions: tuple[str, ...] | None = None,
) -> pl.DataFrame:
    """Barras conocibles en `as_of` (naive UTC), opcionalmente desde `start` (por ts_utc)."""
    if as_of.tzinfo is not None:
        raise ValueError("as_of debe ser datetime naive en UTC")
    table = TABLES[timeframe]
    syms = _as_list(symbols)
    sql = f"SELECT * FROM {table} WHERE symbol IN ({','.join('?' * len(syms))}) AND available_at <= ?"
    params: list = [*syms, as_of]
    if start is not None:
        sql += " AND ts_utc >= ?"
        params.append(start)
    if sessions:
        sql += f" AND session IN ({','.join('?' * len(sessions))})"
        params.extend(sessions)
    sql += " ORDER BY symbol, ts_utc"
    return store.query(sql, params)


def resample(bars_1m: pl.DataFrame, minutes: int, as_of: datetime | None) -> pl.DataFrame:
    """Agrega barras de 1 min a N min (buckets alineados al reloj, etiquetados por su inicio).

    `as_of` es obligatorio a propósito: si las barras de entrada ya se cortaron en un
    instante t, el bucket en curso estaría incompleto y no debe usarse. Pasar `None`
    solo cuando el input es historia completa (p. ej. análisis exploratorio).
    """
    if minutes < 1 or 60 % minutes and minutes % 60:
        raise ValueError("minutes debe dividir a 60 (o ser múltiplo de 60)")
    if bars_1m.is_empty():
        return bars_1m
    out = (
        bars_1m.sort("symbol", "ts_utc")
        .with_columns(pl.col("ts_utc").dt.truncate(f"{minutes}m").alias("bucket"))
        .group_by("symbol", "session_date", "session", "bucket", maintain_order=True)
        .agg(
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
            pl.col("trade_count").sum(),
            ((pl.col("vwap") * pl.col("volume")).sum() / pl.col("volume").sum()).alias("vwap"),
            pl.len().alias("n_bars"),
        )
        .rename({"bucket": "ts_utc"})
        .with_columns((pl.col("ts_utc") + pl.duration(minutes=minutes)).alias("available_at"))
    )
    if as_of is not None:
        out = out.filter(pl.col("available_at") <= as_of)
    return out.sort("symbol", "ts_utc")
