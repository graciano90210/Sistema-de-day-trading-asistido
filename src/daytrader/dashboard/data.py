"""Datos del dashboard (fase 6). Funciones puras: todo número sale de aquí, la UI solo dibuja."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import polars as pl

from daytrader.backtest.metrics import trade_stats

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

RUN_LABELS = {
    "orb_5__gappers": "R1 · ORB 5 · gappers", "orb_15__gappers": "R1 · ORB 15 · gappers",
    "vwap_rev__gappers": "R1 · VWAP · gappers", "orb_5__control": "R1 · ORB 5 · control",
    "orb_15__control": "R1 · ORB 15 · control", "vwap_rev__control": "R1 · VWAP · control",
    "r2_H1": "R2 · H1 ORB stocks in play", "r2_H2": "R2 · H2 ORB stop gappers",
    "r2_H3_gappers": "R2 · H3 VWAP amplio · gappers", "r2_H3_control": "R2 · H3 VWAP amplio · control",
    "r2_H4": "R2 · H4 meta-labeling LightGBM", "r2_H5a": "R2 · H5a ORB + HMM volátil",
    "r2_H5b": "R2 · H5b VWAP + HMM tranquilo", "r3_walk_forward": "R3 · VWAP límite (walk-forward)",
}  # fmt: skip


# ------------------------------------------------------------------ carga
def load_journal(path: Path) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """(trades cerrados, tickets, notas) del journal paper. Vacíos si no existe."""
    if not Path(path).exists():
        return pl.DataFrame(), pl.DataFrame(), pl.DataFrame()
    con = duckdb.connect(str(path), read_only=True)
    try:
        q = lambda s: con.sql(s).pl()  # noqa: E731
        trades = q(
            "SELECT t.*, k.setup, k.catalyst FROM trades t LEFT JOIN tickets k USING (fingerprint) ORDER BY exit_ts"
        )
        return trades, q("SELECT * FROM tickets ORDER BY created_at"), q("SELECT * FROM notes ORDER BY ts")
    finally:
        con.close()


def list_backtests(folder: Path) -> dict[str, Path]:
    out = {}
    for f in sorted(Path(folder).glob("*.parquet")):
        key = f.stem.split("__2024")[0]
        if key in RUN_LABELS:
            out[RUN_LABELS[key]] = f
    order = list(RUN_LABELS.values())
    return dict(sorted(out.items(), key=lambda kv: order.index(kv[0])))


def load_backtest(path: Path) -> pl.DataFrame:
    """Trades tomados por la cartera, con columnas homogéneas: session_date, exit_ts, symbol, side, r, pnl."""
    t = pl.read_parquet(path)
    if "taken" in t.columns:
        t = t.filter(pl.col("taken"))
    pnl = "pnl_usd" if "pnl_usd" in t.columns else "pnl"
    return t.select(
        "session_date", "entry_ts", "exit_ts", "symbol", "side", pl.col("r_net").alias("r"),
        pl.col(pnl).alias("pnl"), pl.col("exit_reason"), pl.col("strategy"),
    ).sort("exit_ts")  # fmt: skip


def journal_as_trades(j: pl.DataFrame) -> pl.DataFrame:
    if j.is_empty():
        return j
    return j.select(
        "session_date", "entry_ts", "exit_ts", "symbol", pl.when(pl.col("side") == "long").then(1).otherwise(-1).alias("side"),
        pl.col("r_multiple").alias("r"), "pnl", "exit_reason", pl.col("setup").fill_null(""),
        pl.col("entry_slippage_r"),
    ).sort("exit_ts")  # fmt: skip


# ------------------------------------------------------------------ métricas
def equity_curve(t: pl.DataFrame, initial: float = 100_000.0) -> pl.DataFrame:
    """Capital diario a partir del PnL realizado; incluye drawdown."""
    if t.is_empty():
        return pl.DataFrame(schema={"session_date": pl.Date, "equity": pl.Float64, "drawdown": pl.Float64})
    d = t.group_by("session_date").agg(pl.col("pnl").sum()).sort("session_date")
    eq = d.with_columns((initial + pl.col("pnl").cum_sum()).alias("equity"))
    peak = np.maximum.accumulate(np.concatenate([[initial], eq["equity"].to_numpy()]))[1:]
    return eq.with_columns(pl.Series("drawdown", eq["equity"].to_numpy() / peak - 1)).select(
        "session_date", "equity", "drawdown"
    )


def kpis(t: pl.DataFrame, initial: float = 100_000.0) -> dict:
    if t.is_empty():
        return {"trades": 0}
    s = trade_stats(t, "r")
    eq = equity_curve(t, initial)
    return {**s, "pnl": float(t["pnl"].sum()), "retorno": float(eq["equity"][-1] / initial - 1),
            "max_dd": float(eq["drawdown"].min())}  # fmt: skip


def r_ci(t: pl.DataFrame) -> tuple[float, float]:
    """IC 95% del R medio (normal); amplio con pocos trades."""
    x = t["r"].to_numpy()
    if len(x) < 2:
        return (float("nan"), float("nan"))
    se = x.std(ddof=1) / np.sqrt(len(x))
    return float(x.mean() - 1.96 * se), float(x.mean() + 1.96 * se)


def with_entry_hour(t: pl.DataFrame) -> pl.DataFrame:
    if t.is_empty():
        return t
    hours = [x.replace(tzinfo=UTC).astimezone(ET).strftime("%H:00") for x in t["entry_ts"].to_list()]
    return t.with_columns(pl.Series("hora_et", hours))


def by(t: pl.DataFrame, col: str, min_trades: int = 1) -> pl.DataFrame:
    if t.is_empty() or col not in t.columns:
        return pl.DataFrame()
    return (
        t.group_by(col)
        .agg(
            pl.len().alias("trades"),
            (pl.col("r") > 0).mean().alias("win_rate"),
            pl.col("r").mean().alias("R_medio"),
            pl.col("r").sum().alias("R_total"),
            pl.col("pnl").sum().alias("PnL"),
        )  # fmt: skip
        .filter(pl.col("trades") >= min_trades)
        .sort(col)
    )


def spy_curve(daily_close: pl.DataFrame, start, end, initial: float = 100_000.0) -> pl.DataFrame:
    """Buy & hold de SPY comprando al cierre previo a `start`."""
    df = daily_close.sort("session_date")
    before = df.filter(pl.col("session_date") < start).tail(1)
    period = df.filter(pl.col("session_date").is_between(start, end))
    if period.is_empty():
        return period
    base = float(before["close"][0]) if before.height else float(period["close"][0])
    return period.select("session_date", (pl.col("close") / base * initial).alias("equity"))


# ------------------------------------------------------------------ en vivo (posiciones abiertas)
def live_positions(positions: list[dict], tickets: pl.DataFrame) -> pl.DataFrame:
    """Une las posiciones abiertas de Alpaca con su ticket enviado (stop, objetivo, riesgo planificado).

    R actual = PnL flotante / riesgo planificado del ticket. `progreso` = posición del precio entre el stop (0)
    y el objetivo (1); < 0 significa más allá del stop (la orden de stop debería ejecutarse).
    """
    cols = {"símbolo": pl.Utf8, "dirección": pl.Utf8, "acciones": pl.Float64, "entrada": pl.Float64,
            "precio": pl.Float64, "PnL $": pl.Float64, "R actual": pl.Float64, "stop": pl.Float64,
            "objetivo": pl.Float64, "a stop (R)": pl.Float64, "progreso": pl.Float64}  # fmt: skip
    if not positions:
        return pl.DataFrame(schema=cols)
    sent = (
        tickets.filter(pl.col("status") == "enviado").sort("created_at").group_by("symbol").last()
        if not tickets.is_empty() else pl.DataFrame(schema={"symbol": pl.Utf8})
    )  # fmt: skip
    tk = {r["symbol"]: r for r in sent.iter_rows(named=True)} if not sent.is_empty() else {}
    rows = []
    for p in positions:
        qty = float(p["qty"])
        d = 1 if qty > 0 else -1
        price = abs(float(p["market_value"]) / qty) if qty else float("nan")
        t = tk.get(p["symbol"])
        stop = t["stop_price"] if t else None
        target = t["target_price"] if t else None
        rps = abs((t["limit_price"] or t["ref_price"]) - stop) if t else None
        pnl = float(p["unrealized_pl"])
        prog = None
        if stop is not None and target is not None and target != stop:
            prog = (price - stop) / (target - stop)
        rows.append({
            "símbolo": p["symbol"], "dirección": "largo" if d == 1 else "corto", "acciones": abs(qty),
            "entrada": float(p["avg_entry"]), "precio": price, "PnL $": pnl,
            "R actual": pnl / (rps * abs(qty)) if rps else None, "stop": stop, "objetivo": target,
            "a stop (R)": (price - stop) * d / rps if rps else None, "progreso": prog,
        })  # fmt: skip
    return pl.DataFrame(rows, schema=cols)


def minutes_to(target_utc, now_utc) -> float:
    return (target_utc - now_utc).total_seconds() / 60
