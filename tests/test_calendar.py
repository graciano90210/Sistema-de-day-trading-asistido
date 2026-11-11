from datetime import date, datetime

import polars as pl

from daytrader.market_calendar import classify_sessions, is_session, last_complete_session, sessions


def test_dst_shifts_open_in_utc():
    before = sessions(date(2025, 3, 7), date(2025, 3, 7)).row(0, named=True)  # EST
    after = sessions(date(2025, 3, 10), date(2025, 3, 10)).row(0, named=True)  # EDT
    assert before["open_utc"] == datetime(2025, 3, 7, 14, 30)
    assert after["open_utc"] == datetime(2025, 3, 10, 13, 30)
    assert before["rth_minutes"] == after["rth_minutes"] == 390


def test_half_day_after_thanksgiving():
    s = sessions(date(2025, 11, 28), date(2025, 11, 28)).row(0, named=True)
    assert s["early_close"] is True
    assert s["close_utc"] == datetime(2025, 11, 28, 18, 0)  # 13:00 ET
    assert s["rth_minutes"] == 210


def test_holidays_are_not_sessions():
    assert not is_session(date(2025, 12, 25))
    assert not is_session(date(2025, 7, 4))
    assert is_session(date(2025, 7, 3))


def test_classify_sessions():
    df = pl.DataFrame(
        {
            "ts_utc": [
                datetime(2025, 3, 14, 8, 0),  # 04:00 ET pre
                datetime(2025, 3, 14, 13, 29),  # 09:29 pre
                datetime(2025, 3, 14, 13, 30),  # 09:30 rth
                datetime(2025, 3, 14, 19, 59),  # 15:59 rth
                datetime(2025, 3, 14, 20, 0),  # 16:00 post
                datetime(2025, 3, 15, 0, 0),  # 20:00 closed
                datetime(2025, 3, 15, 14, 0),  # sábado closed
            ]
        },
        schema={"ts_utc": pl.Datetime("us")},
    )
    out = classify_sessions(df)
    assert out["session"].to_list() == ["pre", "pre", "rth", "rth", "post", "closed", "closed"]
    assert out["session_date"][0] == date(2025, 3, 14)


def test_last_complete_session_excludes_today():
    # Lunes 2025-03-17 a las 15:00 ET → última sesión completa: viernes 14
    assert last_complete_session(datetime(2025, 3, 17, 19, 0)) == date(2025, 3, 14)


def test_last_session_for_daily_includes_today_after_post_market():
    """Bug 2026-11-11: a las 20:30 ET del día D la rutina nocturna debe bajar la barra diaria de D."""
    from daytrader.market_calendar import last_session_for_daily

    # Martes 2026-11-10 (horario de invierno, ET = UTC−5)
    assert last_session_for_daily(datetime(2026, 11, 11, 1, 30)) == date(2026, 11, 10)  # 20:30 ET
    assert last_session_for_daily(datetime(2026, 11, 11, 1, 5)) == date(2026, 11, 9)  # 20:05 ET: aún no
    assert last_session_for_daily(datetime(2026, 11, 10, 20, 0)) == date(2026, 11, 9)  # 15:00 ET
    assert last_session_for_daily(datetime(2026, 11, 14, 15, 0)) == date(2026, 11, 13)  # sábado
