"""Reporte Markdown de la ronda 3."""

from __future__ import annotations

import polars as pl

from daytrader.backtest.metrics import breakdown
from daytrader.backtest.report import _f, _table, add_dims


def render(res: dict, d0, d1) -> str:
    wf, c = res["wf"], res["calib"]
    grid = pl.DataFrame([
        {"config": g["config"], "trades": g["trades"], "tasa_ejecución": g["fill_rate"], "win_rate": g["win_rate"],
         "R_neto": g["R_neto"], "t": g["t_stat"], "PF": g["profit_factor"], "Sharpe": g["sharpe"], "max_dd": g["max_dd"]}
        for g in res["grid"]
    ]).sort("R_neto", descending=True)  # fmt: skip
    m = res["market_ref"]
    lines = [
        "# Ronda 3 — VWAP con órdenes límite (pre-registrada)\n",
        f"Periodo {d0} → {d1}. Pre-registro `docs/preregistro_ronda3.md` (commit 80b1ec2). OOS 2026 **sellado**.\n",
        "## Resultado que decide: ajuste walk-forward\n",
        "Cada mes se opera con la configuración que mejor funcionó en los meses ANTERIORES (los 3 primeros solo "
        "historia). Este es el único resultado que cuenta para la regla de promoción.\n",
        f"- Trades: **{wf['trades']}** · win rate {_f(wf['win_rate'], '{:.1%}')} · R neto **{_f(wf['R_neto'], '{:+.3f}')}** "
        f"(t = {_f(wf['t_stat'])}) · PF **{_f(wf['profit_factor'])}** · Sharpe {_f(wf['sharpe'])} · max DD {_f(wf['max_dd'], '{:.1%}')}",
        f"- R con costos pesimistas: {_f(wf['R_pesimista'], '{:+.3f}')} · R con supuesto conservador: {_f(wf['R_cons'], '{:+.3f}')}",
        f"- DSR (N = 25 intentos): **{_f(wf['dsr'], '{:.2f}')}** · **¿Pasa la regla?: {'SÍ' if wf['pasa'] else 'NO'}**\n",
        "### Configuración elegida cada mes\n",
        _table(pl.DataFrame(res["chosen"]), digits=3),
        "## Referencia: misma señal con entrada a mercado\n",
        f"{m['trades']} trades · R neto {_f(m['R_neto'], '{:+.3f}')} · PF {_f(m['profit_factor'])}.\n",
        "## Ejecución en la barra de entrada\n",
        f"Trades con barra de entrada ambigua: {_f(c.get('tasa_ambiguas'), '{:.1%}')}. "
        + (f"Calibrado con ticks: p = {_f(c['p'], '{:.1%}')} ({c.get('n_resueltos')} resueltos)."
           if c.get("n_resueltos") else c.get("nota", "")) + "\n",
        "## Rejilla completa (informativa: in-sample, optimista por selección)\n",
        _table(grid, pct_cols=("tasa_ejecución", "win_rate", "max_dd")),
    ]  # fmt: skip
    t = add_dims(wf["_trades"])
    if not t.is_empty():
        lines += ["## Walk-forward por dirección\n", _table(breakdown(t, "direccion")),
                  "## Walk-forward por motivo de salida\n", _table(breakdown(t, "exit_reason")),
                  "## Walk-forward por mes\n", _table(breakdown(t, "mes"))]  # fmt: skip
    return "\n".join(lines)
