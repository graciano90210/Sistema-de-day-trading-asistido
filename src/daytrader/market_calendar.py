"""Calendario NYSE: sesiones, medias sesiones y clasificación pre/rth/post.

Todas las columnas de tiempo devueltas son datetimes *naive en UTC*, igual que en DuckDB.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xc
import polars as pl

ET = ZoneInfo("America/New_York")
ET_NAME = "America/New_York"
PRE_OPEN_ET = time(4, 0)
POST_CLOSE_ET = time(20, 0)
REGULAR_CLOSE_ET = time(16, 0)


@lru_cache(maxsize=1)
def nyse() -> xc.ExchangeCalendar:
    return xc.get_calendar("XNYS")


def et_to_utc_naive(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=ET).astimezone(UTC).replace(tzinfo=None)


def sessions(start: date, end: date) -> pl.DataFrame:
    """Sesiones NYSE en [start, end] (ambas inclusive).

    Columnas: session_date, pre_open_utc, open_utc, close_utc, post_close_utc,
    rth_minutes, early_close.
    """
    sched = nyse().schedule.loc[str(start) : str(end)]
    rows = []
    for d, row in sched.iterrows():
        sd = d.date()
        open_utc = row["open"].tz_convert("UTC").tz_localize(None).to_pydatetime()
        close_utc = row["close"].tz_convert("UTC").tz_localize(None).to_pydatetime()
        close_et = row["close"].tz_convert(ET).time()
        rows.append(
            {
                "session_date": sd,
                "pre_open_utc": et_to_utc_naive(sd, PRE_OPEN_ET),
                "open_utc": open_utc,
                "close_utc": close_utc,
                "post_close_utc": et_to_utc_naive(sd, POST_CLOSE_ET),
                "rth_minutes": int((close_utc - open_utc) / timedelta(minutes=1)),
                "early_close": close_et < REGULAR_CLOSE_ET,
            }
        )
    schema = {
        "session_date": pl.Date,
        "pre_open_utc": pl.Datetime("us"),
        "open_utc": pl.Datetime("us"),
        "close_utc": pl.Datetime("us"),
        "post_close_utc": pl.Datetime("us"),
        "rth_minutes": pl.Int64,
        "early_close": pl.Boolean,
    }
    return pl.DataFrame(rows, schema=schema)


def is_session(d: date) -> bool:
    return bool(nyse().is_session(str(d)))


def last_complete_session(now_utc: datetime | None = None) -> date:
    """Última sesión cuya jornada (incl. post-market) terminó antes de `now_utc`.

    Se exige además que sea anterior a hoy (ET) para no pedir datos SIP de los
    últimos 15 minutos, que el plan gratuito de Alpaca no permite.
    """
    now_utc = now_utc or datetime.now(UTC).replace(tzinfo=None)
    today_et = now_utc.replace(tzinfo=UTC).astimezone(ET).date()
    s = sessions(today_et - timedelta(days=15), today_et - timedelta(days=1))
    return s["session_date"].max()




def et_date_expr(col: str = "ts_utc") -> pl.Expr:
    """Expresión polars: fecha ET de un datetime naive UTC."""
    return pl.col(col).dt.replace_time_zone("UTC").dt.convert_time_zone(ET_NAME).dt.date()


def classify_sessions(df: pl.DataFrame, ts_col: str = "ts_utc") -> pl.DataFrame:
    """Añade `session_date` (fecha ET) y `session` ∈ {pre, rth, post, closed}."""
    if df.is_empty():
        return df.with_columns(
            pl.lit(None, dtype=pl.Date).alias("session_date"),
            pl.lit(None, dtype=pl.Utf8).alias("session"),
        )
    df = df.with_columns(et_date_expr(ts_col).alias("session_date"))
    lo, hi = df["session_date"].min(), df["session_date"].max()
    cal = sessions(lo, hi).select("session_date", "pre_open_utc", "open_utc", "close_utc", "post_close_utc")
    ts = pl.col(ts_col)
    out = df.join(cal, on="session_date", how="left").with_columns(
        pl.when(ts.is_between(pl.col("open_utc"), pl.col("close_utc"), closed="left"))
        .then(pl.lit("rth"))
        .when(ts.is_between(pl.col("pre_open_utc"), pl.col("open_utc"), closed="left"))
        .then(pl.lit("pre"))
        .when(ts.is_between(pl.col("close_utc"), pl.col("post_close_utc"), closed="left"))
        .then(pl.lit("post"))
        .otherwise(pl.lit("closed"))
        .alias("session")
    )
    return out.drop("pre_open_utc", "open_utc", "close_utc", "post_close_utc")
