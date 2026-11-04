"""Regla 5: ninguna consulta devuelve información posterior a `as_of`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from daytrader.data.access import get_bars, resample
from daytrader.data.ingest import prepare_bars

DAY = date(2025, 3, 14)  # viernes, EDT → apertura 13:30 UTC
OPEN = datetime(2025, 3, 14, 13, 30)
TRAP = 1_000_000.0


def test_minute_bar_not_visible_until_it_closes(loaded_store):
    as_of = OPEN + timedelta(minutes=30)  # 10:00 ET
    bars = get_bars(loaded_store, "AAA", as_of, start=OPEN)
    assert bars["ts_utc"].max() == as_of - timedelta(minutes=1)  # la barra 09:59 sí
    assert (bars["ts_utc"] < as_of).all()  # la barra 10:00 (disponible 10:01) no


def test_trap_bars_after_as_of_never_leak(store, synthetic_1m):
    raw = synthetic_1m("AAA", DAY)
    as_of = OPEN + timedelta(minutes=47)
    # Toda barra que empieza en/tras as_of se vuelve extrema: si se filtra, salta a la vista.
    trap = raw.with_columns(
        [
            pl.when(pl.col("ts_utc") >= as_of).then(pl.lit(TRAP)).otherwise(pl.col(c)).alias(c)
            for c in ("open", "high", "low", "close")
        ]
    )
    store.upsert_bars(prepare_bars(trap, "1m", "test"), "1m")
    bars = get_bars(store, "AAA", as_of)
    assert bars["high"].max() < TRAP
    for m in (1, 5, 15):
        rs = resample(bars, m, as_of=as_of)
        assert rs["high"].max() < TRAP
        assert (rs["available_at"] <= as_of).all()


def test_resample_drops_incomplete_bucket(loaded_store):
    as_of = OPEN + timedelta(minutes=12)  # 09:42 ET
    bars = get_bars(loaded_store, "AAA", as_of, start=OPEN)
    rs = resample(bars, 5, as_of=as_of)
    assert rs["ts_utc"].to_list() == [OPEN, OPEN + timedelta(minutes=5)]  # 09:30 y 09:35; 09:40 no ha cerrado
    first = bars.filter(pl.col("ts_utc") < OPEN + timedelta(minutes=5))
    row = rs.row(0, named=True)
    assert row["open"] == first["open"][0]
    assert row["close"] == first["close"][-1]
    assert row["high"] == first["high"].max()
    assert row["low"] == first["low"].min()
    assert row["volume"] == first["volume"].sum()


def test_resample_point_in_time_matches_full_history(loaded_store):
    """Lo que se ve en t con datos cortados == lo que se ve con historia completa filtrada a t."""
    full = get_bars(loaded_store, "AAA", datetime(2030, 1, 1))
    for minutes_after_open in (0, 3, 15, 16, 61, 389):
        t = OPEN + timedelta(minutes=minutes_after_open)
        pit = resample(get_bars(loaded_store, "AAA", t), 15, as_of=t)
        ref = resample(full, 15, as_of=None).filter(pl.col("available_at") <= t)
        assert pit.equals(ref)


def test_daily_bar_hidden_during_its_own_session(loaded_store):
    during = datetime(2025, 3, 14, 19, 0)  # 15:00 ET
    after_post = datetime(2025, 3, 15, 0, 0)  # 20:00 ET
    seen = get_bars(loaded_store, "AAA", during, timeframe="1d")["session_date"].to_list()
    assert seen == [date(2025, 3, 13)]
    seen = get_bars(loaded_store, "AAA", after_post, timeframe="1d")["session_date"].to_list()
    assert seen == [date(2025, 3, 13), date(2025, 3, 14)]


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(offset=st.integers(min_value=-400, max_value=1000))
def test_property_nothing_after_as_of(loaded_store, offset):
    as_of = OPEN + timedelta(minutes=offset)
    for tf in ("1m", "1d"):
        bars = get_bars(loaded_store, "AAA", as_of, timeframe=tf)
        assert bars.is_empty() or (bars["available_at"] <= as_of).all()
        assert bars.is_empty() or (bars["ts_utc"] < as_of).all()


def test_as_of_must_be_naive_utc(loaded_store):

    import pytest

    with pytest.raises(ValueError):
        get_bars(loaded_store, "AAA", datetime(2025, 3, 14, 15, tzinfo=UTC))
