"""Motores de backtest diario para swing (fase 8). Conservadores y deterministas.

- `simulate_events` (S3, S4): señal al cierre de D → entrada en la apertura de D+1; stop desde el precio de
  apertura; si la apertura ya cruzó el stop se sale en la apertura (gap); stop antes que la salida del cierre;
  salidas por tiempo (cierre de la sesión `max_hold`) o por cierre > SMA5; deslistado → último cierre.
- `simulate_rotation` (S1, S2): cartera igual-ponderada que se rebalancea en la apertura siguiente a cada fecha
  de decisión; costos sobre el turnover.

Costos: `slip` por lado (spread + slippage, fracción del precio), tasa SEC sobre ventas y TAF por acción vendida,
préstamo de cortos y (escenario pesimista) dividendos en cortos, ambos por sesión mantenida.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl


@dataclass(frozen=True)
class SwingCosts:
    slip: float = 0.0010  # 10 pb por lado
    borrow_annual: float = 0.005
    short_div_annual: float = 0.0
    sec_fee_rate: float = 0.0000278
    taf_per_share: float = 0.000166
    taf_max: float = 8.30


BASE = SwingCosts()
PESSIMISTIC = SwingCosts(slip=0.0025, borrow_annual=0.03, short_div_annual=0.02)


@dataclass(frozen=True)
class EventAccount:
    initial_equity: float = 100_000.0
    risk_per_trade: float = 0.005
    max_positions: int = 10
    max_position_frac: float = 0.25


class Panel:
    """Barras por símbolo en arrays numpy (búsqueda por fecha con searchsorted)."""

    def __init__(self, bars: pl.DataFrame):
        self.data: dict[str, dict[str, np.ndarray]] = {}
        cols = [c for c in ("open", "high", "low", "close", "sma5") if c in bars.columns]
        for (sym,), g in bars.sort("symbol", "session_date").group_by("symbol", maintain_order=True):
            arr = {"d": g["session_date"].to_numpy().astype("datetime64[D]").astype(np.int64)}
            for c in cols:
                arr[c] = g[c].to_numpy().astype(float)
            self.data[sym] = arr

    def idx(self, sym: str, day: date) -> int | None:
        a = self.data.get(sym)
        if a is None:
            return None
        k = int(np.datetime64(day, "D").astype(np.int64))
        j = int(np.searchsorted(a["d"], k))
        return j if j < len(a["d"]) and a["d"][j] == k else None

    def last_idx_on_or_before(self, sym: str, day: date) -> int | None:
        a = self.data[sym]
        k = int(np.datetime64(day, "D").astype(np.int64))
        j = int(np.searchsorted(a["d"], k, side="right")) - 1
        return j if j >= 0 else None

    def last_date(self, sym: str) -> int:
        return int(self.data[sym]["d"][-1])


def _day(k: int) -> date:
    return np.datetime64(k, "D").astype(object)


def _fees(c: SwingCosts, shares: int, entry_px: float, exit_px: float, side: int) -> float:
    sell_px = exit_px if side == 1 else entry_px
    return c.sec_fee_rate * shares * sell_px + min(c.taf_per_share * shares, c.taf_max)


def simulate_events(signals: pl.DataFrame, panel: Panel, sessions: list[date], costs: SwingCosts = BASE,
                    acct: EventAccount | None = None) -> tuple[pl.DataFrame, pl.DataFrame]:  # fmt: skip
    """signals: symbol, session_date (D), side, stop_dist ($ ajustados), max_hold, exit_rule, prio.
    Devuelve (trades, equity diaria con columnas session_date, equity, ret)."""
    acct = acct or EventAccount()
    by_day: dict[date, list[dict]] = {}
    for r in signals.sort(["session_date", "prio", "symbol"], descending=[False, True, False]).iter_rows(named=True):
        by_day.setdefault(r["session_date"], []).append(r)
    data_end = max((panel.last_date(s) for s in panel.data), default=0)
    realized = 0.0
    open_pos: list[dict] = []
    trades, eq_rows = [], []
    prev_equity = acct.initial_equity
    for i, t in enumerate(sessions):
        # 1) entradas en la apertura con las señales del cierre anterior
        if i > 0:
            held = {p["symbol"] for p in open_pos}
            for s in by_day.get(sessions[i - 1], []):
                if len(open_pos) >= acct.max_positions:
                    break
                if s["symbol"] in held:
                    continue
                j = panel.idx(s["symbol"], t)
                if j is None or not s["stop_dist"] or s["stop_dist"] <= 0:
                    continue
                a = panel.data[s["symbol"]]
                o, side = a["open"][j], int(s["side"])
                fill = o * (1 + side * costs.slip)
                stop = o - side * s["stop_dist"]
                rps = abs(fill - stop)
                shares = min(math.floor(prev_equity * acct.risk_per_trade / rps),
                             math.floor(prev_equity * acct.max_position_frac / fill))  # fmt: skip
                if shares < 1 or stop <= 0:
                    continue
                open_pos.append({"symbol": s["symbol"], "side": side, "signal_date": s["session_date"],
                                 "entry_date": t, "entry_px": fill, "stop": stop, "rps": rps, "shares": shares,
                                 "n": 0, "max_hold": int(s["max_hold"]), "exit_rule": s["exit_rule"],
                                 "last_close": o, "entry_j": j})  # fmt: skip
                held.add(s["symbol"])
        # 2) gestión de posiciones durante la sesión t
        still = []
        for p in open_pos:
            a = panel.data[p["symbol"]]
            j = panel.idx(p["symbol"], t)
            side = p["side"]
            exit_px = reason = None
            if j is not None:
                p["n"] += 1
                o, h, lo, c = a["open"][j], a["high"][j], a["low"][j], a["close"][j]
                first = j == p["entry_j"] and p["n"] == 1
                gap = (not first) and ((side == 1 and o <= p["stop"]) or (side == -1 and o >= p["stop"]))
                if gap:
                    exit_px, reason = o, "stop_gap"
                elif (side == 1 and lo <= p["stop"]) or (side == -1 and h >= p["stop"]):
                    exit_px, reason = p["stop"], "stop"
                elif p["exit_rule"] == "sma5" and side == 1 and "sma5" in a and c > a["sma5"][j]:
                    exit_px, reason = c, "sma5"
                elif p["n"] >= p["max_hold"]:
                    exit_px, reason = c, "time"
                elif j == len(a["d"]) - 1 and a["d"][j] < data_end:
                    exit_px, reason = c, "delisted"
                p["last_close"] = c
            elif panel.last_date(p["symbol"]) < int(np.datetime64(t, "D").astype(np.int64)):
                exit_px, reason = p["last_close"], "delisted"
            if exit_px is None:
                still.append(p)
                continue
            fill = exit_px * (1 - side * costs.slip)
            gross = side * (fill - p["entry_px"]) * p["shares"]
            notional = p["entry_px"] * p["shares"]
            carry = (notional * (costs.borrow_annual + costs.short_div_annual) / 252 * max(p["n"], 1)
                     if side == -1 else 0.0)  # fmt: skip
            fees = _fees(costs, p["shares"], p["entry_px"], fill, side)
            pnl = gross - fees - carry
            realized += pnl
            trades.append({"symbol": p["symbol"], "side": side, "signal_date": p["signal_date"],
                           "entry_date": p["entry_date"], "exit_date": t, "entry_px": p["entry_px"],
                           "exit_px": fill, "shares": p["shares"], "sessions": p["n"], "reason": reason,
                           "pnl_usd": pnl, "risk_usd": p["rps"] * p["shares"],
                           "r_net": pnl / (p["rps"] * p["shares"]),
                           "r_gross": side * (exit_px - p["entry_px"] / (1 + side * costs.slip)) / p["rps"]})  # fmt: skip
        open_pos = still
        unreal = sum(p["side"] * (p["last_close"] - p["entry_px"]) * p["shares"] for p in open_pos)
        equity = acct.initial_equity + realized + unreal
        eq_rows.append({"session_date": t, "equity": equity, "ret": equity / prev_equity - 1,
                        "positions": len(open_pos)})  # fmt: skip
        prev_equity = equity
    tr = pl.DataFrame(trades) if trades else pl.DataFrame(schema={"r_net": pl.Float64, "entry_date": pl.Date})
    return tr, pl.DataFrame(eq_rows)


def simulate_rotation(targets: dict, panel: Panel, sessions: list[date], costs: SwingCosts = BASE,
                      initial: float = 100_000.0) -> tuple[pl.DataFrame, pl.DataFrame]:  # fmt: skip
    """targets: {fecha de decisión D: [símbolos]} (lista vacía = efectivo). Rebalanceo igual-ponderado en la
    apertura de la sesión siguiente a D. Devuelve (holdings por periodo, equity diaria)."""
    sidx = {d: i for i, d in enumerate(sessions)}
    exec_at = {}
    for d, syms in targets.items():
        if d in sidx and sidx[d] + 1 < len(sessions):
            exec_at[sessions[sidx[d] + 1]] = syms
    cash = initial
    hold: dict[str, dict] = {}  # símbolo → {"value", "last_close", "entry_date", "entry_value"}
    periods, eq_rows = [], []
    prev_equity = initial

    def close_out(sym: str, h: dict, t: date, value: float):
        periods.append({"symbol": sym, "entry_date": h["entry_date"], "exit_date": t,
                        "ret": value / h["entry_value"] - 1})  # fmt: skip

    for t in sessions:
        # a) valorar a la apertura y rebalancear si toca
        if t in exec_at:
            for sym, h in hold.items():
                j = panel.idx(sym, t)
                if j is not None:
                    h["value"] *= panel.data[sym]["open"][j] / h["last_close"]
                    h["last_close"] = panel.data[sym]["open"][j]  # base para el retorno apertura→cierre
            total = cash + sum(h["value"] for h in hold.values())
            new = [s for s in exec_at[t] if panel.idx(s, t) is not None]
            tgt = total / len(new) if new else 0.0
            cost = 0.0
            for sym in list(hold):
                h = hold[sym]
                keep = tgt if sym in new else 0.0
                sold = max(h["value"] - keep, 0.0)
                px = h["last_close"]
                cost += sold * (costs.slip + costs.sec_fee_rate) + min(costs.taf_per_share * sold / px, costs.taf_max)
                if sym not in new:
                    close_out(sym, h, t, h["value"])
                    del hold[sym]
            for sym in new:
                j = panel.idx(sym, t)
                o = panel.data[sym]["open"][j]
                cur = hold[sym]["value"] if sym in hold else 0.0
                cost += max(tgt - cur, 0.0) * costs.slip
                if sym in hold:
                    hold[sym]["value"] = tgt
                else:
                    hold[sym] = {"value": tgt, "last_close": o, "entry_date": t, "entry_value": tgt}
            cash = total - tgt * len(new) - cost
        # b) del precio base (cierre previo o apertura) al cierre de t; deslistados → efectivo al último cierre
        for sym in list(hold):
            h = hold[sym]
            j = panel.idx(sym, t)
            if j is not None:
                c = panel.data[sym]["close"][j]
                h["value"] *= c / h["last_close"]
                h["last_close"] = c
            elif panel.last_date(sym) < int(np.datetime64(t, "D").astype(np.int64)):
                close_out(sym, h, t, h["value"])
                cash += h["value"] * (1 - costs.slip)
                del hold[sym]
        equity = cash + sum(h["value"] for h in hold.values())
        eq_rows.append({"session_date": t, "equity": equity, "ret": equity / prev_equity - 1,
                        "positions": len(hold)})  # fmt: skip
        prev_equity = equity
    for sym, h in hold.items():
        close_out(sym, h, sessions[-1], h["value"])
    per = pl.DataFrame(periods) if periods else pl.DataFrame(schema={"ret": pl.Float64, "entry_date": pl.Date})
    return per, pl.DataFrame(eq_rows)
