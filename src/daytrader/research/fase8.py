"""Fase 8 — swing trading pre-registrado (docs/preregistro_fase8_swing.md). Todo fijo antes de los resultados.

Datos hasta 2025-12-31 como máximo: el OOS ≥ 2026 sigue sellado (ni siquiera se cargan sus barras).
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl

from daytrader.backtest.daily import BASE, PESSIMISTIC, Panel, simulate_events, simulate_rotation
from daytrader.backtest.metrics import deflated_sharpe, equity_stats, trade_stats
from daytrader.data.adjust import adjust_for_splits
from daytrader.data.store import Store
from daytrader.strategies import swing

N_TRIALS = 34  # 30 previos + S1–S4
LOAD_FROM, SIM_FROM, DATA_END = date(2015, 12, 1), date(2016, 12, 1), date(2025, 12, 31)
FIRST_YEAR, LAST_YEAR, UNIVERSE_N = 2017, 2025, 500
PERIODS = {
    "desarrollo": (date(2017, 1, 3), date(2021, 12, 31)),
    "validacion": (date(2022, 1, 3), date(2024, 10, 31)),
    "ya_visto": (date(2024, 11, 1), date(2025, 12, 31)),
}
VAL_YEARS = [(date(2022, 1, 3), date(2022, 12, 31)), (date(2023, 1, 1), date(2023, 12, 31)),
             (date(2024, 1, 1), date(2024, 10, 31))]  # fmt: skip

MAIN = {
    "S1": ("rotation", {"lookback_months": 12, "skip_months": 1, "top": 10}),
    "S2": ("rotation", {"window": 5, "top": 10, "min_price": 10.0, "max_drop": 0.30}),
    "S3": ("events", {"vol_mult": 3.0, "atr_mult": 1.5, "close_frac": 0.3, "stop_atr": 2.0, "max_hold": 10}),
    "S4": ("events", {"rsi_max": 10.0, "stop_atr": 2.5, "max_hold": 10}),
}
NEIGHBORS = {
    "S1": [("top5", {"top": 5}), ("top20", {"top": 20}), ("lb6", {"lookback_months": 6}),
           ("lb9", {"lookback_months": 9})],
    "S2": [("top5", {"top": 5}), ("top20", {"top": 20}), ("w3", {"window": 3}), ("w10", {"window": 10})],
    "S3": [("vol2.5", {"vol_mult": 2.5}), ("vol4", {"vol_mult": 4.0}), ("atr1.25", {"atr_mult": 1.25}),
           ("atr2", {"atr_mult": 2.0})],
    "S4": [("rsi5", {"rsi_max": 5.0}), ("rsi15", {"rsi_max": 15.0}), ("hold5", {"max_hold": 5}),
           ("hold15", {"max_hold": 15})],
}  # fmt: skip
LABELS = {"S1": "S1 momentum 12−1", "S2": "S2 reversión semanal", "S3": "S3 deriva tras shock de volumen",
          "S4": "S4 RSI(2) en tendencia"}  # fmt: skip


# ------------------------------------------------------------------ datos
def universe(hist: Store, n: int = UNIVERSE_N) -> pl.DataFrame:
    """Top `n` acciones comunes por $ volumen medio del año Y−1 (≥ 200 sesiones, último cierre ≥ $5)."""
    from daytrader.scanner.universe import VALID_SYMBOL

    parts = []
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        q = hist.query(
            "SELECT b.symbol, avg(b.close * b.volume) AS adv_usd, arg_max(b.close, b.session_date) AS last_close, "
            "count(*) AS n FROM bars_1d b JOIN assets a ON a.symbol = b.symbol AND a.is_common "
            "WHERE b.session_date BETWEEN ? AND ? GROUP BY b.symbol "
            "HAVING count(*) >= 200 AND arg_max(b.close, b.session_date) >= 5 ORDER BY adv_usd DESC LIMIT ?",
            [date(y - 1, 1, 1), date(y - 1, 12, 31), n + 300],
        )
        q = q.filter(pl.col("symbol").map_elements(lambda s: bool(VALID_SYMBOL.match(s)), return_dtype=pl.Boolean))
        parts.append(q.head(n).select(pl.lit(y).alias("year"), "symbol", "adv_usd"))
    return pl.concat(parts)


def load_bars(hist: Store, symbols: list[str]) -> pl.DataFrame:
    bars = hist.query(
        "SELECT symbol, session_date, open, high, low, close, volume FROM bars_1d "
        "WHERE session_date BETWEEN ? AND ? AND symbol IN (SELECT unnest(?))",
        [LOAD_FROM, DATA_END, symbols],
    ).with_columns(pl.col("close").alias("close_raw"))
    splits = hist.query("SELECT symbol, ex_date, old_rate, new_rate FROM splits WHERE ex_date <= ?", [DATA_END])
    # Base común por símbolo (todos los splits hasta DATA_END): retornos/ATR %/medias/RSI no cambian con la escala.
    return adjust_for_splits(bars, splits, as_of=DATA_END, price_cols=("open", "high", "low", "close"))


# ------------------------------------------------------------------ simulación
def run_config(name: str, kind: str, p: dict, ind: pl.DataFrame, uni: pl.DataFrame, spy: pl.DataFrame,
               panel: Panel, all_sessions: list, sim_sessions: list, costs=BASE) -> dict:  # fmt: skip
    if kind == "rotation":
        if name == "S1":
            tg = swing.s1_momentum(ind, uni, spy, all_sessions, p)
        else:
            tg = swing.s2_reversal(ind, uni, all_sessions, p)
        per, eq = simulate_rotation(tg, panel, sim_sessions, costs)
        return {"kind": kind, "eq": eq, "trades": per, "decisions": sorted(tg)}
    sig = swing.s3_volume_shock(ind, uni, p) if name == "S3" else swing.s4_rsi2(ind, uni, p)
    tr, eq = simulate_events(sig, panel, sim_sessions, costs)
    return {"kind": kind, "eq": eq, "trades": tr, "signals": sig.height}


def _slice(df: pl.DataFrame, col: str, a: date, b: date) -> pl.DataFrame:
    return df.filter(pl.col(col).is_between(a, b)) if not df.is_empty() else df


def evaluate(res: dict, spy_ret: pl.DataFrame, a: date, b: date) -> dict:
    eq = _slice(res["eq"], "session_date", a, b)
    j = (
        eq.join(spy_ret, on="session_date", how="inner")
        .with_columns((pl.col("ret") - pl.col("spy_ret")).alias("excess"))
        .drop_nulls("excess")
    )
    ex = j["excess"].to_numpy()
    st = equity_stats(eq)
    out = {
        "days": eq.height, "ann_ret": float(eq["ret"].mean() * 252), "sharpe": st.get("sharpe", float("nan")),
        "max_dd": st.get("max_drawdown", float("nan")), "total": st.get("total_return", float("nan")),
        "excess_ann": float(ex.mean() * 252) if len(ex) else float("nan"),
        "excess_sharpe_d": float(ex.mean() / ex.std(ddof=1)) if len(ex) > 2 and ex.std(ddof=1) > 0 else 0.0,
        "_excess": ex,
    }  # fmt: skip
    out["excess_sharpe"] = out["excess_sharpe_d"] * math.sqrt(252)
    t = _slice(res["trades"], "entry_date", a, b)
    if res["kind"] == "events":
        out.update({f"t_{k}": v for k, v in trade_stats(t).items()})
        out["r_gross"] = float(t["r_gross"].mean()) if t.height else float("nan")
        out["n"] = t.height
    else:
        out["n"] = len([d for d in res["decisions"] if a <= d <= b])
        out["holdings"] = t.height
        out["hold_win"] = float((t["ret"] > 0).mean()) if t.height else float("nan")
    return out


def promotion(name: str, v: dict, vp: dict, dev: dict, years: list[float], neigh: list[float], dsr: float) -> list:
    why = []
    events = MAIN[name][0] == "events"
    if events and v["n"] < 100:
        why.append("menos de 100 trades")
    if not events and v["n"] < 30:
        why.append("menos de 30 rebalanceos")
    if not v["excess_sharpe"] > 0:
        why.append("no le gana a SPY (exceso ≤ 0)")
    if not dsr >= 0.95:
        why.append("DSR < 0,95")
    if events:
        if not (v.get("t_avg_r", -1) > 0 and v.get("t_t_stat", 0) >= 2):
            why.append("R neto no es > 0 con t ≥ 2")
        if not v.get("t_profit_factor", 0) >= 1.3:
            why.append("PF < 1,3")
    if not vp["excess_ann"] > 0:
        why.append("exceso ≤ 0 con costos pesimistas")
    if not v["max_dd"] >= -0.25:
        why.append("drawdown peor que −25 %")
    if not dev["excess_ann"] > 0:
        why.append("exceso ≤ 0 en desarrollo")
    if sum(x > 0 for x in years) < 2:
        why.append("exceso > 0 en menos de 2 de 3 años")
    if sum(x > 0 for x in neigh) < 3:
        why.append("menos de 3 de 4 vecinos con exceso > 0")
    return why


def run_fase8(hist: Store, prior: list[float], on_step=None) -> dict:
    say = on_step or (lambda m: None)
    uni = universe(hist)
    say(f"universo: {uni.height:,} símbolo-años, {uni['symbol'].n_unique():,} símbolos distintos")
    syms = sorted(set(uni["symbol"].to_list()) | {"SPY"})
    bars = load_bars(hist, syms)
    if bars["session_date"].max() > DATA_END:
        raise RuntimeError("Datos ≥ 2026 cargados: el OOS debe seguir sellado.")
    say(f"barras diarias: {bars.height:,}")
    ind = swing.indicators(bars)
    del bars
    spy = ind.filter(pl.col("symbol") == "SPY")
    all_sessions = spy["session_date"].to_list()
    sim_sessions = [d for d in all_sessions if d >= SIM_FROM]
    spy_ret = spy.select("session_date", pl.col("ret1").alias("spy_ret"))
    panel = Panel(ind.select("symbol", "session_date", "open", "high", "low", "close", "sma5"))
    ew = (
        ind.with_columns(pl.col("session_date").dt.year().alias("year"))
        .join(uni.select("year", "symbol"), on=["year", "symbol"], how="semi")
        .group_by("session_date").agg(pl.col("ret1").mean().alias("ret"))
        .filter(pl.col("session_date") >= SIM_FROM).sort("session_date")
        .with_columns((100_000 * (1 + pl.col("ret").fill_null(0)).cum_prod()).alias("equity"))
    )  # fmt: skip
    spy_eq = spy_ret.filter(pl.col("session_date") >= SIM_FROM).with_columns(
        pl.col("spy_ret").alias("ret"), (100_000 * (1 + pl.col("spy_ret").fill_null(0)).cum_prod()).alias("equity")
    )
    bench = {}
    for bname, beq in (("SPY", spy_eq), ("Universo igual-ponderado", ew)):
        bench[bname] = {pn: evaluate({"eq": beq, "trades": pl.DataFrame(), "kind": "rotation", "decisions": []},
                                     spy_ret, a, b) for pn, (a, b) in PERIODS.items()}  # fmt: skip

    runs = {}
    for name, (kind, p) in MAIN.items():
        runs[name] = run_config(name, kind, p, ind, uni, spy, panel, all_sessions, sim_sessions)
        runs[name + "|pes"] = run_config(name, kind, p, ind, uni, spy, panel, all_sessions, sim_sessions,
                                         PESSIMISTIC)  # fmt: skip
        say(f"{name}: simulado (base y pesimista)")
        for lab, delta in NEIGHBORS[name]:
            runs[f"{name}|{lab}"] = run_config(name, kind, {**p, **delta}, ind, uni, spy, panel, all_sessions,
                                               sim_sessions)  # fmt: skip
        say(f"{name}: vecinos simulados")

    rows = {}
    for name in MAIN:
        rows[name] = {pn: evaluate(runs[name], spy_ret, a, b) for pn, (a, b) in PERIODS.items()}
        rows[name]["pesimista"] = evaluate(runs[name + "|pes"], spy_ret, *PERIODS["validacion"])
        rows[name]["years"] = [evaluate(runs[name], spy_ret, a, b)["excess_ann"] for a, b in VAL_YEARS]
        rows[name]["neighbors"] = {lab: evaluate(runs[f"{name}|{lab}"], spy_ret, *PERIODS["validacion"])["excess_ann"]
                                   for lab, _ in NEIGHBORS[name]}  # fmt: skip
        rows[name]["by_year"] = {
            y: evaluate(runs[name], spy_ret, date(y, 1, 1), date(y, 12, 31)) for y in range(FIRST_YEAR, LAST_YEAR + 1)
        }
    trial = list(prior) + [rows[n]["validacion"]["excess_sharpe_d"] for n in MAIN]
    for name in MAIN:
        v = rows[name]["validacion"]
        dsr = deflated_sharpe(v["_excess"], trial, n_trials=N_TRIALS)
        rows[name]["dsr"] = dsr
        rows[name]["why"] = promotion(name, v, rows[name]["pesimista"], rows[name]["desarrollo"],
                                      rows[name]["years"], list(rows[name]["neighbors"].values()), dsr)  # fmt: skip
    return {"rows": rows, "bench": bench, "universe": uni, "runs": runs, "n_prior": len(prior)}


# ------------------------------------------------------------------ reporte
def _f(x, fmt="{:+.1%}"):
    return "—" if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else fmt.format(x)


def render(res: dict) -> str:
    rows, bench = res["rows"], res["bench"]
    u = res["universe"]
    L = ["# Fase 8 — swing trading (2 a 20 días) con barras diarias", "",
         "Pre-registro: `docs/preregistro_fase8_swing.md`. Universo point-in-time: top 500 por $ volumen del año "
         f"anterior ({u['symbol'].n_unique():,} símbolos distintos 2017–2025). Ejecución en la apertura siguiente a "
         f"la señal. N = {N_TRIALS} intentos para el DSR. Datos hasta 2025-12-31 (OOS 2026 sellado).", "",
         "## Decisión (validación 2022-01 → 2024-10, costos base)", "",
         "| Hipótesis | trades / rebal. | retorno anual | Sharpe | exceso anual vs SPY | Sharpe exceso | DSR | "
         "R neto (t, PF) | exceso pesimista | max DD | exceso desarrollo | ¿Pasa? | motivos |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for n in MAIN:
        r = rows[n]
        v = r["validacion"]
        rt = (f"{v['t_avg_r']:+.3f} (t {v['t_t_stat']:.2f}, PF {v['t_profit_factor']:.2f})"
              if "t_avg_r" in v else "—")  # fmt: skip
        L.append(f"| {LABELS[n]} | {v['n']} | {_f(v['ann_ret'])} | {_f(v['sharpe'], '{:.2f}')} | "
                 f"{_f(v['excess_ann'])} | {_f(v['excess_sharpe'], '{:.2f}')} | {_f(r['dsr'], '{:.2f}')} | {rt} | "
                 f"{_f(r['pesimista']['excess_ann'])} | {_f(v['max_dd'])} | {_f(r['desarrollo']['excess_ann'])} | "
                 f"{'**sí**' if not r['why'] else 'no'} | {'; '.join(r['why']) or '—'} |")  # fmt: skip
    L += ["", "## Referencias (mismo periodo)", "", "| Referencia | periodo | retorno anual | Sharpe | max DD |",
          "|---|---|---|---|---|"]  # fmt: skip
    for bn, per in bench.items():
        for pn, v in per.items():
            L.append(f"| {bn} | {pn} | {_f(v['ann_ret'])} | {_f(v['sharpe'], '{:.2f}')} | {_f(v['max_dd'])} |")
    L += [
        "",
        "## Todos los periodos (exceso anual vs SPY · retorno anual · trades)",
        "",
        "| Hipótesis | desarrollo | validación | ya visto | R bruto val. (S3/S4) |",
        "|---|---|---|---|---|",
    ]
    for n in MAIN:
        r = rows[n]
        cells = [f"{_f(r[p]['excess_ann'])} · {_f(r[p]['ann_ret'])} · {r[p]['n']}"
                 for p in ("desarrollo", "validacion", "ya_visto")]  # fmt: skip
        L.append(f"| {LABELS[n]} | " + " | ".join(cells) + f" | {_f(r['validacion'].get('r_gross'), '{:+.3f}')} |")
    L += [
        "",
        "## Exceso anual vs SPY por año",
        "",
        "| Hipótesis | " + " | ".join(str(y) for y in range(FIRST_YEAR, LAST_YEAR + 1)) + " |",
        "|---|" + "---|" * (LAST_YEAR - FIRST_YEAR + 1),
    ]
    for n in MAIN:
        L.append(f"| {LABELS[n]} | " + " | ".join(_f(rows[n]["by_year"][y]["excess_ann"], "{:+.0%}")
                                                  for y in range(FIRST_YEAR, LAST_YEAR + 1)) + " |")  # fmt: skip
    L += ["", "## Estabilidad (vecinos, exceso anual en validación)", ""]
    for n in MAIN:
        nb = rows[n]["neighbors"]
        pos = sum(x > 0 for x in nb.values())
        L.append(f"- {LABELS[n]}: " + " · ".join(f"{k} {_f(x)}" for k, x in nb.items()) + f" → {pos}/4 positivos")
    passed = [n for n in MAIN if not rows[n]["why"]]
    L += ["", "## Conclusión", ""]
    if passed:
        L.append(f"**Pasan la regla pre-registrada: {', '.join(LABELS[n] for n in passed)}.** Siguiente paso "
                 "(solo con OK del usuario): abrir el OOS 2026 una única vez.")  # fmt: skip
    else:
        L.append("**Ninguna hipótesis pasa la regla pre-registrada.** El OOS 2026 sigue sellado.")
    return "\n".join(L) + "\n"


def summary_lines(res: dict) -> list[str]:
    out = []
    for n in MAIN:
        r = res["rows"][n]
        v = r["validacion"]
        out.append(f"{n}: n={v['n']} exceso={v['excess_ann']:+.1%} Sharpe={v['sharpe']:.2f} DSR={r['dsr']:.2f} "
                   f"{'PASA' if not r['why'] else 'no pasa'}")  # fmt: skip
    return out
