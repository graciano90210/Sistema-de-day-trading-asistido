"""Contrato de estrategias.

Una estrategia es una función pura `(bars, ctx, params) -> list[Signal]`:
- `bars`: barras RTH de 1 min de UN símbolo en UNA sesión, ordenadas, con `available_at`.
- Debe ser **invariante a prefijos**: la señal decidida en t debe salir idéntica si se le pasan solo
  las barras con available_at <= t. `tests/test_strategies.py` lo verifica (anti-lookahead).
- No accede a la base de datos ni al reloj.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import polars as pl

from daytrader.market_calendar import et_to_utc_naive


@dataclass(frozen=True)
class DayContext:
    symbol: str
    session_date: date
    prev_close: float
    gap: float | None  # gap de pre-market (último pre-market / cierre anterior - 1), conocido a las 09:25
    atr14: float
    open_utc: datetime
    close_utc: datetime
    catalyst: str | None = None

    def et(self, hhmm: str) -> datetime:
        h, m = hhmm.split(":")
        return et_to_utc_naive(self.session_date, time(int(h), int(m)))

    def last_entry(self, hhmm: str) -> datetime:
        """Hora límite de entrada, nunca dentro de los últimos 15 min (respeta medias sesiones)."""
        return min(self.et(hhmm), self.close_utc - timedelta(minutes=15))


@dataclass(frozen=True)
class Signal:
    symbol: str
    session_date: date
    strategy: str
    side: int  # +1 largo, -1 corto
    signal_ts: datetime  # inicio de la barra que confirma la señal
    decided_at: datetime  # = available_at de esa barra; la entrada es posterior
    ref_price: float  # cierre de la barra de señal (para dimensionar)
    stop: float
    target: float | None
    max_hold: timedelta | None = None
    meta: dict = field(default_factory=dict, compare=False)
    # Orden stop de entrada (ronda 2): se ejecuta cuando el precio alcanza entry_level entre decided_at y valid_until.
    entry_type: str = "next_open"  # next_open | stop
    entry_level: float | None = None
    stop_offset: float | None = None  # stop = precio ejecutado ∓ stop_offset (si se define, reemplaza a `stop`)
    valid_until: datetime | None = None
    # Orden límite de entrada (ronda 3): L = ref_price − lado × limit_offset_hs × medio spread estimado.
    limit_offset_hs: float | None = None
    # Ronda 4: objetivo a `target_r` × riesgo desde el precio de entrada ejecutado (órdenes stop de entrada).
    target_r: float | None = None

    @property
    def planned_risk(self) -> float:
        if self.stop_offset is not None:
            return self.stop_offset
        return abs(self.ref_price - self.stop)


StrategyFn = Callable[[pl.DataFrame, DayContext, dict], list[Signal]]


def get_strategy(kind: str) -> StrategyFn:
    from daytrader.strategies.orb import orb
    from daytrader.strategies.orb_stop import orb_stop
    from daytrader.strategies.patterns import double, flag
    from daytrader.strategies.vwap_limit import vwap_limit
    from daytrader.strategies.vwap_reversion import vwap_reversion

    return {"orb": orb, "orb_stop": orb_stop, "vwap_reversion": vwap_reversion, "vwap_limit": vwap_limit,
            "flag": flag, "double": double}[kind]  # fmt: skip
