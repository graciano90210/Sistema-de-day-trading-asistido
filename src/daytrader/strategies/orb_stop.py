"""ORB de 5 minutos con orden stop de entrada (ronda 2, H1/H2; Zarattini, Barbon y Aziz 2024).

- Vela de apertura = barras de 1 min 09:30–09:34 (completa a las 09:35).
- Dirección: vela alcista → solo largo (stop de compra en el máximo); bajista → solo corto (stop de venta en
  el mínimo); doji → sin orden.
- Stop de pérdida a `stop_atr` × ATR(14) del precio ejecutado (lo calcula el motor). Salida al cierre forzado.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

from daytrader.strategies.base import DayContext, Signal


def orb_stop(bars: pl.DataFrame, ctx: DayContext, p: dict) -> list[Signal]:
    n = int(p.get("or_minutes", 5))
    or_end = ctx.open_utc + timedelta(minutes=n)
    if bars.is_empty() or bars["available_at"].max() < or_end or ctx.atr14 <= 0:
        return []
    rng = bars.filter((pl.col("ts_utc") >= ctx.open_utc) & (pl.col("ts_utc") < or_end)).sort("ts_utc")
    if rng.height < int(p.get("min_or_bars", 3)):
        return []
    o, c = float(rng["open"][0]), float(rng["close"][-1])
    hi, lo = float(rng["high"].max()), float(rng["low"].min())
    if c == o:
        return []  # doji
    side = 1 if c > o else -1
    level = hi if side == 1 else lo
    offset = float(p.get("stop_atr", 0.10)) * ctx.atr14
    return [
        Signal(
            symbol=ctx.symbol,
            session_date=ctx.session_date,
            strategy=p.get("name", "orb_stop"),
            side=side,
            signal_ts=or_end - timedelta(minutes=1),
            decided_at=or_end,
            ref_price=level,
            stop=level - side * offset,
            target=None,
            entry_type="stop",
            entry_level=level,
            stop_offset=offset,
            valid_until=ctx.last_entry(p.get("last_entry_et", "15:45")),
            meta={"or_open": o, "or_close": c, "or_high": hi, "or_low": lo, "or_range_atr": (hi - lo) / ctx.atr14},
        )  # fmt: skip
    ]
