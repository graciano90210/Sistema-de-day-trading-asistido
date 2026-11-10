"""Guardián en la nube (cloud/flatten_job.py): solo paper, ventana correcta, interruptor, idempotente."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime

import pytest

from daytrader.config import ROOT

spec = importlib.util.spec_from_file_location("flatten_job", ROOT / "cloud" / "flatten_job.py")
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)

CLOSE = "2026-11-09T16:00:00-05:00"
ENV = {"DAYTRADER_AUTO_FLATTEN": "1", "ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s"}


class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


class FakeHTTP:
    def __init__(self, clock, positions, account=None):
        self.clock, self.positions, self.calls = clock, positions, []
        self.account = account or {"equity": "100000", "last_equity": "100000"}

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        if url.endswith("/v2/clock"):
            return Resp(self.clock)
        return Resp(self.account if url.endswith("/v2/account") else self.positions)

    def delete(self, url, **kw):
        self.calls.append(("DELETE", url, kw.get("params")))
        return Resp([])


def _now(hh, mm):
    return datetime(2026, 11, 9, hh, mm, tzinfo=UTC)  # 15:50 ET = 20:50 UTC (horario de invierno)


@pytest.mark.parametrize(("hh", "mm", "expected"), [(20, 40, False), (20, 48, True), (20, 50, True), (20, 59, True),
                                                    (21, 0, False), (15, 0, False)])  # fmt: skip
def test_window(hh, mm, expected):
    assert job.should_flatten({"is_open": True, "next_close": CLOSE}, _now(hh, mm)) is expected


def test_closed_market_never_flattens():
    assert not job.should_flatten({"is_open": False, "next_close": CLOSE}, _now(20, 55))


def test_flattens_in_window_with_positions_on_paper_only():
    http = FakeHTTP({"is_open": True, "next_close": CLOSE}, [{"symbol": "TTD"}, {"symbol": "IBRX"}])
    out = job.run(ENV, http, _now(20, 51))
    assert out.startswith("CIERRE (cierre del día): 2")
    deletes = [c for c in http.calls if c[0] == "DELETE"]
    assert deletes == [("DELETE", "https://paper-api.alpaca.markets/v2/positions", {"cancel_orders": "true"})]
    assert all(c[1].startswith("https://paper-api.alpaca.markets/") for c in http.calls)


def test_no_positions_or_outside_window_does_nothing():
    http = FakeHTTP({"is_open": True, "next_close": CLOSE}, [])
    assert "sin posiciones" in job.run(ENV, http, _now(20, 51))
    http2 = FakeHTTP({"is_open": True, "next_close": CLOSE}, [{"symbol": "TTD"}])
    assert "fuera de ventana" in job.run(ENV, http2, _now(19, 0))
    assert not [c for c in http.calls + http2.calls if c[0] == "DELETE"]


def test_switch_off_does_nothing():
    http = FakeHTTP({"is_open": True, "next_close": CLOSE}, [{"symbol": "TTD"}])
    assert "desactivado" in job.run({**ENV, "DAYTRADER_AUTO_FLATTEN": "0"}, http, _now(20, 51))
    assert http.calls == []


def test_live_url_aborts():
    http = FakeHTTP({"is_open": True, "next_close": CLOSE}, [{"symbol": "TTD"}])
    with pytest.raises(job.LiveTradingForbidden):
        job.run({**ENV, "ALPACA_BASE_URL": "https://api.alpaca" + ".markets"}, http, _now(20, 51))
    assert http.calls == []


@pytest.mark.parametrize(("pnl", "closes"), [(59.99, False), (60.0, True), (75.0, True), (-50.0, False)])
def test_profit_target_closes_everything_midday(pnl, closes):
    acct = {"equity": str(100_000 + pnl), "last_equity": "100000"}
    http = FakeHTTP({"is_open": True, "next_close": CLOSE}, [{"symbol": "TTD"}], acct)
    out = job.run({**ENV, "DAYTRADER_PROFIT_TARGET": "60"}, http, _now(17, 30))  # 12:30 ET, lejos del cierre
    assert out.startswith("CIERRE (meta") is closes
    assert bool([c for c in http.calls if c[0] == "DELETE"]) is closes


def test_profit_target_ignored_when_market_closed_or_unset():
    acct = {"equity": "100100", "last_equity": "100000"}
    http = FakeHTTP({"is_open": False, "next_close": CLOSE}, [{"symbol": "TTD"}], acct)
    assert "fuera de ventana" in job.run({**ENV, "DAYTRADER_PROFIT_TARGET": "60"}, http, _now(17, 30))
    http2 = FakeHTTP({"is_open": True, "next_close": CLOSE}, [{"symbol": "TTD"}], acct)
    assert "fuera de ventana" in job.run(ENV, http2, _now(17, 30))
    assert not [c for c in http.calls + http2.calls if c[0] == "DELETE"]


@pytest.mark.parametrize(("pnl", "closes"), [(-69.99, False), (-70.0, True), (-120.0, True), (30.0, False)])
def test_loss_limit_closes_everything(pnl, closes):
    acct = {"equity": str(100_000 + pnl), "last_equity": "100000"}
    http = FakeHTTP({"is_open": True, "next_close": CLOSE}, [{"symbol": "TTD"}], acct)
    out = job.run({**ENV, "DAYTRADER_PROFIT_TARGET": "70", "DAYTRADER_LOSS_LIMIT": "70"}, http, _now(17, 30))
    assert out.startswith("CIERRE (pérdida") is closes
    assert bool([c for c in http.calls if c[0] == "DELETE"]) is closes
