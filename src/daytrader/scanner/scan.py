"""Scanner de gappers de pre-market, point-in-time a las `cutoff_et` de la sesión D."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import polars as pl

from daytrader.data.adjust import adjust_for_splits
from daytrader.data.alpaca_client import MultiFetcher
from daytrader.data.store import Store
from daytrader.market_calendar import et_to_utc_naive, is_session
from daytrader.scanner.premarket import ensure_snapshots, load_snapshots, parse_hhmm
from daytrader.scanner.universe import previous_sessions, stage1


@dataclass
class ScanResult:
    session_date: date
    cutoff_utc: datetime
    funnel: list[tuple[str, int]] = field(default_factory=list)
    universe: pl.DataFrame = field(default_factory=pl.DataFrame)
    candidates: pl.DataFrame = field(default_factory=pl.DataFrame)  # pasan todos los filtros
    watchlist: pl.DataFrame = field(default_factory=pl.DataFrame)  # top N


def run_scan(
    store: Store,
    d: date,
    cfg: dict,
    fetch_many: MultiFetcher,
    shares_lookup=None,  # callable(symbols, d) -> DataFrame[symbol, shares_out, ...] o None
) -> ScanResult:
    if not is_session(d):
        raise ValueError(f"{d} no es una sesión NYSE")
    start_et, cutoff_et = parse_hhmm(cfg["premarket_start_et"]), parse_hhmm(cfg["cutoff_et"])
    cutoff_utc = et_to_utc_naive(d, cutoff_et)
    g = cfg["gappers"]
    res = ScanResult(d, cutoff_utc)

    # Etapa 1: universo líquido (sesiones < d).
    uni, funnel = stage1(store, d, cfg["universe"], as_of=cutoff_utc)
    res.universe, res.funnel = uni, funnel
    syms = uni["symbol"].to_list()

    # Etapa 2a: pre-market de hoy para todo el universo → gap y volumen.
    ensure_snapshots(store, fetch_many, syms, [d], start_et, cutoff_et)
    today = load_snapshots(store, syms, [d], cutoff_et).select(
        "symbol",
        pl.col("last").alias("pm_last"),
        pl.col("high").alias("pm_high"),
        pl.col("low").alias("pm_low"),
        pl.col("volume").alias("pm_volume"),
        pl.col("dollar_volume").alias("pm_dollar_volume"),
        pl.col("n_bars").alias("pm_bars"),
    )
    df = uni.join(today, on="symbol", how="left").with_columns(
        (pl.col("pm_last") / pl.col("prev_close") - 1).alias("gap")
    )
    df = df.filter(pl.col("pm_bars") > 0)
    res.funnel.append(("con operaciones en pre-market", df.height))
    df = df.filter(pl.col("gap").abs() >= g["min_abs_gap"])
    res.funnel.append((f"|gap| >= {g['min_abs_gap']:.0%}", df.height))
    df = df.filter(pl.col("pm_volume") >= g["min_premarket_volume"])
    res.funnel.append((f"volumen pre-market >= {g['min_premarket_volume']:,}", df.height))

    # Etapa 2b: RVOL a la misma hora vs. las N sesiones previas (solo para los que quedan).
    prior = previous_sessions(d, int(g["rvol_lookback"]))
    left = df["symbol"].to_list()
    ensure_snapshots(store, fetch_many, left, prior, start_et, cutoff_et)
    hist = load_snapshots(store, left, prior, cutoff_et)
    hist = adjust_for_splits(hist, store.query("SELECT * FROM splits"), d, price_cols=("last", "high", "low"))
    avg = hist.group_by("symbol").agg(pl.col("volume").mean().alias("pm_avg_volume"), pl.len().alias("rvol_days"))
    df = df.join(avg, on="symbol", how="left").with_columns(
        pl.when(pl.col("pm_avg_volume") > 0)
        .then(pl.col("pm_volume") / pl.col("pm_avg_volume"))
        .otherwise(float("inf"))
        .alias("rvol")
    )
    df = df.filter(pl.col("rvol") >= g["min_rvol"])
    res.funnel.append((f"RVOL >= {g['min_rvol']}", df.height))

    # Float (acciones en circulación, SEC) — informativo y filtro opcional.
    if shares_lookup is not None:
        so = shares_lookup(df["symbol"].to_list(), d)
        df = df.join(so, on="symbol", how="left")
        if g.get("max_shares_outstanding"):
            df = df.filter(pl.col("shares_out") <= g["max_shares_outstanding"])
            res.funnel.append((f"acciones en circulación <= {g['max_shares_outstanding']:,}", df.height))

    df = df.with_columns((pl.col("gap").abs() * pl.col("pm_dollar_volume")).alias("score")).sort(
        "score", descending=True
    )
    res.candidates = df
    res.watchlist = df.head(int(g["top_n"])).with_row_index("rank", offset=1)
    res.funnel.append((f"watchlist (top {g['top_n']})", res.watchlist.height))
    return res
