"""Estrategias: invariancia a prefijos (anti-lookahead) y lógica básica."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from daytrader.strategies.base import DayContext
from daytrader.strategies.orb import orb
from daytrader.strategies.vwap_reversion import vwap_reversion

D = date(2025, 3, 14)
OPEN = datetime(2025, 3, 14, 13, 30)
CLOSE = datetime(2025, 3, 14, 20, 0)
ORB5 = {"or_minutes": 5, "direction": "both", "stop": "or_opposite", "target_r": 2.0, "min_range_atr": 0.0,
        "max_range_atr": 10.0, "min_or_bars": 3, "last_entry_et": "15:45"}  # fmt: skip
VWAP = {"k_sigma": 1.5, "min_bars": 30, "lookback_extreme": 10, "stop_buffer_atr": 0.0, "min_rr": 0.5,
        "max_hold_minutes": 60, "first_entry_et": "10:00", "last_entry_et": "15:00", "direction": "both",
        "max_trades_per_symbol": 3}  # fmt: skip


def make_bars(closes, start=OPEN, spread=0.05, seed=0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    c = np.asarray(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]
    w = np.abs(rng.normal(0, spread, len(c)))
    ts = [start + timedelta(minutes=i) for i in range(len(c))]
    return pl.DataFrame(
        {"symbol": "AAA", "session_date": D, "ts_utc": ts, "available_at": [t + timedelta(minutes=1) for t in ts],
         "open": o, "high": np.maximum(o, c) + w, "low": np.minimum(o, c) - w, "close": c,
         "volume": rng.integers(1000, 5000, len(c)).astype(float), "vwap": (o + c) / 2, "trade_count": 10},
        schema_overrides={"ts_utc": pl.Datetime("us"), "available_at": pl.Datetime("us")},
    )  # fmt: skip


def ctx(gap=0.05, atr=2.0) -> DayContext:
    return DayContext("AAA", D, 100.0, gap, atr, OPEN, CLOSE)


def random_day(seed: int, n=390) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    return make_bars(100 + np.cumsum(rng.normal(0, 0.15, n)), seed=seed)


@pytest.mark.parametrize("fn,params", [(orb, ORB5), (orb, {**ORB5, "or_minutes": 15}), (vwap_reversion, VWAP)])
@pytest.mark.parametrize("seed", range(25))
def test_prefix_invariance(fn, params, seed):
    """Toda señal decidida en t sale idéntica usando solo barras con available_at <= t,
    y alterar el futuro (después de t) no la cambia."""
    bars = random_day(seed)
    full = fn(bars, ctx(), params)
    for s in full:
        prefix = bars.filter(pl.col("available_at") <= s.decided_at)
        assert s in fn(prefix, ctx(), params)
        future = pl.col("ts_utc") >= s.decided_at
        trapped = bars.with_columns(
            [
                pl.when(future).then(pl.col(x) * 3).otherwise(pl.col(x)).alias(x)
                for x in ("open", "high", "low", "close")
            ]
        )
        assert [x for x in fn(trapped, ctx(), params) if x.decided_at <= s.decided_at] == [
            x for x in full if x.decided_at <= s.decided_at
        ]
    # Ningún prefijo produce señales que no estén en el resultado completo.
    for k in (5, 16, 45, 120, 300):
        t = OPEN + timedelta(minutes=k)
        early = fn(bars.filter(pl.col("available_at") <= t), ctx(), params)
        assert all(s in full for s in early)


def test_orb_long_breakout_levels():
    closes = [100, 100.5, 99.8, 100.2, 100.1] + [100.3] * 5 + [101.5] + [101.6] * 20
    bars = make_bars(closes, spread=0.0)
    sigs = orb(bars, ctx(gap=0.03), {**ORB5, "direction": "with_gap"})
    assert len(sigs) == 1
    s = sigs[0]
    hi = float(bars.head(5)["high"].max())
    lo = float(bars.head(5)["low"].min())
    assert s.side == 1 and s.stop == lo and s.signal_ts == OPEN + timedelta(minutes=10)
    assert s.decided_at == s.signal_ts + timedelta(minutes=1)
    assert s.target == pytest.approx(s.ref_price + 2 * (s.ref_price - lo))
    assert s.ref_price > hi


def test_orb_with_gap_ignores_counter_direction():
    closes = [100, 100.5, 99.8, 100.2, 100.1] + [98.0] * 20
    assert orb(make_bars(closes, spread=0.0), ctx(gap=0.03), {**ORB5, "direction": "with_gap"}) == []
    assert orb(make_bars(closes, spread=0.0), ctx(gap=-0.03), {**ORB5, "direction": "with_gap"})[0].side == -1


def test_orb_no_signal_before_range_complete():
    bars = random_day(1)
    assert orb(bars.filter(pl.col("available_at") <= OPEN + timedelta(minutes=4)), ctx(), ORB5) == []


def test_no_entries_in_last_15_minutes_on_half_day():
    half_close = datetime(2025, 3, 14, 17, 0)  # sesión ficticia que cierra a las 13:00 ET
    c = DayContext("AAA", D, 100.0, 0.05, 2.0, OPEN, half_close)
    closes = [100] * 5 + [100] * 200 + [105] * 10  # ruptura a las 13:05 ET (> cierre - 15 min)
    assert orb(make_bars(closes, spread=0.0), c, ORB5) == []
