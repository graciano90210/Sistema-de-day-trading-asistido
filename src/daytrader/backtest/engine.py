"""Simulación de una operación sobre barras de 1 min, con ejecuciones conservadoras.

Reglas de ejecución:
- Entrada: apertura de la primera barra que empieza en/después de `decided_at`, ± slippage.
- Stop (orden a mercado al tocarse): si una barra toca el stop, sale al peor entre el stop y la
  apertura de esa barra (gap a través del stop), ± slippage × stop_slippage_mult.
  Se evalúa también en la barra de entrada.
- Objetivo (orden límite): solo se ejecuta si el precio lo SUPERA (high > target en largos);
  sin slippage. Nunca en la barra de entrada. Si stop y objetivo caen en la misma barra → stop.
- Cierre forzado: apertura de la barra `eod_exit` (15:50 ET) o fin del stop por tiempo, ± slippage.
- R neto = PnL neto por acción (incluye slippage y tasas) / riesgo planificado por acción.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime

import polars as pl

from daytrader.backtest.costs import CostModel
from daytrader.strategies.base import Signal


@dataclass
class Trade:
    symbol: str
    session_date: date
    strategy: str
    side: int
    signal_ts: datetime
    entry_ts: datetime
    entry_px: float
    exit_ts: datetime
    exit_px: float
    exit_reason: str  # stop | target | eod | time
    stop: float
    target: float | None
    shares: int
    planned_risk: float
    slippage_ps: float
    fees: float
    pnl: float  # $ netos a tamaño de referencia
    r_gross: float  # R antes de costos
    r_net: float  # R después de costos
    # Solo órdenes stop de entrada: la barra de entrada tocó el stop pero cerró del lado bueno (orden incierto).
    ambiguous: bool = False
    r_net_opt: float | None = None  # resultado si en la barra ambigua el stop NO se ejecutó
    pnl_opt: float | None = None


def simulate(
    sig: Signal, bars: pl.DataFrame, costs: CostModel, eod_exit: datetime, ref_risk_dollars: float
) -> Trade | None:
    """`bars`: barras RTH del símbolo en la sesión (todas; el motor solo mira hacia delante tras entrar)."""
    if sig.entry_type == "stop":
        return simulate_stop_entry(sig, bars, costs, eod_exit, ref_risk_dollars)
    if sig.entry_type == "limit":
        return simulate_limit_entry(sig, bars, costs, eod_exit, ref_risk_dollars)
    ts = bars["ts_utc"].to_list()
    o, h, lo, c, v = (bars[x].to_numpy() for x in ("open", "high", "low", "close", "volume"))
    i0 = next((i for i, t in enumerate(ts) if t >= sig.decided_at), None)
    if i0 is None or ts[i0] >= eod_exit or sig.planned_risk <= 0:
        return None
    shares = int(math.floor(ref_risk_dollars / sig.planned_risk))
    if shares < 1:
        return None
    prior = slice(0, i0)  # barras con available_at <= decided_at
    slip = costs.slippage_per_share(o[i0], h[prior], lo[prior], c[prior], v[prior], shares)
    side = sig.side
    entry_px = o[i0] + side * slip
    deadline = eod_exit if sig.max_hold is None else min(eod_exit, ts[i0] + sig.max_hold)

    raw_exit = exit_ts = reason = None
    exit_slip = 0.0
    for i in range(i0, len(ts)):
        if ts[i] >= deadline and i > i0:
            raw_exit, exit_ts, exit_slip = float(o[i]), ts[i], slip
            reason = "eod" if deadline == eod_exit else "time"
            break
        stop_hit = lo[i] <= sig.stop if side == 1 else h[i] >= sig.stop
        if stop_hit:
            if i == i0:  # la entrada ya fue a la apertura: si abrió más allá del stop, sale ahí mismo
                raw_exit = float(o[i]) if (o[i] - sig.stop) * side <= 0 else sig.stop
            else:
                raw_exit = float(min(o[i], sig.stop) if side == 1 else max(o[i], sig.stop))
            exit_ts, reason, exit_slip = ts[i], "stop", slip * costs.stop_slippage_mult
            break
        if sig.target is not None and i > i0:
            tgt_hit = h[i] > sig.target if side == 1 else lo[i] < sig.target
            if tgt_hit:
                raw_exit, exit_ts, reason = sig.target, ts[i], "target"  # límite: sin slippage
                break
    if raw_exit is None:  # se acabaron las barras (faltan barras al final del día)
        raw_exit, exit_ts, reason, exit_slip = float(c[-1]), ts[-1], "eod", slip

    exit_px = raw_exit - side * exit_slip
    fees = costs.fees(shares, entry_px, exit_px, side)
    pnl = (exit_px - entry_px) * side * shares - fees
    r_gross = (raw_exit - float(o[i0])) * side / sig.planned_risk
    return Trade(
        symbol=sig.symbol, session_date=sig.session_date, strategy=sig.strategy, side=side, signal_ts=sig.signal_ts,
        entry_ts=ts[i0], entry_px=float(entry_px), exit_ts=exit_ts, exit_px=float(exit_px), exit_reason=reason,
        stop=sig.stop, target=sig.target, shares=shares, planned_risk=sig.planned_risk, slippage_ps=float(slip),
        fees=float(fees), pnl=float(pnl), r_gross=float(r_gross), r_net=float(pnl / (shares * sig.planned_risk)),
    )  # fmt: skip


def simulate_stop_entry(
    sig: Signal, bars: pl.DataFrame, costs: CostModel, eod_exit: datetime, ref_risk_dollars: float
) -> Trade | None:
    """Orden stop de entrada en `entry_level`, stop de pérdida a `stop_offset` del precio ejecutado, salida EOD.

    Barra de entrada: si toca el stop pero cierra del lado bueno, el orden es incierto → `ambiguous`.
    `r_net` es el supuesto conservador (stop en esa barra); `r_net_opt`, el optimista (sigue abierta).
    """
    ts = bars["ts_utc"].to_list()
    o, h, lo, c, v = (bars[x].to_numpy() for x in ("open", "high", "low", "close", "volume"))
    side, level, off = sig.side, float(sig.entry_level), float(sig.stop_offset)
    valid_until = min(sig.valid_until or eod_exit, eod_exit)
    shares = int(math.floor(ref_risk_dollars / off)) if off > 0 else 0
    if shares < 1:
        return None
    i0 = None
    for i, t in enumerate(ts):
        if t < sig.decided_at:
            continue
        if t >= valid_until:
            break
        if (side == 1 and h[i] >= level) or (side == -1 and lo[i] <= level):
            i0 = i
            break
    if i0 is None:
        return None
    prior = slice(0, i0)
    slip = costs.slippage_per_share(level, h[prior], lo[prior], c[prior], v[prior], shares)
    fill_raw = float(max(level, o[i0]) if side == 1 else min(level, o[i0]))  # gap a través del nivel → apertura
    entry_px = fill_raw + side * slip
    stop = entry_px - side * off

    def run(skip_entry_bar_touch: bool):
        for i in range(i0, len(ts)):
            if i > i0 and ts[i] >= eod_exit:
                return float(o[i]), ts[i], "eod", slip
            touched = lo[i] <= stop if side == 1 else h[i] >= stop
            if i == i0:
                closed_beyond = (c[i] - stop) * side <= 0
                if closed_beyond or (touched and not skip_entry_bar_touch):
                    return stop, ts[i], "stop", slip * costs.stop_slippage_mult
                continue
            if touched:
                raw = float(min(o[i], stop) if side == 1 else max(o[i], stop))
                return raw, ts[i], "stop", slip * costs.stop_slippage_mult
        return float(c[-1]), ts[-1], "eod", slip

    def outcome(res):
        raw_exit, exit_ts, reason, exit_slip = res
        exit_px = raw_exit - side * exit_slip
        fees = costs.fees(shares, entry_px, exit_px, side)
        pnl = (exit_px - entry_px) * side * shares - fees
        return exit_px, exit_ts, reason, pnl, (raw_exit - fill_raw) * side / off, fees

    cons = outcome(run(False))
    touched0 = lo[i0] <= stop if side == 1 else h[i0] >= stop
    ambiguous = bool(touched0 and (c[i0] - stop) * side > 0)
    opt = outcome(run(True)) if ambiguous else cons
    exit_px, exit_ts, reason, pnl, r_gross, fees = cons
    return Trade(
        symbol=sig.symbol, session_date=sig.session_date, strategy=sig.strategy, side=side, signal_ts=sig.signal_ts,
        entry_ts=ts[i0], entry_px=float(entry_px), exit_ts=exit_ts, exit_px=float(exit_px), exit_reason=reason,
        stop=float(stop), target=None, shares=shares, planned_risk=off, slippage_ps=float(slip), fees=float(fees),
        pnl=float(pnl), r_gross=float(r_gross), r_net=float(pnl / (shares * off)), ambiguous=ambiguous,
        r_net_opt=float(opt[3] / (shares * off)), pnl_opt=float(opt[3]),
    )  # fmt: skip


LIMIT_PRICE_K = 0.10  # k calibrado con NBBO: el precio límite no depende del escenario de costos (pre-registro)


def simulate_limit_entry(
    sig: Signal, bars: pl.DataFrame, costs: CostModel, eod_exit: datetime, ref_risk_dollars: float
) -> Trade | None:
    """Orden límite de entrada (ronda 3). Ejecución solo por trade-through: compra si low < L (estricto),
    venta si high > L, dentro de [decided_at, valid_until). Precio = L o la apertura si la barra abrió más allá.
    Stop a mercado (slippage ×mult), objetivo límite (solo si se supera), stop por tiempo desde la ejecución.
    """
    ts = bars["ts_utc"].to_list()
    o, h, lo, c, v = (bars[x].to_numpy() for x in ("open", "high", "low", "close", "volume"))
    side = sig.side
    i_start = next((i for i, t in enumerate(ts) if t >= sig.decided_at), None)
    if i_start is None or ts[i_start] >= eod_exit:
        return None
    prior = slice(0, i_start)
    hs = costs.half_spread(h[prior], lo[prior], k=LIMIT_PRICE_K)
    limit = sig.ref_price - side * float(sig.limit_offset_hs or 0.0) * hs
    planned = (limit - sig.stop) * side
    if planned <= 0:
        return None
    shares = int(math.floor(ref_risk_dollars / planned))
    if shares < 1:
        return None
    valid_until = min(sig.valid_until or eod_exit, eod_exit)
    j = None
    for i in range(i_start, len(ts)):
        if ts[i] >= valid_until:
            break
        if (side == 1 and lo[i] < limit) or (side == -1 and h[i] > limit):
            j = i
            break
    if j is None:
        return None
    fill = float(min(limit, o[j]) if side == 1 else max(limit, o[j]))
    slip = costs.slippage_per_share(fill, h[prior], lo[prior], c[prior], v[prior], shares)
    deadline = eod_exit if sig.max_hold is None else min(eod_exit, ts[j] + sig.max_hold)

    def run(skip_entry_bar_touch: bool):
        for i in range(j, len(ts)):
            if i > j and ts[i] >= deadline:
                return float(o[i]), ts[i], "eod" if deadline == eod_exit else "time", slip
            touched = lo[i] <= sig.stop if side == 1 else h[i] >= sig.stop
            if i == j:
                if (c[i] - sig.stop) * side <= 0 or (touched and not skip_entry_bar_touch):
                    return sig.stop, ts[i], "stop", slip * costs.stop_slippage_mult
                continue
            if touched:
                raw = float(min(o[i], sig.stop) if side == 1 else max(o[i], sig.stop))
                return raw, ts[i], "stop", slip * costs.stop_slippage_mult
            if sig.target is not None and (h[i] > sig.target if side == 1 else lo[i] < sig.target):
                return sig.target, ts[i], "target", 0.0
        return float(c[-1]), ts[-1], "eod", slip

    def outcome(res):
        raw_exit, exit_ts, reason, exit_slip = res
        exit_px = raw_exit - side * exit_slip
        fees = costs.fees(shares, fill, exit_px, side)
        pnl = (exit_px - fill) * side * shares - fees
        return exit_px, exit_ts, reason, pnl, (raw_exit - fill) * side / planned, fees

    cons = outcome(run(False))
    touched0 = lo[j] <= sig.stop if side == 1 else h[j] >= sig.stop
    ambiguous = bool(touched0 and (c[j] - sig.stop) * side > 0)
    opt = outcome(run(True)) if ambiguous else cons
    exit_px, exit_ts, reason, pnl, r_gross, fees = cons
    return Trade(
        symbol=sig.symbol, session_date=sig.session_date, strategy=sig.strategy, side=side, signal_ts=sig.signal_ts,
        entry_ts=ts[j], entry_px=fill, exit_ts=exit_ts, exit_px=float(exit_px), exit_reason=reason, stop=sig.stop,
        target=sig.target, shares=shares, planned_risk=planned, slippage_ps=float(slip), fees=float(fees),
        pnl=float(pnl), r_gross=float(r_gross), r_net=float(pnl / (shares * planned)), ambiguous=ambiguous,
        r_net_opt=float(opt[3] / (shares * planned)), pnl_opt=float(opt[3]),
    )  # fmt: skip


def trades_frame(trades: list[Trade]) -> pl.DataFrame:
    if not trades:
        return pl.DataFrame()
    return pl.DataFrame([asdict(t) for t in trades])
