"""Reporte Markdown del backtest."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import polars as pl

from daytrader.backtest.metrics import breakdown, equity_stats, trade_stats

ET = ZoneInfo("America/New_York")


def _f(x, fmt="{:.2f}"):
    if x is None or (isinstance(x, float) and x != x):
        return "—"
    return fmt.format(x)


def _table(df: pl.DataFrame, pct_cols=("win_rate",), digits=2) -> str:
    if df.is_empty():
        return "_(sin datos)_\n"
    cols = df.columns
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.iter_rows(named=True):
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float):
                cells.append(_f(v, "{:.1%}") if c in pct_cols else _f(v, f"{{:.{digits}f}}"))
            else:
                cells.append("—" if v is None else str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def summary_row(name: str, universe: str, t: pl.DataFrame, eq: pl.DataFrame) -> dict:
    taken = t.filter(pl.col("taken")) if "taken" in t.columns else t
    ts, es = trade_stats(taken), equity_stats(eq)
    gross = trade_stats(taken, "r_gross") if not taken.is_empty() else {}
    exp_usd = float(taken["pnl_usd"].mean()) if "pnl_usd" in taken.columns and taken.height else float("nan")
    return {
        "estrategia": name, "universo": universe, "trades": ts.get("trades", 0),
        "win_rate": ts.get("win_rate"), "R_medio_bruto": gross.get("avg_r"), "R_medio_neto": ts.get("avg_r"),
        "profit_factor": ts.get("profit_factor"), "expectancy_usd": exp_usd, "t_stat": ts.get("t_stat"),
        "retorno": es.get("total_return"), "sharpe": es.get("sharpe"), "max_dd": es.get("max_drawdown"),
    }  # fmt: skip


def add_dims(t: pl.DataFrame) -> pl.DataFrame:
    """Columnas para desgloses: dirección, hora de entrada ET, mes."""
    if t.is_empty():
        return t
    hours = [x.replace(tzinfo=ZoneInfo("UTC")).astimezone(ET).strftime("%H:00") for x in t["entry_ts"].to_list()]
    return t.with_columns(
        pl.when(pl.col("side") == 1).then(pl.lit("largo")).otherwise(pl.lit("corto")).alias("direccion"),
        pl.Series("hora_entrada_et", hours),
        pl.col("session_date").dt.strftime("%Y-%m").alias("mes"),
        pl.when(pl.col("gap").is_null()).then(pl.lit("n/d"))
        .when(pl.col("gap").abs() < 0.05).then(pl.lit("3-5%"))
        .when(pl.col("gap").abs() < 0.10).then(pl.lit("5-10%"))
        .otherwise(pl.lit(">10%")).alias("gap_abs"),
    )  # fmt: skip


def render(
    title: str, period: tuple[date, date], holdout: date, cfg_text: str, rows: list[dict],
    runs: dict[str, tuple[pl.DataFrame, pl.DataFrame]], spy: pl.DataFrame, sens: list[dict] | None = None,
) -> str:  # fmt: skip
    spy_s = equity_stats(spy)
    lines = [
        f"# {title}\n",
        f"Periodo **{period[0]} → {period[1]}** (in-sample). Muestra OOS **sellada desde {holdout}**: no evaluada.\n",
        "R = PnL por acción / riesgo planificado (entrada de referencia − stop). *Bruto* = antes de slippage y "
        "tasas; *neto* = después. Cartera: 1% de riesgo por trade sobre el capital vigente, límites de posiciones, "
        "trades/día, kill switch −3% y poder de compra 4×.\n",
        "## Resumen\n",
        _table(pl.DataFrame(rows), pct_cols=("win_rate", "retorno", "max_dd")),
        f"**SPY buy & hold** en el mismo periodo: retorno {_f(spy_s.get('total_return'), '{:.1%}')}, "
        f"Sharpe {_f(spy_s.get('sharpe'))}, max DD {_f(spy_s.get('max_drawdown'), '{:.1%}')}.\n",
        "Criterio de éxito (se juzga en OOS, fase 4): ≥100 trades, profit factor > 1.3, drawdown aceptable, "
        "estabilidad ante cambios de parámetros.\n",
    ]
    if sens:
        s = (
            pl.DataFrame(sens)
            .select("estrategia", "universo", "escenario", "trades", "R_medio_neto", "profit_factor", "retorno")
            .sort("estrategia", "universo", "escenario")
        )
        lines += [
            "## Sensibilidad a costos\n",
            "Mismas señales; cambia solo el modelo de costos (optimista: k=0.05; base: k=0.10 calibrado con NBBO; "
            "pesimista: k=0.20, impacto ×2 y $0.005/acción de comisión).\n",
            _table(s, pct_cols=("retorno",)),
        ]
    for key, (t, eq) in runs.items():
        taken = add_dims(t.filter(pl.col("taken")) if "taken" in t.columns else t)
        if taken.is_empty():
            continue
        es = equity_stats(eq)
        lines += [
            f"\n## {key}\n",
            f"Cartera: retorno {_f(es.get('total_return'), '{:.1%}')} · CAGR {_f(es.get('cagr'), '{:.1%}')} · "
            f"Sharpe {_f(es.get('sharpe'))} · Sortino {_f(es.get('sortino'))} · max DD {_f(es.get('max_drawdown'), '{:.1%}')} "
            f"({es.get('max_dd_sessions')} sesiones). Trades descartados por la cartera: "
            f"{t.filter(~pl.col('taken')).height if 'taken' in t.columns else 0}.\n",
            f"Costos medios: slippage {_f(taken['slippage_ps'].mean(), '${:.3f}')}/acción · "
            f"R bruto→neto {_f(taken['r_gross'].mean(), '{:+.3f}')} → {_f(taken['r_net'].mean(), '{:+.3f}')}.\n",
            "### Por dirección\n",
            _table(breakdown(taken, "direccion")),
            "### Por motivo de salida\n",
            _table(breakdown(taken, "exit_reason")),
            "### Por hora de entrada (ET)\n",
            _table(breakdown(taken, "hora_entrada_et")),
            "### Por |gap|\n",
            _table(breakdown(taken, "gap_abs")),
        ]
        if taken["catalyst"].drop_nulls().len():
            lines += ["### Por catalizador\n", _table(breakdown(taken, "catalyst", min_trades=5))]
        lines += ["### Por mes\n", _table(breakdown(taken, "mes"))]
    lines.append(f"\n---\nConfiguración usada:\n\n```yaml\n{cfg_text}\n```\n")
    return "\n".join(lines)
