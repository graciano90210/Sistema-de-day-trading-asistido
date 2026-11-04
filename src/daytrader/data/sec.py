"""Acciones en circulación (proxy de float) desde SEC EDGAR, point-in-time por fecha de publicación.

Fuente: dei:EntityCommonStockSharesOutstanding en companyfacts. Un dato con `filed = F`
solo es visible para sesiones D > F (estricto: se publicó en algún momento del día F).
Empresas con varias clases (p. ej. GOOGL) reportan una fila por clase; se suman las del mismo reporte.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime

import polars as pl
import requests

from daytrader.data.store import Store

log = logging.getLogger(__name__)
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
MIN_INTERVAL = 0.15  # SEC permite 10 req/s; vamos más lento


def _get(url: str, user_agent: str) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"}, timeout=60)
    _time.sleep(MIN_INTERVAL)
    return r


def refresh_sec_tickers(store: Store, user_agent: str) -> int:
    r = _get(TICKERS_URL, user_agent)
    r.raise_for_status()
    rows = [
        {"symbol": v["ticker"].upper().replace("-", "."), "cik": int(v["cik_str"]), "title": v["title"]}
        for v in r.json().values()
    ]
    df = pl.DataFrame(rows).unique(subset=["symbol"], keep="first")
    return store.upsert("sec_tickers", df)


# Por prioridad: portada del reporte (por clase, se suma) → balance → promedio ponderado del periodo.
SHARE_TAGS = [
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
    ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic"),
]


def parse_companyfacts(cik: int, facts: dict) -> pl.DataFrame:
    rows = []
    for prio, (tax, tag) in enumerate(SHARE_TAGS):
        items = facts.get("facts", {}).get(tax, {}).get(tag, {})
        for x in items.get("units", {}).get("shares", []):
            if not x.get("val"):  # algunos emisores reportan 0 en el balance
                continue
            rows.append(
                {
                    "cik": cik,
                    "tag": tag,
                    "priority": prio,
                    "end_date": date.fromisoformat(x["end"]),
                    "filed": date.fromisoformat(x["filed"]),
                    "accn": x["accn"],
                    "shares": float(x["val"]),
                    "form": x.get("form"),
                }
            )
    schema = {
        "cik": pl.Int64,
        "tag": pl.Utf8,
        "priority": pl.Int32,
        "end_date": pl.Date,
        "filed": pl.Date,
        "accn": pl.Utf8,
        "shares": pl.Float64,
        "form": pl.Utf8,
    }
    return pl.DataFrame(rows, schema=schema).unique()


def ensure_companyfacts(store: Store, user_agent: str, ciks: list[int]) -> int:
    done = set(store.query("SELECT cik FROM sec_fetch_log")["cik"].to_list())
    n = 0
    for cik in ciks:
        if cik in done:
            continue
        status = "ok"
        try:
            r = _get(FACTS_URL.format(cik=cik), user_agent)
            if r.status_code == 404:
                status = "not_found"
            else:
                r.raise_for_status()
                store.upsert("shares_outstanding", parse_companyfacts(cik, r.json()))
        except Exception as exc:  # no bloquear el scan por un fallo de la SEC
            log.warning("SEC CIK %s: %s", cik, exc)
            status = "error"
        if status != "error":
            store.upsert(
                "sec_fetch_log", pl.DataFrame({"cik": [cik], "fetched_at": [datetime.now()], "status": [status]})
            )
        n += 1
    return n


def shares_outstanding_asof(store: Store, symbols: list[str], d: date) -> pl.DataFrame:
    """symbol, shares_out, so_filed, so_end, so_tag usando solo datos publicados antes de d.

    Se usa la etiqueta de mayor prioridad que tenga algún dato visible; dentro de ella, el reporte
    más reciente. Solo la etiqueta `dei` (por clase de acción) se suma; las demás ya son totales.
    """
    if not symbols:
        return pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "shares_out": pl.Float64,
                "so_filed": pl.Date,
                "so_end": pl.Date,
                "so_tag": pl.Utf8,
            }
        )
    return store.query(
        f"""
        WITH m AS (SELECT symbol, cik FROM sec_tickers WHERE symbol IN ({",".join("?" * len(symbols))})),
        visible AS (SELECT s.* FROM shares_outstanding s JOIN m USING (cik) WHERE s.filed < ?),
        -- 1) el reporte (accn) publicado más recientemente
        latest AS (SELECT cik, arg_max(accn, (filed, end_date)) AS accn FROM visible GROUP BY cik),
        -- 2) dentro de ese reporte, la etiqueta de mayor prioridad
        f AS (SELECT visible.* FROM visible JOIN latest USING (cik, accn)),
        best AS (SELECT cik, min(priority) AS priority FROM f GROUP BY cik),
        g AS (SELECT f.* FROM f JOIN best USING (cik, priority)),
        -- 3) y la fecha de corte más reciente de esa etiqueta
        last_end AS (SELECT cik, max(end_date) AS end_date FROM g GROUP BY cik),
        pick AS (
            SELECT g.cik, g.tag, g.filed, g.end_date,
                   CASE WHEN g.priority = 0 THEN sum(g.shares) ELSE max(g.shares) END AS shares
            FROM g JOIN last_end USING (cik, end_date)
            GROUP BY g.cik, g.tag, g.filed, g.end_date, g.priority
        )
        SELECT m.symbol, p.shares AS shares_out, p.filed AS so_filed, p.end_date AS so_end, p.tag AS so_tag
        FROM pick p JOIN m USING (cik)
        """,
        [*symbols, d],
    )
