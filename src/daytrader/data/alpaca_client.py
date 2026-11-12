"""Cliente de DATOS de Alpaca (barras y splits).

Este módulo no importa ni usa TradingClient: en la fase 1 no existe código capaz
de enviar órdenes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import polars as pl
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.corporate_actions import CorporateActionsClient
from alpaca.data.requests import CorporateActionsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

log = logging.getLogger(__name__)

# fetch(symbol, timeframe, start_utc, end_utc) -> DataFrame con columnas RAW_COLUMNS
Fetcher = Callable[[str, str, datetime, datetime], pl.DataFrame]

RAW_SCHEMA = {
    "symbol": pl.Utf8,
    "ts_utc": pl.Datetime("us"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "trade_count": pl.Int64,
    "vwap": pl.Float64,
}

_TIMEFRAMES = {"1m": TimeFrame.Minute, "5m": TimeFrame(5, TimeFrameUnit.Minute), "1d": TimeFrame.Day}


class RateLimiter:
    """Espaciado mínimo entre llamadas (aprox. de requests/min)."""

    def __init__(self, per_minute: int):
        self.interval = 60.0 / max(per_minute, 1)
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.interval:
            time.sleep(self.interval - delta)
        self._last = time.monotonic()


def with_retries(fn: Callable[[], object], max_retries: int, base_wait: float = 2.0):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # red, 429 persistente, 5xx
            status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
            if attempt == max_retries or (status is not None and 400 <= status < 500 and status != 429):
                raise  # errores de cliente (p. ej. símbolo inválido) no mejoran reintentando
            wait = base_wait * 2**attempt
            log.warning("Reintento %d/%d en %.0fs: %s", attempt + 1, max_retries, wait, exc)
            time.sleep(wait)


def raw_bars_to_frame(symbol: str, bars: list[dict]) -> pl.DataFrame:
    """Convierte la respuesta cruda de Alpaca (t,o,h,l,c,v,n,vw) a un DataFrame tipado."""
    if not bars:
        return pl.DataFrame(schema=RAW_SCHEMA)
    df = pl.DataFrame(bars)
    for k in ("n", "vw"):
        if k not in df.columns:
            df = df.with_columns(pl.lit(None).alias(k))
    return df.select(
        pl.lit(symbol).alias("symbol"),
        pl.col("t").str.to_datetime(time_unit="us", time_zone="UTC").dt.replace_time_zone(None).alias("ts_utc"),
        pl.col("o").cast(pl.Float64).alias("open"),
        pl.col("h").cast(pl.Float64).alias("high"),
        pl.col("l").cast(pl.Float64).alias("low"),
        pl.col("c").cast(pl.Float64).alias("close"),
        pl.col("v").cast(pl.Float64).alias("volume"),
        pl.col("n").cast(pl.Int64).alias("trade_count"),
        pl.col("vw").cast(pl.Float64).alias("vwap"),
    )


HTTP_TIMEOUT = (10, 120)  # (conectar, leer) en segundos: sin esto, una conexión caída cuelga el hilo para siempre


def with_timeout(client):
    """El SDK de Alpaca usa requests sin timeout; se lo añadimos a su sesión HTTP."""
    session = client._session
    original = session.request

    def request(method, url, **kw):
        kw.setdefault("timeout", HTTP_TIMEOUT)
        return original(method, url, **kw)

    session.request = request
    return client


def make_bar_fetcher(
    api_key: str,
    secret_key: str,
    feed: str = "sip",
    adjustment: str = "raw",
    max_requests_per_minute: int = 180,
    max_retries: int = 5,
) -> Fetcher:
    client = with_timeout(StockHistoricalDataClient(api_key, secret_key, raw_data=True))
    limiter = RateLimiter(max_requests_per_minute)

    def fetch(symbol: str, timeframe: str, start_utc: datetime, end_utc: datetime) -> pl.DataFrame:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=_TIMEFRAMES[timeframe],
            start=start_utc.replace(tzinfo=UTC),
            # nunca pedir los últimos 15 min (plan gratuito SIP): recortar el fin a ahora − 16 min
            end=min(end_utc.replace(tzinfo=UTC), datetime.now(UTC) - timedelta(minutes=16)),
            feed=DataFeed(feed),
            adjustment=Adjustment(adjustment),
        )

        def call():
            limiter.wait()
            return client.get_stock_bars(req)

        raw = with_retries(call, max_retries) or {}
        return raw_bars_to_frame(symbol, raw.get(symbol, []))

    return fetch


# fetch_many(symbols, timeframe, start_utc, end_utc) -> DataFrame con RAW_SCHEMA para todos los símbolos
MultiFetcher = Callable[[list[str], str, datetime, datetime], pl.DataFrame]


def make_multi_fetcher(
    api_key: str,
    secret_key: str,
    feed: str = "sip",
    adjustment: str = "raw",
    max_requests_per_minute: int = 180,
    max_retries: int = 5,
) -> MultiFetcher:
    """Igual que make_bar_fetcher pero con varios símbolos por request (Alpaca pagina internamente)."""
    client = with_timeout(StockHistoricalDataClient(api_key, secret_key, raw_data=True))
    limiter = RateLimiter(max_requests_per_minute)

    def fetch_many(symbols: list[str], timeframe: str, start_utc: datetime, end_utc: datetime) -> pl.DataFrame:
        req = StockBarsRequest(
            symbol_or_symbols=list(symbols),
            timeframe=_TIMEFRAMES[timeframe],
            start=start_utc.replace(tzinfo=UTC),
            end=min(end_utc.replace(tzinfo=UTC), datetime.now(UTC) - timedelta(minutes=16)),  # plan gratuito SIP
            feed=DataFeed(feed),
            adjustment=Adjustment(adjustment),
        )

        def call():
            limiter.wait()
            return client.get_stock_bars(req)

        raw = with_retries(call, max_retries) or {}
        frames = [raw_bars_to_frame(sym, bars) for sym, bars in raw.items() if bars]
        return pl.concat(frames) if frames else pl.DataFrame(schema=RAW_SCHEMA)

    return fetch_many


def fetch_assets(api_key: str, secret_key: str) -> pl.DataFrame:
    """Lista de acciones de EE. UU. (activas e inactivas). Endpoint de solo lectura de la cuenta paper."""
    import requests

    from daytrader.config import PAPER_TRADING_URL, assert_paper_url

    base = assert_paper_url(PAPER_TRADING_URL)
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
    rows = []
    for status in ("active", "inactive"):
        r = with_retries(
            lambda status=status: requests.get(
                f"{base}/v2/assets", params={"status": status, "asset_class": "us_equity"}, headers=headers, timeout=120
            ),
            3,
        )
        r.raise_for_status()
        rows += [
            {"symbol": a["symbol"], "name": a.get("name") or "", "exchange": a["exchange"], "status": a["status"]}
            for a in r.json()
        ]
    return pl.DataFrame(rows).unique(subset=["symbol"], keep="first")  # 'active' gana si hay duplicado


def fetch_news(api_key: str, secret_key: str, symbols: list[str], start_utc: datetime, end_utc: datetime) -> list[dict]:
    """Noticias (Benzinga vía Alpaca) para `symbols` en [start, end], todas las páginas."""
    import requests

    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
    params = {
        "symbols": ",".join(symbols),
        "start": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 50,
        "sort": "asc",
        "include_content": "false",
    }
    out: list[dict] = []
    while True:
        r = with_retries(
            lambda p=dict(params): requests.get(
                "https://data.alpaca.markets/v1beta1/news", params=p, headers=headers, timeout=60
            ),
            3,
        )
        r.raise_for_status()
        body = r.json()
        out += body.get("news", [])
        token = body.get("next_page_token")
        if not token:
            return out
        params["page_token"] = token


def fetch_splits(api_key: str, secret_key: str, symbols: list[str] | None, start: date, end: date) -> pl.DataFrame:
    """Splits en [start, end]. `symbols=None` = todo el mercado.

    Se consulta en ventanas de 30 días y se subdivide si una ventana llega al tope de 1.000
    resultados (señal de truncado).
    """
    client = CorporateActionsClient(api_key, secret_key, raw_data=True)
    cap = 1000

    def window(a: date, b: date) -> list[tuple[str, dict]]:
        req = CorporateActionsRequest(symbols=symbols, types=["forward_split", "reverse_split"], start=a, end=b)
        raw = with_retries(lambda: client.get_corporate_actions(req), 3) or {}
        items = [(k, it) for k in ("forward_splits", "reverse_splits") for it in (raw.get(k) or [])]
        if len(items) >= cap and b > a:
            mid = a + (b - a) / 2
            return window(a, mid) + window(mid + timedelta(days=1), b)
        if len(items) >= cap:
            raise RuntimeError(f"Splits truncados en {a}: {len(items)} resultados en un solo día")
        return items

    items: list[tuple[str, dict]] = []
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=29), end)
        items += window(cur, nxt)
        cur = nxt + timedelta(days=1)
    rows = []
    for key, item in items:
        rows.append(
            {
                "symbol": item["symbol"],
                "ex_date": date.fromisoformat(item["ex_date"]),
                "old_rate": float(item["old_rate"]),
                "new_rate": float(item["new_rate"]),
                "kind": "forward" if key == "forward_splits" else "reverse",
            }
        )
    schema = {"symbol": pl.Utf8, "ex_date": pl.Date, "old_rate": pl.Float64, "new_rate": pl.Float64, "kind": pl.Utf8}
    return pl.DataFrame(rows, schema=schema).unique(subset=["symbol", "ex_date"], keep="last")
