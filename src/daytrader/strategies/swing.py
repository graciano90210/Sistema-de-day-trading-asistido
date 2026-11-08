"""Señales swing de la fase 8 (docs/preregistro_fase8_swing.md). Funciones puras sobre barras diarias.

Las barras llegan ajustadas por splits (base común por símbolo). Todos los indicadores son ventanas hacia atrás
(rolling / shift / EWM hacia adelante), así que la fila de la sesión D solo usa sesiones <= D → invariantes a prefijos.
La señal de D se decide con el cierre de D (disponible D 20:00 ET) y se ejecuta en la apertura de D+1 (motor).
Retornos, ATR %, medias y RSI son invariantes a escala, así que el ajuste por splits no altera ninguna señal; los
filtros de precio absoluto (S2: ≥ $10) usan el cierre RAW (`close_raw`).
"""

from __future__ import annotations

import polars as pl

SIGNAL_COLS = ["symbol", "session_date", "side", "stop_dist", "max_hold", "exit_rule", "prio"]


def indicators(daily: pl.DataFrame) -> pl.DataFrame:
    """daily: symbol, session_date, open, high, low, close, volume (ajustados) [+ close_raw]."""
    d = daily.sort("symbol", "session_date")
    if "close_raw" not in d.columns:
        d = d.with_columns(pl.col("close").alias("close_raw"))
    pc = pl.col("close").shift(1).over("symbol")
    d = d.with_columns(pc.alias("prev_close"))
    tr = pl.max_horizontal("high", "prev_close") - pl.min_horizontal("low", "prev_close")
    diff = (pl.col("close") - pl.col("prev_close")).fill_null(0.0)
    d = d.with_columns(
        pl.when(pl.col("prev_close").is_null()).then(pl.col("high") - pl.col("low")).otherwise(tr).alias("tr"),
        diff.clip(lower_bound=0).alias("_gain"),
        (-diff).clip(lower_bound=0).alias("_loss"),
    )
    d = d.with_columns(
        pl.col("tr").rolling_mean(14).over("symbol").alias("atr14"),
        pl.col("volume").rolling_mean(50).shift(1).over("symbol").alias("vol50_prev"),
        (pl.col("close") / pl.col("prev_close") - 1).alias("ret1"),
        pl.when(pl.col("high") > pl.col("low"))
        .then((pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low")))
        .otherwise(0.5)
        .alias("range_pos"),
        pl.col("close").rolling_mean(200).over("symbol").alias("sma200"),
        pl.col("close").rolling_mean(5).over("symbol").alias("sma5"),
        pl.col("_gain").ewm_mean(alpha=0.5, adjust=False).over("symbol").alias("_ag"),  # RSI(2) de Wilder
        pl.col("_loss").ewm_mean(alpha=0.5, adjust=False).over("symbol").alias("_al"),
        pl.len().over("symbol").alias("_n"),
        pl.int_range(pl.len()).over("symbol").alias("_i"),
    )
    rsi = pl.when(pl.col("_al") == 0).then(100.0).otherwise(100 - 100 / (1 + pl.col("_ag") / pl.col("_al")))
    return d.with_columns(
        pl.col("atr14").shift(1).over("symbol").alias("atr14_prev"),
        pl.when(pl.col("_i") >= 2).then(rsi).otherwise(None).alias("rsi2"),
    ).drop("_gain", "_loss", "_ag", "_al", "_n", "_i")


def _in_universe(d: pl.DataFrame, universe: pl.DataFrame) -> pl.DataFrame:
    """universe: year, symbol, adv_usd → filtra al universo del año de la señal y añade la prioridad."""
    return d.with_columns(pl.col("session_date").dt.year().alias("year")).join(
        universe.select("year", "symbol", pl.col("adv_usd").alias("prio")), on=["year", "symbol"], how="inner"
    )


def s3_volume_shock(ind: pl.DataFrame, universe: pl.DataFrame, p: dict) -> pl.DataFrame:
    """S3: volumen ≥ vol_mult × media 50 (hasta D−1) y |ret| ≥ atr_mult × ATR14 % (hasta D−1); cierre fuerte."""
    d = _in_universe(ind, universe).filter(
        pl.col("vol50_prev").is_not_null() & pl.col("atr14_prev").is_not_null() & pl.col("atr14").is_not_null()
    )
    shock = (pl.col("volume") >= float(p["vol_mult"]) * pl.col("vol50_prev")) & (
        pl.col("ret1").abs() >= float(p["atr_mult"]) * pl.col("atr14_prev") / pl.col("prev_close")
    )
    cl = float(p["close_frac"])
    side = (
        pl.when((pl.col("ret1") > 0) & (pl.col("range_pos") >= 1 - cl)).then(1)
        .when((pl.col("ret1") < 0) & (pl.col("range_pos") <= cl)).then(-1)
        .otherwise(0)
    )  # fmt: skip
    return (
        d.filter(shock)
        .with_columns(side.alias("side"))
        .filter(pl.col("side") != 0)
        .with_columns(
            (float(p["stop_atr"]) * pl.col("atr14")).alias("stop_dist"),
            pl.lit(int(p["max_hold"])).alias("max_hold"),
            pl.lit("time").alias("exit_rule"),
        )
        .select(SIGNAL_COLS)
    )


def s4_rsi2(ind: pl.DataFrame, universe: pl.DataFrame, p: dict) -> pl.DataFrame:
    """S4: cierre > SMA200 y RSI(2) < umbral → largo; sale al primer cierre > SMA5 o a las max_hold sesiones."""
    d = _in_universe(ind, universe).filter(pl.col("sma200").is_not_null() & pl.col("rsi2").is_not_null())
    return (
        d.filter((pl.col("close") > pl.col("sma200")) & (pl.col("rsi2") < float(p["rsi_max"])))
        .with_columns(
            pl.lit(1).alias("side"),
            (float(p["stop_atr"]) * pl.col("atr14")).alias("stop_dist"),
            pl.lit(int(p["max_hold"])).alias("max_hold"),
            pl.lit("sma5").alias("exit_rule"),
        )
        .select(SIGNAL_COLS)
    )


def month_ends(sessions: list) -> list:
    """Última sesión de cada mes del calendario."""
    s = pl.DataFrame({"d": sessions}).with_columns(pl.col("d").dt.strftime("%Y-%m").alias("m"))
    return s.group_by("m").agg(pl.col("d").max()).sort("d")["d"].to_list()


def week_ends(sessions: list) -> list:
    s = pl.DataFrame({"d": sessions}).with_columns((pl.col("d").dt.iso_year() * 100 + pl.col("d").dt.week()).alias("w"))
    return s.group_by("w").agg(pl.col("d").max()).sort("d")["d"].to_list()


def s1_momentum(ind: pl.DataFrame, universe: pl.DataFrame, spy: pl.DataFrame, sessions: list, p: dict) -> dict:
    """S1: en cada fin de mes D, top `top` por retorno de los meses (m−L … m−1) — se salta el mes actual.
    Retorno = cierre del fin del mes m−1 / cierre del fin del mes m−L−1 ... implementado como
    close(fin de mes m−1) / close(fin de mes m−lookback) − 1 (12−1 → 11 meses de retorno, sin el último mes).
    Filtro: si SPY cierra ≤ SMA200 en D → efectivo. Devuelve {D: [símbolos]}."""
    me = month_ends(sessions)
    lb, skip, top = int(p["lookback_months"]), int(p.get("skip_months", 1)), int(p["top"])
    closes = ind.filter(pl.col("session_date").is_in(me)).select("symbol", "session_date", "close")
    idx = {d: i for i, d in enumerate(me)}
    spy_f = spy.select("session_date", "close", "sma200")
    out = {}
    for d in me:
        i = idx[d]
        if i - lb < 0:
            continue
        srow = spy_f.filter(pl.col("session_date") == d)
        if srow.is_empty() or srow["sma200"][0] is None or srow["close"][0] <= srow["sma200"][0]:
            out[d] = []
            continue
        a, b = me[i - skip], me[i - lb]
        uni = universe.filter(pl.col("year") == d.year).select("symbol")
        ca = closes.filter(pl.col("session_date") == a).select("symbol", pl.col("close").alias("ca"))
        cb = closes.filter(pl.col("session_date") == b).select("symbol", pl.col("close").alias("cb"))
        cur = closes.filter(pl.col("session_date") == d).select("symbol")  # cotiza hoy (no deslistado)
        r = (
            uni.join(cur, on="symbol").join(ca, on="symbol").join(cb, on="symbol")
            .with_columns((pl.col("ca") / pl.col("cb") - 1).alias("mom"))
            .sort(["mom", "symbol"], descending=[True, False])
            .head(top)
        )  # fmt: skip
        out[d] = r["symbol"].to_list()
    return out


def s2_reversal(ind: pl.DataFrame, universe: pl.DataFrame, sessions: list, p: dict) -> dict:
    """S2: cada fin de semana D, las `top` con peor retorno de `window` sesiones (precio raw ≥ min_price,
    caída > max_drop excluida). Devuelve {D: [símbolos]}."""
    w, top = int(p["window"]), int(p["top"])
    we = week_ends(sessions)
    d = ind.with_columns((pl.col("close") / pl.col("close").shift(w).over("symbol") - 1).alias("retw")).filter(
        pl.col("session_date").is_in(we)
    )
    d = _in_universe(d, universe).filter(
        pl.col("retw").is_not_null()
        & (pl.col("close_raw") >= float(p["min_price"]))
        & (pl.col("retw") > -float(p["max_drop"]))
    )
    ranked = d.sort(["session_date", "retw", "symbol"]).group_by("session_date", maintain_order=True).head(top)
    out = {x: [] for x in we}
    for (dt,), g in ranked.group_by("session_date", maintain_order=True):
        out[dt] = g["symbol"].to_list()
    return out
