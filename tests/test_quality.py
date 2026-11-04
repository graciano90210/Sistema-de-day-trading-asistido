from datetime import datetime

from daytrader.data.quality import build_report, render_markdown


def test_clean_data_passes(loaded_store):
    r = build_report(loaded_store, now=datetime(2026, 1, 1))
    assert r.integrity_ok
    row = r.coverage_by_symbol.row(0, named=True)
    assert row["sesiones"] == 2 and row["sesiones_sin_datos"] == 0
    assert row["cobertura_mediana"] == 1.0
    assert "Integridad — OK" in render_markdown(r)


def test_detects_bad_ohlc_and_missing_minutes(loaded_store):
    loaded_store.con.execute("UPDATE bars_1m SET low = high + 1 WHERE ts_utc = TIMESTAMP '2025-03-14 14:00:00'")
    loaded_store.con.execute(
        "DELETE FROM bars_1m WHERE session_date = DATE '2025-03-13' AND session = 'rth' AND ts_utc < TIMESTAMP '2025-03-13 15:30:00'"
    )
    r = build_report(loaded_store, now=datetime(2026, 1, 1))
    assert not r.integrity_ok
    bad = r.integrity.filter((r.integrity["check"] == "ohlc_inconsistente") & (r.integrity["table"] == "bars_1m"))
    assert bad["violations"][0] == 1
    worst = r.worst_days.row(0, named=True)
    assert str(worst["session_date"]) == "2025-03-13"
    assert worst["rth_bars"] == 390 - 120


def test_detects_future_timestamps(loaded_store):
    r = build_report(loaded_store, now=datetime(2025, 3, 14, 12, 0))
    fut = r.integrity.filter((r.integrity["check"] == "timestamp_futuro") & (r.integrity["table"] == "bars_1m"))
    assert fut["violations"][0] > 0
