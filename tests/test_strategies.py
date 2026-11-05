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


from daytrader.strategies.orb_stop import orb_stop  # noqa: E402

ORBSTOP = {"or_minutes": 5, "stop_atr": 0.10, "min_or_bars": 3, "last_entry_et": "15:45"}


@pytest.mark.parametrize("seed", range(25))
def test_orb_stop_prefix_invariance(seed):
    bars = random_day(seed)
    full = orb_stop(bars, ctx(), ORBSTOP)
    for s in full:
        assert s.decided_at == OPEN + timedelta(minutes=5)
        assert s in orb_stop(bars.filter(pl.col("available_at") <= s.decided_at), ctx(), ORBSTOP)
    assert orb_stop(bars.filter(pl.col("available_at") <= OPEN + timedelta(minutes=4)), ctx(), ORBSTOP) == []


def test_orb_stop_direction_and_levels():
    up = make_bars([100, 100.4, 100.8, 101.0, 101.2] + [101] * 10, spread=0.0)
    s = orb_stop(up, ctx(atr=3.0), ORBSTOP)[0]
    assert s.side == 1 and s.entry_level == float(up.head(5)["high"].max()) and s.stop_offset == pytest.approx(0.3)
    down = make_bars([100, 99.6, 99.2, 99.0, 98.8] + [99] * 10, spread=0.0)
    assert orb_stop(down, ctx(), ORBSTOP)[0].side == -1
    doji = make_bars([100, 100.5, 99.5, 100.2, 100.0] + [100] * 10, spread=0.0)
    doji = doji.with_columns(pl.when(pl.col("ts_utc") == OPEN).then(100.0).otherwise(pl.col("open")).alias("open"))
    assert orb_stop(doji, ctx(), ORBSTOP) == []


# ---------------- Ronda 4: patrones ----------------
from daytrader.config import load_yaml  # noqa: E402
from daytrader.strategies.patterns import double, flag  # noqa: E402

_S = load_yaml("strategies.yaml")
P1, P2 = _S["p1_flag"], _S["p2_double"]


# Parámetros relajados SOLO aquí para que el ruido aleatorio genere señales (se prueba el anti-lookahead, no la regla).
@pytest.mark.parametrize("fn,params", [(flag, {**P1, "vol_ratio": 10.0, "pole_atr": 0.3}),
                                       (double, {**P2, "tol_atr": 0.3, "depth_atr": 0.15})])  # fmt: skip
def test_patterns_prefix_invariance(fn, params):
    """Mismo test anti-lookahead que las demás estrategias, sobre 60 días aleatorios; exige que haya señales."""
    n_sig = 0
    for seed in range(60):
        bars = random_day(seed)
        full = fn(bars, ctx(atr=1.5), params)
        n_sig += len(full)
        for s in full:
            assert s.decided_at > s.signal_ts
            prefix = bars.filter(pl.col("available_at") <= s.decided_at)
            assert fn(prefix, ctx(atr=1.5), params) == [s]
            future = pl.col("ts_utc") >= s.decided_at
            trapped = bars.with_columns(
                [pl.when(future).then(pl.col(x) * 3).otherwise(pl.col(x)).alias(x) for x in ("open", "high", "low", "close")]
            )  # fmt: skip
            assert fn(trapped, ctx(atr=1.5), params) == [s]
        for k in (40, 95, 200):
            early = fn(bars.filter(pl.col("available_at") <= OPEN + timedelta(minutes=k)), ctx(atr=1.5), params)
            assert all(s in full for s in early)
    assert n_sig >= 5


def _five_min_path(points: list[float], vols: list[float] | None = None) -> pl.DataFrame:
    """Barras de 1 min que recorren linealmente cada vela de 5 min entre puntos dados (cierres de 5 min)."""
    closes, vol = [], []
    for k in range(1, len(points)):
        closes += list(np.linspace(points[k - 1], points[k], 6)[1:])
        vol += [(vols[k] if vols else 3000.0)] * 5
    b = make_bars(closes, spread=0.0)
    return b.with_columns(pl.Series("volume", vol))


def test_bull_flag_detected_with_levels():
    # 30 min planos, mástil de 100 → 101,2 (3 velas, volumen alto), bandera de 4 velas en 100,9–101,1 (volumen bajo)
    pts = [100.0] * 7 + [100.4, 100.8, 101.2] + [101.0, 100.95, 101.05, 101.0]
    vols = [3000.0] * 7 + [9000.0] * 3 + [2000.0] * 4
    s = flag(_five_min_path(pts, vols), ctx(atr=2.0), P1)
    assert len(s) == 1 and s[0].side == 1 and s[0].entry_type == "stop" and s[0].target_r == 2.0
    assert s[0].entry_level > s[0].stop and s[0].entry_level <= 101.2 + 0.01 + 1e-9


def test_double_bottom_detected():
    # caída 103 → 100, rebote a 101, vuelta a 100,05, y sube sin cruzar el cuello
    down = list(np.linspace(103, 100, 9))
    pts = [103.0] * 4 + down + [100.5, 101.0, 101.0, 100.6, 100.05, 100.3, 100.5, 100.6]
    s = double(_five_min_path(pts), ctx(atr=2.0), P2)
    assert len(s) == 1 and s[0].side == 1
    assert abs(s[0].entry_level - 101.01) < 0.02 and s[0].stop < 100.05
