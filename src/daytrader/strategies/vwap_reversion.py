"""Reversión a VWAP.

- VWAP de sesión acumulado desde 09:30 con las barras disponibles hasta cada momento.
- sigma = desviación estándar EXPANSIVA de (close - VWAP) durante la sesión (solo pasado).
- Señal larga: la barra anterior cerró por debajo de VWAP - k·sigma y la barra actual cierra por
  encima del máximo de la anterior (barra de giro). Corta: simétrico.
- Stop: extremo de las últimas `lookback_extreme` barras ± colchón. Objetivo: VWAP en el momento
  de la señal. Stop por tiempo: `max_hold_minutes`.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import polars as pl

from daytrader.strategies.base import DayContext, Signal


def session_vwap(bars: pl.DataFrame) -> pl.DataFrame:
    px = pl.coalesce("vwap", "close")
    return bars.with_columns(
        ((px * pl.col("volume")).cum_sum() / pl.col("volume").cum_sum()).alias("svwap")
    ).with_columns((pl.col("close") - pl.col("svwap")).alias("dev"))


def vwap_reversion(bars: pl.DataFrame, ctx: DayContext, p: dict) -> list[Signal]:
    b = bars.filter(pl.col("ts_utc") >= ctx.open_utc)
    if b.height < int(p["min_bars"]) + 1:  # el bucle empieza en i = min_bars (necesita min_bars+1 barras)
        return []
    b = session_vwap(b)
    dev = b["dev"].to_numpy()
    # sigma expansiva: en la barra i usa dev[0..i] (todo conocido al cierre de la barra i)
    n = np.arange(1, len(dev) + 1)
    mean = np.cumsum(dev) / n
    var = np.maximum(np.cumsum(dev**2) / n - mean**2, 0.0)
    sigma = np.sqrt(var * n / np.maximum(n - 1, 1))

    ts, avail = b["ts_utc"].to_list(), b["available_at"].to_list()
    o, h, lw, c = (b[x].to_numpy() for x in ("open", "high", "low", "close"))
    vw = b["svwap"].to_numpy()
    first, last = ctx.et(p.get("first_entry_et", "10:00")), ctx.last_entry(p.get("last_entry_et", "15:00"))
    k, look = float(p["k_sigma"]), int(p["lookback_extreme"])
    buf = float(p.get("stop_buffer_atr", 0)) * ctx.atr14
    allowed = {"both": (1, -1), "long_only": (1,), "short_only": (-1,)}[p.get("direction", "both")]
    out: list[Signal] = []
    for i in range(max(int(p["min_bars"]), 1), len(b)):
        if not (first <= ts[i] and avail[i] <= last):
            continue
        prev_sigma = sigma[i - 1]
        if prev_sigma <= 0:
            continue
        side = 0
        if dev[i - 1] < -k * prev_sigma and c[i] > h[i - 1] and c[i] > o[i]:
            side = 1
        elif dev[i - 1] > k * prev_sigma and c[i] < lw[i - 1] and c[i] < o[i]:
            side = -1
        if side == 0 or side not in allowed:
            continue
        lo_i = max(0, i - look + 1)
        stop = (lw[lo_i : i + 1].min() - buf) if side == 1 else (h[lo_i : i + 1].max() + buf)
        target = vw[i]
        risk, reward = abs(c[i] - stop), (target - c[i]) * side
        if risk <= 0 or reward <= 0 or reward / risk < float(p.get("min_rr", 0)):
            continue
        out.append(
            Signal(
                symbol=ctx.symbol,
                session_date=ctx.session_date,
                strategy=p.get("name", "vwap_rev"),
                side=side,
                signal_ts=ts[i],
                decided_at=avail[i],
                ref_price=float(c[i]),
                stop=float(stop),
                target=float(target),
                max_hold=timedelta(minutes=int(p["max_hold_minutes"])),
                meta={"dev_sigma": float(dev[i - 1] / prev_sigma)},
            )  # fmt: skip
        )
        if len(out) >= int(p.get("max_trades_per_symbol", 1)):
            break
    return out
