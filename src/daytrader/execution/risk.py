"""Risk-manager: tamaño de posición, reglas del día y huella de la orden aprobada. Lógica pura (sin red).

Flujo: build_ticket() → check() → (si OK) huella → confirmación y/n del usuario → el ejecutor solo envía
un ticket cuya huella coincide con la aprobada (idea tomada de day-trader-skill: nada se modifica en medio).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from daytrader.market_calendar import ET


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade: float = 0.01
    daily_loss_limit: float = 0.03
    max_trades_per_day: int = 5
    max_positions: int = 3
    buying_power_mult: float = 4.0
    max_position_pct: float = 1.0
    min_stop_distance_pct: float = 0.002
    max_stop_distance_pct: float = 0.10
    no_entries_last_minutes: int = 15
    no_entries_first_minutes: int = 0
    flatten_et: str = "15:50"
    confirm_timeout_s: int = 60
    max_price_drift_r: float = 0.25
    # Capital con el que se practica (None = capital real de la cuenta paper). Evoluciona con el PnL del journal.
    simulated_capital: float | None = None
    simulated_start: str | None = None  # AAAA-MM-DD: desde cuándo se acumula el PnL al capital simulado
    account_type: str = "margin"  # cash | margin. Cash (< $2.000 en EE. UU.): sin cortos, sin apalancamiento
    # Margen con menos de $25.000 (regla PDT de FINRA): máx. 3 day trades en 5 sesiones y poder de compra 2×
    pdt_equity_min: float = 25_000
    pdt_max_day_trades: int = 3
    small_margin_mult: float = 2.0


@dataclass(frozen=True)
class AccountState:
    equity: float
    last_equity: float  # capital al cierre de la sesión anterior (Alpaca)
    open_positions: int
    open_notional: float
    trades_today: int
    day_notional_used: float = 0.0  # nocional ya comprado hoy (cuenta de efectivo: fondos liquidados)
    day_trades_5d: int = 0  # entradas enviadas en las últimas 5 sesiones, incluida hoy (regla PDT)


@dataclass(frozen=True)
class Session:
    open_utc: datetime
    close_utc: datetime


@dataclass(frozen=True)
class OrderTicket:
    symbol: str
    side: str  # "long" | "short"
    qty: int
    entry_type: str  # "market" | "limit"
    ref_price: float  # precio de referencia (último/medio) usado para dimensionar
    limit_price: float | None
    stop_price: float
    target_price: float | None
    risk_usd: float
    created_at: datetime  # naive UTC
    setup: str = ""
    catalyst: str = ""
    notes: str = ""

    @property
    def direction(self) -> int:
        return 1 if self.side == "long" else -1

    @property
    def risk_per_share(self) -> float:
        return abs((self.limit_price or self.ref_price) - self.stop_price)

    @property
    def notional(self) -> float:
        return self.qty * (self.limit_price or self.ref_price)

    def fingerprint(self) -> str:
        keys = ("symbol", "side", "qty", "entry_type", "limit_price", "stop_price", "target_price")
        payload = {k: getattr(self, k) for k in keys}
        payload = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in payload.items()}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def size_position(equity: float, entry: float, stop: float, cfg: RiskConfig) -> int:
    """Acciones tales que, si salta el stop, se pierde risk_per_trade × capital; recortado por nocional máximo."""
    rps = abs(entry - stop)
    if rps <= 0 or entry <= 0:
        return 0
    by_risk = math.floor(cfg.risk_per_trade * equity / rps)
    by_notional = math.floor(cfg.max_position_pct * equity / entry)
    return max(0, min(by_risk, by_notional))


def build_ticket(
    symbol: str, side: str, ref_price: float, stop: float, target: float | None, account: AccountState,
    cfg: RiskConfig, now_utc: datetime, entry_type: str = "market", limit_price: float | None = None,
    setup: str = "", catalyst: str = "", notes: str = "",
) -> OrderTicket:  # fmt: skip
    entry = limit_price if entry_type == "limit" and limit_price else ref_price
    qty = size_position(account.equity, entry, stop, cfg)
    return OrderTicket(
        symbol=symbol.upper(), side=side, qty=qty, entry_type=entry_type, ref_price=ref_price,
        limit_price=limit_price if entry_type == "limit" else None, stop_price=stop, target_price=target,
        risk_usd=round(qty * abs(entry - stop), 2), created_at=now_utc, setup=setup, catalyst=catalyst, notes=notes,
    )  # fmt: skip


def _et(dt_utc: datetime) -> datetime:
    from datetime import UTC

    return dt_utc.replace(tzinfo=UTC).astimezone(ET)


def check(
    ticket: OrderTicket, account: AccountState, session: Session | None, cfg: RiskConfig, now_utc: datetime
) -> Verdict:
    """Todas las reglas de riesgo. Devuelve OK solo si se cumplen todas (lista de motivos si no)."""
    r: list[str] = []
    d = ticket.direction
    entry = ticket.limit_price or ticket.ref_price
    if ticket.side not in ("long", "short"):
        r.append("lado inválido (long/short)")
    if ticket.qty < 1:
        r.append("tamaño 0: el riesgo por acción es demasiado grande para el 1% del capital")
    # Stop obligatorio y del lado correcto
    if ticket.stop_price is None or (entry - ticket.stop_price) * d <= 0:
        r.append("stop obligatorio y del lado correcto (debajo en largos, encima en cortos)")
    else:
        dist = abs(entry - ticket.stop_price) / entry
        if dist < cfg.min_stop_distance_pct:
            r.append(f"stop demasiado cerca ({dist:.2%} < {cfg.min_stop_distance_pct:.2%})")
        if dist > cfg.max_stop_distance_pct:
            r.append(f"stop demasiado lejos ({dist:.2%} > {cfg.max_stop_distance_pct:.2%})")
    if ticket.target_price is not None and (ticket.target_price - entry) * d <= 0:
        r.append("objetivo del lado incorrecto")
    # Cuenta de efectivo: sin cortos ni apalancamiento; cada dólar se usa una vez al día (fondos liquidados)
    if cfg.account_type == "cash":
        if ticket.side == "short":
            r.append("cuenta de efectivo: no se permite vender en corto (requiere margen, mínimo $2.000)")
        if account.day_notional_used + ticket.notional > account.equity * 1.001:
            r.append(f"cuenta de efectivo: nocional ${ticket.notional:,.2f} + ya usado hoy ${account.day_notional_used:,.2f} "
                     f"> capital ${account.equity:,.2f} (fondos liquidados)")  # fmt: skip
    # Margen con menos de $25.000: regla PDT (cada entrada del sistema se cierra el mismo día = 1 day trade)
    pdt = cfg.account_type == "margin" and account.equity < cfg.pdt_equity_min
    if pdt and account.day_trades_5d >= cfg.pdt_max_day_trades:
        r.append(f"regla PDT: ya hay {account.day_trades_5d} day trades en las últimas 5 sesiones "
                 f"(máx. {cfg.pdt_max_day_trades} con capital < ${cfg.pdt_equity_min:,.0f})")  # fmt: skip
    # Riesgo por trade
    if ticket.risk_usd > cfg.risk_per_trade * account.equity * 1.001:
        r.append(f"riesgo ${ticket.risk_usd:,.2f} > {cfg.risk_per_trade:.0%} del capital")
    # Kill switch diario (realizado + flotante)
    day_pnl = account.equity - account.last_equity
    if day_pnl <= -cfg.daily_loss_limit * account.last_equity:
        r.append(f"KILL SWITCH: PnL del día {day_pnl:,.2f} <= -{cfg.daily_loss_limit:.0%}")
    if account.trades_today >= cfg.max_trades_per_day:
        r.append(f"máximo de {cfg.max_trades_per_day} trades por día alcanzado")
    if account.open_positions >= cfg.max_positions:
        r.append(f"máximo de {cfg.max_positions} posiciones abiertas")
    mult = 1.0 if cfg.account_type == "cash" else (cfg.small_margin_mult if pdt else cfg.buying_power_mult)
    if account.open_notional + ticket.notional > mult * account.equity:
        r.append(f"excede el poder de compra ({mult:g}× capital)")
    if ticket.notional > cfg.max_position_pct * account.equity * 1.001:
        r.append("nocional de la posición > límite por posición")
    # Horario
    if session is None:
        r.append("el mercado está cerrado hoy")
    else:
        if now_utc < session.open_utc + timedelta(minutes=cfg.no_entries_first_minutes):
            r.append("antes de la apertura (o dentro de los minutos iniciales excluidos)")
        if now_utc >= session.close_utc:
            r.append("la sesión de hoy ya cerró")
        elif now_utc >= session.close_utc - timedelta(minutes=cfg.no_entries_last_minutes):
            r.append(f"sin entradas en los últimos {cfg.no_entries_last_minutes} min de la sesión")
    return Verdict(ok=not r, reasons=r)


def price_drift_ok(ticket: OrderTicket, new_price: float, cfg: RiskConfig) -> bool:
    """¿El precio se movió menos de max_price_drift_r × R desde que se creó el ticket?"""
    return abs(new_price - ticket.ref_price) <= cfg.max_price_drift_r * ticket.risk_per_share


def ticket_dict(t: OrderTicket) -> dict:
    d = asdict(t)
    d["fingerprint"] = t.fingerprint()
    return d
