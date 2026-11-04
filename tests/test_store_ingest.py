from datetime import date

import polars as pl

from daytrader.data.ingest import ingest, month_chunks, prepare_bars


def test_month_chunks():
    assert month_chunks(date(2024, 11, 15), date(2025, 2, 3)) == [
        (date(2024, 11, 15), date(2024, 12, 1)),
        (date(2024, 12, 1), date(2025, 1, 1)),
        (date(2025, 1, 1), date(2025, 2, 1)),
        (date(2025, 2, 1), date(2025, 2, 3)),
    ]


def test_upsert_is_idempotent_and_replaces(store, synthetic_1m):
    df = prepare_bars(synthetic_1m("AAA", date(2025, 3, 14)), "1m", "test")
    store.upsert_bars(df, "1m")
    store.upsert_bars(df, "1m")
    assert store.query("SELECT count(*) AS n FROM bars_1m")["n"][0] == df.height
    store.upsert_bars(df.head(1).with_columns(pl.lit(42.0).alias("close")), "1m")
    assert store.query("SELECT count(*) AS n FROM bars_1m")["n"][0] == df.height
    assert store.query("SELECT close FROM bars_1m ORDER BY ts_utc LIMIT 1")["close"][0] == 42.0


def test_ingest_is_resumable_and_logs(store, synthetic_1m):
    calls = []

    def fake_fetch(symbol, timeframe, start_utc, end_utc):
        calls.append((symbol, start_utc))
        if symbol == "BAD":
            raise ConnectionError("boom")
        d = date(start_utc.year, start_utc.month, 14)
        return synthetic_1m(symbol, d)

    start, end = date(2025, 3, 1), date(2025, 5, 1)
    s1 = ingest(store, fake_fetch, ["AAA", "BAD"], start, end, "1m", "test")
    assert s1.chunks_done == 2 and len(s1.errors) == 2
    s2 = ingest(store, fake_fetch, ["AAA", "BAD"], start, end, "1m", "test")
    assert s2.chunks_skipped == 2  # AAA en caché; BAD se reintenta
    assert [c[0] for c in calls].count("AAA") == 2
    assert [c[0] for c in calls].count("BAD") == 4
    log = store.query("SELECT status, count(*) AS n FROM ingest_log GROUP BY 1 ORDER BY 1")
    assert log.to_dicts() == [{"status": "error", "n": 2}, {"status": "ok", "n": 2}]


def test_prepare_1m_columns(synthetic_1m):
    df = prepare_bars(synthetic_1m("AAA", date(2025, 3, 14)), "1m", "sip")
    assert set(df["session"].unique()) == {"pre", "rth", "post"}
    assert df.filter(pl.col("session") == "rth").height == 390
    assert ((df["available_at"] - df["ts_utc"]).dt.total_seconds() == 60).all()


def test_raw_alpaca_payload_parsing():
    from datetime import datetime

    from daytrader.data.alpaca_client import raw_bars_to_frame

    payload = [
        {"t": "2025-03-14T13:30:00Z", "o": 10, "h": 11, "l": 9.5, "c": 10.5, "v": 1200, "n": 30, "vw": 10.2},
        {"t": "2025-03-14T13:31:00Z", "o": 10.5, "h": 10.6, "l": 10.1, "c": 10.2, "v": 800, "n": 12, "vw": 10.3},
    ]
    df = raw_bars_to_frame("AAA", payload)
    assert df["ts_utc"].to_list() == [datetime(2025, 3, 14, 13, 30), datetime(2025, 3, 14, 13, 31)]
    assert df["ts_utc"].dtype.time_zone is None
    out = prepare_bars(df, "1m", "sip")
    assert out["session"].to_list() == ["rth", "rth"]
    assert raw_bars_to_frame("AAA", []).is_empty()
