"""Fase 6: funciones de datos del dashboard."""

from datetime import date, datetime

import polars as pl
import pytest

from daytrader.dashboard import data as D


def _t():
    return pl.DataFrame({
        "session_date": [date(2025, 1, 2), date(2025, 1, 2), date(2025, 1, 3)],
        "entry_ts": [datetime(2025, 1, 2, 15), datetime(2025, 1, 2, 16), datetime(2025, 1, 3, 15)],
        "exit_ts": [datetime(2025, 1, 2, 17), datetime(2025, 1, 2, 18), datetime(2025, 1, 3, 17)],
        "symbol": ["A", "B", "A"], "side": [1, -1, 1], "r": [2.0, -1.0, -1.0], "pnl": [2000.0, -1000.0, -1000.0],
        "exit_reason": ["target", "stop", "stop"],
    })  # fmt: skip


def test_equity_and_drawdown():
    eq = D.equity_curve(_t())
    assert eq["equity"].to_list() == [101_000.0, 100_000.0]
    assert eq["drawdown"].to_list() == pytest.approx([0.0, 100_000 / 101_000 - 1])


def test_kpis_and_breakdowns():
    k = D.kpis(_t())
    assert k["trades"] == 3 and k["avg_r"] == pytest.approx(0.0) and k["pnl"] == 0.0 and k["retorno"] == 0.0
    h = D.by(D.with_entry_hour(_t()), "hora_et")
    assert h["hora_et"].to_list() == ["10:00", "11:00"]  # 15:00 UTC = 10:00 ET en enero
    assert D.by(_t(), "symbol", min_trades=2)["symbol"].to_list() == ["A"]
    lo, hi = D.r_ci(_t())
    assert lo < 0 < hi


def test_empty_journal_is_safe(tmp_path):
    t, k, n = D.load_journal(tmp_path / "no_existe.duckdb")
    assert t.is_empty() and D.kpis(t) == {"trades": 0} and D.equity_curve(t).is_empty()


def test_spy_curve_buys_at_previous_close():
    spy = pl.DataFrame(
        {"session_date": [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)], "close": [100.0, 110.0, 99.0]}
    )
    c = D.spy_curve(spy, date(2025, 1, 2), date(2025, 1, 3))
    assert c["equity"].to_list() == pytest.approx([110_000.0, 99_000.0])
