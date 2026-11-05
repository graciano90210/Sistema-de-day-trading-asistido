"""H4 — Meta-labeling con LightGBM y validación walk-forward (López de Prado, 2018).

No predice precios: decide si tomar o no una señal ya generada por la regla primaria (H1/H2).
Walk-forward expansivo por mes, primeros `warmup_months` solo entrenan, embargo de 1 día.
Hiperparámetros fijos del pre-registro; sin tuning.
"""

from __future__ import annotations

from datetime import timedelta

import lightgbm as lgb
import numpy as np
import polars as pl

PARAMS = {
    "objective": "binary", "num_leaves": 15, "min_data_in_leaf": 50, "learning_rate": 0.05,
    "feature_fraction": 0.8, "seed": 7, "verbose": -1, "deterministic": True, "force_row_wise": True,
}  # fmt: skip
N_TREES = 200
NUMERIC = ["rvol", "gap", "abs_gap", "side", "or_range_atr", "atr_pct", "price", "log_adv", "min_to_entry",
           "spy_gap", "spy_or_ret", "dow", "p_vol", "is_h1"]  # fmt: skip
CATEGORICAL = ["catalyst"]


def _matrix(df: pl.DataFrame, cats: list[str]) -> tuple[np.ndarray, list[str]]:
    x = df.select(NUMERIC).to_numpy().astype(float)
    cat = df["catalyst"].fill_null("n/d").to_list()
    onehot = np.array([[1.0 if c == k else 0.0 for k in cats] for c in cat]) if cats else np.zeros((len(cat), 0))
    return np.hstack([x, onehot]), NUMERIC + [f"cat_{k}" for k in cats]


def walk_forward(df: pl.DataFrame, label: str = "label", warmup_months: int = 4, embargo_days: int = 1) -> pl.DataFrame:
    """df: una fila por trade con NUMERIC, catalyst, session_date y `label` (0/1). Devuelve df con `p_meta`
    solo para las filas evaluadas fuera de muestra (las del warm-up quedan con null)."""
    df = df.sort("session_date", "entry_ts").with_row_index("_i")
    cats = sorted(set(df["catalyst"].fill_null("n/d").to_list()))
    x_all, _ = _matrix(df, cats)
    y_all = df[label].to_numpy()
    months = sorted({(d.year, d.month) for d in df["session_date"].to_list()})
    p = np.full(df.height, np.nan)
    sd = df["session_date"].to_list()
    for k, (y, m) in enumerate(months):
        if k < warmup_months:
            continue
        first = min(d for d in sd if (d.year, d.month) == (y, m))
        train = np.array([d < first - timedelta(days=embargo_days) for d in sd])
        test = np.array([(d.year, d.month) == (y, m) for d in sd])
        if train.sum() < 200 or len(set(y_all[train])) < 2:
            continue
        booster = lgb.train(PARAMS, lgb.Dataset(x_all[train], y_all[train]), num_boost_round=N_TREES)
        p[test] = booster.predict(x_all[test])
    return df.with_columns(pl.Series("p_meta", p).fill_nan(None)).drop("_i")
