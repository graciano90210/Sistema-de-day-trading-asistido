"""CLI: `uv run daytrader --help`."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from daytrader.config import Secrets, load_config, load_universe
from daytrader.data.ingest import ingest as run_ingest
from daytrader.data.ingest import month_chunks
from daytrader.data.store import Store
from daytrader.market_calendar import last_complete_session

app = typer.Typer(no_args_is_help=True, help="Sistema de day trading asistido (solo paper).")
console = Console()


def _parse_symbols(symbols: str | None) -> list[str]:
    return [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else load_universe()


@app.command()
def ingest(
    timeframe: Annotated[str, typer.Option(help="1m, 1d o all")] = "all",
    symbols: Annotated[str | None, typer.Option(help="Coma-separados; por defecto config/universe.yaml")] = None,
    start: Annotated[str | None, typer.Option(help="YYYY-MM-DD (por defecto settings.yaml)")] = None,
    end: Annotated[str | None, typer.Option(help="YYYY-MM-DD inclusive (por defecto última sesión completa)")] = None,
    splits: Annotated[bool, typer.Option(help="Descargar también splits")] = True,
) -> None:
    """Descarga/actualiza barras de Alpaca (SIP, raw) a DuckDB. Incremental y reanudable."""
    from daytrader.data.alpaca_client import fetch_splits, make_bar_fetcher

    logging.basicConfig(level=logging.WARNING)
    cfg = load_config()
    key, secret = Secrets().require_alpaca()
    syms = _parse_symbols(symbols)
    d0 = date.fromisoformat(start) if start else cfg.data.history_start
    d1 = date.fromisoformat(end) if end else (cfg.data.history_end or last_complete_session())
    end_excl = d1 + timedelta(days=1)
    fetch = make_bar_fetcher(
        key, secret, cfg.data.feed, cfg.data.adjustment, cfg.data.max_requests_per_minute, cfg.data.max_retries
    )
    tfs = ["1d", "1m"] if timeframe == "all" else [timeframe]
    console.print(f"[bold]Ingesta[/] {len(syms)} símbolos · {d0} → {d1} · feed={cfg.data.feed} · {tfs}")

    with Store(cfg.db_path, memory_limit=cfg.duckdb_memory_limit) as store:
        if splits:
            n = store.upsert_splits(fetch_splits(key, secret, syms, d0, d1))
            console.print(f"Splits: {n}")
        for tf in tfs:
            total = len(syms) * (len(month_chunks(d0, end_excl)) if tf == "1m" else 1)
            with Progress(
                TextColumn(f"[cyan]{tf}[/] {{task.description}}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as prog:
                task = prog.add_task("", total=total)

                def on_chunk(sym, c0, _c1, n, task=task, prog=prog):
                    prog.update(task, advance=1, description=f"{sym} {c0:%Y-%m} (+{n})")

                summary = run_ingest(store, fetch, syms, d0, end_excl, tf, cfg.data.feed, on_chunk=on_chunk)
            console.print(
                f"{tf}: {summary.chunks_done} bloques nuevos, {summary.chunks_skipped} ya en caché, "
                f"{summary.rows:,} filas, {len(summary.errors)} errores"
            )
            for sym, c0, err in summary.errors[:10]:
                console.print(f"  [red]{sym} {c0}: {err}[/]")


@app.command()
def quality() -> None:
    """Genera reports/data_quality.md a partir de la DB."""
    from daytrader.data.quality import build_report, render_markdown

    cfg = load_config()
    with Store(cfg.db_path, read_only=True) as store:
        report = build_report(store)
    cfg.reports_path.mkdir(parents=True, exist_ok=True)
    out = cfg.reports_path / "data_quality.md"
    out.write_text(render_markdown(report))
    console.print(report.overview)
    console.print(f"Integridad: {'[green]OK' if report.integrity_ok else '[red]VIOLACIONES'}[/]")
    console.print(f"Reporte: {out}")


@app.command()
def info() -> None:
    """Resumen rápido de la DB y del universo."""
    cfg = load_config()
    console.print(f"Universo: {len(load_universe())} símbolos · DB: {cfg.db_path}")
    if not cfg.db_path.exists():
        console.print("DB aún no creada. Ejecuta `daytrader ingest`.")
        return
    with Store(cfg.db_path, read_only=True) as store:
        console.print(
            store.query(
                "SELECT timeframe, status, count(*) AS bloques, sum(rows) AS filas FROM ingest_log GROUP BY 1, 2 ORDER BY 1, 2"
            )
        )
    console.print(f"Tamaño: {cfg.db_path.stat().st_size / 1e6:,.0f} MB")


if __name__ == "__main__":
    app()
