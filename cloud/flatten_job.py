"""Guardián en la nube (Heroku Scheduler, cada 10 min): cierra TODO en la cuenta PAPER antes del cierre.

Autorización PERMANENTE del usuario (2026-11-09, opción "a"); interruptor: Config Var DAYTRADER_AUTO_FLATTEN=1
(cualquier otro valor o ausente → no hace nada). Equivale al `daytrader guard` local, sin depender del portátil.

- Solo PAPER: la URL está fija y se verifica; con cualquier otra URL aborta (regla 1 del proyecto).
- Usa /v2/clock de Alpaca: sabe si hay sesión hoy y a qué hora cierra (respeta festivos y medias sesiones).
- Actúa solo si el mercado está abierto y faltan <= WINDOW_MIN minutos para el cierre, y solo si hay posiciones.
- Meta de ganancia diaria (autorizada 2026-11-09): si DAYTRADER_PROFIT_TARGET > 0 y el PnL del día de la cuenta
  (equity − last_equity, realizado + flotante) llega a la meta, cierra todo aunque falte para el cierre.
- Pérdida máxima diaria (autorizada 2026-11-10): si DAYTRADER_LOSS_LIMIT > 0 y el PnL del día <= −límite, cierra todo.
- Cancela órdenes, espera a que se liberen, cierra posiciones y VERIFICA que no quede ninguna (close_all). Idempotente.
Keys (solo PAPER) en Config Vars: ALPACA_API_KEY, ALPACA_SECRET_KEY. Nunca en el código.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime

import requests

PAPER_TRADING_URL = "https://paper-api.alpaca.markets"
WINDOW_MIN = 12  # Scheduler corre cada ~10 min: la ventana cubre un ciclo con margen (cierre ≈ 15:48–15:58 ET)
TIMEOUT = (10, 30)


class LiveTradingForbidden(RuntimeError):
    pass


def assert_paper_url(url: str) -> str:
    if url.rstrip("/") != PAPER_TRADING_URL:
        raise LiveTradingForbidden(f"URL no permitida: {url!r}. Solo {PAPER_TRADING_URL}.")
    return PAPER_TRADING_URL


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def should_flatten(clock: dict, now: datetime, window_min: int = WINDOW_MIN) -> bool:
    """clock: respuesta de /v2/clock. True si el mercado está abierto y faltan <= window_min min al cierre."""
    if not clock.get("is_open"):
        return False
    left = (_ts(clock["next_close"]) - now).total_seconds() / 60
    return 0 < left <= window_min


def run(env: dict | None = None, http=requests, now: datetime | None = None, sleep=time.sleep) -> str:
    env = os.environ if env is None else env
    if env.get("DAYTRADER_AUTO_FLATTEN") != "1":
        return "desactivado (DAYTRADER_AUTO_FLATTEN != 1)"
    base = assert_paper_url(env.get("ALPACA_BASE_URL", PAPER_TRADING_URL))
    h = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"]}
    clock = http.get(f"{base}/v2/clock", headers=h, timeout=TIMEOUT)
    clock.raise_for_status()
    now = now or datetime.now(UTC)
    ck = clock.json()
    in_window = should_flatten(ck, now)
    target = float(env.get("DAYTRADER_PROFIT_TARGET") or 0)
    loss = float(env.get("DAYTRADER_LOSS_LIMIT") or 0)
    if not in_window and not ((target > 0 or loss > 0) and ck.get("is_open")):
        return f"fuera de ventana (próximo cierre {ck.get('next_close')})"
    pos = http.get(f"{base}/v2/positions", headers=h, timeout=TIMEOUT)
    pos.raise_for_status()
    if not pos.json():
        return "sin posiciones"
    if in_window:
        reason = "cierre del día"
    else:
        acct = http.get(f"{base}/v2/account", headers=h, timeout=TIMEOUT)
        acct.raise_for_status()
        a = acct.json()
        pnl = float(a["equity"]) - float(a["last_equity"])
        if target > 0 and pnl >= target:
            reason = f"meta de ganancia: PnL del día {pnl:+.2f} >= {target:.2f}"
        elif loss > 0 and pnl <= -loss:
            reason = f"pérdida máxima: PnL del día {pnl:+.2f} <= -{loss:.2f}"
        else:
            return f"PnL del día {pnl:+.2f} dentro de [-{loss:.2f}, +{target:.2f}]: sin cambios"
    syms = [p["symbol"] for p in pos.json()]
    close_all(base, h, http, sleep)
    return f"CIERRE ({reason}): {len(syms)} posiciones cerradas y órdenes canceladas ({syms})"


def _open(base: str, h: dict, http, what: str) -> list:
    params = {"status": "open"} if what == "orders" else None
    r = http.get(f"{base}/v2/{what}", params=params, headers=h, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def close_all(base: str, h: dict, http, sleep=time.sleep, tries: int = 3) -> None:
    """Cierra TODO de forma verificada.

    Lección 2026-11-10: DELETE /v2/positions?cancel_orders=true canceló los stops/OCO pero la venta fue rechazada
    (acciones aún retenidas por las órdenes en cancelación) y Alpaca responde 207 sin error HTTP → las posiciones
    quedaron abiertas SIN stop. Ahora: 1) cancelar órdenes y esperar a que no quede ninguna abierta; 2) cerrar
    posiciones; 3) verificar que no quede ninguna (reintenta); si quedan, error (sale en el log de Heroku).
    """
    for _ in range(tries):
        http.delete(f"{base}/v2/orders", headers=h, timeout=TIMEOUT).raise_for_status()
        for _ in range(20):
            if not _open(base, h, http, "orders"):
                break
            sleep(0.5)
        http.delete(f"{base}/v2/positions", headers=h, timeout=TIMEOUT).raise_for_status()
        for _ in range(20):
            if not _open(base, h, http, "positions"):
                return
            sleep(0.5)
    left = [p["symbol"] for p in _open(base, h, http, "positions")]
    raise RuntimeError(f"no se pudieron cerrar: {left}")


if __name__ == "__main__":
    try:
        print(f"[{datetime.now(UTC):%Y-%m-%d %H:%M} UTC] {run()}", flush=True)
    except Exception as e:  # noqa: BLE001 — que el log de Heroku muestre el error y el job termine con código 1
        print(f"ERROR: {e!r}", flush=True)
        sys.exit(1)
