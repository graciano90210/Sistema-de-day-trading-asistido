"""`daytrader contexto SYMBOL`: contexto objetivo para decidir largo / corto / no operar.

Todo lo calcula Python. Las "lecturas" son DESCRIPTIVAS (dónde está el precio respecto a niveles que
los traders vigilan), no señales con ventaja probada: en la fase 3 ninguna regla mecánica la tuvo.
Barras SIP hasta hace ~15 min (límite del plan gratuito) + precio actual IEX en tiempo real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import polars as pl


@dataclass
class Context:
    symbol: str
    price: float
    prev_close: float | None
    atr14: float | None
    pm_high: float | None
    pm_low: float | None
    or_high: float | None
    or_low: float | None
    day_high: float | None
    day_low: float | None
    vwap: float | None
    price_30m_ago: float | None
    bars_until: datetime | None
    rel: dict = field(default_factory=dict)  # SPY/QQQ: cambio del día y posición vs su VWAP


def _vwap(rth: pl.DataFrame) -> float | None:
    if rth.is_empty() or rth["volume"].sum() == 0:
        return None
    px = rth["vwap"].fill_null(rth["close"])
    return float((px * rth["volume"]).sum() / rth["volume"].sum())


def compute(symbol: str, bars: pl.DataFrame, daily: pl.DataFrame, price: float, open_utc: datetime) -> Context:
    """bars: barras 1 min de HOY (ts_utc inicio, naive UTC) desde las 04:00 ET; daily: sesiones anteriores."""
    pre = bars.filter(pl.col("ts_utc") < open_utc)
    rth = bars.filter(pl.col("ts_utc") >= open_utc)
    orb = rth.filter(pl.col("ts_utc") < open_utc + timedelta(minutes=5))
    d = daily.sort("session_date")
    atr = None
    if d.height >= 15:
        pc = pl.col("close").shift(1)
        tr = d.select(
            pl.max_horizontal(pl.col("high") - pl.col("low"), (pl.col("high") - pc).abs(), (pl.col("low") - pc).abs())
        ).to_series()
        atr = float(tr.tail(14).mean())
    last_ts = rth["ts_utc"].max() if not rth.is_empty() else None
    ago = None
    if last_ts is not None:
        old = rth.filter(pl.col("ts_utc") <= last_ts - timedelta(minutes=30))
        ago = float(old["close"][-1]) if not old.is_empty() else float(rth["open"][0])
    return Context(
        symbol=symbol, price=price, prev_close=float(d["close"][-1]) if d.height else None, atr14=atr,
        pm_high=float(pre["high"].max()) if not pre.is_empty() else None,
        pm_low=float(pre["low"].min()) if not pre.is_empty() else None,
        or_high=float(orb["high"].max()) if not orb.is_empty() else None,
        or_low=float(orb["low"].min()) if not orb.is_empty() else None,
        day_high=float(rth["high"].max()) if not rth.is_empty() else None,
        day_low=float(rth["low"].min()) if not rth.is_empty() else None,
        vwap=_vwap(rth), price_30m_ago=ago, bars_until=(last_ts + timedelta(minutes=1)) if last_ts else None,
    )  # fmt: skip


def readings(c: Context) -> list[tuple[str, int]]:
    """Lecturas descriptivas con su inclinación: +1 favorece largo, −1 favorece corto, 0 neutral."""
    out: list[tuple[str, int]] = []
    p = c.price
    if c.vwap:
        dv = (p / c.vwap - 1) * 100
        out.append((f"Precio {'sobre' if dv > 0 else 'bajo'} el VWAP del día ({dv:+.2f}%): "
                    f"{'dominan los compradores' if dv > 0 else 'dominan los vendedores'}", 1 if dv > 0 else -1))  # fmt: skip
    if c.prev_close:
        ch = (p / c.prev_close - 1) * 100
        out.append((f"Cambio frente al cierre de ayer: {ch:+.2f}%", 0))
    if c.pm_high and p > c.pm_high:
        out.append((f"Por encima del máximo del pre-market ({c.pm_high:.2f})", 1))
    elif c.pm_low and p < c.pm_low:
        out.append((f"Por debajo del mínimo del pre-market ({c.pm_low:.2f})", -1))
    if c.or_high and c.or_low:
        if p > c.or_high:
            out.append((f"Sobre el rango de apertura de 5 min ({c.or_low:.2f}–{c.or_high:.2f})", 1))
        elif p < c.or_low:
            out.append((f"Bajo el rango de apertura de 5 min ({c.or_low:.2f}–{c.or_high:.2f})", -1))
        else:
            out.append(("Dentro del rango de apertura: sin dirección clara", 0))
    if c.price_30m_ago:
        m = (p / c.price_30m_ago - 1) * 100
        out.append((f"Últimos ~30 min: {m:+.2f}% ({'subiendo' if m > 0 else 'bajando'})", 1 if m > 0.15 else (-1 if m < -0.15 else 0)))  # fmt: skip
    if c.day_high and c.day_low and c.day_high > c.day_low:
        pos = (p - c.day_low) / (c.day_high - c.day_low)
        out.append((f"En el {pos:.0%} del rango del día (0% = mínimo, 100% = máximo)", 0))
    for name, (ch, above) in c.rel.items():
        out.append((f"{name} {ch:+.2f}% hoy y {'sobre' if above else 'bajo'} su VWAP: mercado "
                    f"{'a favor del largo' if above else 'a favor del corto'}", 1 if above else -1))  # fmt: skip
    return out


def candidate_stops(c: Context, side: int) -> list[tuple[str, float]]:
    """Niveles donde la idea quedaría invalidada (debajo del precio en largos, encima en cortos)."""
    lv = {"VWAP": c.vwap, "mínimo del rango de apertura": c.or_low, "máximo del rango de apertura": c.or_high,
          "mínimo del día": c.day_low, "máximo del día": c.day_high, "mínimo pre-market": c.pm_low,
          "máximo pre-market": c.pm_high}  # fmt: skip
    out = [(k, v) for k, v in lv.items() if v and (v - c.price) * side < 0 and abs(v / c.price - 1) >= 0.002]
    return sorted(out, key=lambda kv: abs(kv[1] - c.price))[:3]
