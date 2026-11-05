"""CLI: `uv run daytrader --help`."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Annotated

import polars as pl
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


@app.command()
def universe(
    start: Annotated[str | None, typer.Option(help="YYYY-MM-DD (por defecto settings.yaml)")] = None,
    end: Annotated[str | None, typer.Option(help="YYYY-MM-DD inclusive (por defecto última sesión completa)")] = None,
) -> None:
    """Descarga la lista de acciones (activas+inactivas), splits de todo el mercado y barras DIARIAS del universo."""
    from daytrader.config import load_yaml
    from daytrader.data.alpaca_client import fetch_assets, fetch_splits, make_multi_fetcher
    from daytrader.scanner.universe import eligible_symbols, ingest_universe_daily, refresh_assets

    logging.basicConfig(level=logging.WARNING)
    cfg, scfg = load_config(), load_yaml("scanner.yaml")["universe"]
    key, secret = Secrets().require_alpaca()
    d0 = date.fromisoformat(start) if start else cfg.data.history_start
    d1 = date.fromisoformat(end) if end else (cfg.data.history_end or last_complete_session())
    with Store(cfg.db_path, memory_limit=cfg.duckdb_memory_limit) as store:
        n = refresh_assets(store, fetch_assets(key, secret))
        syms = eligible_symbols(store, scfg["exchanges"], scfg["include_inactive"])
        console.print(f"Activos: {n:,} · acciones comunes elegibles: {len(syms):,}")
        n_splits = store.upsert_splits(fetch_splits(key, secret, None, d0, d1))
        console.print(f"Splits (todo el mercado): {n_splits:,}")
        fetch_many = make_multi_fetcher(
            key, secret, cfg.data.feed, cfg.data.adjustment, cfg.data.max_requests_per_minute
        )
        with Progress(
            TextColumn("diarias"), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(), console=console
        ) as prog:
            task = prog.add_task("", total=None)
            rows, errors = ingest_universe_daily(
                store, fetch_many, syms, d0, d1 + timedelta(days=1), cfg.data.feed,
                on_batch=lambda done, total: prog.update(task, completed=done, total=total),
            )  # fmt: skip
        console.print(f"Barras diarias nuevas: {rows:,} · lotes con error: {errors}")


@app.command()
def watchlist(
    day: Annotated[str, typer.Option("--date", help="Sesión YYYY-MM-DD")],
    cutoff: Annotated[str | None, typer.Option(help="Hora ET HH:MM (por defecto scanner.yaml)")] = None,
    top: Annotated[int | None, typer.Option(help="Tamaño de la watchlist")] = None,
) -> None:
    """Scanner de gappers + catalizadores para una sesión → reports/watchlist_<fecha>.md"""
    from daytrader.catalysts.news import catalyst_summary, ensure_news, news_for
    from daytrader.config import load_yaml
    from daytrader.data.alpaca_client import fetch_news, make_multi_fetcher
    from daytrader.data.sec import ensure_companyfacts, refresh_sec_tickers, shares_outstanding_asof
    from daytrader.market_calendar import REGULAR_CLOSE_ET, et_to_utc_naive
    from daytrader.scanner.report import render_watchlist
    from daytrader.scanner.scan import run_scan
    from daytrader.scanner.universe import previous_sessions

    logging.basicConfig(level=logging.WARNING)
    d = date.fromisoformat(day)
    cfg, scfg = load_config(), load_yaml("scanner.yaml")
    if cutoff:
        scfg["cutoff_et"] = cutoff
    if top:
        scfg["gappers"]["top_n"] = top
    secrets = Secrets()
    key, secret = secrets.require_alpaca()
    ua = secrets.require_sec_user_agent()
    fetch_many = make_multi_fetcher(key, secret, cfg.data.feed, cfg.data.adjustment, cfg.data.max_requests_per_minute)

    with Store(cfg.db_path, memory_limit=cfg.duckdb_memory_limit) as store:
        if store.query("SELECT count(*) AS n FROM sec_tickers")["n"][0] == 0:
            refresh_sec_tickers(store, ua)

        def shares_lookup(symbols, d):
            ciks = store.query(
                f"SELECT cik FROM sec_tickers WHERE symbol IN ({','.join('?' * len(symbols))})", symbols
            )["cik"].to_list() if symbols else []  # fmt: skip
            ensure_companyfacts(store, ua, ciks)
            return shares_outstanding_asof(store, symbols, d)

        with console.status("Escaneando…"):
            res = run_scan(store, d, scfg, fetch_many, shares_lookup)
        wl_syms = res.watchlist["symbol"].to_list()
        names = dict(store.query("SELECT symbol, name FROM assets").iter_rows())
        prev_day = previous_sessions(d, 1)[0]
        news_start = et_to_utc_naive(prev_day, REGULAR_CLOSE_ET)
        ensure_news(store, lambda s, a, b: fetch_news(key, secret, s, a, b), wl_syms, news_start, res.cutoff_utc)
        news = news_for(
            store, wl_syms, news_start, res.cutoff_utc, names, scfg["catalysts"]["max_symbols_for_relevance"]
        )
        cats = catalyst_summary(news)

    md = render_watchlist(res, names, cats, news)
    cfg.reports_path.mkdir(parents=True, exist_ok=True)
    out = cfg.reports_path / f"watchlist_{d}.md"
    out.write_text(md)
    for name, n in res.funnel:
        console.print(f"  {name:<45} {n:>6,}")
    console.print(f"Reporte: {out}")


@app.command()
def backfill(
    start: Annotated[
        str | None, typer.Option(help="YYYY-MM-DD (por defecto: primera sesión con 21 días de historia)")
    ] = None,
    end: Annotated[str | None, typer.Option(help="YYYY-MM-DD inclusive (por defecto: última sesión completa)")] = None,
    no_news: Annotated[bool, typer.Option(help="No descargar noticias")] = False,
) -> None:
    """Reconstruye watchlists históricas (point-in-time) y descarga barras 1m de sus tickers. Reanudable."""
    from daytrader.config import load_yaml
    from daytrader.data.alpaca_client import fetch_news, make_multi_fetcher
    from daytrader.data.sec import ensure_companyfacts, refresh_sec_tickers, shares_outstanding_asof
    from daytrader.scanner.history import backfill as run_backfill
    from daytrader.scanner.history import scannable_days

    logging.basicConfig(level=logging.WARNING)
    cfg, scfg = load_config(), load_yaml("scanner.yaml")
    secrets = Secrets()
    key, secret = secrets.require_alpaca()
    ua = secrets.require_sec_user_agent()
    fetch_many = make_multi_fetcher(key, secret, cfg.data.feed, cfg.data.adjustment, cfg.data.max_requests_per_minute)
    d1 = date.fromisoformat(end) if end else last_complete_session()
    with Store(cfg.db_path, memory_limit=cfg.duckdb_memory_limit) as store:
        if store.query("SELECT count(*) AS n FROM sec_tickers")["n"][0] == 0:
            refresh_sec_tickers(store, ua)

        def shares_lookup(symbols, d):
            ciks = store.query(
                f"SELECT cik FROM sec_tickers WHERE symbol IN ({','.join('?' * len(symbols))})", symbols
            )["cik"].to_list() if symbols else []  # fmt: skip
            ensure_companyfacts(store, ua, ciks)
            return shares_outstanding_asof(store, symbols, d)

        days = scannable_days(store, date.fromisoformat(start) if start else date(2000, 1, 1), d1)
        console.print(f"Backfill: {len(days)} sesiones {days[0]} → {days[-1]}")
        news_fetch = None if no_news else (lambda s, a, b: fetch_news(key, secret, s, a, b))
        with Progress(
            TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(), console=console
        ) as prog:
            task = prog.add_task("", total=len(days))
            ok, err = run_backfill(
                store, days, scfg, fetch_many, news_fetch, shares_lookup, cfg.data.feed,
                on_day=lambda d, ok, err: prog.update(task, advance=1, description=f"{d} ok={ok} err={err}"),
            )  # fmt: skip
        console.print(f"Sesiones nuevas OK: {ok} · errores: {err}")


@app.command()
def opening(
    start: Annotated[str, typer.Option(help="YYYY-MM-DD")] = "2024-11-22",
    end: Annotated[str | None, typer.Option(help="YYYY-MM-DD inclusive (por defecto última sesión completa)")] = None,
    workers: Annotated[int, typer.Option(help="Días en paralelo")] = 4,
) -> None:
    """Ronda 2 / H1: velas de apertura 5 min del universo amplio, selección de stocks in play y barras 1m del top 20."""
    from daytrader.data.alpaca_client import make_multi_fetcher
    from daytrader.market_calendar import sessions
    from daytrader.scanner.history import ensure_intraday
    from daytrader.scanner.opening import ensure_opening_bars, select_stocks_in_play

    logging.basicConfig(level=logging.WARNING)
    cfg = load_config()
    key, secret = Secrets().require_alpaca()
    d1 = date.fromisoformat(end) if end else last_complete_session()
    days = sessions(date.fromisoformat(start), d1)["session_date"].to_list()

    def factory():
        return make_multi_fetcher(
            key, secret, cfg.data.feed, cfg.data.adjustment, cfg.data.max_requests_per_minute // workers
        )

    with Store(cfg.db_path, memory_limit=cfg.duckdb_memory_limit) as store:
        with Progress(
            TextColumn("aperturas {task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as prog:
            task = prog.add_task("", total=len(days))
            ensure_opening_bars(store, factory, days, workers,
                                on_day=lambda d, n: prog.update(task, advance=1, description=f"{d} ({n})"))  # fmt: skip
        fetch = factory()
        have = set(store.query("SELECT DISTINCT session_date FROM stocks_in_play")["session_date"].to_list())
        n_sel = 0
        with Progress(
            TextColumn("selección + barras {task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as prog:
            task = prog.add_task("", total=len(days))
            for d in days:
                if d not in have:
                    sel = select_stocks_in_play(store, d)
                    if not sel.is_empty():
                        store.upsert("stocks_in_play", sel)
                        ensure_intraday(
                            store, fetch, sel.filter(pl.col("side") != 0)["symbol"].to_list(), d, cfg.data.feed
                        )
                        n_sel += sel.height
                prog.update(task, advance=1, description=str(d))
        console.print(f"Selecciones nuevas: {n_sel}")


@app.command()
def round2(
    p_entry: Annotated[float | None, typer.Option(help="Fijar p (si no, se calibra con ticks)")] = None,
) -> None:
    """Ronda 2 pre-registrada (H1–H5) en el periodo de desarrollo → reports/ronda2_IS.md"""
    import glob

    from daytrader.config import ROOT, load_yaml
    from daytrader.data.alpaca_client import make_multi_fetcher
    from daytrader.research.report2 import render
    from daytrader.research.round2 import finalize, run_round2, trial_sharpes_round1

    logging.basicConfig(level=logging.WARNING)
    cfg, bt, strat, scfg = (
        load_config(),
        load_yaml("backtest.yaml"),
        load_yaml("strategies.yaml"),
        load_yaml("scanner.yaml"),
    )
    key, secret = Secrets().require_alpaca()
    holdout = date.fromisoformat(bt["holdout_start"])
    d0, d1 = date.fromisoformat(bt["in_sample_start"]), holdout - timedelta(days=1)

    spy_path = ROOT / "data" / "spy_daily_2016.parquet"
    if not spy_path.exists():
        from datetime import datetime

        raw = make_multi_fetcher(key, secret)(["SPY"], "1d", datetime(2015, 12, 1), datetime(2026, 1, 1))
        raw.with_columns(pl.col("ts_utc").dt.date().alias("session_date")).write_parquet(spy_path)
    spy_long = pl.read_parquet(spy_path).filter(pl.col("session_date") < holdout)

    with Store(cfg.db_path, read_only=True) as store:
        with console.status("Ronda 2: backtests, calibración, HMM y meta-labeling…"):
            result = run_round2(store, bt, strat, scfg, load_universe(), spy_long, p_entry, (key, secret), d0, d1)
        r1 = sorted(glob.glob(str(ROOT / "data" / "backtests" / "*__20*-12-03_2025-12-31.parquet")))
        r1 = [f for f in r1 if any(s in f for s in ("orb_5__", "orb_15__", "vwap_rev__"))]
        round1 = trial_sharpes_round1(store, bt, r1)
    rows = finalize(result, round1)
    (cfg.reports_path / "ronda2_IS.md").write_text(render(result, rows, d0, d1, round1))
    for r in rows:
        console.print(f"  {r['config']:<11} trades={r['trades']:>5} R={r['R_neto'] or 0:+.3f} PF={r['profit_factor'] or 0:.2f} "
                      f"DSR={r['dsr']:.2f} {'PASA' if r['pasa'] else ''}")  # fmt: skip
    console.print(f"p calibrado = {result['calib']['p']}")
    console.print(f"Reporte: {cfg.reports_path / 'ronda2_IS.md'}")


@app.command()
def backtest(
    strategies: Annotated[
        str, typer.Option(help="Variantes de config/strategies.yaml, coma-separadas")
    ] = "orb_5,orb_15,vwap_rev",
    universes: Annotated[str, typer.Option(help="gappers, control o ambos")] = "gappers,control",
    start: Annotated[str | None, typer.Option(help="YYYY-MM-DD (por defecto in_sample_start)")] = None,
    end: Annotated[str | None, typer.Option(help="YYYY-MM-DD (por defecto el día antes del holdout)")] = None,
    db: Annotated[str | None, typer.Option(help="Ruta alternativa de la DB (p. ej. copia de desarrollo)")] = None,
    out: Annotated[str, typer.Option(help="Nombre del reporte en reports/")] = "backtest_IS.md",
    unseal_oos: Annotated[
        bool, typer.Option("--unseal-oos", help="Permite evaluar el periodo OOS (solo fase 4)")
    ] = False,
) -> None:
    """Backtest de estrategias con costos y cartera → reports/<out> y data/backtests/*.parquet"""
    import yaml

    from daytrader.backtest.costs import CostModel
    from daytrader.backtest.metrics import spy_buy_and_hold
    from daytrader.backtest.portfolio import simulate_portfolio
    from daytrader.backtest.report import render, summary_row
    from daytrader.backtest.runner import check_holdout, control_contexts, gapper_contexts, run_backtest, session_list
    from daytrader.config import ROOT, load_yaml
    from daytrader.scanner.premarket import parse_hhmm

    cfg, bt, strat_cfg, scfg = (
        load_config(),
        load_yaml("backtest.yaml"),
        load_yaml("strategies.yaml"),
        load_yaml("scanner.yaml"),
    )
    holdout = date.fromisoformat(bt["holdout_start"])
    d0 = date.fromisoformat(start or bt["in_sample_start"])
    d1 = date.fromisoformat(end) if end else holdout - timedelta(days=1)
    check_holdout(d0, d1, holdout, unseal_oos)
    variants = {s: strat_cfg[s] for s in strategies.split(",")}
    costs = CostModel.from_cfg(bt["costs"], bt["execution"])
    days = session_list(d0, d1)
    rows, runs, sens = [], {}, []
    outdir = ROOT / "data" / "backtests"
    outdir.mkdir(parents=True, exist_ok=True)
    with Store(db or cfg.db_path, read_only=True) as store:
        spy = spy_buy_and_hold(store, d0, d1)
        for uni in universes.split(","):
            with console.status(f"Contextos {uni}…"):
                ctx = (
                    gapper_contexts(store, d0, d1) if uni == "gappers"
                    else control_contexts(store, load_universe(), d0, d1, parse_hhmm(scfg["cutoff_et"]))
                )  # fmt: skip
            console.print(f"{uni}: {ctx.height:,} símbolo-días")
            with console.status(f"Backtest {uni}…"):
                trades = run_backtest(store, ctx, variants, bt, costs)
            for name in variants:
                t = trades.filter(pl.col("strategy") == name) if not trades.is_empty() else trades
                t, eq = simulate_portfolio(t, bt["account"], days)
                key = f"{name} · {uni}"
                runs[key] = (t, eq)
                rows.append(summary_row(name, uni, t, eq))
                if not t.is_empty():
                    t.write_parquet(outdir / f"{name}__{uni}__{d0}_{d1}.parquet")
                console.print(f"  {key}: {t.filter(pl.col('taken')).height if not t.is_empty() else 0} trades")
            # Sensibilidad a costos: mismas señales, distinto modelo de costos.
            for scen, over in (bt.get("cost_scenarios") or {}).items():
                c2 = CostModel.from_cfg({**bt["costs"], **over}, bt["execution"])
                with console.status(f"Escenario de costos {scen} · {uni}…"):
                    tr2 = run_backtest(store, ctx, variants, bt, c2)
                for name in variants:
                    t2 = tr2.filter(pl.col("strategy") == name) if not tr2.is_empty() else tr2
                    t2, eq2 = simulate_portfolio(t2, bt["account"], days)
                    sens.append({**summary_row(name, uni, t2, eq2), "escenario": scen})
            sens += [{**r, "escenario": "base"} for r in rows if r["universo"] == uni]
    md = render(
        f"Backtest {d0} → {d1}", (d0, d1), holdout,
        yaml.safe_dump({"strategies": variants, **bt}, sort_keys=False, allow_unicode=True), rows, runs, spy, sens,
    )  # fmt: skip
    (cfg.reports_path / out).write_text(md)
    console.print(f"Reporte: {cfg.reports_path / out}")


if __name__ == "__main__":
    app()
