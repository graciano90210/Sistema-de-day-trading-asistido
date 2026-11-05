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


def test_journal_allows_concurrent_processes(tmp_path):
    """guard y trade usan el journal a la vez: ninguna conexión queda abierta entre operaciones."""
    p = tmp_path / "j.duckdb"
    a, b = Journal(p), Journal(p)  # como dos procesos
    a.event("guard", "autorizado")
    b.record_ticket(ticket(), "enviado")
    assert a.trades_today(NOW.date()) == 1 and b.query("SELECT count(*) AS n FROM events")["n"][0] == 1


def test_ticket_session_date_is_new_york_date():
    late = ticket(now_utc=datetime(2025, 3, 15, 0, 30))  # 20:30 ET del 14 de marzo
    j = Journal()
    j.record_ticket(late, "rechazado", ["x"])
    assert str(j.query("SELECT session_date FROM tickets")["session_date"][0]) == "2025-03-14"


# ---------------- Capital simulado y cuenta de efectivo ----------------
CASH = RiskConfig(simulated_capital=1000, simulated_start="2026-11-06", account_type="cash")


def test_simulated_state_tracks_journal_pnl():
    from daytrader.execution.simulated import account_state

    a = account_state(100_050, 100_000, 1, 500, 1, 500, realized_before_today=25.0, cfg=CASH)
    assert a.last_equity == 1025.0 and a.equity == 1075.0  # 1000 + 25 realizado + 50 del día
    real = account_state(100_050, 100_000, 0, 0, 0, 0, 0.0, RiskConfig())
    assert real.equity == 100_050


def test_cash_account_rules_with_1000_dollars():
    acc = AccountState(equity=1000, last_equity=1000, open_positions=0, open_notional=0, trades_today=0)
    t = build_ticket("XYZ", "long", 50.0, 48.0, 54.0, acc, CASH, NOW)
    assert t.qty == 5 and t.risk_usd == 10.0  # 1% de $1.000 / $2 por acción
    assert check(t, acc, SES, CASH, NOW).ok
    spy = build_ticket("SPY", "long", 737.0, 733.5, 744.0, acc, CASH, NOW)
    assert spy.qty == 1  # recortado por nocional (no hay apalancamiento)
    short = build_ticket("XYZ", "short", 50.0, 52.0, 46.0, acc, CASH, NOW)
    assert any("corto" in r for r in check(short, acc, SES, CASH, NOW).reasons)
    used = replace(acc, day_notional_used=800)  # fondos ya usados hoy
    assert any("fondos liquidados" in r for r in check(t, used, SES, CASH, NOW).reasons)
    kill = replace(acc, equity=969.0)  # -3,1% del capital simulado
    assert any("KILL SWITCH" in r for r in check(t, kill, SES, CASH, NOW).reasons)


MARGIN = RiskConfig(simulated_capital=3000, account_type="margin")


def test_small_margin_account_pdt_and_shorts():
    acc = AccountState(equity=3000, last_equity=3000, open_positions=0, open_notional=0, trades_today=0)
    short = build_ticket("XYZ", "short", 50.0, 51.0, 48.0, acc, MARGIN, NOW)
    assert short.qty == 30 and check(short, acc, SES, MARGIN, NOW).ok  # cortos permitidos
    third = replace(acc, day_trades_5d=2)
    assert check(short, third, SES, MARGIN, NOW).ok
    fourth = replace(acc, day_trades_5d=3)
    assert any("PDT" in r for r in check(short, fourth, SES, MARGIN, NOW).reasons)
    big = replace(acc, open_notional=5000)  # 2× = $6.000 de poder de compra
    assert any("poder de compra (2×" in r for r in check(short, big, SES, MARGIN, NOW).reasons)
    rich = AccountState(equity=30_000, last_equity=30_000, open_positions=0, open_notional=0, trades_today=0,
                        day_trades_5d=9)  # fmt: skip
    t = build_ticket("XYZ", "short", 50.0, 51.0, 48.0, rich, MARGIN, NOW)
    assert check(t, rich, SES, MARGIN, NOW).ok  # con >= $25.000 no aplica


def test_pdt_window_is_five_sessions():
    from datetime import date

    from daytrader.execution.simulated import pdt_window_start

    assert pdt_window_start(date(2026, 11, 6)) == date(2026, 11, 2)  # lun–vie
    assert pdt_window_start(date(2026, 11, 8)) == date(2026, 11, 2)  # domingo: últimas 5 sesiones
