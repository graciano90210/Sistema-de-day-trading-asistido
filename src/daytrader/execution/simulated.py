"""Capital simulado: practicar en la cuenta paper con el tamaño real que se operará después.

capital simulado de hoy = capital inicial + PnL realizado (journal) desde `simulated_start` hasta ayer
                          + PnL del día de la cuenta paper (realizado + flotante; solo operan trades del sistema).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from daytrader.execution.risk import AccountState, RiskConfig


def account_state(broker_equity: float, broker_last_equity: float, open_positions: int, open_notional: float,
                  trades_today: int, day_notional: float, realized_before_today: float, cfg: RiskConfig) -> AccountState:  # fmt: skip
    if cfg.simulated_capital is None:
        return AccountState(
            broker_equity, broker_last_equity, open_positions, open_notional, trades_today, day_notional
        )
    start_of_day = float(cfg.simulated_capital) + realized_before_today
    day_pnl = broker_equity - broker_last_equity
    return AccountState(start_of_day + day_pnl, start_of_day, open_positions, open_notional, trades_today, day_notional)


def pdt_window_start(today: date) -> date:
    """Primera de las 5 sesiones NYSE que terminan hoy (o en la última sesión si hoy no hay mercado)."""
    from daytrader.market_calendar import sessions

    return sessions(today - timedelta(days=14), today)["session_date"].to_list()[-5]


def from_broker(broker, journal, cfg: RiskConfig, today: date) -> AccountState:
    a = broker.client.get_account()
    pos = broker.client.get_all_positions()
    since = date.fromisoformat(cfg.simulated_start) if cfg.simulated_start else today
    st = account_state(
        float(a.equity), float(a.last_equity), len(pos), sum(abs(float(p.market_value)) for p in pos),
        journal.trades_today(today), journal.notional_today(today), journal.realized_pnl(since, today), cfg,
    )  # fmt: skip
    return replace(st, day_trades_5d=journal.entries_since(pdt_window_start(today)))
