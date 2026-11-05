"""Orquestación del backtest: contextos por día, señales, simulación y cartera.

Universos:
- gappers: watchlists históricas (tabla `watchlists`, reconstruidas point-in-time).
- control: los tickers fijos de config/universe.yaml, todos los días.
"""

from __future__ import annotations

import logging
from datetime import date, time, timedelta

import polars as pl

from daytrader.backtest.costs import CostModel
from daytrader.backtest.engine import simulate, trades_frame
from daytrader.data.access import get_bars
from daytrader.data.adjust import adjust_for_splits
from daytrader.data.store import Store
from daytrader.market_calendar import et_to_utc_naive, sessions
from daytrader.strategies.base import DayContext, get_strategy

log = logging.getLogger(__name__)


class HoldoutSealed(RuntimeError):
    """Intento de evaluar el periodo fuera de muestra sin desellarlo explícitamente."""


def check_holdout(start: date, end: date, holdout_start: date, allow_oos: bool) -> None:
    if not allow_oos and end >= holdout_start:
        raise HoldoutSealed(
            f"El periodo {start}..{end} toca la muestra OOS sellada (>= {holdout_start}). "
            "Usa un fin anterior o --unseal-oos (solo en fase 4)."
        )


def gapper_contexts(store: Store, start: date, end: date) -> pl.DataFrame:
    return store.query(
        "SELECT session_date, symbol, gap, prev_close, atr14, catalyst, rank FROM watchlists "
        "WHERE session_date BETWEEN ? AND ? ORDER BY session_date, rank",
        [start, end],
    )


def control_contexts(store: Store, symbols: list[str], start: date, end: date, cutoff_et: time) -> pl.DataFrame:
    """prev_close/ATR (ajustados por split a la fecha de cada sesión) y gap de pre-market a cutoff_et."""
    daily = store.query(
        f"SELECT symbol, session_date, high, low, close FROM bars_1d WHERE symbol IN ({','.join('?' * len(symbols))}) "
        "ORDER BY symbol, session_date",
        symbols,
    )
    splits = store.query("SELECT * FROM splits")
    # Ajuste "hasta hoy" y luego re-escalado a la base de acciones vigente en cada sesión d.
    full = adjust_for_splits(daily, splits, date(2100, 1, 1), price_cols=("high", "low", "close"))
    full = full.sort("symbol", "session_date").with_columns(pl.col("close").shift(1).over("symbol").alias("pc"))
    full = full.with_columns(
        pl.max_horizontal(
            pl.col("high") - pl.col("low"), (pl.col("high") - pl.col("pc")).abs(), (pl.col("low") - pl.col("pc")).abs()
        ).alias("tr")
    ).with_columns(pl.col("tr").rolling_mean(14).over("symbol").alias("atr_full"))
    # Para la sesión d se usan valores de la sesión anterior (shift 1): prev_close y ATR conocidos antes de abrir.
    full = full.with_columns(
        pl.col("close").shift(1).over("symbol").alias("prev_close_full"),
        pl.col("atr_full").shift(1).over("symbol").alias("atr14_full"),
    )
    s = splits.filter(pl.col("symbol").is_in(symbols)).with_columns(
        (pl.col("new_rate") / pl.col("old_rate")).alias("ratio")
    )
    # factor(d) = producto de ratios con ex_date > d  → escala "ajustado total" a "escala vigente en d"
    fac = (
        full.select("symbol", "session_date")
        .join(s.select("symbol", "ex_date", "ratio"), on="symbol", how="left")
        .with_columns(
            pl.when(pl.col("ex_date") > pl.col("session_date")).then(pl.col("ratio")).otherwise(1.0).alias("r")
        )
        .group_by("symbol", "session_date")
        .agg(pl.col("r").fill_null(1.0).product().alias("factor"))
    )
    full = full.join(fac, on=["symbol", "session_date"], how="left").with_columns(
        (pl.col("prev_close_full") * pl.col("factor")).alias("prev_close"),
        (pl.col("atr14_full") * pl.col("factor")).alias("atr14"),
    )
    ctx = full.filter(pl.col("session_date").is_between(start, end)).select(
        "symbol", "session_date", "prev_close", "atr14"
    )

    # Gap: último cierre de pre-market con available_at <= cutoff (barras de 1 min ya en la DB).
    cal = (
        sessions(start, end)
        .select("session_date")
        .with_columns(
            pl.col("session_date")
            .map_elements(lambda d: et_to_utc_naive(d, cutoff_et), return_dtype=pl.Datetime("us"))
            .alias("cut")
        )
    )
    store.con.register("_cuts", cal)
    try:
        pm = store.query(
            f"""
            SELECT b.symbol, b.session_date, arg_max(b.close, b.ts_utc) AS pm_last
            FROM bars_1m b JOIN _cuts c USING (session_date)
            WHERE b.session = 'pre' AND b.available_at <= c.cut AND b.symbol IN ({",".join("?" * len(symbols))})
            GROUP BY 1, 2
            """,
            symbols,
        )
    finally:
        store.con.unregister("_cuts")
    return (
        ctx.join(pm, on=["symbol", "session_date"], how="left")
        .with_columns(
            (pl.col("pm_last") / pl.col("prev_close") - 1).alias("gap"), pl.lit(None, pl.Utf8).alias("catalyst")
        )
        .filter(pl.col("prev_close").is_not_null() & pl.col("atr14").is_not_null())
        .sort("session_date", "symbol")
    )


def _month_chunks(days: list[date]) -> list[list[date]]:
    out: dict[tuple, list[date]] = {}
    for d in days:
        out.setdefault((d.year, d.month), []).append(d)
    return list(out.values())


def run_backtest(
    store: Store,
    contexts: pl.DataFrame,
    variants: dict[str, dict],
    bt_cfg: dict,
    costs: CostModel,
    alt_costs: CostModel | None = None,
    alt_variants: set[str] | None = None,
) -> pl.DataFrame:
    """Corre todas las variantes sobre los contextos. Devuelve trades a tamaño de referencia.

    Con `alt_costs`, las señales de `alt_variants` se simulan también con ese modelo (columna `costs` = "alt";
    las de `costs`, "base"); así las señales se generan una sola vez.
    """
    ref_risk = float(bt_cfg["account"]["initial_equity"]) * float(bt_cfg["account"]["risk_per_trade"])
    eod_h, eod_m = (int(x) for x in bt_cfg["execution"]["eod_exit_et"].split(":"))
    fns = {name: (get_strategy(p["type"]), {**p, "name": name}) for name, p in variants.items()}
    days = sorted(contexts["session_date"].unique().to_list())
    trades = []
    for chunk in _month_chunks(days):
        ctx_m = contexts.filter(pl.col("session_date").is_in(chunk))
        syms = ctx_m["symbol"].unique().to_list()
        start_utc = et_to_utc_naive(chunk[0], time(9, 30))
        as_of = et_to_utc_naive(chunk[-1], time(16, 0)) + timedelta(minutes=1)
        bars = get_bars(store, syms, as_of, start=start_utc, sessions=("rth",))
        groups = {k: g for k, g in bars.partition_by(["symbol", "session_date"], as_dict=True).items()}
        cal = {r["session_date"]: r for r in sessions(chunk[0], chunk[-1]).iter_rows(named=True)}
        for row in ctx_m.iter_rows(named=True):
            sd, sym = row["session_date"], row["symbol"]
            day_bars = groups.get((sym, sd))
            if day_bars is None or day_bars.height < 30 or not row["atr14"]:
                continue
            c = cal[sd]
            ctx = DayContext(
                symbol=sym, session_date=sd, prev_close=row["prev_close"], gap=row["gap"], atr14=row["atr14"],
                open_utc=c["open_utc"], close_utc=c["close_utc"], catalyst=row.get("catalyst"),
            )  # fmt: skip
            eod = min(et_to_utc_naive(sd, time(eod_h, eod_m)), c["close_utc"] - timedelta(minutes=10))
            for name, (fn, params) in fns.items():
                for sig in fn(day_bars, ctx, params):
                    tr = simulate(sig, day_bars, costs, eod, ref_risk)
                    if tr is not None:
                        trades.append((tr, row.get("catalyst"), row["gap"], "base"))
                    if alt_costs is not None and (alt_variants is None or name in alt_variants):
                        tr = simulate(sig, day_bars, alt_costs, eod, ref_risk)
                        if tr is not None:
                            trades.append((tr, row.get("catalyst"), row["gap"], "alt"))
    if not trades:
        return pl.DataFrame()
    df = trades_frame([t[0] for t in trades])
    df = df.with_columns(
        pl.Series("catalyst", [t[1] for t in trades], dtype=pl.Utf8),
        pl.Series("gap", [t[2] for t in trades], dtype=pl.Float64),
    )
    if alt_costs is None:
        return df
    return df.with_columns(pl.Series("costs", [t[3] for t in trades], dtype=pl.Utf8))


def session_list(start: date, end: date) -> list[date]:
    return sessions(start, end)["session_date"].to_list()
