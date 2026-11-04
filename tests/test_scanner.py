"""Scanner: point-in-time, ajuste por split, filtros y RVOL con un fetcher falso."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import polars as pl
import pytest

from daytrader.data.adjust import adjust_for_splits
from daytrader.data.ingest import prepare_bars
from daytrader.market_calendar import et_to_utc_naive
from daytrader.scanner.premarket import summarize_premarket
from daytrader.scanner.scan import run_scan
from daytrader.scanner.universe import is_common_stock, previous_sessions, refresh_assets

D = date(2025, 3, 14)
TRAP = 1e6
CFG = {
    "cutoff_et": "09:25",
    "premarket_start_et": "04:00",
    "universe": {
        "exchanges": ["NYSE", "NASDAQ"], "include_inactive": True, "min_price": 5.0, "max_price": 1000.0,
        "min_adv_usd": 20e6, "min_atr": 0.5, "min_atr_pct": 0.02, "min_history": 20, "lookback_sessions": 20,
    },
    "gappers": {
        "min_abs_gap": 0.03, "min_premarket_volume": 100_000, "min_rvol": 2.0, "rvol_lookback": 20,
        "max_shares_outstanding": None, "top_n": 15,
    },
}  # fmt: skip
# Precio "raw" previo por símbolo y (precio pre-market de D, volumen pre-market de D)
SETUP = {
    "AAA": (50.0, (55.0, 300_000)),  # gap +10%
    "BBB": (50.0, (50.5, 300_000)),  # gap +1% → fuera
    "SPL": (500.0, (52.5, 250_000)),  # split 10:1 en D: cierre ajustado 50 → gap +5% (no -89%)
    "LOWV": (50.0, (60.0, 20_000)),  # gap +20% pero poco volumen → fuera
    "ETFX": (50.0, (60.0, 900_000)),  # ETF → excluido en etapa 1
}
PRIOR_PM_VOLUME = 10_000.0


def _daily(store):
    rows = []
    days = previous_sessions(D, 30)
    for sym, (px, _) in SETUP.items():
        for d in days:
            rows.append({"symbol": sym, "ts_utc": et_to_utc_naive(d, time(0)), "open": px, "high": px * 1.02,
                         "low": px * 0.98, "close": px, "volume": 2e6 if px < 100 else 2e5, "trade_count": 1000, "vwap": px})  # fmt: skip
        # Barra TRAMPA de la propia sesión D: no debe verse a las 09:25.
        rows.append({"symbol": sym, "ts_utc": et_to_utc_naive(D, time(0)), "open": TRAP, "high": TRAP, "low": TRAP,
                     "close": TRAP, "volume": 1.0, "trade_count": 1, "vwap": TRAP})  # fmt: skip
    raw = pl.DataFrame(rows, schema_overrides={"ts_utc": pl.Datetime("us")})
    store.upsert_bars(prepare_bars(raw, "1d", "test"), "1d")


def _assets(store):
    df = pl.DataFrame(
        {
            "symbol": list(SETUP),
            "name": ["Alpha Inc Common Stock", "Beta Corp", "Split Co", "Low Vol Inc", "Fancy Sector ETF"],
            "exchange": ["NASDAQ", "NYSE", "NASDAQ", "NYSE", "NASDAQ"],
            "status": ["active"] * 5,
        }
    )
    refresh_assets(store, df)
    store.upsert_splits(
        pl.DataFrame({"symbol": ["SPL"], "ex_date": [D], "old_rate": [1.0], "new_rate": [10.0], "kind": ["forward"]})
    )


def fake_fetch_many(symbols, timeframe, start_utc, end_utc):
    """Pre-market sintético. Ignora `end` a propósito y devuelve barras trampa después del cutoff."""
    d = (start_utc - timedelta(hours=4)).date()
    rows = []
    for sym in symbols:
        px, vol = SETUP[sym][1] if d == D else (SETUP[sym][0] if d < D else 0, PRIOR_PM_VOLUME)
        if d < D and sym == "SPL":
            px = 500.0
        ts = start_utc
        bars = []
        while ts < et_to_utc_naive(d, time(9, 25)):
            bars.append(ts)
            ts += timedelta(minutes=5)
        for t in bars:
            rows.append({"symbol": sym, "ts_utc": t, "open": px, "high": px, "low": px, "close": px,
                         "volume": vol / len(bars), "trade_count": 10, "vwap": px})  # fmt: skip
        for k in range(10):  # trampa: 09:25..09:34
            t = et_to_utc_naive(d, time(9, 25)) + timedelta(minutes=k)
            rows.append({"symbol": sym, "ts_utc": t, "open": TRAP, "high": TRAP, "low": TRAP, "close": TRAP,
                         "volume": 1e9, "trade_count": 1, "vwap": TRAP})  # fmt: skip
    return pl.DataFrame(rows, schema_overrides={"ts_utc": pl.Datetime("us")})


@pytest.fixture
def scan_store(store):
    _assets(store)
    _daily(store)
    return store


def test_is_common_stock():
    assert is_common_stock("NVIDIA Corporation Common Stock")
    assert is_common_stock("Alibaba Group Holding Limited American Depositary Shares")
    for bad in ("SPDR S&P 500 ETF Trust", "Foo Acquisition Corp Units", "Bar Inc Warrants", "Baz 6.5% Notes due 2030"):
        assert not is_common_stock(bad), bad


def test_adjust_for_splits_point_in_time():
    df = pl.DataFrame(
        {
            "symbol": ["X", "X"],
            "session_date": [date(2025, 3, 13), date(2025, 3, 14)],
            "close": [500.0, 50.0],
            "volume": [1.0, 10.0],
        }
    )
    splits = pl.DataFrame({"symbol": ["X"], "ex_date": [date(2025, 3, 14)], "old_rate": [1.0], "new_rate": [10.0]})
    adj = adjust_for_splits(df, splits, as_of=date(2025, 3, 14))
    assert adj["close"].to_list() == [50.0, 50.0] and adj["volume"].to_list() == [10.0, 10.0]
    # Antes del ex_date el split aún no existe: no se ajusta.
    assert adjust_for_splits(df, splits, as_of=date(2025, 3, 13))["close"].to_list() == [500.0, 50.0]


def test_premarket_summary_excludes_bars_after_cutoff():
    start, cutoff = et_to_utc_naive(D, time(4)), et_to_utc_naive(D, time(9, 25))
    raw = fake_fetch_many(["AAA"], "1m", start, cutoff)
    snap = summarize_premarket(raw, ["AAA", "ZZZ"], D, start, cutoff)
    a = snap.filter(pl.col("symbol") == "AAA").row(0, named=True)
    assert a["last"] == 55.0 and a["high"] < TRAP and a["volume"] == pytest.approx(300_000)
    assert a["last_bar_ts"] + timedelta(minutes=1) <= cutoff
    z = snap.filter(pl.col("symbol") == "ZZZ").row(0, named=True)
    assert z["volume"] == 0 and z["n_bars"] == 0


def test_bar_ending_exactly_at_cutoff_is_included():
    cutoff = et_to_utc_naive(D, time(9, 25))
    raw = pl.DataFrame(
        {"symbol": ["A", "A"], "ts_utc": [cutoff - timedelta(minutes=1), cutoff], "open": [1.0, 9.0], "high": [1.0, 9.0],
         "low": [1.0, 9.0], "close": [1.0, 9.0], "volume": [5.0, 5.0], "trade_count": [1, 1], "vwap": [1.0, 9.0]},
        schema_overrides={"ts_utc": pl.Datetime("us")},
    )  # fmt: skip
    snap = summarize_premarket(raw, ["A"], D, cutoff - timedelta(hours=5), cutoff)
    assert snap["last"][0] == 1.0 and snap["volume"][0] == 5.0  # 09:24 sí (disponible 09:25); 09:25 no


def test_run_scan_end_to_end(scan_store):
    res = run_scan(scan_store, D, CFG, fake_fetch_many)
    assert "ETFX" not in res.universe["symbol"].to_list()
    assert set(res.universe["symbol"]) == {"AAA", "BBB", "SPL", "LOWV"}
    assert res.universe["prev_close"].max() < 100  # trampa diaria de D no visible; SPL ajustado a 50
    wl = {r["symbol"]: r for r in res.watchlist.iter_rows(named=True)}
    assert set(wl) == {"AAA", "SPL"}
    assert wl["AAA"]["gap"] == pytest.approx(0.10)
    assert wl["SPL"]["gap"] == pytest.approx(0.05)
    assert wl["AAA"]["rvol"] == pytest.approx(300_000 / PRIOR_PM_VOLUME)
    assert wl["SPL"]["rvol"] == pytest.approx(250_000 / (PRIOR_PM_VOLUME * 10))  # volumen previo ajustado por split
    assert res.watchlist["rank"].to_list() == [1, 2]
    assert wl["AAA"]["rank"] == 1  # mayor |gap| × $ pre-market


def test_scan_rejects_non_session(scan_store):
    with pytest.raises(ValueError):
        run_scan(scan_store, date(2025, 3, 15), CFG, fake_fetch_many)


def test_scan_uses_cache_on_second_run(scan_store):
    calls = []

    def counting(*a):
        calls.append(a[0])
        return fake_fetch_many(*a)

    run_scan(scan_store, D, CFG, counting)
    n_first = len(calls)
    run_scan(scan_store, D, CFG, counting)
    assert n_first > 0 and len(calls) == n_first


def test_shares_outstanding_point_in_time(store):
    from daytrader.data.sec import shares_outstanding_asof

    store.upsert("sec_tickers", pl.DataFrame({"symbol": ["GOOGL"], "cik": [1652044], "title": ["Alphabet"]}))
    so = pl.DataFrame(
        {
            "cik": [1652044] * 4,
            "tag": ["EntityCommonStockSharesOutstanding"] * 3 + ["CommonStockSharesOutstanding"],
            "priority": [0, 0, 0, 1],
            "end_date": [date(2025, 1, 20), date(2025, 1, 20), date(2025, 4, 20), date(2024, 12, 31)],
            "filed": [date(2025, 2, 4), date(2025, 2, 4), date(2025, 4, 25), date(2025, 2, 4)],
            "accn": ["a1", "a1", "a2", "a1"],
            # dos clases en el mismo reporte; el de abril aún no publicado; el de balance pierde por prioridad
            "shares": [5.8e9, 6.4e9, 1.0, 999.0],
            "form": ["10-K", "10-K", "10-Q", "10-K"],
        }
    )
    store.upsert("shares_outstanding", so)
    r = shares_outstanding_asof(store, ["GOOGL"], date(2025, 3, 14)).row(0, named=True)
    assert r["shares_out"] == pytest.approx(12.2e9) and r["so_filed"] == date(2025, 2, 4)
    r = shares_outstanding_asof(store, ["GOOGL"], date(2025, 4, 25)).row(0, named=True)
    assert r["so_filed"] == date(2025, 2, 4)  # publicado el 25: visible recién el 26
    assert shares_outstanding_asof(store, ["GOOGL"], date(2025, 4, 28))["shares_out"][0] == 1.0
    # Empresa sin dato `dei` (p. ej. PLTR): cae al balance.
    store.upsert("sec_tickers", pl.DataFrame({"symbol": ["PLTR"], "cik": [1321655], "title": ["Palantir"]}))
    store.upsert(
        "shares_outstanding",
        pl.DataFrame(
            {"cik": [1321655], "tag": ["CommonStockSharesOutstanding"], "priority": [1], "end_date": [date(2024, 12, 31)],
             "filed": [date(2025, 2, 18)], "accn": ["p1"], "shares": [2.3e9], "form": ["10-K"]}
        ),
    )  # fmt: skip
    r = shares_outstanding_asof(store, ["PLTR"], date(2025, 3, 14)).row(0, named=True)
    assert r["shares_out"] == 2.3e9 and r["so_tag"] == "CommonStockSharesOutstanding"


def test_universe_first_day_has_no_today_data(scan_store):
    as_of = et_to_utc_naive(D, time(9, 25))
    assert as_of < datetime(2025, 3, 15)
    from daytrader.scanner.universe import stage1

    uni, _ = stage1(scan_store, D, CFG["universe"], as_of)
    assert (uni["prev_date"] < D).all()
