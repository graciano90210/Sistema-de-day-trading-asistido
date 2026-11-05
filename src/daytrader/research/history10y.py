"""Fase 7: historia larga (2015–2025) en una base aparte, data/history.duckdb.

Base aparte para no competir por el bloqueo de escritura de data/market.duckdb con la rutina nocturna.
Pasos (todos incrementales y reanudables):
  1. copiar assets, splits y barras diarias ya descargadas (2024-11 → 2025-12) de market.duckdb
  2. splits de todo el mercado 2015 → 2024-10
  3. barras diarias de TODAS las acciones comunes (activas e inactivas) 2015 → 2024-10
  4. universo point-in-time por año (tabla universe_pit): top N por $ volumen medio del AÑO ANTERIOR
  5. barras de 1 min del universo de cada año (más SPY, QQQ, IWM)

Sesgo de supervivencia: se mitiga incluyendo acciones inactivas (deslistadas) y eligiendo el universo de cada año
solo con datos del año anterior. Limitación: `is_common` se calcula con el nombre ACTUAL del activo en Alpaca.
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

from daytrader.data.store import Store

log = logging.getLogger(__name__)

BENCHMARKS = ["SPY", "QQQ", "IWM"]
DAILY_START = date(2015, 1, 1)
DAILY_COPY_FROM = date(2024, 11, 1)  # desde aquí las diarias ya están en market.duckdb
FIRST_YEAR, LAST_YEAR = 2016, 2025

UNIVERSE_PIT = """
CREATE TABLE IF NOT EXISTS universe_pit (
    year INTEGER, symbol VARCHAR, rank INTEGER, adv_usd DOUBLE, last_close DOUBLE, n_sessions INTEGER,
    PRIMARY KEY (year, symbol)
)"""


def copy_from_market(hist: Store, market_path: str) -> dict[str, int]:
    """Copia assets, splits y barras diarias recientes de market.duckdb (solo lectura) a la base de historia."""
    hist.con.execute(f"ATTACH '{market_path}' AS mk (READ_ONLY)")
    try:
        out = {}
        for t in ("assets", "splits"):
            hist.con.execute(f"INSERT OR REPLACE INTO {t} BY NAME SELECT * FROM mk.{t}")
            out[t] = hist.con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]
        hist.con.execute(
            "INSERT OR REPLACE INTO bars_1d BY NAME SELECT * FROM mk.bars_1d WHERE session_date >= ?",
            [DAILY_COPY_FROM],
        )
        hist.con.execute("INSERT OR REPLACE INTO ingest_log BY NAME SELECT * FROM mk.ingest_log WHERE timeframe = '1d'")
        out["bars_1d"] = hist.con.execute("SELECT count(*) FROM bars_1d").fetchall()[0][0]
        return out
    finally:
        hist.con.execute("DETACH mk")


def pit_universe(daily: pl.DataFrame, common: set[str], year: int, n: int = 100, min_price: float = 5.0,
                 min_sessions: int = 200) -> pl.DataFrame:  # fmt: skip
    """Top `n` acciones comunes por $ volumen medio diario del año `year - 1` (solo datos de ese año).

    daily: symbol, session_date, close, volume. Requiere ≥ `min_sessions` sesiones en el año y último cierre ≥ min_price.
    """
    prev = daily.filter(pl.col("session_date").dt.year() == year - 1).filter(pl.col("symbol").is_in(list(common)))
    agg = (
        prev.sort("symbol", "session_date")
        .group_by("symbol")
        .agg(
            (pl.col("close") * pl.col("volume")).mean().alias("adv_usd"),
            pl.col("close").last().alias("last_close"),
            pl.len().alias("n_sessions"),
        )
        .filter((pl.col("n_sessions") >= min_sessions) & (pl.col("last_close") >= min_price))
        .sort("adv_usd", descending=True)
        .head(n)
    )
    return (
        agg.with_row_index("rank", offset=1)
        .with_columns(pl.lit(year).alias("year"), pl.col("rank").cast(pl.Int32))
        .select("year", "symbol", "rank", "adv_usd", "last_close", pl.col("n_sessions").cast(pl.Int32))
    )


def build_universe(hist: Store, n: int = 100) -> pl.DataFrame:
    from daytrader.scanner.universe import VALID_SYMBOL

    hist.con.execute(UNIVERSE_PIT)
    common = {s for s in hist.query("SELECT symbol FROM assets WHERE is_common")["symbol"].to_list()
              if VALID_SYMBOL.match(s)}  # fmt: skip
    daily = hist.query("SELECT symbol, session_date, close, volume FROM bars_1d")
    parts = [pit_universe(daily, common, y, n) for y in range(FIRST_YEAR, LAST_YEAR + 1)]
    u = pl.concat(parts)
    hist.upsert("universe_pit", u)
    return u


def universe_for(hist: Store, year: int) -> list[str]:
    syms = hist.query("SELECT symbol FROM universe_pit WHERE year = ? ORDER BY rank", [year])["symbol"].to_list()
    return BENCHMARKS + [s for s in syms if s not in BENCHMARKS]
