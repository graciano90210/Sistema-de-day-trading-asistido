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
    def __init__(self, clock, positions):
        self.clock, self.positions, self.calls = clock, positions, []

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        return Resp(self.clock if url.endswith("/v2/clock") else self.positions)

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
    assert out.startswith("CIERRE: 2")
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
