"""Ajuste por splits point-in-time.

Para una fecha de referencia D, una fila de la sesión s se ajusta por cada split con
s < ex_date <= D. Los splits con ex_date > D aún no han ocurrido y se ignoran.

ratio = new_rate / old_rate  (acciones nuevas por acción vieja; 10:1 forward → 10, 1:10 reverse → 0.1)
precio_ajustado = precio / ratio ; volumen_ajustado = volumen * ratio
"""

from __future__ import annotations

from datetime import date

import polars as pl


def adjust_for_splits(
    df: pl.DataFrame,
    splits: pl.DataFrame,
    as_of: date,
    price_cols: tuple[str, ...] = ("open", "high", "low", "close", "vwap"),
    volume_cols: tuple[str, ...] = ("volume",),
    date_col: str = "session_date",
) -> pl.DataFrame:
    """Devuelve `df` con precios/volúmenes ajustados a la base de acciones vigente en `as_of`."""
    s = splits.filter(pl.col("ex_date") <= as_of).select(
        "symbol", "ex_date", (pl.col("new_rate") / pl.col("old_rate")).alias("ratio")
    )
    if df.is_empty() or s.is_empty():
        return df
    key = df.with_row_index("_row").select("_row", "symbol", date_col)
    factors = (
        key.join(s, on="symbol", how="inner")
        .filter(pl.col(date_col) < pl.col("ex_date"))
        .group_by("_row")
        .agg(pl.col("ratio").product().alias("_ratio"))
    )
    out = df.with_row_index("_row").join(factors, on="_row", how="left").with_columns(pl.col("_ratio").fill_null(1.0))
    pcols = [c for c in price_cols if c in out.columns]
    vcols = [c for c in volume_cols if c in out.columns]
    return out.with_columns(
        *[(pl.col(c) / pl.col("_ratio")).alias(c) for c in pcols],
        *[(pl.col(c) * pl.col("_ratio")).alias(c) for c in vcols],
    ).drop("_row", "_ratio")
