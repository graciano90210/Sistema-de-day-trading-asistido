"""Reporte Markdown de la ronda 2."""

from __future__ import annotations

import polars as pl

from daytrader.backtest.metrics import breakdown
from daytrader.backtest.report import _f, _table, add_dims

DESC = {
    "H1": "ORB 5 min en Stocks in Play (top 20 RVOL), stop 10% ATR, salida al cierre",
    "H2": "Mecánica de H1 sobre la watchlist de gappers",
    "H3_gappers": "VWAP con stops amplios — gappers",
    "H3_control": "VWAP con stops amplios — control (50 líquidos)",
    "H4": "Meta-labeling LightGBM sobre H1 ∪ H2 (walk-forward; tras 4 meses de entrenamiento)",
    "H5a": "H1 solo en días de régimen volátil (HMM)",
    "H5b": "H3 gappers solo en días de régimen tranquilo (HMM)",
}


def render(result: dict, rows: list[dict], d0, d1, round1_sharpes: list[float]) -> str:
    c = result["calib"]
    tab = pl.DataFrame([
        {"config": r["config"], "descripción": DESC[r["config"]], "trades": r["trades"], "win_rate": r["win_rate"],
         "R_neto (cal)": r["R_neto"], "R cons": r["R_cons"], "R opt": r["R_opt"], "R pesimista": r["R_pesimista"],
         "t": r["t_stat"], "PF": r["profit_factor"], "Sharpe": r["sharpe"], "max_dd": r["max_dd"], "DSR": r["dsr"],
         "PASA": "SÍ" if r["pasa"] else "no"}
        for r in rows
    ])  # fmt: skip
    pv = result["pvol"]
    lines = [
        "# Ronda 2 — resultados in-sample (pre-registrados)\n",
        f"Periodo {d0} → {d1}. Pre-registro: `docs/preregistro_ronda2.md` (commit 71bff15, anterior a estos "
        "resultados). OOS 2026 sigue **sellado**.\n",
        "## Calibración de la barra de entrada (trades tick SIP)\n",
        f"Barras de entrada ambiguas (tocan nivel y stop en el mismo minuto): {c.get('n_ambiguos', '—')}. "
        f"Muestra resuelta con ticks: {c.get('n_resueltos', '—')} de {c.get('n_muestra', '—')}. "
        f'**p = {_f(c["p"], "{:.1%}")}** de los casos fueron "entrada y luego stop". '
        "El resultado calibrado (decisión) pondera las barras ambiguas con p; *cons* = siempre stop, *opt* = nunca.\n",
        "## Resumen y regla de promoción\n",
        "Pasa al OOS solo si: ≥100 trades, R neto > 0 con t ≥ 2, PF ≥ 1,2, DSR ≥ 0,95 (N = 13 intentos) y R > 0 "
        "en el escenario de costos pesimista.\n",
        _table(tab, pct_cols=("win_rate", "max_dd"), digits=2),
        f"Régimen HMM: {pv.filter(pl.col('p_vol') >= 0.5).height} de {pv.height} sesiones clasificadas como "
        "volátiles (probabilidad predicha con información hasta el día anterior).\n",
        "## Variantes informativas de H1 (no deciden)\n",
    ]
    for r in result["extra"].values():
        lines.append(f"- **{r['config']}**: {r['trades']} trades, R neto {_f(r['R_neto'], '{:+.3f}')}, "
                     f"PF {_f(r['profit_factor'])}, retorno {_f(r['retorno'], '{:.1%}')}, max DD {_f(r['max_dd'], '{:.1%}')}")  # fmt: skip
    lines.append("")
    for r in rows:
        t = add_dims(r["_trades"])
        if t.is_empty():
            continue
        lines += [f"\n## {r['config']} — {DESC[r['config']]}\n",
                  "### Por dirección\n", _table(breakdown(t, "direccion")),
                  "### Por motivo de salida\n", _table(breakdown(t, "exit_reason")),
                  "### Por mes\n", _table(breakdown(t, "mes"))]  # fmt: skip
    lines.append(
        f"\n---\nSharpe diarios de los 6 intentos de la ronda 1 usados en el DSR: "
        f"{', '.join(_f(s, '{:.3f}') for s in round1_sharpes)}.\n"
    )
    return "\n".join(lines)
