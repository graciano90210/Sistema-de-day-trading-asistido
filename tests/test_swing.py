"""Fase 8 (swing): señales sin lookahead y reglas del motor diario."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from daytrader.backtest.daily import BASE, Panel, SwingCosts, simulate_events, simulate_rotation
from daytrader.strategies import swing

ZERO = SwingCosts(slip=0.0, borrow_annual=0.0, sec_fee_rate=0.0, taf_per_share=0.0)


def _sessions(n: int, start=date(2020, 1, 1)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _random_daily(syms=("AAA", "BBB", "SPY"), n=320, seed=1) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    days = _sessions(n)
    rows = []
    for s in syms:
        c = 50.0
        for d in days:
            o = c * (1 + rng.normal(0, 0.01))
            c = o * (1 + rng.normal(0, 0.02))
            h, lo = max(o, c) * (1 + abs(rng.normal(0, 0.01))), min(o, c) * (1 - abs(rng.normal(0, 0.01)))
            v = float(rng.lognormal(13, 0.6))
            rows.append((s, d, o, h, lo, c, v))
    return pl.DataFrame(rows, schema=["symbol", "session_date", "open", "high", "low", "close", "volume"],
                        orient="row")  # fmt: skip


def _uni(df: pl.DataFrame) -> pl.DataFrame:
    years = df["session_date"].dt.year().unique().to_list()
    syms = [s for s in df["symbol"].unique().to_list() if s != "SPY"]
    return pl.DataFrame([(y, s, 1e9) for y in years for s in syms], schema=["year", "symbol", "adv_usd"],
                        orient="row")  # fmt: skip


@pytest.mark.parametrize("cut", [150, 230, 300])
def test_indicators_and_event_signals_prefix_invariant(cut):
    full = _random_daily()
    days = sorted(full["session_date"].unique().to_list())
    pre = full.filter(pl.col("session_date") <= days[cut])
    a, b = swing.indicators(full), swing.indicators(pre)
    cols = ["atr14", "atr14_prev", "vol50_prev", "sma200", "sma5", "rsi2", "range_pos"]
    fa = a.filter(pl.col("session_date") <= days[cut]).sort("symbol", "session_date").select(cols)
    assert fa.equals(b.sort("symbol", "session_date").select(cols), null_equal=True)
    uni = _uni(full)
    p3 = {"vol_mult": 1.5, "atr_mult": 0.5, "close_frac": 0.3, "stop_atr": 2.0, "max_hold": 10}
    p4 = {"rsi_max": 30.0, "stop_atr": 2.5, "max_hold": 10}
    for f, p in ((swing.s3_volume_shock, p3), (swing.s4_rsi2, p4)):
        sa = f(a, uni, p).filter(pl.col("session_date") <= days[cut]).sort("symbol", "session_date")
        sb = f(b, uni, p).sort("symbol", "session_date")
        assert sa.height > 0 or (f is swing.s4_rsi2 and cut < 200)  # S4 necesita SMA200
        assert sa.equals(sb)


def test_rotation_targets_prefix_invariant():
    full = _random_daily(syms=("AAA", "BBB", "CCC", "DDD", "SPY"), n=320)
    days = sorted(full["session_date"].unique().to_list())
    cut = days[290]
    ia, ib = swing.indicators(full), swing.indicators(full.filter(pl.col("session_date") <= cut))
    uni = _uni(full)
    p2 = {"window": 5, "top": 2, "min_price": 1.0, "max_drop": 0.9}
    t_a = swing.s2_reversal(ia, uni, days, p2)
    t_b = swing.s2_reversal(ib, uni, [d for d in days if d <= cut], p2)
    assert {d: s for d, s in t_a.items() if d <= cut and d in t_b} == t_b or all(
        t_a[d] == t_b[d]
        for d in t_b
        if d in t_a and d < cut  # la última semana puede estar incompleta en el corte
    )


def test_s3_detects_volume_shock_with_strong_close():
    days = _sessions(80)
    rows = []
    for i, d in enumerate(days):
        o = c = 100.0
        h, lo, v = 101.0, 99.0, 1e6
        if i == 70:  # shock: +8 %, volumen 5×, cierre en el máximo
            o, h, lo, c, v = 100.0, 108.0, 99.5, 108.0, 5e6
        rows.append(("AAA", d, o, h, lo, c, v))
    df = pl.DataFrame(rows, schema=["symbol", "session_date", "open", "high", "low", "close", "volume"], orient="row")
    p = {"vol_mult": 3.0, "atr_mult": 1.5, "close_frac": 0.3, "stop_atr": 2.0, "max_hold": 10}
    sig = swing.s3_volume_shock(swing.indicators(df), _uni(df), p)
    assert sig.height == 1 and sig["session_date"][0] == days[70] and sig["side"][0] == 1


def _bars(sym, days, ohlc):
    return pl.DataFrame([(sym, d, *x) for d, x in zip(days, ohlc, strict=True)],
                        schema=["symbol", "session_date", "open", "high", "low", "close"], orient="row")  # fmt: skip


def _sig(sym, d, side=1, stop=5.0, hold=3, rule="time"):
    return pl.DataFrame([{"symbol": sym, "session_date": d, "side": side, "stop_dist": stop, "max_hold": hold,
                          "exit_rule": rule, "prio": 1.0}])  # fmt: skip


def test_events_entry_next_open_and_time_exit():
    days = _sessions(6)
    ohlc = [(100, 101, 99, 100), (102, 104, 101, 103), (103, 105, 102, 104), (104, 106, 103, 105),
            (105, 107, 104, 106), (106, 107, 105, 106)]  # fmt: skip
    tr, eq = simulate_events(_sig("AAA", days[0], hold=3), Panel(_bars("AAA", days, ohlc)), days, ZERO)
    t = tr.row(0, named=True)
    assert t["entry_date"] == days[1] and t["entry_px"] == 102  # apertura de D+1
    assert t["exit_date"] == days[3] and t["exit_px"] == 105 and t["reason"] == "time"  # cierre de la 3.ª sesión
    assert t["r_net"] == pytest.approx(3 / 5)


def test_events_gap_through_stop_exits_at_open():
    days = _sessions(4)
    ohlc = [(100, 101, 99, 100), (100, 101, 99, 100), (90, 92, 89, 91), (91, 92, 90, 91)]
    tr, _ = simulate_events(_sig("AAA", days[0], stop=5.0, hold=10), Panel(_bars("AAA", days, ohlc)), days, ZERO)
    t = tr.row(0, named=True)
    assert t["reason"] == "stop_gap" and t["exit_px"] == 90 and t["r_net"] == pytest.approx(-2.0)


def test_events_stop_and_exit_same_day_counts_stop_and_short_mirror():
    days = _sessions(4)
    ohlc = [(100, 101, 99, 100), (100, 103, 99, 101), (101, 106, 100, 99), (99, 100, 98, 99)]
    tr, _ = simulate_events(_sig("AAA", days[0], side=-1, stop=5.0, hold=2), Panel(_bars("AAA", days, ohlc)),
                            days, ZERO)  # fmt: skip
    t = tr.row(0, named=True)
    assert t["reason"] == "stop" and t["exit_px"] == 105 and t["r_net"] == pytest.approx(-1.0)


def test_events_costs_reduce_r():
    days = _sessions(6)
    ohlc = [(100, 101, 99, 100), (102, 104, 101, 103), (103, 105, 102, 104), (104, 106, 103, 105),
            (105, 107, 104, 106), (106, 107, 105, 106)]  # fmt: skip
    tr0, _ = simulate_events(_sig("AAA", days[0]), Panel(_bars("AAA", days, ohlc)), days, ZERO)
    tr1, _ = simulate_events(_sig("AAA", days[0]), Panel(_bars("AAA", days, ohlc)), days, BASE)
    assert tr1["r_net"][0] < tr0["r_net"][0]


def test_rotation_equal_weight_and_delisting():
    days = _sessions(5)
    a = _bars("AAA", days, [(10, 10, 10, 10), (10, 11, 10, 11), (11, 12, 11, 12), (12, 12, 12, 12), (12, 12, 12, 12)])
    b = _bars("BBB", days[:3], [(20, 20, 20, 20), (20, 20, 20, 20), (20, 20, 20, 10)])  # deja de cotizar
    per, eq = simulate_rotation({days[0]: ["AAA", "BBB"]}, Panel(pl.concat([a, b])), days, ZERO)
    v = eq["equity"].to_list()
    assert v[1] == pytest.approx(50_000 * 1.1 + 50_000)  # AAA abre 10 → cierra 11
    assert v[2] == pytest.approx(50_000 * 1.2 + 25_000)
    assert v[4] == pytest.approx(60_000 + 25_000)  # BBB pasó a efectivo a su último cierre
    assert per.filter(pl.col("symbol") == "BBB")["ret"][0] == pytest.approx(-0.5)


def test_s1_cash_when_spy_below_sma200_and_picks_winner():
    days = _sessions(560)
    rows = []
    for i, d in enumerate(days):
        for s, g in (("WIN", 0.002), ("LOS", -0.001)):
            c = 100 * (1 + g) ** i
            rows.append((s, d, c, c, c, c, 1e6))
        spy = 100 * (1.0005**i if i < 500 else 1.0005**500 * 0.99 ** (i - 500))
        rows.append(("SPY", d, spy, spy, spy, spy, 1e6))
    df = pl.DataFrame(rows, schema=["symbol", "session_date", "open", "high", "low", "close", "volume"], orient="row")
    ind = swing.indicators(df)
    spy = ind.filter(pl.col("symbol") == "SPY")
    tg = swing.s1_momentum(ind, _uni(df), spy, days, {"lookback_months": 12, "skip_months": 1, "top": 1})
    filled = [d for d, s in tg.items() if s]
    assert filled and all(tg[d] == ["WIN"] for d in filled)
    assert tg[max(tg)] == []  # al final SPY cae bajo su SMA200 → efectivo
