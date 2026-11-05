"""Fase 5: risk-manager y flujo de confirmación (sin red, broker falso)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from daytrader.execution.executor import FingerprintMismatch, run_ticket, submit_approved
from daytrader.execution.journal import Journal
from daytrader.execution.risk import AccountState, RiskConfig, Session, build_ticket, check, size_position

CFG = RiskConfig()
OPEN = datetime(2025, 3, 14, 13, 30)
SES = Session(OPEN, OPEN + timedelta(hours=6, minutes=30))
NOW = OPEN + timedelta(hours=1)
ACC = AccountState(equity=100_000, last_equity=100_000, open_positions=0, open_notional=0, trades_today=0)


class FakeBroker:
    def __init__(self):
        self.sent = []

    def submit(self, t, coid):
        self.sent.append((t, coid))
        return type("O", (), {"id": "ord-1"})()


def ticket(**kw):
    base = dict(symbol="NVDA", side="long", ref_price=100.0, stop=98.0, target=104.0, account=ACC, cfg=CFG, now_utc=NOW)
    return build_ticket(**{**base, **kw})


def flow(t, answer="y", acc=ACC, now=NOW, requote=None, broker=None):
    b, j = broker or FakeBroker(), Journal()
    out = run_ticket(t, acc, SES, CFG, b, j, now=lambda: now, ask=lambda p, s: answer, show=lambda x: None,
                     requote=requote or (lambda s: t.ref_price))  # fmt: skip
    return out, b, j


def test_sizing_one_percent_risk_and_notional_cap():
    assert size_position(100_000, 100.0, 98.0, CFG) == 500  # 1.000 $ / 2 $ ; nocional 50.000 ≤ 100%
    assert size_position(100_000, 100.0, 99.9, CFG) == 1000  # por riesgo serían 10.000 → recorte por nocional
    t = ticket()
    assert t.qty == 500 and t.risk_usd == 1000.0


def test_rules_reject():
    cases = {
        "stop": ticket(stop=101.0),
        "cerca": ticket(stop=99.9),
        "lejos": ticket(stop=80.0),
        "objetivo": ticket(target=95.0),
    }
    for name, t in cases.items():
        assert not check(t, ACC, SES, CFG, NOW).ok, name
    assert not check(ticket(), replace(ACC, equity=96_900), SES, CFG, NOW).ok  # kill switch -3,1%
    assert not check(ticket(), replace(ACC, trades_today=5), SES, CFG, NOW).ok
    assert not check(ticket(), replace(ACC, open_positions=3), SES, CFG, NOW).ok
    assert not check(ticket(), replace(ACC, open_notional=380_000), SES, CFG, NOW).ok
    assert not check(ticket(), ACC, SES, CFG, SES.close_utc - timedelta(minutes=14)).ok  # últimos 15 min
    assert not check(ticket(), ACC, None, CFG, NOW).ok  # mercado cerrado
    assert check(ticket(), ACC, SES, CFG, NOW).ok


def test_short_ticket():
    t = ticket(side="short", stop=102.0, target=96.0)
    assert check(t, ACC, SES, CFG, NOW).ok and t.qty == 500


def test_nothing_sent_without_explicit_yes():
    for ans in (None, "n", "", "yes please", "si"):
        out, b, j = flow(ticket(), answer=ans)
        assert b.sent == [] and out.status in ("caducado", "declinado"), ans
    out, b, j = flow(ticket(), answer="y")
    assert out.status == "enviado" and len(b.sent) == 1
    assert j.query("SELECT status FROM tickets")["status"].to_list() == ["enviado"]


def test_rejected_ticket_never_asks():
    asked = []
    j, b = Journal(), FakeBroker()
    out = run_ticket(ticket(stop=101.0), ACC, SES, CFG, b, j, now=lambda: NOW, ask=lambda p, s: asked.append(1) or "y",
                     show=lambda x: None, requote=lambda s: 100.0)  # fmt: skip
    assert out.status == "rechazado" and asked == [] and b.sent == []


def test_price_drift_cancels_after_confirmation():
    out, b, _ = flow(ticket(), answer="y", requote=lambda s: 100.6)  # 0,6 $ = 0,3 R > 0,25 R
    assert out.status == "deriva" and b.sent == []
    out, b, _ = flow(ticket(), answer="y", requote=lambda s: 100.4)
    assert out.status == "enviado"


def test_fingerprint_blocks_tampering():
    t = ticket()
    fp = t.fingerprint()
    with pytest.raises(FingerprintMismatch):
        submit_approved(FakeBroker(), replace(t, qty=t.qty * 2), fp, "x")
    with pytest.raises(FingerprintMismatch):
        submit_approved(FakeBroker(), replace(t, stop_price=97.0), fp, "x")


def test_journal_notes_and_trade_count():
    _, _, j = flow(ticket(), answer="y")
    fp = j.query("SELECT fingerprint FROM tickets")["fingerprint"][0]
    j.note(fp, "entré tarde, persiguiendo el precio", kind="error")
    assert j.query("SELECT kind FROM notes")["kind"].to_list() == ["error"]
    assert j.trades_today(NOW.date()) == 1
    with pytest.raises(ValueError):
        j.note(fp, "x", kind="otra")


def test_paper_broker_refuses_non_paper_url(monkeypatch):
    from daytrader.config import LiveTradingForbidden
    from daytrader.execution import broker as br

    class FakeClient:
        def __init__(self, *a, **k):
            self._base_url = "https://api.alpaca.markets"

    monkeypatch.setattr(br, "TradingClient", FakeClient)
    with pytest.raises(LiveTradingForbidden):
        br.PaperBroker("k", "s")


def test_sync_builds_trade_with_real_slippage_and_r():
    from datetime import UTC
    from types import SimpleNamespace as NS

    from daytrader.execution.sync import build_trades

    t = ticket()
    fp = t.fingerprint()
    t0 = datetime(2025, 3, 14, 14, 30, tzinfo=UTC)
    stop_leg = NS(status="filled", filled_avg_price="97.95", filled_at=t0 + timedelta(minutes=20), order_type="stop")
    tp_leg = NS(status="canceled", filled_avg_price=None, filled_at=None, order_type="limit")
    parent = NS(client_order_id=f"dt-{fp}-143000", status="filled", filled_avg_price="100.05", filled_at=t0,
                filled_qty="500", symbol="NVDA", legs=[stop_leg, tp_leg])  # fmt: skip
    row = build_trades([parent], {fp: {"side": "long", "ref_price": 100.0, "limit_price": None, "stop_price": 98.0}})[0]
    assert row["exit_reason"] == "stop" and row["entry_slippage"] == pytest.approx(0.05)
    assert row["r_multiple"] == pytest.approx((97.95 - 100.05) / 2.0)
    assert row["pnl"] == pytest.approx((97.95 - 100.05) * 500)


def test_time_messages_are_specific():
    after = check(ticket(), ACC, SES, CFG, SES.close_utc + timedelta(hours=2)).reasons
    assert "la sesión de hoy ya cerró" in after and not any("últimos" in x for x in after)
    before = check(ticket(), ACC, SES, CFG, OPEN - timedelta(hours=1)).reasons
    assert any("antes de la apertura" in x for x in before)
