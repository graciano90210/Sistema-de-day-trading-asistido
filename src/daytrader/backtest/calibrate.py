"""Calibración del medio spread contra cotizaciones NBBO reales (SIP) de Alpaca.

Para una muestra de entradas del backtest se descarga el NBBO del minuto de entrada y se compara el
medio spread real con el rango de 1 min previo (la variable del modelo). Solo usa microestructura,
no resultados de trades, así que calibrar con trades in-sample no contamina la evaluación.
"""

from __future__ import annotations

import logging
from datetime import UTC, timedelta

import numpy as np
import polars as pl
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockQuotesRequest

from daytrader.data.access import get_bars
from daytrader.data.alpaca_client import with_retries
from daytrader.data.store import Store

log = logging.getLogger(__name__)


def real_half_spread(client: StockHistoricalDataClient, symbol: str, t0) -> float | None:
    req = StockQuotesRequest(
        symbol_or_symbols=symbol, start=t0.replace(tzinfo=UTC), end=(t0 + timedelta(seconds=60)).replace(tzinfo=UTC),
        feed=DataFeed.SIP, limit=500,
    )  # fmt: skip
    raw = with_retries(lambda: client.get_stock_quotes(req), 3) or {}
    q = raw.get(symbol, [])
    hs = [(x["ap"] - x["bp"]) / 2 for x in q if x.get("ap", 0) > x.get("bp", 0) > 0]
    return float(np.median(hs)) if hs else None


def calibrate(
    store: Store, trades: pl.DataFrame, api_key: str, secret: str, n: int = 300, seed: int = 7, lookback: int = 30
) -> pl.DataFrame:
    client = StockHistoricalDataClient(api_key, secret, raw_data=True)
    sample = trades.sample(min(n, trades.height), seed=seed)
    rows = []
    for r in sample.iter_rows(named=True):
        t0 = r["entry_ts"]
        prior = get_bars(store, r["symbol"], t0, start=t0 - timedelta(minutes=lookback), sessions=("rth",))
        if prior.height < 5:
            continue
        rng = float((prior["high"] - prior["low"]).median())
        dollar_vol = float((prior["close"] * prior["volume"]).mean())
        hs = real_half_spread(client, r["symbol"], t0)
        if hs is None:
            continue
        rows.append({"symbol": r["symbol"], "entry_ts": t0, "price": r["entry_px"], "range_1m": rng,
                     "dollar_vol_1m": dollar_vol, "half_spread": hs, "model_half_spread": r["slippage_ps"]})  # fmt: skip
    return pl.DataFrame(rows)


def fit(df: pl.DataFrame) -> dict:
    """k = mediana(medio spread real / rango 1m). También el ajuste log-log como diagnóstico."""
    d = df.filter((pl.col("range_1m") > 0) & (pl.col("half_spread") > 0))
    ratio = (d["half_spread"] / d["range_1m"]).to_numpy()
    x, y = np.log(d["range_1m"].to_numpy()), np.log(d["half_spread"].to_numpy())
    b, a = np.polyfit(x, y, 1)
    pred = np.exp(a + b * x)
    return {
        "n": int(d.height),
        "k_median": float(np.median(ratio)),
        "k_p75": float(np.quantile(ratio, 0.75)),
        "half_spread_bps_median": float(np.median(d["half_spread"] / d["price"]) * 1e4),
        "loglog_slope": float(b),
        "loglog_r2": float(1 - np.sum((y - np.log(pred)) ** 2) / np.sum((y - y.mean()) ** 2)),
    }
