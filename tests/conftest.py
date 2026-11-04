from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from daytrader.data.ingest import prepare_bars
from daytrader.data.store import Store
from daytrader.market_calendar import sessions


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def synthetic_raw_1m(symbol: str, day: date, seed: int = 0, extended: bool = True) -> pl.DataFrame:
    """Barras de 1 min sintéticas y válidas (OHLC coherente) para una sesión real."""
    s = sessions(day, day).row(0, named=True)
    start = s["pre_open_utc"] if extended else s["open_utc"]
    end = s["post_close_utc"] if extended else s["close_utc"]
    n = int((end - start) / timedelta(minutes=1))
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.05, n))
    open_ = np.r_[100.0, close[:-1]]
    spread = np.abs(rng.normal(0, 0.03, n))
    return pl.DataFrame(
        {
            "symbol": symbol,
            "ts_utc": [start + timedelta(minutes=i) for i in range(n)],
            "open": open_,
            "high": np.maximum(open_, close) + spread,
            "low": np.minimum(open_, close) - spread,
            "close": close,
            "volume": rng.integers(100, 10_000, n).astype(float),
            "trade_count": rng.integers(1, 100, n),
            "vwap": (open_ + close) / 2,
        },
        schema_overrides={"ts_utc": pl.Datetime("us")},
    )


@pytest.fixture
def synthetic_1m():
    return synthetic_raw_1m


@pytest.fixture
def loaded_store(store):
    """Store con 2 días sintéticos de AAA (1m + 1d)."""
    days = [date(2025, 3, 13), date(2025, 3, 14)]
    for i, d in enumerate(days):
        raw = synthetic_raw_1m("AAA", d, seed=i)
        store.upsert_bars(prepare_bars(raw, "1m", "test"), "1m")
        daily = pl.DataFrame(
            {
                "symbol": ["AAA"],
                "ts_utc": [datetime(d.year, d.month, d.day, 4, 0)],  # 00:00 ET (EDT) como Alpaca
                "open": [raw["open"][0]],
                "high": [raw["high"].max()],
                "low": [raw["low"].min()],
                "close": [raw["close"][-1]],
                "volume": [raw["volume"].sum()],
                "trade_count": [int(raw["trade_count"].sum())],
                "vwap": [100.0],
            },
            schema_overrides={"ts_utc": pl.Datetime("us")},
        )
        store.upsert_bars(prepare_bars(daily, "1d", "test"), "1d")
    return store
