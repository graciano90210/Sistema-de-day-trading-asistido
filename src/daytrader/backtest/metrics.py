"""Métricas de trades (en R) y de cartera (equity diaria). Todo calculado aquí, nunca a ojo."""

from __future__ import annotations

import math

import numpy as np
import polars as pl

TRADING_DAYS = 252


def trade_stats(t: pl.DataFrame, r: str = "r_net") -> dict:
    if t.is_empty():
        return {"trades": 0}
    x = t[r].to_numpy()
    wins, losses = x[x > 0], x[x <= 0]
    gross_loss = -losses.sum()
    sd = float(np.std(x, ddof=1)) if len(x) > 1 else float("nan")
    # racha máxima de pérdidas
    streak = best = 0
    for v in x:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    return {
        "trades": int(len(x)),
        "win_rate": float(len(wins) / len(x)),
        "avg_r": float(x.mean()),  # = expectancy en R
        "median_r": float(np.median(x)),
        "avg_win_r": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_r": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": float(wins.sum() / gross_loss) if gross_loss > 0 else float("inf"),
        "sum_r": float(x.sum()),
        "t_stat": float(x.mean() / (sd / math.sqrt(len(x)))) if len(x) > 1 and sd > 0 else float("nan"),
        "max_loss_streak": int(best),
    }


def equity_stats(eq: pl.DataFrame, value: str = "equity") -> dict:
    """Retorno total, CAGR, Sharpe/Sortino anualizados (retornos diarios), max drawdown."""
    v = eq[value].to_numpy().astype(float)
    if len(v) < 2:
        return {}
    if "ret" in eq.columns:
        rets = eq["ret"].fill_null(0.0).to_numpy().astype(float)
    else:
        rets = np.concatenate([[0.0], np.diff(v) / v[:-1]])
    start_val = v[0] / (1 + rets[0])  # capital antes de la primera sesión
    path = np.concatenate([[start_val], v])
    dd = (path / np.maximum.accumulate(path) - 1)[1:]
    years = len(v) / TRADING_DAYS
    sd, dsd = np.std(rets, ddof=1), np.std(np.minimum(rets, 0), ddof=1)
    # duración máxima en drawdown (sesiones)
    longest = cur = 0
    for x in dd:
        cur = cur + 1 if x < 0 else 0
        longest = max(longest, cur)
    total = v[-1] / start_val - 1
    return {
        "total_return": float(total),
        "cagr": float((1 + total) ** (1 / years) - 1) if years > 0 and total > -1 else float("nan"),
        "sharpe": float(rets.mean() / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else float("nan"),
        "sortino": float(rets.mean() / dsd * math.sqrt(TRADING_DAYS)) if dsd > 0 else float("nan"),
        "max_drawdown": float(dd.min()),
        "max_dd_sessions": int(longest),
        "days": int(len(v)),
    }


def deflated_sharpe(returns: np.ndarray, trial_sharpes: list[float], n_trials: int | None = None) -> float:
    """Deflated Sharpe Ratio (Bailey y López de Prado, 2014): P(SR verdadero > SR0), con SR0 el máximo
    esperado entre N intentos sin habilidad. Sharpe y varianzas en frecuencia diaria (no anualizados)."""
    from scipy.stats import kurtosis, norm, skew

    r = np.asarray(returns, dtype=float)
    t = len(r)
    if t < 3 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    n = max(n_trials or len(trial_sharpes), 2)  # n_trials: intentos totales si no todos tienen Sharpe guardado
    var_sr = float(np.var(trial_sharpes, ddof=1)) if len(trial_sharpes) > 1 else 0.0
    gamma = 0.5772156649
    sr0 = math.sqrt(var_sr) * ((1 - gamma) * norm.ppf(1 - 1 / n) + gamma * norm.ppf(1 - 1 / (n * math.e)))
    g3, g4 = float(skew(r)), float(kurtosis(r, fisher=False))
    denom = math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr**2, 1e-12))
    return float(norm.cdf((sr - sr0) * math.sqrt(t - 1) / denom))


def daily_sharpe(eq: pl.DataFrame) -> float:
    r = eq["ret"].fill_null(0.0).to_numpy()
    return float(r.mean() / r.std(ddof=1)) if r.std(ddof=1) > 0 else 0.0


def spy_buy_and_hold(store, start, end) -> pl.DataFrame:
    """Equity diaria de comprar SPY al cierre previo a `start` y mantener (precios raw; SPY sin splits)."""
    df = store.query(
        "SELECT session_date, close FROM bars_1d WHERE symbol = 'SPY' AND session_date <= ? ORDER BY session_date",
        [end],
    )
    before = df.filter(pl.col("session_date") < start).tail(1)
    period = df.filter(pl.col("session_date") >= start)
    base = float(before["close"][0]) if before.height else float(period["close"][0])
    return period.with_columns((pl.col("close") / base * 100_000).alias("equity")).with_columns(
        (pl.col("equity") / pl.col("equity").shift(1).fill_null(100_000) - 1).alias("ret")
    )


def breakdown(t: pl.DataFrame, by: str | list[str], r: str = "r_net", min_trades: int = 1) -> pl.DataFrame:
    if t.is_empty():
        return t
    return (
        t.group_by(by)
        .agg(
            pl.len().alias("trades"),
            (pl.col(r) > 0).mean().alias("win_rate"),
            pl.col(r).mean().alias("avg_r"),
            pl.col(r).sum().alias("sum_r"),
            (pl.col(r).filter(pl.col(r) > 0).sum() / -pl.col(r).filter(pl.col(r) <= 0).sum()).alias("profit_factor"),
        )
        .filter(pl.col("trades") >= min_trades)
        .sort(by)
    )
