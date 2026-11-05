"""Backfill de watchlists históricas + barras intradía de sus tickers (reanudable por día)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, time

import polars as pl

from daytrader.catalysts.news import NewsFetcher, catalyst_summary, ensure_news, news_for
from daytrader.data.alpaca_client import MultiFetcher
from daytrader.data.ingest import prepare_bars
from daytrader.data.store import Store
from daytrader.market_calendar import REGULAR_CLOSE_ET, et_to_utc_naive, sessions
from daytrader.scanner.scan import run_scan
from daytrader.scanner.universe import previous_sessions

log = logging.getLogger(__name__)

WL_COLUMNS = [
    "session_date", "cutoff_utc", "rank", "symbol", "gap", "pm_last", "prev_close", "pm_volume", "rvol",
    "pm_dollar_volume", "atr14", "atr_pct", "adv_usd", "shares_out", "catalyst", "n_news", "n_relevant",
]  # fmt: skip


def scannable_days(store: Store, start: date, end: date, min_history: int = 21) -> list[date]:
    """Sesiones en [start, end] con al menos `min_history` sesiones diarias previas en la DB."""
    first = store.query("SELECT min(session_date) AS d FROM bars_1d")["d"][0]
    all_days = sessions(first, end)["session_date"].to_list()
    return [d for i, d in enumerate(all_days) if i >= min_history and d >= start]


def ensure_intraday(store: Store, fetch_many: MultiFetcher, symbols: list[str], d: date, feed: str) -> int:
    """Barras de 1 min 04:00–20:00 ET de `symbols` en la sesión d (salta los que ya tienen datos RTH)."""
    if not symbols:
        return 0
    have = set(
        store.query(
            f"SELECT DISTINCT symbol FROM bars_1m WHERE session_date = ? AND session = 'rth' "
            f"AND symbol IN ({','.join('?' * len(symbols))})",
            [d, *symbols],
        )["symbol"].to_list()
    )
    todo = [s for s in symbols if s not in have]
    if not todo:
        return 0
    raw = fetch_many(todo, "1m", et_to_utc_naive(d, time(4)), et_to_utc_naive(d, time(19, 59)))
    df = prepare_bars(raw, "1m", feed).filter(pl.col("session_date") == d)
    return store.upsert_bars(df, "1m")


def backfill(
    store: Store,
    days: list[date],
    scan_cfg: dict,
    fetch_many: MultiFetcher,
    news_fetch: NewsFetcher | None,
    shares_lookup: Callable | None,
    feed: str,
    on_day: Callable[[date, int, int], None] | None = None,
) -> tuple[int, int]:
    done = set(store.query("SELECT session_date FROM scan_log WHERE status = 'ok'")["session_date"].to_list())
    names = dict(store.query("SELECT symbol, name FROM assets").iter_rows())
    ok = err = 0
    for d in days:
        if d in done:
            continue
        try:
            res = run_scan(store, d, scan_cfg, fetch_many, shares_lookup)
            wl = res.watchlist
            syms = wl["symbol"].to_list()
            cats = None
            if news_fetch is not None and syms:
                start = et_to_utc_naive(previous_sessions(d, 1)[0], REGULAR_CLOSE_ET)
                ensure_news(store, news_fetch, syms, start, res.cutoff_utc)
                news = news_for(
                    store, syms, start, res.cutoff_utc, names, scan_cfg["catalysts"]["max_symbols_for_relevance"]
                )
                cats = catalyst_summary(news)
            if syms:
                out = wl.with_columns(pl.lit(d).alias("session_date"), pl.lit(res.cutoff_utc).alias("cutoff_utc"))
                if cats is not None:
                    out = out.join(cats.drop("top_headline"), on="symbol", how="left")
                for c in WL_COLUMNS:
                    if c not in out.columns:
                        out = out.with_columns(pl.lit(None).alias(c))
                if news_fetch is not None:
                    out = out.with_columns(pl.col("catalyst").fill_null("sin_noticias"))
                store.upsert("watchlists", out.select(WL_COLUMNS).with_columns(pl.col("rank").cast(pl.Int32)))
                ensure_intraday(store, fetch_many, syms, d, feed)
            store.upsert(
                "scan_log",
                pl.DataFrame(
                    {"session_date": [d], "n_universe": [res.universe.height], "n_candidates": [res.candidates.height],
                     "n_watchlist": [wl.height], "status": ["ok"], "error": [None], "finished_at": [datetime.now()]},
                    schema_overrides={"error": pl.Utf8},
                ),
            )  # fmt: skip
            ok += 1
        except Exception as exc:
            log.exception("Backfill %s falló", d)
            store.upsert(
                "scan_log",
                pl.DataFrame(
                    {"session_date": [d], "n_universe": [0], "n_candidates": [0], "n_watchlist": [0],
                     "status": ["error"], "error": [str(exc)[:500]], "finished_at": [datetime.now()]}
                ),
            )  # fmt: skip
            err += 1
        if on_day:
            on_day(d, ok, err)
    return ok, err
