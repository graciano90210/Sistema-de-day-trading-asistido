"""Ronda 3: misma señal que vwap_reversion, pero entrada pasiva con orden límite.

Parámetros extra: limit_offset_hs (m, en medios spreads estimados) y limit_valid_min (W, minutos).
La señal es idéntica a la de vwap_reversion (invariante a prefijos); solo cambia cómo se ejecuta.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import polars as pl

from daytrader.strategies.base import DayContext, Signal
from daytrader.strategies.vwap_reversion import vwap_reversion


def vwap_limit(bars: pl.DataFrame, ctx: DayContext, p: dict) -> list[Signal]:
    last = ctx.last_entry(p.get("last_entry_et", "15:00"))
    out = []
    for s in vwap_reversion(bars, ctx, p):
        valid = min(s.decided_at + timedelta(minutes=int(p["limit_valid_min"])), last)
        out.append(replace(s, entry_type="limit", limit_offset_hs=float(p["limit_offset_hs"]), valid_until=valid))
    return out
