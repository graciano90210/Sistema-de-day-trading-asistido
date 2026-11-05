"""Almacenamiento en DuckDB: esquema, upsert idempotente y registro de ingesta."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import polars as pl

BAR_COLUMNS = [
    "symbol",
    "ts_utc",
    "available_at",
    "session_date",
    "session",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_count",
    "vwap",
    "feed",
]

_BAR_DDL = """
    symbol        VARCHAR   NOT NULL,
    ts_utc        TIMESTAMP NOT NULL,   -- inicio de la barra, UTC
    available_at  TIMESTAMP NOT NULL,   -- primer instante en que la barra es conocible, UTC
    session_date  DATE      NOT NULL,   -- fecha ET
    session       VARCHAR   NOT NULL,   -- pre | rth | post | closed | day
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    volume DOUBLE, trade_count BIGINT, vwap DOUBLE,
    feed          VARCHAR   NOT NULL,
    PRIMARY KEY (symbol, ts_utc)
"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS bars_1m ({_BAR_DDL});
CREATE TABLE IF NOT EXISTS bars_1d ({_BAR_DDL});
CREATE TABLE IF NOT EXISTS splits (
    symbol VARCHAR NOT NULL, ex_date DATE NOT NULL,
    old_rate DOUBLE, new_rate DOUBLE, kind VARCHAR,
    PRIMARY KEY (symbol, ex_date)
);
CREATE TABLE IF NOT EXISTS assets (
    symbol VARCHAR NOT NULL, name VARCHAR, exchange VARCHAR, status VARCHAR,
    is_common BOOLEAN, fetched_at TIMESTAMP,
    PRIMARY KEY (symbol)
);
-- Resumen del pre-market de un símbolo en una sesión, usando SOLO barras con available_at <= cutoff_utc.
CREATE TABLE IF NOT EXISTS premarket_snap (
    symbol VARCHAR NOT NULL, session_date DATE NOT NULL, cutoff_utc TIMESTAMP NOT NULL,
    last DOUBLE, high DOUBLE, low DOUBLE, volume DOUBLE, dollar_volume DOUBLE,
    n_bars BIGINT, last_bar_ts TIMESTAMP,
    PRIMARY KEY (symbol, session_date, cutoff_utc)
);
CREATE TABLE IF NOT EXISTS news (
    id BIGINT NOT NULL, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP,
    headline VARCHAR, summary VARCHAR, source VARCHAR, url VARCHAR, n_symbols INTEGER,
    PRIMARY KEY (id)
);
CREATE TABLE IF NOT EXISTS news_symbols (
    id BIGINT NOT NULL, symbol VARCHAR NOT NULL,
    PRIMARY KEY (id, symbol)
);
-- Rangos ya consultados de noticias (caché): símbolo × [start, end] UTC.
CREATE TABLE IF NOT EXISTS news_log (
    symbol VARCHAR NOT NULL, start_utc TIMESTAMP NOT NULL, end_utc TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, start_utc, end_utc)
);
CREATE TABLE IF NOT EXISTS sec_tickers (
    symbol VARCHAR NOT NULL, cik BIGINT NOT NULL, title VARCHAR,
    PRIMARY KEY (symbol)
);
-- dei:EntityCommonStockSharesOutstanding; visible desde `filed` (fecha de publicación en EDGAR).
CREATE TABLE IF NOT EXISTS shares_outstanding (
    cik BIGINT NOT NULL, tag VARCHAR NOT NULL, priority INTEGER NOT NULL,
    end_date DATE NOT NULL, filed DATE NOT NULL, accn VARCHAR NOT NULL,
    shares DOUBLE, form VARCHAR,
    PRIMARY KEY (cik, tag, end_date, filed, accn, shares)
);
-- Watchlists históricas reconstruidas point-in-time (una fila por símbolo y sesión).
CREATE TABLE IF NOT EXISTS watchlists (
    session_date DATE NOT NULL, cutoff_utc TIMESTAMP NOT NULL, rank INTEGER NOT NULL, symbol VARCHAR NOT NULL,
    gap DOUBLE, pm_last DOUBLE, prev_close DOUBLE, pm_volume DOUBLE, rvol DOUBLE, pm_dollar_volume DOUBLE,
    atr14 DOUBLE, atr_pct DOUBLE, adv_usd DOUBLE, shares_out DOUBLE,
    catalyst VARCHAR, n_news INTEGER, n_relevant INTEGER,
    PRIMARY KEY (session_date, symbol)
);
CREATE TABLE IF NOT EXISTS scan_log (
    session_date DATE PRIMARY KEY, n_universe INTEGER, n_candidates INTEGER, n_watchlist INTEGER,
    status VARCHAR, error VARCHAR, finished_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sec_fetch_log (cik BIGINT PRIMARY KEY, fetched_at TIMESTAMP, status VARCHAR);
CREATE TABLE IF NOT EXISTS ingest_log (
    symbol VARCHAR NOT NULL, timeframe VARCHAR NOT NULL,
    chunk_start DATE NOT NULL, chunk_end DATE NOT NULL,   -- [start, end)
    rows BIGINT, status VARCHAR NOT NULL, error VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, timeframe, chunk_start, chunk_end)
);
"""

TABLES = {"1m": "bars_1m", "1d": "bars_1d"}


class Store:
    def __init__(self, path: str | Path = ":memory:", read_only: bool = False, memory_limit: str | None = None):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.con = duckdb.connect(self.path, read_only=read_only)
        if memory_limit:
            self.con.execute(f"SET memory_limit = '{memory_limit}'")
        if not read_only:
            self.con.execute(SCHEMA)

    # -- barras ---------------------------------------------------------------
    def upsert_bars(self, df: pl.DataFrame, timeframe: str) -> int:
        """Inserta o reemplaza barras por (symbol, ts_utc). Idempotente."""
        if df.is_empty():
            return 0
        table = TABLES[timeframe]
        missing = set(BAR_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"Faltan columnas para {table}: {sorted(missing)}")
        batch = df.select(BAR_COLUMNS).unique(subset=["symbol", "ts_utc"], keep="last")  # noqa: F841
        self.con.execute(f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM batch")
        return batch.height

    def upsert(self, table: str, df: pl.DataFrame) -> int:
        """INSERT OR REPLACE genérico por nombre de columna."""
        if df.is_empty():
            return 0
        self.con.register("_upsert_df", df)
        try:
            self.con.execute(f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM _upsert_df")
        finally:
            self.con.unregister("_upsert_df")
        return df.height

    def upsert_splits(self, df: pl.DataFrame) -> int:
        if df.is_empty():
            return 0
        batch = df.select("symbol", "ex_date", "old_rate", "new_rate", "kind")  # noqa: F841
        self.con.execute("INSERT OR REPLACE INTO splits BY NAME SELECT * FROM batch")
        return df.height

    # -- registro de ingesta --------------------------------------------------
    def log_chunk(
        self,
        symbol: str,
        timeframe: str,
        chunk_start: date,
        chunk_end: date,
        rows: int,
        status: str,
        error: str | None = None,
    ) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO ingest_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                symbol,
                timeframe,
                chunk_start,
                chunk_end,
                rows,
                status,
                error,
                datetime.now(UTC).replace(tzinfo=None),
            ],
        )

    def completed_chunks(self, symbol: str, timeframe: str) -> set[tuple[date, date]]:
        rows = self.con.execute(
            "SELECT chunk_start, chunk_end FROM ingest_log WHERE symbol = ? AND timeframe = ? AND status = 'ok'",
            [symbol, timeframe],
        ).fetchall()
        return {(r[0], r[1]) for r in rows}

    def query(self, sql: str, params: list | None = None) -> pl.DataFrame:
        return self.con.sql(sql, params=params or None).pl()

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
