"""`daytrader mediodia`: re-evalúa la watchlist de la mañana con datos de AHORA y propone 3 candidatos.

El ranking es DESCRIPTIVO ("¿sigue en juego y es operable con mi cuenta?"), no una señal con ventaja probada.
Todo lo calcula Python; el usuario elige los 3 y luego la dirección con `daytrader contexto`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from daytrader.execution.context import Context, readings


@dataclass
class Candidate:
    symbol: str
    gap_am: float | None  # gap de pre-market de la watchlist (09:25)
    change: float | None  # precio ahora / cierre de ayer − 1
    rvol_rth: float | None  # volumen RTH hasta ahora / (volumen medio diario × fracción de sesión transcurrida)
    range_atr: float | None  # (máx − mín del día) / ATR 14
    spread_pct: float | None
    up: int
    down: int
    price: float
    shares_1r: int  # acciones con riesgo 1% y stop a 0,25 ATR (recortado por capital)
    catalyst: str | None
    score: float
    notes: list[str]

    @property
    def lean(self) -> str:
        d = self.up - self.down
        return "largo" if d >= 2 else "corto" if d <= -2 else "mixto"


def evaluate(c: Context, gap_am: float | None, catalyst: str | None, avg_volume: float | None, rth_volume: float,
             elapsed_frac: float, bid: float | None, ask: float | None, capital: float, risk_pct: float,
             allow_short: bool) -> Candidate:  # fmt: skip
    rd = readings(c)
    up, dn = sum(1 for _, x in rd if x > 0), sum(1 for _, x in rd if x < 0)
    change = c.price / c.prev_close - 1 if c.prev_close else None
    rvol = rth_volume / (avg_volume * elapsed_frac) if avg_volume and elapsed_frac > 0 else None
    rng = (c.day_high - c.day_low) / c.atr14 if c.atr14 and c.day_high and c.day_low else None
    spread = (ask - bid) / ((ask + bid) / 2) if bid and ask and ask > bid else None
    stop_dist = 0.25 * c.atr14 if c.atr14 else None
    shares = 0
    if stop_dist and c.price > 0:
        shares = max(0, min(math.floor(risk_pct * capital / stop_dist), math.floor(capital / c.price)))
    notes = []
    if shares < 5:
        notes.append("precio alto para tu capital: pocas acciones")
    if spread is not None and spread > 0.002:
        notes.append(f"spread amplio ({spread:.2%})")
    if rvol is not None and rvol < 1:
        notes.append("volumen por debajo de lo normal: se enfrió")
    lean = "largo" if up - dn >= 2 else "corto" if dn - up >= 2 else "mixto"
    if lean == "corto" and not allow_short:
        notes.append("se inclina a corto pero tu cuenta no permite cortos")
    if lean == "mixto":
        notes.append("lecturas mixtas")
    # Puntuación: actividad (volumen relativo y rango vs ATR, saturados) × operabilidad (spread, tamaño) × claridad
    act = min(rvol or 0, 5) / 5 + min(rng or 0, 2) / 2
    tradable = (0.5 if spread is not None and spread > 0.002 else 1.0) * (0.5 if shares < 5 else 1.0)
    clarity = 1.0 if lean != "mixto" else 0.6
    if lean == "corto" and not allow_short:
        clarity = 0.3
    return Candidate(c.symbol, gap_am, change, rvol, rng, spread, up, dn, c.price, shares, catalyst,
                     round(act * tradable * clarity, 3), notes)  # fmt: skip


def top3(cands: list[Candidate]) -> list[Candidate]:
    return sorted(cands, key=lambda x: x.score, reverse=True)[:3]
