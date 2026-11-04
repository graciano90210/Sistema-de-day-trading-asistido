"""Validaciones de calidad de datos y reporte en Markdown. Todo calculado en SQL/polars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from daytrader.data.store import Store
from daytrader.market_calendar import sessions

LOW_COVERAGE = 0.90


@dataclass
class QualityReport:
    overview: pl.DataFrame
    integrity: pl.DataFrame  # check, table, violations
    coverage_by_symbol: pl.DataFrame
    worst_days: pl.DataFrame
    daily_vs_minute: pl.DataFrame
    splits: pl.DataFrame

    @property
    def integrity_ok(self) -> bool:
        return int(self.integrity["violations"].sum()) == 0


def _integrity(store: Store, now: datetime) -> pl.DataFrame:
    checks = {
        "ohlc_inconsistente": "low > high OR low > least(open, close) OR high < greatest(open, close)",
        "precio_no_positivo": "least(open, high, low, close) <= 0",
        "volumen_negativo": "volume < 0",
        "timestamp_futuro": "ts_utc > ?",
        "available_at_no_posterior": "available_at <= ts_utc",
        "nulos_ohlc": "open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL",
    }
    rows = []
    for table in ("bars_1m", "bars_1d"):
        for name, cond in checks.items():
            params = [now] if "?" in cond else []
            n = store.con.execute(f"SELECT count(*) FROM {table} WHERE {cond}", params).fetchall()[0][0]
            rows.append({"check": name, "table": table, "violations": n})
        dup = store.con.execute(
            f"SELECT count(*) FROM (SELECT symbol, ts_utc FROM {table} GROUP BY 1, 2 HAVING count(*) > 1)"
        ).fetchall()[0][0]
        rows.append({"check": "duplicados", "table": table, "violations": dup})
    closed = store.con.execute("SELECT count(*) FROM bars_1m WHERE session = 'closed'").fetchall()[0][0]
    rows.append({"check": "barras_fuera_de_sesion (info)", "table": "bars_1m", "violations": 0, "info": closed})
    return pl.DataFrame(rows, schema_overrides={"info": pl.Int64})


def build_report(store: Store, now: datetime | None = None) -> QualityReport:
    now = now or datetime.now(UTC).replace(tzinfo=None)

    overview = store.query(
        """
        SELECT 'bars_1m' AS tabla, count(*) AS filas, count(DISTINCT symbol) AS simbolos,
               min(session_date) AS desde, max(session_date) AS hasta FROM bars_1m
        UNION ALL
        SELECT 'bars_1d', count(*), count(DISTINCT symbol), min(session_date), max(session_date) FROM bars_1d
        """
    )

    rng = store.con.execute("SELECT min(session_date), max(session_date) FROM bars_1m").fetchall()[0]
    if rng[0] is None:
        empty = pl.DataFrame()
        return QualityReport(overview, _integrity(store, now), empty, empty, empty, store.query("SELECT * FROM splits"))

    store.con.register("sess", sessions(rng[0], rng[1]).select("session_date", "rth_minutes", "early_close"))
    # Rejilla símbolo × sesión (desde la primera barra de cada símbolo) con conteo de barras RTH.
    per_day = store.query(
        """
        WITH first_seen AS (SELECT symbol, min(session_date) AS d0 FROM bars_1m GROUP BY 1),
        grid AS (
            SELECT f.symbol, s.session_date, s.rth_minutes, s.early_close
            FROM first_seen f JOIN sess s ON s.session_date >= f.d0
        ),
        counts AS (
            SELECT symbol, session_date,
                   count(*) FILTER (WHERE session = 'rth') AS rth_bars,
                   count(*) FILTER (WHERE session = 'pre') AS pre_bars,
                   count(*) FILTER (WHERE session = 'post') AS post_bars,
                   sum(volume) FILTER (WHERE session = 'rth') AS rth_volume,
                   sum(volume) AS all_volume
            FROM bars_1m GROUP BY 1, 2
        )
        SELECT g.*, coalesce(c.rth_bars, 0) AS rth_bars, coalesce(c.pre_bars, 0) AS pre_bars,
               coalesce(c.post_bars, 0) AS post_bars, c.rth_volume, c.all_volume,
               coalesce(c.rth_bars, 0) / g.rth_minutes AS coverage
        FROM grid g LEFT JOIN counts c USING (symbol, session_date)
        """
    )
    store.con.unregister("sess")

    coverage_by_symbol = (
        per_day.group_by("symbol")
        .agg(
            pl.len().alias("sesiones"),
            (pl.col("rth_bars") == 0).sum().alias("sesiones_sin_datos"),
            pl.col("coverage").median().round(4).alias("cobertura_mediana"),
            pl.col("coverage").quantile(0.05).round(4).alias("cobertura_p05"),
            (pl.col("coverage") < LOW_COVERAGE).sum().alias(f"dias_cobertura_<{int(LOW_COVERAGE * 100)}%"),
            pl.col("pre_bars").median().alias("barras_pre_mediana"),
        )
        .sort("cobertura_mediana")
    )
    worst_days = (
        per_day.sort("coverage")
        .head(20)
        .select("symbol", "session_date", "early_close", "rth_minutes", "rth_bars", "coverage")
    )

    daily_vs_minute = store.query(
        """
        WITH m AS (
            SELECT symbol, session_date,
                   sum(volume) FILTER (WHERE session = 'rth') AS rth_vol, sum(volume) AS all_vol
            FROM bars_1m GROUP BY 1, 2
        )
        SELECT d.symbol,
               median(d.volume / nullif(m.rth_vol, 0)) AS ratio_diario_vs_rth,
               median(d.volume / nullif(m.all_vol, 0)) AS ratio_diario_vs_total
        FROM bars_1d d JOIN m USING (symbol, session_date)
        GROUP BY 1 ORDER BY 1
        """
    )
    return QualityReport(
        overview=overview,
        integrity=_integrity(store, now),
        coverage_by_symbol=coverage_by_symbol,
        worst_days=worst_days,
        daily_vs_minute=daily_vs_minute,
        splits=store.query("SELECT * FROM splits ORDER BY ex_date"),
    )


def _md_table(df: pl.DataFrame) -> str:
    if df.is_empty():
        return "_(vacío)_\n"
    cols = df.columns
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.iter_rows():
        lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(lines) + "\n"


def render_markdown(r: QualityReport, generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(UTC).replace(tzinfo=None)
    parts = [
        "# Reporte de calidad de datos\n",
        f"Generado: {generated_at:%Y-%m-%d %H:%M} UTC. Feed SIP, precios raw.\n",
        "## Resumen\n",
        _md_table(r.overview),
        f"## Integridad — {'OK' if r.integrity_ok else 'HAY VIOLACIONES'}\n",
        _md_table(r.integrity),
        "## Cobertura RTH por símbolo\n",
        "Cobertura = barras de 1 min en horario regular / minutos de la sesión. "
        "Un minuto sin operaciones no genera barra, así que < 100% no es necesariamente un error.\n\n",
        _md_table(r.coverage_by_symbol),
        "## 20 peores días (cobertura)\n",
        _md_table(r.worst_days),
        "## Volumen diario vs. suma de barras de 1 min (mediana)\n",
        "Ratio ≈ 1 en `vs_rth` indica que la barra diaria cubre solo horario regular; ≈ 1 en `vs_total`, que incluye extended hours.\n\n",
        _md_table(r.daily_vs_minute),
        "## Splits en el periodo\n",
        _md_table(r.splits),
    ]
    return "\n".join(parts)
