"""Patrones de gráfico de la ronda 4 (docs/preregistro_ronda4.md). Parámetros fijos en config/strategies.yaml.

P1 `flag`: bandera alcista (largo) / bajista (corto). P2 `double`: doble suelo (largo) / doble techo (corto).
Se detectan sobre velas de 5 min COMPLETAS (remuestreo de 1 min con as_of = última barra disponible) y se decide al
cierre de cada vela, mirando solo velas ya cerradas → invariantes a prefijos. Entrada con orden stop.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import polars as pl

from daytrader.data.access import resample
from daytrader.strategies.base import DayContext, Signal

TICK = 0.01


def _bars5(bars: pl.DataFrame) -> pl.DataFrame:
    if bars.is_empty():
        return bars
    if "session" not in bars.columns:  # barras RTH sin etiqueta (tests)
        bars = bars.with_columns(pl.lit("rth").alias("session"))
    return resample(bars, 5, bars["available_at"].max())


def _signal(ctx: DayContext, p: dict, name: str, side: int, ts, decided, entry: float, stop: float, meta: dict):
    off = abs(entry - stop)
    if off < float(p.get("min_stop_pct", 0.002)) * entry:
        return None
    valid = min(decided + timedelta(minutes=int(p["valid_min"])), ctx.last_entry(p.get("last_entry_et", "15:45")))
    return Signal(
        symbol=ctx.symbol, session_date=ctx.session_date, strategy=p.get("name", name), side=side, signal_ts=ts,
        decided_at=decided, ref_price=round(entry, 4), stop=round(stop, 4), target=None,
        max_hold=timedelta(minutes=int(p["max_hold_min"])), entry_type="stop", entry_level=round(entry, 4),
        stop_offset=round(off, 4), valid_until=valid, target_r=float(p["target_r"]), meta=meta,
    )  # fmt: skip


def _window(ctx: DayContext, p: dict, decided) -> bool:
    return ctx.et(p.get("first_decision_et", "10:00")) <= decided <= ctx.et(p.get("last_decision_et", "15:00"))


# ------------------------------------------------------------------ P1: bandera
def _flag_at(k: int, side: int, h, lo, v, atr: float, p: dict):
    """Devuelve (entrada, stop, meta) si en la vela k termina una bandera del lado `side`, si no None."""
    hi_, lo_ = (h, lo) if side == 1 else (-lo, -h)  # espejo: el corto es el largo sobre −precio
    for f in range(int(p["flag_min"]), int(p["flag_max"]) + 1):
        pe = k - f  # última vela del mástil
        if pe < 1:
            break
        w0 = max(0, pe - int(p["max_pole_bars"]) + 1)
        top = hi_[pe]
        if top < hi_[w0 : pe + 1].max():
            continue  # el mástil debe terminar en su máximo
        i_min = w0 + int(np.argmin(lo_[w0 : pe + 1]))
        pole = top - lo_[i_min]
        if pole < float(p["pole_atr"]) * atr or i_min == pe:
            continue
        fh, fl = hi_[pe + 1 : k + 1].max(), lo_[pe + 1 : k + 1].min()
        if fh > top or fl < top - float(p["max_retrace"]) * pole:
            continue
        if v[pe + 1 : k + 1].mean() > float(p["vol_ratio"]) * v[i_min : pe + 1].mean():
            continue
        entry, stop = fh + TICK, fl - TICK
        if side == -1:
            entry, stop = -entry, -stop
        return entry, stop, {"flag_bars": f, "pole_atr": pole / atr}
    return None


def flag(bars: pl.DataFrame, ctx: DayContext, p: dict) -> list[Signal]:
    b = _bars5(bars)
    if b.height < 6 or ctx.atr14 <= 0:
        return []
    ts = b["ts_utc"].to_list()
    h, lo, v = (b[c].to_numpy().astype(float) for c in ("high", "low", "volume"))
    for k in range(b.height):
        decided = ts[k] + timedelta(minutes=5)
        if not _window(ctx, p, decided):
            continue
        for side in (1, -1):
            hit = _flag_at(k, side, h, lo, v, ctx.atr14, p)
            if hit:
                s = _signal(ctx, p, "flag", side, ts[k], decided, *hit)
                if s:
                    return [s]
    return []


# ------------------------------------------------------------------ P2: doble suelo / techo
def _is_pivot(x: np.ndarray, i: int, n: int) -> bool:
    """Mínimo estrictamente menor que las n velas previas y <= que las n siguientes."""
    return i >= n and i + n < len(x) and x[i] < x[i - n : i].min() and x[i] <= x[i + 1 : i + n + 1].min()


def _double_at(k: int, side: int, h, lo, c, atr: float, p: dict):
    n = int(p["pivot_n"])
    lo_, hi_, c_ = (lo, h, c) if side == 1 else (-h, -lo, -c)
    j = k - n
    x = lo_[: k + 1]  # solo velas cerradas hasta k
    if j < n or not _is_pivot(x, j, n):
        return None
    for i in range(j - int(p["min_sep"]), max(n - 1, j - int(p["max_sep"]) - 1), -1):
        if not _is_pivot(x, i, n):
            continue
        li, lj = lo_[i], lo_[j]
        if abs(lj - li) > float(p["tol_atr"]) * atr:
            continue
        neck = hi_[i + 1 : j].max()
        base = min(li, lj)
        depth = neck - base
        if depth < float(p["depth_atr"]) * atr:
            continue
        pre = hi_[max(0, i - int(p["prior_bars"])) : i]
        if pre.size == 0 or pre.max() < li + depth:
            continue
        if c_[j : k + 1].max() > neck:
            continue
        entry, stop = neck + TICK, base - TICK
        if side == -1:
            entry, stop = -entry, -stop
        return entry, stop, {"sep_bars": j - i, "depth_atr": depth / atr}
    return None


def double(bars: pl.DataFrame, ctx: DayContext, p: dict) -> list[Signal]:
    b = _bars5(bars)
    if b.height < 12 or ctx.atr14 <= 0:
        return []
    ts = b["ts_utc"].to_list()
    h, lo, c = (b[x].to_numpy().astype(float) for x in ("high", "low", "close"))
    for k in range(b.height):
        decided = ts[k] + timedelta(minutes=5)
        if not _window(ctx, p, decided):
            continue
        for side in (1, -1):
            hit = _double_at(k, side, h, lo, c, ctx.atr14, p)
            if hit:
                s = _signal(ctx, p, "double", side, ts[k], decided, *hit)
                if s:
                    return [s]
    return []
