"""H5 — Régimen de mercado con un HMM gaussiano de 2 estados sobre SPY diario (aprendizaje dinámico).

Point-in-time: para la sesión d se usa la probabilidad PREDICHA del estado volátil con información
hasta d−1 (filtrado en d−1 × matriz de transición). El modelo se reajusta cada mes con datos hasta el
último día del mes anterior. "Volátil" = estado con mayor varianza del log-retorno.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import polars as pl
from hmmlearn.hmm import GaussianHMM

log = logging.getLogger(__name__)


def features(spy: pl.DataFrame) -> pl.DataFrame:
    """spy: session_date, high, low, close (ordenado). Devuelve session_date, r, rng."""
    return (
        spy.sort("session_date")
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1)).log().alias("r"),
            (pl.col("high") / pl.col("low")).log().alias("rng"),
        )
        .drop_nulls(["r", "rng"])
        .select("session_date", "r", "rng")
    )


def _fit(x: np.ndarray, seed: int = 7) -> GaussianHMM:
    m = GaussianHMM(n_components=2, covariance_type="full", n_iter=200, random_state=seed, tol=1e-4)
    m.fit(x)
    return m


def predicted_vol_prob(spy: pl.DataFrame, eval_days: list[date], seed: int = 7) -> pl.DataFrame:
    """P(estado volátil en d | info hasta d−1) para cada d en eval_days."""
    f = features(spy)
    dates = f["session_date"].to_list()
    x = f.select("r", "rng").to_numpy() * np.array([100.0, 100.0])  # escala en %, estabiliza el ajuste
    out = []
    months = sorted({(d.year, d.month) for d in eval_days})
    for y, mth in months:
        first = date(y, mth, 1)
        n_train = sum(1 for d in dates if d < first)
        if n_train < 250:
            continue
        model = _fit(x[:n_train], seed)
        vol_state = int(np.argmax([c[0, 0] for c in model.covars_]))
        for d in [d for d in eval_days if (d.year, d.month) == (y, mth)]:
            k = sum(1 for dd in dates if dd < d)  # observaciones hasta d−1
            post = model.predict_proba(x[:k])[-1]  # en el último punto, suavizado == filtrado
            pred = post @ model.transmat_
            out.append({"session_date": d, "p_vol": float(pred[vol_state])})
    return pl.DataFrame(out, schema={"session_date": pl.Date, "p_vol": pl.Float64})
