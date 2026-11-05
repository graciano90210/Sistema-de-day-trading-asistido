"""Reporte de la ronda 4 → reports/ronda4.md (todos los números salen de round4.run_round4)."""

from __future__ import annotations

from daytrader.research.round4 import N_TRIALS, PERIODS

NAMES = {"P1": "P1 bandera", "P2": "P2 doble suelo/techo", "H3": "H3' VWAP amplio", "H5b": "H5b' VWAP + HMM tranquilo",
         "H4": "H4' meta-labeling LightGBM"}  # fmt: skip


def _f(v, fmt="{:+.3f}"):
    return "—" if v is None or v != v else fmt.format(v)


def render(res: dict) -> str:
    rows, trials = res["rows"], res["trials"]
    out = ["# Ronda 4 (fase 7) — patrones de gráfico y re-evaluación con 10 años", "",
           "Pre-registro: `docs/preregistro_ronda4.md`. Costos base del backtester; cartera $100.000, 1 % por trade.",
           f"Universo point-in-time: {res['n_ctx']:,} símbolo-días. N = {N_TRIALS} intentos para el DSR.", ""]  # fmt: skip
    out += ["## Decisión (periodo de validación 2022-01 → 2024-10)", "",
            "| Hipótesis | trades | R neto | t | PF | DSR | R pesimista | max DD | R desarrollo | ¿Pasa? | motivos |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for n in trials:
        v = rows[n]["validacion"]
        out.append(f"| {NAMES[n]} | {v['trades']} | {_f(v['R_neto'])} | {_f(v['t_stat'], '{:.2f}')} | "
                   f"{_f(v['profit_factor'], '{:.2f}')} | {_f(v.get('dsr'), '{:.2f}')} | {_f(v.get('R_pesimista'))} | "
                   f"{_f(v['max_dd'], '{:.1%}')} | {_f(v.get('R_desarrollo'))} | {'**SÍ**' if v['pasa'] else 'no'} | "
                   f"{'; '.join(v['motivos'])} |")  # fmt: skip
    out += [
        "",
        "## Todos los periodos (R neto por trade · trades)",
        "",
        "| Hipótesis | " + " | ".join(PERIODS) + " | R bruto (sin costos) val. |",
        "|---|---|---|---|---|",
    ]
    for n in trials:
        cells = [f"{_f(rows[n][p]['R_neto'])} · {rows[n][p]['trades']}" for p in PERIODS]
        out.append(f"| {NAMES[n]} | " + " | ".join(cells) + f" | {_f(res['gross'][n]['validacion'])} |")
    out += ["", "## R neto por año", "", "| Hipótesis | " + " | ".join(str(y) for y in range(2016, 2026)) + " |",
            "|---|" + "---|" * 10]  # fmt: skip
    for n in trials:
        ya = {}
        for p in PERIODS:
            ya.update(rows[n][p]["R_por_anio"])
        out.append(f"| {NAMES[n]} | " + " | ".join(_f(ya.get(y), "{:+.2f}") for y in range(2016, 2026)) + " |")
    out += ["", "## Estabilidad (vecinos, validación)", ""]
    for n in ("P1", "P2"):
        v = rows[n]["validacion"]
        out.append(f"- {NAMES[n]}: " + " · ".join(f"{k.split('_', 1)[1]} {_f(x)}" for k, x in v["vecinos"].items())
                   + f" → {v['vecinos_pos']}/4 positivos")  # fmt: skip
    passed = [n for n in trials if rows[n]["validacion"]["pasa"]]
    out += ["", "## Conclusión", ""]
    if passed:
        out.append(f"Pasan la regla: {', '.join(NAMES[n] for n in passed)}. Siguiente paso (con OK del usuario): "
                   "prueba única en el OOS sellado 2026.")  # fmt: skip
    else:
        out.append("**Ninguna hipótesis pasa la regla pre-registrada.** El OOS 2026 sigue sellado.")
    return "\n".join(out) + "\n"
