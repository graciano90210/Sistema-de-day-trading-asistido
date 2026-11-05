"""Ronda 2: mezcla de ejecución calibrada y regla de promoción (pre-registro)."""

import polars as pl
import pytest

from daytrader.research.round2 import promotion, with_r


def _t():
    return pl.DataFrame({"r_net": [-1.0, 2.0, -1.0], "pnl": [-100.0, 200.0, -100.0],
                         "ambiguous": [True, False, False], "r_net_opt": [3.0, 2.0, -1.0],
                         "pnl_opt": [300.0, 200.0, -100.0]})  # fmt: skip


def test_with_r_modes():
    t = _t()
    assert with_r(t, "cons", 0.3)["r_net"].to_list() == [-1.0, 2.0, -1.0]
    assert with_r(t, "opt", 0.3)["r_net"].to_list() == [3.0, 2.0, -1.0]
    cal = with_r(t, "cal", 0.25)
    assert cal["r_net"].to_list() == pytest.approx([0.25 * -1 + 0.75 * 3, 2.0, -1.0])
    assert cal["pnl"][0] == pytest.approx(0.25 * -100 + 0.75 * 300)


def test_promotion_rule_matches_preregistration():
    ok = {"trades": 150, "R_neto": 0.1, "t_stat": 2.1, "profit_factor": 1.25, "dsr": 0.96, "R_pesimista": 0.02}
    assert promotion(ok)
    for k, bad in [("trades", 99), ("R_neto", -0.01), ("t_stat", 1.99), ("profit_factor", 1.19), ("dsr", 0.94),
                   ("R_pesimista", -0.001)]:  # fmt: skip
        assert not promotion({**ok, k: bad}), k
