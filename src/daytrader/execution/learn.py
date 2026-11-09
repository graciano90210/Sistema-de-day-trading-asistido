"""Aprender de tus trades: cruza cada trade cerrado con lo que mostraban `mediodia` y `contexto` ANTES de entrar.

Point-in-time: para cada trade se usa la última foto (snapshots) del mismo símbolo y sesión con ts <= entrada.
Todo lo calcula Python (R medio, IC 95 % t-Student, win rate). Con muchos cortes algo parecerá bueno por azar:
un grupo con n < MIN_N es "no concluyente", y cualquier hallazgo debe pre-registrarse antes de cambiar reglas.
"""

from __future__ import annotations

import math

import polars as pl

MIN_N = 30


def trade_features(trades: pl.DataFrame, tickets: pl.DataFrame, snaps: pl.DataFrame) -> pl.DataFrame:
    """trades: tabla `trades` (r_multiple, entry_ts…); tickets: `tickets`; snaps: `snapshots`."""
    if trades.is_empty():
        return trades
    t = trades.filter(pl.col("r_multiple").is_not_null()).join(
        tickets.select("fingerprint", "setup", pl.col("catalyst").alias("ticket_catalyst")), on="fingerprint",
        how="left",
    ).sort("entry_ts")  # fmt: skip
    for src, cols in (("mediodia", ["starred", "score", "rvol", "range_atr", "catalyst", "up", "down", "verdict"]),
                      ("contexto", ["up", "down", "verdict", "patterns"])):  # fmt: skip
        s = (
            snaps.filter(pl.col("source") == src)
            .select("symbol", "session_date", pl.col("ts").alias(f"{src}_ts"), *[pl.col(c).alias(f"{src}_{c}") for c in cols])
            .sort(f"{src}_ts")
        )  # fmt: skip
        t = t.join_asof(s, left_on="entry_ts", right_on=f"{src}_ts", by=["symbol", "session_date"], strategy="backward")
    # lecturas: preferir las de `contexto` (más cercanas a la entrada) y si no, las de `mediodia`
    up = pl.coalesce("contexto_up", "mediodia_up")
    dn = pl.coalesce("contexto_down", "mediodia_down")
    verdict = pl.coalesce("contexto_verdict", "mediodia_verdict")
    side_word = pl.when(pl.col("side") == "long").then(pl.lit("largo")).otherwise(pl.lit("corto"))
    return t.with_columns(
        pl.when(pl.col("mediodia_starred").is_null()).then(pl.lit("sin foto de mediodía"))
        .when(pl.col("mediodia_starred")).then(pl.lit("★ top 3")).otherwise(pl.lit("fuera del top 3"))
        .alias("seleccion"),
        pl.coalesce("ticket_catalyst", "mediodia_catalyst").fill_null("sin dato").alias("catalizador"),
        pl.when(verdict.is_null()).then(pl.lit("sin lecturas"))
        .when(verdict == "mixto").then(pl.lit("lecturas mixtas"))
        .when(verdict == side_word).then(pl.lit("a favor de las lecturas"))
        .otherwise(pl.lit("contra las lecturas")).alias("vs_lecturas"),
        pl.when(up.is_null()).then(pl.lit("sin lecturas"))
        .when((up - dn).abs() >= 4).then(pl.lit("acuerdo fuerte (|▲−▼| ≥ 4)"))
        .otherwise(pl.lit("acuerdo débil (|▲−▼| < 4)")).alias("acuerdo"),
        pl.when(pl.col("contexto_patterns").is_null()).then(pl.lit("sin patrón")).otherwise(pl.lit("con patrón"))
        .alias("patron"),
        pl.col("setup").fill_null("sin setup"),
        pl.col("side").replace({"long": "largo", "short": "corto"}).alias("lado"),
    )  # fmt: skip


def group_stats(df: pl.DataFrame, by: str) -> pl.DataFrame:
    """n, R medio, IC 95 %, win rate y R total por grupo."""
    from scipy.stats import t as student

    rows = []
    for (key,), g in df.group_by(by, maintain_order=True):
        r = g["r_multiple"].to_numpy()
        n = len(r)
        mean = float(r.mean())
        if n > 1 and r.std(ddof=1) > 0:
            h = float(student.ppf(0.975, n - 1) * r.std(ddof=1) / math.sqrt(n))
            lo, hi = mean - h, mean + h
        else:
            lo = hi = float("nan")
        rows.append({"grupo": key, "n": n, "r_medio": mean, "ic_bajo": lo, "ic_alto": hi,
                     "win_rate": float((r > 0).mean()), "r_total": float(r.sum()),
                     "concluyente": n >= MIN_N and not (lo <= 0 <= hi)})  # fmt: skip
    return pl.DataFrame(rows).sort("n", descending=True) if rows else pl.DataFrame()
