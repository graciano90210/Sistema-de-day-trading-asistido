"""Flujo de una orden: ticket → reglas de riesgo → confirmación y/n (con caducidad) → re-verificación → envío.

Regla 2 del proyecto: NINGUNA orden se envía sin una 'y' explícita del usuario en la consola.
El envío exige que la huella del ticket coincida con la aprobada (nada cambia entre confirmar y enviar).
"""

from __future__ import annotations

import select
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from daytrader.execution.journal import Journal
from daytrader.execution.risk import AccountState, OrderTicket, RiskConfig, Session, check, price_drift_ok


class FingerprintMismatch(RuntimeError):
    """El ticket a enviar no es el que el usuario aprobó."""


def ask_yes_no(prompt: str, timeout_s: int) -> str | None:
    """Pregunta en consola; devuelve 'y', 'n' u otra respuesta, o None si caduca."""
    print(prompt, end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if not ready:
        print()
        return None
    return sys.stdin.readline().strip().lower()


@dataclass
class Outcome:
    status: str  # rechazado | declinado | caducado | deriva | enviado | error
    reasons: list[str]
    order_id: str | None = None


def submit_approved(broker, ticket: OrderTicket, approved_fp: str, client_order_id: str):
    if ticket.fingerprint() != approved_fp:
        raise FingerprintMismatch(f"huella {ticket.fingerprint()} != aprobada {approved_fp}")
    return broker.submit(ticket, client_order_id)


def run_ticket(
    ticket: OrderTicket, account: AccountState, session: Session | None, cfg: RiskConfig, broker, journal: Journal,
    now: Callable[[], datetime], ask: Callable[[str, int], str | None], show: Callable[[OrderTicket], None],
    requote: Callable[[str], float],
) -> Outcome:  # fmt: skip
    v = check(ticket, account, session, cfg, now())
    if not v.ok:
        journal.record_ticket(ticket, "rechazado", v.reasons)
        return Outcome("rechazado", v.reasons)
    show(ticket)
    fp = ticket.fingerprint()
    answer = ask(f"¿Enviar esta orden a la cuenta PAPER? (y/n) [{cfg.confirm_timeout_s}s]: ", cfg.confirm_timeout_s)
    if answer is None:
        journal.record_ticket(ticket, "caducado", ["sin respuesta dentro del plazo"])
        return Outcome("caducado", ["sin respuesta dentro del plazo"])
    if answer != "y":
        journal.record_ticket(ticket, "declinado", [f"respuesta: {answer!r}"])
        return Outcome("declinado", [f"respuesta: {answer!r}"])
    # Re-verificación tras la confirmación: precio y reglas (el tiempo pasó).
    px = requote(ticket.symbol)
    if ticket.entry_type == "market" and not price_drift_ok(ticket, px, cfg):
        reason = f"el precio se movió de {ticket.ref_price:.2f} a {px:.2f} (> {cfg.max_price_drift_r} R)"
        journal.record_ticket(ticket, "deriva", [reason])
        return Outcome("deriva", [reason])
    v2 = check(ticket, account, session, cfg, now())
    if not v2.ok:
        journal.record_ticket(ticket, "rechazado", v2.reasons)
        return Outcome("rechazado", v2.reasons)
    coid = f"dt-{fp}-{now():%H%M%S}"
    try:
        order = submit_approved(broker, ticket, fp, coid)
    except Exception as exc:  # error del broker: se registra, no se reintenta solo
        journal.record_ticket(ticket, "error", [str(exc)[:300]], client_order_id=coid)
        return Outcome("error", [str(exc)[:300]])
    oid = str(getattr(order, "id", "") or "")
    journal.record_ticket(ticket, "enviado", [], order_id=oid, client_order_id=coid)
    return Outcome("enviado", [], oid)
