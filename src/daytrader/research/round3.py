"""Ronda 3 (docs/preregistro_ronda3.md): VWAP con órdenes límite, rejilla de 12 y ajuste walk-forward."""

from __future__ import annotations

import itertools
import logging
from datetime import date

import polars as pl

from daytrader.backtest.costs import CostModel
from daytrader.backtest.runner import control_contexts, gapper_contexts, run_backtest, session_list
from daytrader.data.store import Store
from daytrader.research.round2 import evaluate, with_r

log = logging.getLogger(__name__)
GRID_M = [0.0, 0.5, 1.0]
GRID_W = [2, 5]
GRID_REGIME = ["ninguno", "tranquilo"]
DEFAULT = ("m0.5_w5", "ninguno")
WARMUP_MONTHS = 3
MIN_HIST_TRADES = 100
AMBIG_THRESHOLD = 0.05


def variants(base: dict) -> dict[str, dict]:
    return {
        f"m{m}_w{w}": {**base, "type": "vwap_limit", "limit_offset_hs": m, "limit_valid_min": w}
        for m, w in itertools.product(GRID_M, GRID_W)
    }


def configs() -> list[tuple[str, str]]:
    return [(f"m{m}_w{w}", r) for m, w in itertools.product(GRID_M, GRID_W) for r in GRID_REGIME]


def apply_regime(t: pl.DataFrame, regime: str, calm_days) -> pl.DataFrame:
    return t if regime == "ninguno" else t.filter(pl.col("session_date").is_in(calm_days))


def walk_forward_select(trades_by_cfg: dict[tuple[str, str], pl.DataFrame], months: list[tuple[int, int]]):
    """Para cada mes M (tras el warm-up), elige la config con mayor R medio en meses < M (≥ 100 trades)."""
    chosen, parts = [], []
    for k, (y, m) in enumerate(months):
        if k < WARMUP_MONTHS:
            continue
        best, best_r = DEFAULT, None
        for cfg, t in trades_by_cfg.items():
            hist = t.filter((pl.col("session_date").dt.year() * 100 + pl.col("session_date").dt.month()) < y * 100 + m)
            if hist.height >= MIN_HIST_TRADES:
                r = float(hist["r_net"].mean())
                if best_r is None or r > best_r:
                    best, best_r = cfg, r
        chosen.append({"mes": f"{y}-{m:02d}", "config": f"{best[0]} · {best[1]}", "R_hist": best_r})
        cur = trades_by_cfg[best]
        parts.append(cur.filter((pl.col("session_date").dt.year() == y) & (pl.col("session_date").dt.month() == m)))
    wf = pl.concat([p for p in parts if not p.is_empty()], how="diagonal_relaxed") if parts else pl.DataFrame()
    return wf, chosen


def run_round3(store: Store, bt: dict, strat: dict, scfg: dict, universe: list[str], pvol: pl.DataFrame,
               api: tuple[str, str], d0: date, d1: date) -> dict:  # fmt: skip
    from daytrader.backtest.calibrate import entry_then_stop_probability
    from daytrader.scanner.premarket import parse_hhmm

    days = session_list(d0, d1)
    base = CostModel.from_cfg(bt["costs"], bt["execution"])
    pess = CostModel.from_cfg({**bt["costs"], **bt["cost_scenarios"]["pesimista"]}, bt["execution"])
    ctx = pl.concat(
        [gapper_contexts(store, d0, d1).with_columns(pl.lit("gappers").alias("universo")),
         control_contexts(store, universe, d0, d1, parse_hhmm(scfg["cutoff_et"])).with_columns(pl.lit("control").alias("universo"))],
        how="diagonal_relaxed",
    ).unique(subset=["session_date", "symbol"], keep="first")  # fmt: skip
    vs = variants(strat["h3_vwap_wide"])
    ref = {"mercado_ref": strat["h3_vwap_wide"]}  # misma señal con entrada a mercado (referencia y denominador)
    raw_all = run_backtest(store, ctx, {**vs, **ref}, bt, base)
    raw = raw_all.filter(pl.col("strategy") != "mercado_ref")
    market = raw_all.filter(pl.col("strategy") == "mercado_ref")
    raw_p = run_backtest(store, ctx, vs, bt, pess)

    amb_rate = float(raw["ambiguous"].mean()) if raw.height else 0.0
    calib = {"p": 1.0, "tasa_ambiguas": amb_rate, "nota": "≤5% ambiguas: supuesto conservador"}
    if amb_rate > AMBIG_THRESHOLD:
        calib = {**entry_then_stop_probability(raw, *api, kind="limit"), "tasa_ambiguas": amb_rate}
    p = float(calib["p"])
    calm = pvol.filter(pl.col("p_vol") < 0.5)["session_date"]

    def by_cfg(src):
        t = with_r(src, "cal", p)
        return {(v, r): apply_regime(t.filter(pl.col("strategy") == v), r, calm) for v, r in configs()}

    cfg_t, cfg_tp = by_cfg(raw), by_cfg(raw_p)
    months = sorted({(d.year, d.month) for d in days})
    wf, chosen = walk_forward_select(cfg_t, months)
    wf_days = [d for d in days if (d.year, d.month) in {(y, m) for y, m in months[WARMUP_MONTHS:]}]
    # pesimista: mismas elecciones mensuales, otro modelo de costos
    wf_p = pl.concat([
        cfg_tp[(c["config"].split(" · ")[0], c["config"].split(" · ")[1])].filter(
            pl.col("session_date").dt.strftime("%Y-%m") == c["mes"])
        for c in chosen
    ], how="diagonal_relaxed")  # fmt: skip
    acct = bt["account"]
    row = evaluate("Ronda 3 walk-forward", wf, acct, wf_days)
    row["R_pesimista"] = evaluate("pes", wf_p, acct, wf_days)["R_neto"]
    row["R_cons"] = evaluate("cons", with_r(wf, "cons", p), acct, wf_days)["R_neto"]
    n_sig = {"ninguno": market.height,
             "tranquilo": market.filter(pl.col("session_date").is_in(calm)).height}  # fmt: skip
    grid = []
    for (v, r), t in cfg_t.items():
        g = evaluate(f"{v} · {r}", t, acct, days)
        g["fill_rate"] = t.height / n_sig[r] if n_sig[r] else None
        grid.append(g)
    ref_row = evaluate("Mercado (referencia, H3 sobre el mismo universo)", market, acct, days)
    return {"wf": row, "chosen": chosen, "grid": grid, "calib": calib, "raw": raw, "days": days, "wf_days": wf_days,
            "market_ref": ref_row}  # fmt: skip
