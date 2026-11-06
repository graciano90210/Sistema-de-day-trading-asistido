def test_ingest_parallel_matches_sequential_and_resumes():
    """Descarga en paralelo = mismo resultado que la secuencial; un segundo pase no descarga nada."""
    from datetime import date

    import polars as pl

    from daytrader.data.ingest import ingest, ingest_parallel
    from daytrader.data.store import Store

    def fake(symbol, timeframe, s, e):
        ts = pl.Series("ts_utc", [s.replace(hour=15)], dtype=pl.Datetime("us"))
        return pl.DataFrame({"symbol": symbol, "ts_utc": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                             "volume": 1.0, "trade_count": 1, "vwap": 1.0})  # fmt: skip

    a, b = Store(), Store()
    ingest(a, fake, ["AAA", "BBB"], date(2017, 1, 1), date(2017, 7, 1), "1m", "sip")
    s = ingest_parallel(b, [fake, fake, fake], ["AAA", "BBB"], date(2017, 1, 1), date(2017, 7, 1), "1m", "sip")
    assert s.chunks_done == 12 and not s.errors
    q = "SELECT symbol, ts_utc FROM bars_1m ORDER BY 1, 2"
    assert a.query(q).equals(b.query(q))
    again = ingest_parallel(b, [fake, fake], ["AAA", "BBB"], date(2017, 1, 1), date(2017, 7, 1), "1m", "sip")
    assert again.chunks_done == 0 and again.chunks_skipped == 12


def test_alpaca_client_gets_http_timeout():
    from types import SimpleNamespace

    from daytrader.data.alpaca_client import HTTP_TIMEOUT, with_timeout

    seen = {}
    fake = SimpleNamespace(_session=SimpleNamespace(request=lambda m, u, **kw: seen.update(kw)))
    with_timeout(fake)._session.request("GET", "http://x")
    assert seen["timeout"] == HTTP_TIMEOUT
