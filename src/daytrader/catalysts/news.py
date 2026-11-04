"""Noticias por ticker con caché en DuckDB y filtro point-in-time por created_at."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import polars as pl

from daytrader.catalysts.labels import MOVERS, NO_CATALYST, PRIORITY, classify, clean, is_relevant, short_name
from daytrader.data.store import Store

# fetch(symbols, start_utc, end_utc) -> lista de dicts crudos de la API de noticias
NewsFetcher = Callable[[list[str], datetime, datetime], list[dict]]


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)


def ensure_news(
    store: Store, fetch: NewsFetcher, symbols: list[str], start_utc: datetime, end_utc: datetime, batch: int = 20
) -> int:
    covered = set(
        store.query("SELECT symbol FROM news_log WHERE start_utc <= ? AND end_utc >= ?", [start_utc, end_utc])[
            "symbol"
        ].to_list()
    )
    todo = [s for s in symbols if s not in covered]
    n = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i : i + batch]
        items = fetch(chunk, start_utc, end_utc)
        if items:
            news = pl.DataFrame(
                [
                    {
                        "id": int(x["id"]),
                        "created_at": _ts(x["created_at"]),
                        "updated_at": _ts(x["updated_at"]) if x.get("updated_at") else None,
                        "headline": clean(x.get("headline")),
                        "summary": clean(x.get("summary")),
                        "source": x.get("source"),
                        "url": x.get("url"),
                        "n_symbols": len(x.get("symbols") or []),
                    }
                    for x in items
                ],
                schema_overrides={"created_at": pl.Datetime("us"), "updated_at": pl.Datetime("us")},
            ).unique(subset=["id"])
            links = pl.DataFrame(
                [{"id": int(x["id"]), "symbol": s} for x in items for s in (x.get("symbols") or [])]
            ).unique()
            store.upsert("news", news)
            store.upsert("news_symbols", links)
            n += news.height
        store.upsert(
            "news_log",
            pl.DataFrame({"symbol": chunk, "start_utc": [start_utc] * len(chunk), "end_utc": [end_utc] * len(chunk)}),
        )
    return n


def news_for(
    store: Store,
    symbols: list[str],
    start_utc: datetime,
    as_of: datetime,
    names: dict[str, str] | None = None,
    max_symbols_for_relevance: int = 3,
) -> pl.DataFrame:
    """Noticias con start_utc <= created_at <= as_of, etiquetadas y con flag de relevancia."""
    schema = {
        "symbol": pl.Utf8, "id": pl.Int64, "created_at": pl.Datetime("us"), "headline": pl.Utf8,
        "summary": pl.Utf8, "url": pl.Utf8, "n_symbols": pl.Int32, "label": pl.Utf8,
        "labels": pl.List(pl.Utf8), "relevant": pl.Boolean,
    }  # fmt: skip
    if not symbols:
        return pl.DataFrame(schema=schema)
    df = store.query(
        f"""
        SELECT ns.symbol, n.id, n.created_at, n.headline, n.summary, n.url, n.n_symbols
        FROM news n JOIN news_symbols ns USING (id)
        WHERE ns.symbol IN ({",".join("?" * len(symbols))}) AND n.created_at >= ? AND n.created_at <= ?
        ORDER BY ns.symbol, n.created_at DESC
        """,
        [*symbols, start_utc, as_of],
    )
    if df.is_empty():
        return pl.DataFrame(schema=schema)
    names = names or {}
    rows = []
    for r in df.iter_rows(named=True):
        label, labels = classify(r["headline"], r["summary"])
        rel = is_relevant(
            r["symbol"],
            short_name(names.get(r["symbol"])),
            r["headline"],
            r["n_symbols"],
            max_symbols_for_relevance,
            r["summary"],
        )
        rows.append({**r, "label": label, "labels": labels, "relevant": rel})
    return pl.DataFrame(rows, schema=schema)


def catalyst_summary(news: pl.DataFrame) -> pl.DataFrame:
    """Por símbolo: catalizador = etiqueta de MAYOR PRIORIDAD entre noticias relevantes (empate → más reciente)."""
    if news.is_empty():
        return pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "catalyst": pl.Utf8,
                "n_news": pl.UInt32,
                "n_relevant": pl.UInt32,
                "top_headline": pl.Utf8,
            }
        )
    rel = news.filter(pl.col("relevant"))
    labelled = (
        rel.filter(~pl.col("label").is_in([NO_CATALYST, MOVERS]))
        .with_columns(pl.col("label").replace_strict(PRIORITY, return_dtype=pl.Int32).alias("_prio"))
        .sort(["_prio", "created_at"], descending=[False, True])
    )
    top = (
        labelled.group_by("symbol", maintain_order=True)
        .first()
        .select("symbol", pl.col("label").alias("catalyst"), pl.col("headline").alias("top_headline"))
    )
    counts = news.group_by("symbol").agg(
        pl.len().alias("n_news"), pl.col("relevant").sum().cast(pl.UInt32).alias("n_relevant")
    )
    out = counts.join(top, on="symbol", how="left").with_columns(pl.col("catalyst").fill_null("sin_catalizador"))
    # Si no hay etiquetada pero sí relevante, mostrar su titular igualmente.
    fallback = (
        rel.sort("created_at", descending=True)
        .group_by("symbol", maintain_order=True)
        .first()
        .select("symbol", pl.col("headline").alias("fb"))
    )
    return (
        out.join(fallback, on="symbol", how="left")
        .with_columns(pl.coalesce("top_headline", "fb").alias("top_headline"))
        .drop("fb")
        .select("symbol", "catalyst", "n_news", "n_relevant", "top_headline")
    )
