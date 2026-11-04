"""Cliente de DATOS de Alpaca (barras y splits).

Este módulo no importa ni usa TradingClient: en la fase 1 no existe código capaz
de enviar órdenes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime

import polars as pl
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.corporate_actions import CorporateActionsClient
from alpaca.data.requests import CorporateActionsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

log = logging.getLogger(__name__)

# fetch(symbol, timeframe, start_utc, end_utc) -> DataFrame con columnas RAW_COLUMNS
Fetcher = Callable[[str, str, datetime, datetime], pl.DataFrame]

RAW_SCHEMA = {
    "symbol": pl.Utf8,
    "ts_utc": pl.Datetime("us"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "trade_count": pl.Int64,
    "vwap": pl.Float64,
}

_TIMEFRAMES = {"1m": TimeFrame.Minute, "1d": TimeFrame.Day}


class RateLimiter:
    """Espaciado mínimo entre llamadas (aprox. de requests/min)."""

    def __init__(self, per_minute: int):
        self.interval = 60.0 / max(per_minute, 1)
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.interval:
            time.sleep(self.interval - delta)
        self._last = time.monotonic()


def with_retries(fn: Callable[[], object], max_retries: int, base_wait: float = 2.0):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # red, 429 persistente, 5xx
            if attempt == max_retries:
                raise
            wait = base_wait * 2**attempt
            log.warning("Reintento %d/%d en %.0fs: %s", attempt + 1, max_retries, wait, exc)
            time.sleep(wait)


def raw_bars_to_frame(symbol: str, bars: list[dict]) -> pl.DataFrame:
    """Convierte la respuesta cruda de Alpaca (t,o,h,l,c,v,n,vw) a un DataFrame tipado."""
    if not bars:
        return pl.DataFrame(schema=RAW_SCHEMA)
    df = pl.DataFrame(bars)
    for k in ("n", "vw"):
        if k not in df.columns:
            df = df.with_columns(pl.lit(None).alias(k))
    return df.select(
        pl.lit(symbol).alias("symbol"),
        pl.col("t").str.to_datetime(time_unit="us", time_zone="UTC").dt.replace_time_zone(None).alias("ts_utc"),
        pl.col("o").cast(pl.Float64).alias("open"),
        pl.col("h").cast(pl.Float64).alias("high"),
        pl.col("l").cast(pl.Float64).alias("low"),
        pl.col("c").cast(pl.Float64).alias("close"),
        pl.col("v").cast(pl.Float64).alias("volume"),
        pl.col("n").cast(pl.Int64).alias("trade_count"),
        pl.col("vw").cast(pl.Float64).alias("vwap"),
    )


def make_bar_fetcher(
    api_key: str,
    secret_key: str,
    feed: str = "sip",
    adjustment: str = "raw",
    max_requests_per_minute: int = 180,
    max_retries: int = 5,
) -> Fetcher:
    client = StockHistoricalDataClient(api_key, secret_key, raw_data=True)
    limiter = RateLimiter(max_requests_per_minute)

    def fetch(symbol: str, timeframe: str, start_utc: datetime, end_utc: datetime) -> pl.DataFrame:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=_TIMEFRAMES[timeframe],
            start=start_utc.replace(tzinfo=UTC),
            end=end_utc.replace(tzinfo=UTC),
            feed=DataFeed(feed),
            adjustment=Adjustment(adjustment),
        )

        def call():
            limiter.wait()
            return client.get_stock_bars(req)

        raw = with_retries(call, max_retries) or {}
        return raw_bars_to_frame(symbol, raw.get(symbol, []))

    return fetch


def fetch_splits(api_key: str, secret_key: str, symbols: list[str], start: date, end: date) -> pl.DataFrame:
    client = CorporateActionsClient(api_key, secret_key, raw_data=True)
    req = CorporateActionsRequest(symbols=symbols, types=["forward_split", "reverse_split"], start=start, end=end)
    raw = with_retries(lambda: client.get_corporate_actions(req), 3) or {}
    rows = []
    for key, kind in (("forward_splits", "forward"), ("reverse_splits", "reverse")):
        for item in raw.get(key, []) or []:
            rows.append(
                {
                    "symbol": item["symbol"],
                    "ex_date": date.fromisoformat(item["ex_date"]),
                    "old_rate": float(item["old_rate"]),
                    "new_rate": float(item["new_rate"]),
                    "kind": kind,
                }
            )
    schema = {"symbol": pl.Utf8, "ex_date": pl.Date, "old_rate": pl.Float64, "new_rate": pl.Float64, "kind": pl.Utf8}
    return pl.DataFrame(rows, schema=schema)
