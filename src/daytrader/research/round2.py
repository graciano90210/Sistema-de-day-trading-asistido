"""Ronda 2 (pre-registrada en docs/preregistro_ronda2.md): H1–H5, calibración de ejecución y reporte."""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

from daytrader.backtest.costs import CostModel
from daytrader.backtest.metrics import daily_sharpe, deflated_sharpe, equity_stats, trade_stats
from daytrader.backtest.portfolio import simulate_portfolio
from daytrader.backtest.runner import control_contexts, gapper_contexts, run_backtest, session_list
from daytrader.data.store import Store
from daytrader.market_calendar import sessions

log = logging.getLogger(__name__)
N_TRIALS = 13
PAPER_ACCT = {"max_positions": 20, "max_trades_per_day": 20, "daily_loss_limit": 1.0, "buying_power_mult": 4.0}


# ---------------------------------------------------------------- contextos
def h1_contexts(store: Store, d0: date, d1: date) -> pl.DataFrame:
    return store.query(
        """SELECT session_date, symbol, or_open / prev_close - 1 AS gap, prev_close, atr14, NULL::VARCHAR AS catalyst,
                  rank, rvol, avg_volume * prev_close AS adv_usd
           FROM stocks_in_play WHERE side <> 0 AND session_date BETWEEN ? AND ? ORDER BY session_date, rank""",
        [d0, d1],
    )


def gapper_features(store: Store, d0: date, d1: date) -> pl.DataFrame:
    return store.query(
        "SELECT session_date, symbol, rvol, adv_usd FROM watchlists WHERE session_date BETWEEN ? AND ?", [d0, d1]
    )


# ---------------------------------------------------------------- ejecución calibrada
def with_r(t: pl.DataFrame, mode: str, p: float) -> pl.DataFrame:
    """Sustituye r_net/pnl por el supuesto de ejecución: cons | opt | cal (mezcla con probabilidad p)."""
    if t.is_empty() or "ambiguous" not in t.columns:
        return t
    amb = pl.col("ambiguous").fill_null(False)
    r_opt, pnl_opt = pl.coalesce("r_net_opt", "r_net"), pl.coalesce("pnl_opt", "pnl")
    if mode == "cons":
        return t
    if mode == "opt":
        return t.with_columns(r_opt.alias("r_net"), pnl_opt.alias("pnl"))
    return t.with_columns(
        pl.when(amb).then(p * pl.col("r_net") + (1 - p) * r_opt).otherwise(pl.col("r_net")).alias("r_net"),
        pl.when(amb).then(p * pl.col("pnl") + (1 - p) * pnl_opt).otherwise(pl.col("pnl")).alias("pnl"),
    )


# ---------------------------------------------------------------- features H4
def h4_features(store: Store, t: pl.DataFrame, feats: pl.DataFrame, pvol: pl.DataFrame) -> pl.DataFrame:
    """Variables conocidas en el momento de la entrada (pre-registro H4)."""
    days = sorted(t["session_date"].unique().to_list())
    cal = sessions(days[0], days[-1]).select("session_date", "open_utc")
    # Primeros 5 min de RTH (09:30–09:35 ET) de cada símbolo-día y de SPY, con la apertura real de cada sesión.
    keys = pl.concat([t.select("symbol", "session_date").unique(),
                      pl.DataFrame({"symbol": ["SPY"] * len(days), "session_date": days})]).unique()  # fmt: skip
    store.con.register("_k", keys.join(cal, on="session_date"))
    try:
        first5 = store.query(
            """SELECT b.symbol, b.session_date, max(b.high) - min(b.low) AS or_range,
                      arg_min(b.open, b.ts_utc) AS o5, arg_max(b.close, b.ts_utc) AS c5
               FROM bars_1m b JOIN _k k ON b.symbol = k.symbol AND b.session_date = k.session_date
               WHERE b.ts_utc >= k.open_utc AND b.ts_utc < k.open_utc + INTERVAL 5 MINUTE
               GROUP BY 1, 2"""
        )
    finally:
        store.con.unregister("_k")
    orr = first5.filter(pl.col("symbol") != "SPY").select("symbol", "session_date", "or_range")
    spy_prev = store.query(
        "SELECT session_date, close FROM bars_1d WHERE symbol = 'SPY' AND session_date <= ? ORDER BY session_date",
        [days[-1]],
    ).with_columns(pl.col("close").shift(1).alias("spy_prev_close"))
    spy = (
        first5.filter(pl.col("symbol") == "SPY")
        .join(spy_prev.select("session_date", "spy_prev_close"), on="session_date", how="left")
        .with_columns(
            (pl.col("o5") / pl.col("spy_prev_close") - 1).alias("spy_gap"),
            (pl.col("c5") / pl.col("o5") - 1).alias("spy_or_ret"),
        )
    )
    out = (
        t.join(feats, on=["session_date", "symbol"], how="left")
        .join(orr, on=["symbol", "session_date"], how="left")
        .join(spy.select("session_date", "spy_gap", "spy_or_ret"), on="session_date", how="left")
        .join(pvol, on="session_date", how="left")
        .join(cal, on="session_date", how="left")
        .with_columns(
            pl.col("gap").abs().alias("abs_gap"),
            (pl.col("or_range") / pl.col("planned_risk") * 0.10).alias("or_range_atr"),  # planned_risk = 0,10·ATR
            (pl.col("planned_risk") / 0.10 / pl.col("entry_px")).alias("atr_pct"),
            pl.col("entry_px").alias("price"),
            pl.col("adv_usd").log().alias("log_adv"),
            ((pl.col("entry_ts") - pl.col("open_utc")).dt.total_seconds() / 60).alias("min_to_entry"),
            pl.col("session_date").dt.weekday().alias("dow"),
            (pl.col("strategy") == "h1_orb_sip").cast(pl.Int8).alias("is_h1"),
            (pl.col("r_net") > 0).cast(pl.Int8).alias("label"),
        )
    )
    return out


# ---------------------------------------------------------------- evaluación
def evaluate(name: str, t: pl.DataFrame, acct: dict, days: list[date]) -> dict:
    tt, eq = simulate_portfolio(t, acct, days)
    taken = tt.filter(pl.col("taken")) if "taken" in tt.columns else tt
    ts, es = trade_stats(taken), equity_stats(eq)
    return {"config": name, "trades": ts.get("trades", 0), "win_rate": ts.get("win_rate"), "R_neto": ts.get("avg_r"),
            "t_stat": ts.get("t_stat"), "profit_factor": ts.get("profit_factor"), "sharpe": es.get("sharpe"),
            "max_dd": es.get("max_drawdown"), "retorno": es.get("total_return"), "_eq": eq, "_trades": taken}  # fmt: skip


def promotion(row: dict) -> bool:
    return bool(
        row["trades"] >= 100 and (row["R_neto"] or 0) > 0 and (row["t_stat"] or 0) >= 2.0
        and (row["profit_factor"] or 0) >= 1.2 and (row.get("dsr") or 0) >= 0.95 and (row.get("R_pesimista") or -1) > 0
    )  # fmt: skip


def run_round2(store: Store, bt: dict, variants: dict, scfg: dict, universe: list[str], spy_long: pl.DataFrame,
               p_entry: float | None, api: tuple[str, str] | None, d0: date, d1: date) -> dict:  # fmt: skip
    from daytrader.research.metalabel import walk_forward
    from daytrader.research.regime import predicted_vol_prob
    from daytrader.scanner.premarket import parse_hhmm

    days = session_list(d0, d1)
    acct = bt["account"]
    base = CostModel.from_cfg(bt["costs"], bt["execution"])
    pess = CostModel.from_cfg({**bt["costs"], **bt["cost_scenarios"]["pesimista"]}, bt["execution"])
    paper_cost = CostModel.from_cfg({**bt["costs"], "commission_per_share": 0.0035}, bt["execution"])

    ctx_h1 = h1_contexts(store, d0, d1)
    ctx_g = gapper_contexts(store, d0, d1)
    ctx_c = control_contexts(store, universe, d0, d1, parse_hhmm(scfg["cutoff_et"]))
    jobs = {
        "H1": (ctx_h1, {"h1_orb_sip": variants["h1_orb_sip"]}),
        "H2": (ctx_g, {"h2_orb_stop_gappers": variants["h2_orb_stop_gappers"]}),
        "H3_gappers": (ctx_g, {"h3_vwap_wide": variants["h3_vwap_wide"]}),
        "H3_control": (ctx_c, {"h3_vwap_wide": variants["h3_vwap_wide"]}),
    }
    raw = {k: run_backtest(store, c, v, bt, base) for k, (c, v) in jobs.items()}
    raw_p = {k: run_backtest(store, c, v, bt, pess) for k, (c, v) in jobs.items()}
    raw_h1_paper = run_backtest(store, ctx_h1, {"h1_orb_sip": variants["h1_orb_sip"]}, bt, paper_cost)

    # Calibración de la barra de entrada (H1 ∪ H2), con trades tick
    calib = {"p": p_entry}
    if p_entry is None and api is not None:
        from daytrader.backtest.calibrate import entry_then_stop_probability

        calib = entry_then_stop_probability(pl.concat([raw["H1"], raw["H2"]], how="diagonal_relaxed"), *api)
    p = float(calib["p"])

    pvol = predicted_vol_prob(spy_long, days)
    res, modes = [], {}
    for k in jobs:
        for mode in ("cal", "cons", "opt"):
            modes[(k, mode)] = with_r(raw[k], mode, p)
    # H4 — meta-labeling sobre H1 ∪ H2 (etiqueta con ejecución calibrada)
    feats = pl.concat([
        ctx_h1.select("session_date", "symbol", "rvol", "adv_usd"),
        gapper_features(store, d0, d1).join(ctx_g.select("session_date", "symbol"), on=["session_date", "symbol"]),
    ], how="diagonal_relaxed").unique(subset=["session_date", "symbol"], keep="first")  # fmt: skip
    pool = pl.concat([modes[("H1", "cal")], modes[("H2", "cal")]], how="diagonal_relaxed")
    h4 = walk_forward(h4_features(store, pool, feats, pvol))
    keep = (
        h4.filter(pl.col("p_meta") >= 0.5)
        .select("symbol", "session_date", "strategy")
        .with_columns(pl.lit(True).alias("_k"))
    )
    h4_months = h4.filter(pl.col("p_meta").is_not_null())["session_date"]
    h4_start = h4_months.min() if h4_months.len() else d1

    def h4_filter(t):
        return t.join(keep, on=["symbol", "session_date", "strategy"], how="inner").drop("_k")

    hi = pvol.filter(pl.col("p_vol") >= 0.5)["session_date"]
    lo_ = pvol.filter(pl.col("p_vol") < 0.5)["session_date"]

    def cfgs(get):
        return {
            "H1": get("H1"), "H2": get("H2"), "H3_gappers": get("H3_gappers"), "H3_control": get("H3_control"),
            "H4": h4_filter(pl.concat([get("H1"), get("H2")], how="diagonal_relaxed")),
            "H5a": get("H1").filter(pl.col("session_date").is_in(hi)),
            "H5b": get("H3_gappers").filter(pl.col("session_date").is_in(lo_)),
        }  # fmt: skip

    cal_sets = cfgs(lambda k: modes[(k, "cal")])
    cons_sets = cfgs(lambda k: modes[(k, "cons")])
    opt_sets = cfgs(lambda k: modes[(k, "opt")])
    pes_sets = cfgs(lambda k: with_r(raw_p[k], "cal", p))
    for name, t in cal_sets.items():
        dd = [d for d in days if d >= h4_start] if name == "H4" else days
        row = evaluate(name, t, acct, dd)
        row["R_cons"] = evaluate(name, cons_sets[name], acct, dd)["R_neto"]
        row["R_opt"] = evaluate(name, opt_sets[name], acct, dd)["R_neto"]
        row["R_pesimista"] = evaluate(name, pes_sets[name], acct, dd)["R_neto"]
        res.append(row)
    extra = {
        "H1_cartera_paper": evaluate("H1 (cartera del paper)", cal_sets["H1"], {**acct, **PAPER_ACCT}, days),
        "H1_comision_paper": evaluate("H1 (comisión $0,0035)", with_r(raw_h1_paper, "cal", p), acct, days),
    }
    return {"rows": res, "extra": extra, "calib": calib, "pvol": pvol, "h4": h4, "h4_start": h4_start, "days": days}


def trial_sharpes_round1(store: Store, bt: dict, files: list) -> list[float]:
    out = []
    for f in files:
        t = pl.read_parquet(f).drop(["taken", "skip_reason", "pnl_usd", "risk_usd"], strict=False)
        _, eq = simulate_portfolio(t, bt["account"], session_list(t["session_date"].min(), t["session_date"].max()))
        out.append(daily_sharpe(eq))
    return out


def finalize(result: dict, round1_sharpes: list[float]) -> list[dict]:
    rows = result["rows"]
    sharpes = round1_sharpes + [daily_sharpe(r["_eq"]) for r in rows]
    for r in rows:
        r["dsr"] = deflated_sharpe(r["_eq"]["ret"].fill_null(0.0).to_numpy(), sharpes)
        r["pasa"] = promotion(r)
    return rows
