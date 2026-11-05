"""Motor de ejecución, cartera, métricas y candado OOS."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from daytrader.backtest.costs import CostModel
from daytrader.backtest.engine import simulate
from daytrader.backtest.metrics import equity_stats, trade_stats
from daytrader.backtest.portfolio import simulate_portfolio
from daytrader.backtest.runner import HoldoutSealed, check_holdout
from daytrader.strategies.base import Signal

D = date(2025, 3, 14)
T0 = datetime(2025, 3, 14, 13, 30)
EOD = datetime(2025, 3, 14, 19, 50)
FREE = CostModel(
    commission_per_share=0, sec_fee_rate=0, taf_per_share=0, min_half_spread=0, half_spread_k=0, impact_k=0
)


def bars(ohlc: list[tuple[float, float, float, float]]) -> pl.DataFrame:
    ts = [T0 + timedelta(minutes=i) for i in range(len(ohlc))]
    o, h, lw, c = ([float(x) for x in col] for col in zip(*ohlc, strict=True))
    return pl.DataFrame(
        {"ts_utc": ts, "available_at": [t + timedelta(minutes=1) for t in ts], "open": o, "high": h, "low": lw,
         "close": c, "volume": [1e5] * len(ts)},
        schema_overrides={"ts_utc": pl.Datetime("us"), "available_at": pl.Datetime("us")},
    )  # fmt: skip


def sig(side=1, stop=99.0, target=102.0, decided_min=1, ref=100.0, max_hold=None) -> Signal:
    return Signal("AAA", D, "t", side, T0, T0 + timedelta(minutes=decided_min), ref, stop, target, max_hold)


FLAT = (100, 100.5, 99.5, 100)


def test_entry_is_next_bar_open_not_signal_close():
    b = bars([(100, 100, 100, 100), (100.3, 100.4, 100.2, 100.3)] + [FLAT] * 5)
    t = simulate(sig(), b, FREE, EOD, 100)
    assert t.entry_ts == T0 + timedelta(minutes=1) and t.entry_px == 100.3


def test_gap_through_stop_fills_at_open_worse_than_stop():
    b = bars([FLAT, FLAT, (98.0, 98.2, 97.5, 98.0)])
    t = simulate(sig(stop=99.0), b, FREE, EOD, 100)
    assert t.exit_reason == "stop" and t.exit_px == 98.0 and t.r_net < -1


def test_stop_and_target_same_bar_counts_as_stop():
    b = bars([FLAT, FLAT, (100, 103, 98.5, 100)])
    assert simulate(sig(), b, FREE, EOD, 100).exit_reason == "stop"


def test_target_must_be_exceeded_not_touched():
    b = bars([FLAT, FLAT, (100, 102.0, 99.8, 101), (101, 102.01, 100.5, 102)])
    t = simulate(sig(), b, FREE, EOD, 100)
    assert t.exit_reason == "target" and t.exit_ts == T0 + timedelta(minutes=3) and t.exit_px == 102.0


def test_target_not_credited_on_entry_bar_but_stop_is():
    b = bars([FLAT, (100, 105, 99.9, 104)] + [FLAT] * 3)
    assert simulate(sig(), b, FREE, EOD, 100).exit_reason != "target"
    b = bars([FLAT, (100, 100.2, 98.0, 98.5)] + [FLAT] * 3)
    t = simulate(sig(), b, FREE, EOD, 100)
    assert t.exit_reason == "stop" and t.exit_ts == T0 + timedelta(minutes=1)


def test_short_mirror_and_eod_exit():
    b = bars([FLAT] * 3 + [(99, 99.2, 98.8, 99)] * 3)
    eod = T0 + timedelta(minutes=4)
    t = simulate(sig(side=-1, stop=101.0, target=95.0), b, FREE, eod, 100)
    assert t.exit_reason == "eod" and t.exit_ts == eod and t.entry_px == 100 and t.exit_px == 99
    assert t.r_net == pytest.approx(1.0)


def test_time_stop():
    b = bars([FLAT] * 20)
    t = simulate(sig(max_hold=timedelta(minutes=5)), b, FREE, EOD, 100)
    assert t.exit_reason == "time" and t.exit_ts == T0 + timedelta(minutes=6)


def test_costs_reduce_r_and_slippage_uses_only_prior_bars():
    pre = [(100, 100.5, 99.5, 100)] * 30
    post = [(100, 100.1, 99.9, 100), (100, 200, 0.01, 100)]  # barra absurda DESPUÉS de la entrada
    b = bars(pre + post + [FLAT] * 3)
    costly = CostModel(commission_per_share=0.005, half_spread_k=0.25, impact_k=0.0, min_half_spread=0.005)
    s = Signal("AAA", D, "t", 1, T0, T0 + timedelta(minutes=30), 100.0, 98.0, None)
    t = simulate(s, b, costly, EOD, 100)
    assert t.slippage_ps == pytest.approx(0.25 * 1.0)  # mediana(high-low)=1.0 de las 30 barras previas
    assert t.r_net < t.r_gross


def test_holdout_guard():
    check_holdout(date(2025, 1, 1), date(2025, 12, 31), date(2026, 1, 1), allow_oos=False)
    with pytest.raises(HoldoutSealed):
        check_holdout(date(2025, 1, 1), date(2026, 1, 1), date(2026, 1, 1), allow_oos=False)
    check_holdout(date(2025, 1, 1), date(2026, 6, 1), date(2026, 1, 1), allow_oos=True)


ACCT = {"initial_equity": 100_000, "risk_per_trade": 0.01, "max_positions": 2, "max_trades_per_day": 10,
        "daily_loss_limit": 0.03, "buying_power_mult": 4.0}  # fmt: skip


def _trade(minute, r, exit_min=None, day=D):
    t0 = datetime(day.year, day.month, day.day, 14, 0)
    return {"session_date": day, "symbol": f"S{minute}", "entry_ts": t0 + timedelta(minutes=minute),
            "exit_ts": t0 + timedelta(minutes=exit_min if exit_min is not None else minute + 1),
            "shares": 100, "planned_risk": 1.0, "entry_px": 50.0, "r_net": r}  # fmt: skip


def test_portfolio_max_positions_and_kill_switch():
    t = pl.DataFrame([_trade(0, 1.0, 100), _trade(1, 1.0, 100), _trade(2, 1.0, 100)])
    out, _ = simulate_portfolio(t, ACCT, [D])
    assert out["taken"].to_list() == [True, True, False] and out["skip_reason"][2] == "max_posiciones"
    # Con riesgo compuesto, 3 pérdidas de -1R = -2.97% (aún no); la 4.ª lleva a -3.94% → la 5.ª se bloquea.
    t = pl.DataFrame([_trade(i * 2, -1.0) for i in range(5)])
    out, eq = simulate_portfolio(t, ACCT, [D])
    assert out["taken"].to_list() == [True, True, True, True, False] and out["skip_reason"][4] == "kill_switch"
    assert eq["equity"][0] == pytest.approx(100_000 - 1000 - 990 - 980.1 - 970.299)


def test_trade_stats():
    t = pl.DataFrame({"r_net": [2.0, -1.0, -1.0, 2.0, -1.0]})
    s = trade_stats(t)
    assert s["trades"] == 5 and s["win_rate"] == 0.4 and s["avg_r"] == pytest.approx(0.2)
    assert s["profit_factor"] == pytest.approx(4 / 3) and s["max_loss_streak"] == 2


def test_equity_stats_drawdown_and_sharpe():
    eq = pl.DataFrame({"equity": [101.0, 99.0, 102.0, 98.0], "ret": [0.01, 99 / 101 - 1, 102 / 99 - 1, 98 / 102 - 1]})
    s = equity_stats(eq)
    assert s["total_return"] == pytest.approx(-0.02)
    assert s["max_drawdown"] == pytest.approx(98 / 102 - 1)
    r = eq["ret"].to_numpy()
    assert s["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(252))


# ---------------- Órdenes stop de entrada (ronda 2) ----------------
def stop_sig(side=1, level=101.0, offset=0.5):
    return Signal("AAA", D, "t", side, T0, T0 + timedelta(minutes=1), level, level - side * offset, None,
                  entry_type="stop", entry_level=level, stop_offset=offset, valid_until=EOD)  # fmt: skip


def test_stop_entry_fills_at_level_and_stop_from_fill():
    b = bars([FLAT, FLAT, (100.5, 101.6, 100.8, 101.5), (101.5, 102, 101.2, 101.8)] + [FLAT] * 2)
    t = simulate(stop_sig(), b, FREE, EOD, 100)
    assert t.entry_ts == T0 + timedelta(minutes=2) and t.entry_px == 101.0 and t.stop == 100.5
    assert not t.ambiguous


def test_stop_entry_gap_through_level_fills_at_open():
    b = bars([FLAT, FLAT, (102.0, 102.5, 101.8, 102.2)] + [FLAT] * 2)
    t = simulate(stop_sig(), b, FREE, EOD, 100)
    assert t.entry_px == 102.0 and t.stop == 101.5


def test_stop_entry_not_triggered_returns_none():
    assert simulate(stop_sig(level=150.0), bars([FLAT] * 5), FREE, EOD, 100) is None


def test_entry_bar_ambiguity_conservative_vs_optimistic():
    # La barra de entrada toca el nivel (101) y también el stop (100.5) pero cierra en 100.9: orden incierto.
    b = bars([FLAT, (100.6, 101.2, 100.4, 100.9), (100.9, 103, 100.8, 102.5)] + [(102.5, 102.6, 102.4, 102.5)] * 3)
    t = simulate(stop_sig(), b, FREE, T0 + timedelta(minutes=5), 100)
    assert t.ambiguous and t.exit_reason == "stop" and t.r_net == pytest.approx(-1.0)
    assert t.r_net_opt == pytest.approx((102.5 - 101.0) / 0.5)


def test_entry_bar_closing_beyond_stop_is_not_ambiguous():
    b = bars([FLAT, (100.6, 101.2, 100.2, 100.3)] + [FLAT] * 3)
    t = simulate(stop_sig(), b, FREE, EOD, 100)
    assert t.exit_reason == "stop" and not t.ambiguous and t.r_net_opt == t.r_net


def test_stop_entry_respects_valid_until():
    s = stop_sig()
    s = Signal(**{**s.__dict__, "valid_until": T0 + timedelta(minutes=2)})
    b = bars([FLAT, FLAT, (100.5, 101.6, 100.8, 101.5)] + [FLAT] * 2)
    assert simulate(s, b, FREE, EOD, 100) is None


def test_deflated_sharpe_penalizes_many_trials():
    from daytrader.backtest.metrics import deflated_sharpe

    rng = np.random.default_rng(1)
    r = rng.normal(0.001, 0.01, 250)  # SR diario ~0.1
    few = deflated_sharpe(r, [0.0, 0.02])
    many = deflated_sharpe(r, list(rng.normal(0, 0.08, 50)))
    assert 0 <= many < few <= 1
    assert deflated_sharpe(np.zeros(10), [0.1, 0.2]) != deflated_sharpe(np.zeros(10), [0.1, 0.2])  # nan


def test_hmm_regime_is_point_in_time():
    from datetime import date as dt
    from datetime import timedelta as td

    from daytrader.research.regime import predicted_vol_prob

    rng = np.random.default_rng(0)
    n = 600
    days = [dt(2020, 1, 1) + td(days=i) for i in range(n)]
    vol = np.where((np.arange(n) // 60) % 2 == 0, 0.005, 0.03)
    close = 100 * np.exp(np.cumsum(rng.normal(0, vol)))
    spy = pl.DataFrame({"session_date": days, "close": close, "high": close * (1 + vol), "low": close * (1 - vol)})
    ev = days[400:430]
    a = predicted_vol_prob(spy, ev)
    # Alterar datos DESPUÉS de una fecha no cambia las probabilidades de fechas <= esa fecha
    cut = ev[10]
    spy2 = spy.with_columns(
        pl.when(pl.col("session_date") >= cut).then(pl.col("close") * 3).otherwise(pl.col("close")).alias("close")
    )
    b = predicted_vol_prob(spy2, ev)
    ja = a.filter(pl.col("session_date") <= cut)["p_vol"].to_list()
    jb = b.filter(pl.col("session_date") <= cut)["p_vol"].to_list()
    assert np.allclose(ja, jb)
    assert a["p_vol"].is_between(0, 1).all()


# ---------------- Órdenes límite de entrada (ronda 3) ----------------
NOHS = CostModel(commission_per_share=0, sec_fee_rate=0, taf_per_share=0, min_half_spread=0.0, half_spread_k=0,
                 impact_k=0)  # fmt: skip


def lim_sig(side=1, ref=100.0, stop=98.0, target=103.0, w=3, m=0.0):
    return Signal("AAA", D, "t", side, T0, T0 + timedelta(minutes=1), ref, stop, target, timedelta(minutes=60),
                  entry_type="limit", limit_offset_hs=m, valid_until=T0 + timedelta(minutes=1 + w))  # fmt: skip


def test_limit_requires_trade_through_strictly():
    touch = bars([FLAT, (100.2, 100.4, 100.0, 100.1)] + [(100.2, 100.4, 100.05, 100.2)] * 6)  # low == L: no
    assert simulate(lim_sig(), touch, NOHS, EOD, 100) is None
    through = bars([FLAT, (100.2, 100.4, 99.9, 100.1)] + [FLAT] * 6)
    t = simulate(lim_sig(), through, NOHS, EOD, 100)
    assert t.entry_px == 100.0 and t.entry_ts == T0 + timedelta(minutes=1) and t.planned_risk == 2.0


def test_limit_gap_fills_at_better_open_and_expires():
    gap = bars([FLAT, (99.0, 99.5, 98.8, 99.2)] + [FLAT] * 6)
    assert simulate(lim_sig(), gap, NOHS, EOD, 100).entry_px == 99.0
    late = bars([FLAT] + [(100.2, 100.4, 100.1, 100.3)] * 3 + [(100.0, 100.1, 99.5, 99.8)] * 4)
    assert simulate(lim_sig(w=3), late, NOHS, EOD, 100) is None  # se ejecutaría en el minuto 4: ya caducó


def test_limit_offset_uses_estimated_half_spread():
    pre = [(100, 100.5, 99.5, 100)] * 30  # rango 1.0 → medio spread k=0.10 → 0.10
    b = bars(pre + [(100.0, 100.1, 99.85, 99.95)] + [FLAT] * 5)
    s = Signal("AAA", D, "t", 1, T0, T0 + timedelta(minutes=30), 100.0, 98.0, 103.0, None,
               entry_type="limit", limit_offset_hs=1.0, valid_until=T0 + timedelta(minutes=35))  # fmt: skip
    t = simulate(s, b, FREE, EOD, 100)
    assert t.entry_px == pytest.approx(99.9) and t.planned_risk == pytest.approx(1.9)


def test_limit_target_and_stop_exits():
    b = bars([FLAT, (100.2, 100.4, 99.9, 100.1), (100.1, 103.5, 100.0, 103.2)] + [FLAT] * 3)
    t = simulate(lim_sig(), b, NOHS, EOD, 100)
    assert t.exit_reason == "target" and t.exit_px == 103.0 and t.r_net == pytest.approx(1.5)
    b = bars([FLAT, (100.2, 100.4, 99.9, 100.1), (99.0, 99.2, 97.0, 97.5)] + [FLAT] * 3)
    t = simulate(lim_sig(), b, NOHS, EOD, 100)
    assert t.exit_reason == "stop" and t.exit_px == 98.0
