"""Modelo de costos: comisiones, tasas regulatorias y slippage (spread + impacto).

Sin datos de cotizaciones en el backtest, el medio spread se estima con el rango de las barras de 1 min
previas a la entrada (point-in-time) y se calibra contra NBBO reales de Alpaca (`calibrate.py`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CostModel:
    commission_per_share: float = 0.0
    sec_fee_rate: float = 0.0000278
    taf_per_share: float = 0.000166
    taf_max: float = 8.30
    min_half_spread: float = 0.005
    half_spread_k: float = 0.25
    impact_k: float = 0.5
    lookback_bars: int = 30
    stop_slippage_mult: float = 1.5

    @classmethod
    def from_cfg(cls, costs: dict, execution: dict) -> CostModel:
        return cls(**costs, stop_slippage_mult=execution.get("stop_slippage_mult", 1.5))

    def slippage_per_share(
        self, price: float, prior_high: np.ndarray, prior_low: np.ndarray, prior_close: np.ndarray,
        prior_volume: np.ndarray, shares: int,
    ) -> float:  # fmt: skip
        """Medio spread estimado + impacto de mercado, en $/acción. Solo usa barras previas."""
        h, lo = prior_high[-self.lookback_bars :], prior_low[-self.lookback_bars :]
        rng = float(np.median(h - lo)) if len(h) else 0.0
        half_spread = max(self.min_half_spread, self.half_spread_k * rng)
        c = prior_close[-self.lookback_bars :]
        v = prior_volume[-self.lookback_bars :]
        if len(c) >= 3 and np.all(c > 0):
            sigma = float(np.std(np.diff(np.log(c)), ddof=1))
        else:
            sigma = rng / price if price > 0 else 0.0
        avg_vol = float(np.mean(v)) if len(v) else 0.0
        part = shares / avg_vol if avg_vol > 0 else 1.0
        impact = self.impact_k * sigma * price * math.sqrt(min(part, 10.0))
        return half_spread + impact

    def fees(self, shares: int, entry_px: float, exit_px: float, side: int) -> float:
        """Comisiones + SEC + TAF de una operación completa (ida y vuelta), en $."""
        sell_px = exit_px if side == 1 else entry_px  # el largo vende al salir; el corto vende al entrar
        sec = self.sec_fee_rate * shares * sell_px
        taf = min(self.taf_per_share * shares, self.taf_max)
        return 2 * self.commission_per_share * shares + sec + taf
