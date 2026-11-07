"""Ronda 4 (docs/preregistro_ronda4.md): patrones P1/P2, H3'/H5b'/H4' sobre 10 años y universo point-in-time."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, time, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from daytrader.backtest.costs import CostModel
from daytrader.backtest.metrics import daily_sharpe, deflated_sharpe
from daytrader.backtest.runner import control_contexts, run_backtest, session_list
from daytrader.data.store import Store
from daytrader.research.history10y import universe_for
from daytrader.research.metalabel import N_TREES, PARAMS
from daytrader.research.round2 import evaluate

log = logging.getLogger(__name__)

N_TRIALS = 30  # 25 previos + P1, P2, H3', H5b', H4'
CACHE_DIR = Path("data/cache/round4")  # backtests por año (ignorado por git)
PERIODS = {
    "desarrollo": (date(2017, 1, 3), date(2021, 12, 31)),  # desviación 1: Alpaca empieza en 2016-01-04
    "validacion": (date(2022, 1, 3), date(2024, 10, 31)),
    "ya_visto": (date(2024, 11, 1), date(2025, 12, 31)),
}
MAIN = ["P1", "P2", "H3"]
NEIGHBORS = {
    "P1": [("pole_atr", 0.30), ("pole_atr", 0.50), ("vol_ratio", 0.6), ("vol_ratio", 0.8)],
    "P2": [("tol_atr", 0.05), ("tol_atr", 0.15), ("depth_atr", 0.20), ("depth_atr", 0.30)],
}
H4_FEATURES = ["side", "gap", "abs_gap", "atr_pct", "price", "log_adv", "min_from_open", "dow", "p_vol",
               "spy_ret", "sym_ret_atr", "is_p1", "is_p2"]  # fmt: skip
H4_WARMUP_MONTHS = 12


def variants(strat: dict) -> dict[str, dict]:
    base = {"P1": strat["p1_flag"], "P2": strat["p2_double"], "H3": strat["h3_vwap_wide"]}
    out = dict(base)
    for k, nb in NEIGHBORS.items():
        for param, val in nb:
            out[f"{k}_{param}{val}"] = {**base[k], param: val}
    return out


def contexts(hist: Store, d0: date, d1: date, cutoff: time) -> pl.DataFrame:
    """Contextos por año con el universo point-in-time de ese año (+ $ volumen del año previo)."""
    parts = []
    for y in range(d0.year, d1.year + 1):
        a, b = max(d0, date(y, 1, 1)), min(d1, date(y, 12, 31))
        syms = universe_for(hist, y)
        c = control_contexts(hist, syms, a, b, cutoff)
        adv = hist.query("SELECT symbol, adv_usd FROM universe_pit WHERE year = ?", [y])
        parts.append(c.join(adv, on="symbol", how="left"))
    return pl.concat(parts, how="diagonal_relaxed")


# ------------------------------------------------------------------ H4' (meta-labeling)
def h4_features(hist: Store, t: pl.DataFrame, ctx: pl.DataFrame, pvol: pl.DataFrame) -> pl.DataFrame:
    """Variables conocidas ANTES de la vela de señal: precios con ts_utc < signal_ts (barras ya cerradas)."""
    from daytrader.market_calendar import sessions

    days = sorted(t["session_date"].unique().to_list())
    cal = sessions(days[0], days[-1]).select("session_date", "open_utc")
    keys = t.select("symbol", "session_date", "signal_ts").unique().join(cal, on="session_date")
    spy_keys = keys.select("session_date", "signal_ts", "open_utc").unique().with_columns(pl.lit("SPY").alias("symbol"))
    allk = pl.concat([keys, spy_keys.select(keys.columns)]).unique()
    out = []
    for y in sorted({d.year for d in days}):
        k = allk.filter(pl.col("session_date").dt.year() == y)
        hist.con.register("_k", k)
        try:
            out.append(hist.query("""
                WITH b AS (
                    SELECT x.symbol, x.session_date, x.ts_utc, x.open, x.close FROM bars_1m x
                    WHERE x.session = 'rth' AND x.session_date BETWEEN ? AND ?
                      AND x.symbol IN (SELECT DISTINCT symbol FROM _k)
                ), o AS (SELECT symbol, session_date, arg_min(open, ts_utc) AS day_open FROM b GROUP BY 1, 2)
                SELECT k.symbol, k.session_date, k.signal_ts, o.day_open, b.close AS px_before
                FROM _k k LEFT JOIN o USING (symbol, session_date)
                ASOF LEFT JOIN b ON k.symbol = b.symbol AND k.session_date = b.session_date AND k.signal_ts > b.ts_utc
            """, [date(y, 1, 1), date(y, 12, 31)]))  # fmt: skip
        finally:
            hist.con.unregister("_k")
    px = pl.concat(out).with_columns((pl.col("px_before") / pl.col("day_open") - 1).alias("ret_open"))
    spy = px.filter(pl.col("symbol") == "SPY").select("session_date", "signal_ts", pl.col("ret_open").alias("spy_ret"))
    sym = px.filter(pl.col("symbol") != "SPY").select("symbol", "session_date", "signal_ts", "day_open", "px_before")
    c = ctx.select("symbol", "session_date", "atr14", "prev_close", "adv_usd")
    return (
        t.join(c, on=["symbol", "session_date"], how="left")
        .join(sym, on=["symbol", "session_date", "signal_ts"], how="left")
        .join(spy, on=["session_date", "signal_ts"], how="left")
        .join(pvol, on="session_date", how="left")
        .join(cal, on="session_date", how="left")
        .with_columns(
            pl.col("gap").abs().alias("abs_gap"),
            (pl.col("atr14") / pl.col("prev_close")).alias("atr_pct"),
            pl.col("entry_px").alias("price"),
            pl.col("adv_usd").log().alias("log_adv"),
            ((pl.col("signal_ts") - pl.col("open_utc")).dt.total_seconds() / 60).alias("min_from_open"),
            pl.col("session_date").dt.weekday().alias("dow"),
            ((pl.col("px_before") - pl.col("day_open")) / pl.col("atr14")).alias("sym_ret_atr"),
            (pl.col("strategy") == "P1").cast(pl.Int8).alias("is_p1"),
            (pl.col("strategy") == "P2").cast(pl.Int8).alias("is_p2"),
            (pl.col("r_net") > 0).cast(pl.Int8).alias("label"),
        )
    )


def h4_walk_forward(df: pl.DataFrame) -> pl.DataFrame:
    """Expansivo mensual, embargo 1 día, 12 meses de warm-up, hiperparámetros de la ronda 2. Añade p_meta."""
    df = df.sort("session_date", "entry_ts")
    x = df.select(H4_FEATURES).to_numpy().astype(float)
    y = df["label"].to_numpy()
    sd = np.array(df["session_date"].to_list())
    p = np.full(df.height, np.nan)
    months = sorted({(d.year, d.month) for d in sd})
    for k, (yy, mm) in enumerate(months):
        if k < H4_WARMUP_MONTHS:
            continue
        first = date(yy, mm, 1)
        train = sd < first - timedelta(days=1)
        test = np.array([(d.year, d.month) == (yy, mm) for d in sd])
        if train.sum() < 200 or len(set(y[train])) < 2:
            continue
        booster = lgb.train(PARAMS, lgb.Dataset(x[train], y[train]), num_boost_round=N_TREES)
        p[test] = booster.predict(x[test])
    return df.with_columns(pl.Series("p_meta", p).fill_nan(None))


# ------------------------------------------------------------------ evaluación
def _period(t: pl.DataFrame, d0: date, d1: date) -> pl.DataFrame:
    return t.filter(pl.col("session_date").is_between(d0, d1)) if not t.is_empty() else t


def by_year(t: pl.DataFrame) -> dict[int, float]:
    if t.is_empty():
        return {}
    g = t.group_by(pl.col("session_date").dt.year().alias("y")).agg(pl.col("r_net").mean()).sort("y")
    return dict(g.iter_rows())


def promotion(row: dict) -> tuple[bool, list[str]]:
    """Regla del pre-registro. Devuelve (pasa, motivos por los que no pasa)."""
    fails = []
    checks = [
        (row["trades"] >= 100, "menos de 100 trades"),
        ((row["R_neto"] or 0) > 0 and (row["t_stat"] or 0) >= 2.0, "R neto no es > 0 con t ≥ 2"),
        ((row["profit_factor"] or 0) >= 1.3, "PF < 1,3"),
        ((row.get("dsr") or 0) >= 0.95, "DSR < 0,95"),
        ((row.get("R_pesimista") or -1) > 0, "R ≤ 0 con costos pesimistas"),
        ((row["max_dd"] if row["max_dd"] is not None else -1) >= -0.20, "drawdown peor que −20 %"),
        ((row.get("R_desarrollo") or -1) > 0, "R ≤ 0 en desarrollo"),
        (sum(1 for v in row.get("R_por_anio_val", {}).values() if v > 0) >= 2, "R > 0 en menos de 2 de 3 años"),
        (row.get("vecinos_pos") is None or row["vecinos_pos"] >= 3, "menos de 3 de 4 vecinos con R > 0"),
    ]
    for ok, why in checks:
        if not ok:
            fails.append(why)
    return not fails, fails


def prior_sharpes(files: list) -> list[float]:
    from daytrader.backtest.portfolio import simulate_portfolio

    out = []
    for f in files:
        t = pl.read_parquet(f).drop(["taken", "skip_reason", "pnl_usd", "risk_usd"], strict=False)
        if t.is_empty():
            continue
        acct = {"initial_equity": 100_000, "risk_per_trade": 0.01, "max_positions": 5, "max_trades_per_day": 10,
                "daily_loss_limit": 0.03, "buying_power_mult": 4.0}  # fmt: skip
        _, eq = simulate_portfolio(t, acct, session_list(t["session_date"].min(), t["session_date"].max()))
        out.append(daily_sharpe(eq))
    return out


def run_round4(hist: Store, bt: dict, strat: dict, cutoff: time, prior: list[float], on_step=None) -> dict:
    from daytrader.research.regime import predicted_vol_prob

    say = on_step or (lambda m: None)
    d0, d1 = PERIODS["desarrollo"][0], PERIODS["ya_visto"][1]
    base = CostModel.from_cfg(bt["costs"], bt["execution"])
    pess = CostModel.from_cfg({**bt["costs"], **bt["cost_scenarios"]["pesimista"]}, bt["execution"])
    acct = bt["account"]
    first_spy = hist.query("SELECT min(session_date) AS d FROM bars_1d WHERE symbol = 'SPY'")["d"][0]
    if first_spy is None or first_spy > date(2016, 1, 31):
        raise RuntimeError("Falta la historia diaria de SPY 2016+: corre `daytrader historia --paso benchmarks`.")
    say("contextos por año…")
    ctx = contexts(hist, d0, d1, cutoff)
    say(f"contextos: {ctx.height:,} símbolo-días")
    vs = variants(strat)
    parts = []
    # Caché por año (reanudable si se corta): la clave depende de toda la configuración → cambiarla invalida.
    key = hashlib.sha256(json.dumps([vs, bt, str(cutoff), str(d0), str(d1)], sort_keys=True, default=str)
                         .encode()).hexdigest()[:12]  # fmt: skip
    cache = CACHE_DIR / key
    cache.mkdir(parents=True, exist_ok=True)
    for y in range(d0.year, d1.year + 1):  # por año: acota memoria y deja progreso
        f = cache / f"{y}.parquet"
        if f.exists():
            parts.append(pl.read_parquet(f))
            say(f"backtest {y}: {parts[-1].height:,} trades (caché)")
            continue
        cy = ctx.filter(pl.col("session_date").dt.year() == y)
        parts.append(run_backtest(hist, cy, vs, bt, base, alt_costs=pess, alt_variants=set(MAIN)))
        parts[-1].write_parquet(f)
        say(f"backtest {y}: {parts[-1].height:,} trades")
    raw = pl.concat([p for p in parts if not p.is_empty()], how="diagonal_relaxed")
    tb, tp = raw.filter(pl.col("costs") == "base"), raw.filter(pl.col("costs") == "alt")

    spy = hist.query("SELECT session_date, high, low, close FROM bars_1d WHERE symbol = 'SPY' AND session_date <= ? "
                     "ORDER BY session_date", [d1])  # fmt: skip
    if spy.is_empty() or spy["session_date"].min() > date(2016, 1, 31):
        raise RuntimeError("Falta la historia diaria de SPY 2016+: corre `daytrader historia --paso benchmarks`.")
    say("HMM mensual sobre SPY…")
    pvol = predicted_vol_prob(spy, session_list(d0, d1))
    calm = pvol.filter(pl.col("p_vol") < 0.5)["session_date"]

    sets = {k: tb.filter(pl.col("strategy") == k) for k in vs}
    psets = {k: tp.filter(pl.col("strategy") == k) for k in MAIN}
    sets["H5b"] = sets["H3"].filter(pl.col("session_date").is_in(calm))
    psets["H5b"] = psets["H3"].filter(pl.col("session_date").is_in(calm))
    say("meta-labeling walk-forward…")
    union = pl.concat([sets["P1"], sets["P2"], sets["H3"]], how="diagonal_relaxed")
    feats = h4_walk_forward(h4_features(hist, union, ctx, pvol))
    keep = feats.filter(pl.col("p_meta") >= 0.5).select("symbol", "session_date", "strategy", "entry_ts")
    sets["H4"] = feats.filter(pl.col("p_meta") >= 0.5).select(union.columns)
    pu = pl.concat([psets["P1"], psets["P2"], psets["H3"]], how="diagonal_relaxed")
    psets["H4"] = pu.join(keep, on=["symbol", "session_date", "strategy", "entry_ts"], how="semi")

    trials = ["P1", "P2", "H3", "H5b", "H4"]
    rows = {}
    for name in [*trials, *[k for k in vs if k not in MAIN]]:
        res = {}
        for per, (a, b) in PERIODS.items():
            days = session_list(a, b)
            r = evaluate(name, _period(sets[name], a, b), acct, days)
            if name in psets:
                r["R_pesimista"] = evaluate(name, _period(psets[name], a, b), acct, days)["R_neto"]
            r["R_por_anio"] = by_year(r["_trades"])
            res[per] = r
        rows[name] = res
    sharpes = prior + [daily_sharpe(rows[n]["validacion"]["_eq"]) for n in trials]
    for name in trials:
        v = rows[name]["validacion"]
        v["dsr"] = deflated_sharpe(v["_eq"]["ret"].fill_null(0.0).to_numpy(), sharpes, n_trials=N_TRIALS)
        v["R_desarrollo"] = rows[name]["desarrollo"]["R_neto"]
        v["R_por_anio_val"] = v["R_por_anio"]
        if name in NEIGHBORS:
            nb = [f"{name}_{p}{x}" for p, x in NEIGHBORS[name]]
            v["vecinos"] = {k: rows[k]["validacion"]["R_neto"] for k in nb}
            v["vecinos_pos"] = sum(1 for x in v["vecinos"].values() if (x or 0) > 0)
        else:
            v["vecinos_pos"] = None
        v["pasa"], v["motivos"] = promotion(v)
    # Diagnóstico honesto: R bruto (sin costos) por periodo para ver si la señal predice algo
    gross = {n: {per: (float(_period(sets[n], a, b)["r_gross"].mean()) if not _period(sets[n], a, b).is_empty() else None)
                 for per, (a, b) in PERIODS.items()} for n in trials}  # fmt: skip
    return {"rows": rows, "trials": trials, "gross": gross, "sets": sets, "n_ctx": ctx.height, "pvol": pvol}
