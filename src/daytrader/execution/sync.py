"""Sincroniza las órdenes ejecutadas en Alpaca paper con el journal: precio real, salida, R y slippage real.

El slippage real (precio ejecutado vs. precio de referencia del ticket) permite validar el modelo de
costos del backtester con datos en vivo.
"""

from __future__ import annotations

from datetime import date, timedelta

LOOKBACK_DAYS = 7  # upsert por huella: re-sincronizar trades ya guardados es inocuo

def _f(x):
    return None if x is None else float(x)


def _val(x) -> str:
    return str(getattr(x, "value", x)).lower()


def build_trades(orders: list, tickets: dict[str, dict]) -> list[dict]:
    """orders: objetos Order de alpaca-py (anidados). tickets: fingerprint → fila del journal."""
    out = []
    flat = [o for o in orders if not str(o.client_order_id or "").startswith("dt-") and _val(o.status) == "filled"]
    for o in orders:
        coid = str(o.client_order_id or "")
        if not coid.startswith("dt-") or _val(o.status) != "filled":
            continue
        fp = coid.split("-")[1]
        tk = tickets.get(fp)
        if tk is None:
            continue
        d = 1 if tk["side"] == "long" else -1
        entry, entry_ts = _f(o.filled_avg_price), o.filled_at
        exit_px = exit_ts = reason = None
        for leg in o.legs or []:
            if _val(leg.status) == "filled":
                exit_px, exit_ts = _f(leg.filled_avg_price), leg.filled_at
                reason = "objetivo" if "limit" in _val(leg.order_type) else "stop"
        if exit_px is None:  # salida por la OCO del comando `objetivo` (prefijo dx-<huella>-)
            for x in orders:
                if not str(x.client_order_id or "").startswith(f"dx-{fp}-"):
                    continue
                if _val(x.status) == "filled":
                    kind = "objetivo" if "limit" in _val(x.order_type) else "stop"
                    exit_px, exit_ts, reason = _f(x.filled_avg_price), x.filled_at, kind
                for leg in x.legs or []:
                    if _val(leg.status) == "filled":
                        kind = "objetivo" if "limit" in _val(leg.order_type) else "stop"
                        exit_px, exit_ts, reason = _f(leg.filled_avg_price), leg.filled_at, kind
        if exit_px is None:  # cerrada por el cierre forzado (orden sin prefijo dt-)
            cands = [c for c in flat if c.symbol == o.symbol and c.filled_at and entry_ts and c.filled_at > entry_ts]
            if cands:
                c = min(cands, key=lambda c: c.filled_at)
                exit_px, exit_ts, reason = _f(c.filled_avg_price), c.filled_at, "cierre"
        if exit_px is None:
            continue  # sigue abierta
        planned = abs((tk["limit_price"] or tk["ref_price"]) - tk["stop_price"])
        qty = _f(o.filled_qty)
        slip = (entry - tk["ref_price"]) * d
        out.append({
            "fingerprint": fp, "session_date": entry_ts.date() if entry_ts else None, "symbol": o.symbol,
            "side": tk["side"], "qty": qty, "entry_ts": entry_ts.replace(tzinfo=None) if entry_ts else None,
            "entry_px": entry, "exit_ts": exit_ts.replace(tzinfo=None) if exit_ts else None, "exit_px": exit_px,
            "exit_reason": reason, "pnl": (exit_px - entry) * d * qty,
            "r_multiple": (exit_px - entry) * d / planned if planned else None,
            "entry_slippage": slip, "entry_slippage_r": slip / planned if planned else None,
        })  # fmt: skip
    return out


def sync_day(broker, journal, day: date) -> int:
    tickets = {
        r["fingerprint"]: r
        for r in journal.query("SELECT * FROM tickets WHERE status = 'enviado'").iter_rows(named=True)
    }
    # mirar atrás: una posición que pasó la noche abierta (p. ej. 2026-11-10 → 11-11) tiene la entrada en otro día
    rows = build_trades(broker.orders_since(day - timedelta(days=LOOKBACK_DAYS)), tickets)
    for r in rows:
        journal.upsert_trade(r)
    return len(rows)
