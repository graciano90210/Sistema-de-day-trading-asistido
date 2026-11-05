"""Opening Range Breakout (ORB).

1. Rango = máximo/mínimo de las barras de 09:30 a 09:30+N. Se conoce cuando cierra la última barra del rango.
2. Señal: la primera barra (que empieza en/después de 09:30+N) que CIERRA fuera del rango, en la
   dirección permitida. La entrada la simula el backtester en la apertura de la barra siguiente.
3. Stop: extremo opuesto del rango (o su punto medio). Objetivo: target_r × riesgo planificado.
Una señal como máximo por símbolo y día (la primera ruptura válida).
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

from daytrader.strategies.base import DayContext, Signal


def orb(bars: pl.DataFrame, ctx: DayContext, p: dict) -> list[Signal]:
    n = int(p["or_minutes"])
    or_end = ctx.open_utc + timedelta(minutes=n)
    last_entry = ctx.last_entry(p.get("last_entry_et", "15:45"))
    rng = bars.filter((pl.col("ts_utc") >= ctx.open_utc) & (pl.col("ts_utc") < or_end))
    if rng.height < int(p.get("min_or_bars", 1)):
        return []
    # El rango solo está completo cuando su última barra posible está disponible.
    if bars.is_empty() or bars["available_at"].max() < or_end:
        return []
    hi, lo = float(rng["high"].max()), float(rng["low"].min())
    width = hi - lo
    if width <= 0 or ctx.atr14 <= 0:
        return []
    if not (p.get("min_range_atr", 0) * ctx.atr14 <= width <= p.get("max_range_atr", 1e9) * ctx.atr14):
        return []

    direction = p.get("direction", "with_gap")
    sides = {"both": (1, -1), "long_only": (1,)}.get(direction)
    if direction == "with_gap":
        if ctx.gap is None or ctx.gap == 0:
            return []
        sides = (1,) if ctx.gap > 0 else (-1,)

    after = bars.filter((pl.col("ts_utc") >= or_end) & (pl.col("available_at") <= last_entry))
    ts, close = after["ts_utc"].to_list(), after["close"].to_list()
    avail = after["available_at"].to_list()
    for t, c, a in zip(ts, close, avail, strict=True):
        side = 1 if c > hi else (-1 if c < lo else 0)
        if side == 0:
            continue
        if side not in sides:
            return []  # primera ruptura en contra de la dirección permitida: no se opera el día
        if p.get("stop", "or_opposite") == "or_mid":
            stop = (hi + lo) / 2
        else:
            stop = lo if side == 1 else hi
        risk = abs(c - stop)
        if risk <= 0:
            return []
        target = c + side * p["target_r"] * risk if p.get("target_r") else None
        return [
            Signal(
                symbol=ctx.symbol,
                session_date=ctx.session_date,
                strategy=p.get("name", f"orb_{n}"),
                side=side,
                signal_ts=t,
                decided_at=a,
                ref_price=c,
                stop=stop,
                target=target,
                meta={"or_high": hi, "or_low": lo, "or_width_atr": width / ctx.atr14},
            )  # fmt: skip
        ]
    return []
