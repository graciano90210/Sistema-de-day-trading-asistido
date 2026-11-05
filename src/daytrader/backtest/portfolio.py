"""Simulación de cartera sobre la lista de trades (R neto a tamaño de referencia).

Reglas (mismas que aplicará el risk-manager en fase 5):
- Riesgo por trade = risk_per_trade × capital vigente al entrar → PnL$ = R_neto × riesgo$.
- Máximo de posiciones simultáneas y de trades por día.
- Kill switch diario: sin nuevas entradas si el PnL realizado del día <= -daily_loss_limit × capital inicial del día.
- Poder de compra: nocional abierto total <= buying_power_mult × capital.
Los trades se procesan por hora de entrada; una entrada solo "ve" los cierres anteriores a ella.
"""

from __future__ import annotations

from datetime import date

import polars as pl


def simulate_portfolio(
    trades: pl.DataFrame, acct: dict, sessions_list: list[date]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Devuelve (trades con columnas taken/skip_reason/pnl_usd, equity diaria)."""
    equity = float(acct["initial_equity"])
    if trades.is_empty():
        eq = pl.DataFrame({"session_date": sessions_list, "equity": [equity] * len(sessions_list)})
        return trades, eq.with_columns(pl.lit(0.0).alias("ret"))
    t = trades.sort("entry_ts", "symbol")
    risk_pct, max_pos = float(acct["risk_per_trade"]), int(acct["max_positions"])
    max_day, dll, bp_mult = (
        int(acct["max_trades_per_day"]),
        float(acct["daily_loss_limit"]),
        float(acct["buying_power_mult"]),
    )

    open_pos: list[tuple] = []  # (exit_ts, pnl_usd, notional)
    cur_day, day_start_eq, day_realized, day_count = None, equity, 0.0, 0
    taken, reasons, pnls, risks = [], [], [], []

    def release(until):
        nonlocal equity, day_realized
        keep = []
        for p in open_pos:
            if until is None or p[0] <= until:
                equity += p[1]
                day_realized += p[1]
            else:
                keep.append(p)
        open_pos[:] = keep

    for row in t.iter_rows(named=True):
        if row["session_date"] != cur_day:
            release(None)  # todas las posiciones cierran antes del fin de sesión
            cur_day, day_start_eq, day_realized, day_count = row["session_date"], equity, 0.0, 0
        release(row["entry_ts"])
        risk_usd = risk_pct * equity
        scale = risk_usd / (row["shares"] * row["planned_risk"])
        notional = row["shares"] * scale * row["entry_px"]
        reason = None
        if day_realized <= -dll * day_start_eq:
            reason = "kill_switch"
        elif len(open_pos) >= max_pos:
            reason = "max_posiciones"
        elif day_count >= max_day:
            reason = "max_trades_dia"
        elif sum(p[2] for p in open_pos) + notional > bp_mult * equity:
            reason = "poder_compra"
        if reason:
            taken.append(False), reasons.append(reason), pnls.append(0.0), risks.append(0.0)
            continue
        pnl = row["r_net"] * risk_usd
        open_pos.append((row["exit_ts"], pnl, notional))
        day_count += 1
        taken.append(True), reasons.append(None), pnls.append(pnl), risks.append(risk_usd)
    release(None)

    out = t.with_columns(
        pl.Series("taken", taken), pl.Series("skip_reason", reasons, dtype=pl.Utf8),
        pl.Series("pnl_usd", pnls), pl.Series("risk_usd", risks),
    )  # fmt: skip
    daily = out.filter(pl.col("taken")).group_by("session_date").agg(pl.col("pnl_usd").sum().alias("pnl"))
    eq = (
        pl.DataFrame({"session_date": sessions_list})
        .join(daily, on="session_date", how="left")
        .with_columns(pl.col("pnl").fill_null(0.0))
        .sort("session_date")
        .with_columns((float(acct["initial_equity"]) + pl.col("pnl").cum_sum()).alias("equity"))
        .with_columns((pl.col("pnl") / (pl.col("equity") - pl.col("pnl"))).alias("ret"))
    )
    return out, eq
