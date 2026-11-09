"""CLI: `uv run daytrader --help`."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
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
        if wl_syms and not cutoff and not top:  # misma definición que el backfill → se guarda (la usa `mediodia`)
            from daytrader.scanner.history import WL_COLUMNS

            wl_out = res.watchlist.with_columns(
                pl.lit(d).alias("session_date"), pl.lit(res.cutoff_utc).alias("cutoff_utc")
            )
            wl_out = wl_out.join(cats.drop("top_headline"), on="symbol", how="left") if not cats.is_empty() else wl_out
            for c in WL_COLUMNS:
                if c not in wl_out.columns:
                    wl_out = wl_out.with_columns(pl.lit(None).alias(c))
            wl_out = wl_out.with_columns(pl.col("catalyst").fill_null("sin_noticias"))
            store.upsert("watchlists", wl_out.select(WL_COLUMNS).with_columns(pl.col("rank").cast(pl.Int32)))

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
def round3() -> None:
    """Ronda 3 pre-registrada: VWAP con órdenes límite + ajuste walk-forward → reports/ronda3_IS.md"""
    import glob

    from daytrader.backtest.metrics import daily_sharpe, deflated_sharpe
    from daytrader.backtest.runner import session_list
    from daytrader.config import ROOT, load_yaml
    from daytrader.research.regime import predicted_vol_prob
    from daytrader.research.report3 import render
    from daytrader.research.round2 import promotion, run_round2, trial_sharpes_round1
    from daytrader.research.round3 import run_round3

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
    spy_long = pl.read_parquet(ROOT / "data" / "spy_daily_2016.parquet").filter(pl.col("session_date") < holdout)
    with Store(cfg.db_path, read_only=True) as store:
        with console.status("Ronda 3: rejilla de órdenes límite…"):
            pvol = predicted_vol_prob(spy_long, session_list(d0, d1))
            res = run_round3(store, bt, strat, scfg, load_universe(), pvol, (key, secret), d0, d1)
        with console.status("Sharpe de los 13 intentos previos (para el DSR)…"):
            r1 = [f for f in sorted(glob.glob(str(ROOT / "data" / "backtests" / "*__20*-12-03_2025-12-31.parquet")))
                  if any(s in f for s in ("orb_5__", "orb_15__", "vwap_rev__"))]  # fmt: skip
            prev = trial_sharpes_round1(store, bt, r1)
            r2 = run_round2(store, bt, strat, scfg, load_universe(), spy_long, 0.695, None, d0, d1)
            prev += [daily_sharpe(r["_eq"]) for r in r2["rows"]]
    out_dir = ROOT / "data" / "backtests"
    for r in r2["rows"]:  # persistir trades de las rondas 2 y 3 para el dashboard
        if not r["_trades"].is_empty():
            r["_trades"].write_parquet(out_dir / f"r2_{r['config']}.parquet")
    if not res["wf"]["_trades"].is_empty():
        res["wf"]["_trades"].write_parquet(out_dir / "r3_walk_forward.parquet")
    sharpes = prev + [daily_sharpe(g["_eq"]) for g in res["grid"]]
    wf = res["wf"]
    wf["dsr"] = deflated_sharpe(wf["_eq"]["ret"].fill_null(0.0).to_numpy(), sharpes)
    wf["pasa"] = promotion(wf)
    (cfg.reports_path / "ronda3_IS.md").write_text(render(res, d0, d1))
    console.print(f"Walk-forward: trades={wf['trades']} R={wf['R_neto'] or 0:+.3f} PF={wf['profit_factor'] or 0:.2f} "
                  f"t={wf['t_stat'] or 0:.2f} DSR={wf['dsr']:.2f} pesimista={wf['R_pesimista'] or 0:+.3f} "
                  f"{'PASA' if wf['pasa'] else 'NO PASA'}")  # fmt: skip
    console.print(f"N intentos usados en el DSR: {len(sharpes)}")
    console.print(f"Reporte: {cfg.reports_path / 'ronda3_IS.md'}")


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


# ============================================================== FASE 5: operativa PAPER con confirmación
def _exec_ctx():
    from datetime import UTC, datetime

    from daytrader.config import load_yaml
    from daytrader.execution.broker import PaperBroker
    from daytrader.execution.journal import Journal
    from daytrader.execution.risk import RiskConfig, Session
    from daytrader.market_calendar import ET, sessions

    cfg = load_config()
    key, secret = Secrets().require_alpaca()
    rcfg = RiskConfig(**load_yaml("risk.yaml"))
    now = datetime.now(UTC).replace(tzinfo=None)
    today = datetime.now(UTC).astimezone(ET).date()
    s = sessions(today, today)
    ses = Session(s["open_utc"][0], s["close_utc"][0]) if s.height else None
    return cfg, rcfg, PaperBroker(key, secret), Journal(cfg.db_path.parent / "journal.duckdb"), ses, now, today


def _acct(broker, journal, rcfg, today):
    from daytrader.execution.simulated import from_broker

    return from_broker(broker, journal, rcfg, today)


def _show_ticket(t) -> None:
    from rich.table import Table

    tab = Table(title=f"TICKET {t.fingerprint()} · CUENTA PAPER", show_header=False)
    d = "COMPRA (largo)" if t.side == "long" else "VENTA EN CORTO"
    rows = [("Operación", f"{d} {t.qty} {t.symbol}"),
            ("Entrada", f"{'límite ' + format(t.limit_price, '.2f') if t.entry_type == 'limit' else 'a mercado'} (ref. {t.ref_price:.2f})"),
            ("Stop", f"{t.stop_price:.2f}  (riesgo {t.risk_per_share:.2f}/acción)"),
            ("Objetivo", f"{t.target_price:.2f}" if t.target_price else "— (salida por stop o cierre forzado)"),
            ("Riesgo total (1R)", f"${t.risk_usd:,.2f}"), ("Nocional", f"${t.notional:,.2f}")]  # fmt: skip
    if t.target_price:
        rows.append(
            ("Recompensa/riesgo", f"{abs(t.target_price - (t.limit_price or t.ref_price)) / t.risk_per_share:.2f} R")
        )
    for k, v in rows:
        tab.add_row(k, v)
    console.print(tab)


@app.command()
def trade(
    symbol: Annotated[str, typer.Argument(help="Ticker, p. ej. NVDA")],
    side: Annotated[str, typer.Argument(help="largo | corto")],
    stop: Annotated[float, typer.Option(help="Precio del stop (obligatorio)")],
    target: Annotated[float | None, typer.Option("--objetivo", help="Precio objetivo (opcional)")] = None,
    limit: Annotated[float | None, typer.Option("--limite", help="Entrada con orden límite a este precio")] = None,
    setup: Annotated[str, typer.Option(help="Setup (p. ej. ORB, reversión VWAP)")] = "",
    catalyst: Annotated[str, typer.Option("--catalizador")] = "",
    notes: Annotated[str, typer.Option("--notas")] = "",
    riesgo: Annotated[
        float | None,
        typer.Option("--riesgo", help="Riesgo en % del capital (solo puede BAJAR el de risk.yaml), p. ej. 0.1"),
    ] = None,
) -> None:
    """Propones una operación; el sistema calcula el tamaño (1%), aplica las reglas, pide y/n y la envía a PAPER."""
    from daytrader.execution.executor import ask_yes_no, run_ticket
    from daytrader.execution.risk import build_ticket

    side_n = {"largo": "long", "long": "long", "corto": "short", "short": "short"}.get(side.lower())
    if side_n is None:
        raise typer.BadParameter("side debe ser 'largo' o 'corto'")
    cfg, rcfg, broker, journal, ses, now, today = _exec_ctx()
    if riesgo is not None:
        from dataclasses import replace as _replace

        rcfg = _replace(rcfg, risk_per_trade=min(rcfg.risk_per_trade, max(riesgo, 0.0) / 100))  # nunca sube
        console.print(f"[dim]Riesgo de esta operación: {rcfg.risk_per_trade:.2%} del capital[/]")
    q = broker.quote(symbol.upper())
    ref = q["ask"] if side_n == "long" else q["bid"]
    ref = ref or q["mid"]
    console.print(f"[dim]Cotización IEX {symbol.upper()}: bid {q['bid']:.2f} · ask {q['ask']:.2f}[/]")
    acc = _acct(broker, journal, rcfg, today)
    t = build_ticket(symbol, side_n, ref, stop, target, acc, rcfg, now, "limit" if limit else "market", limit,
                     setup, catalyst, notes)  # fmt: skip

    def requote(sym):
        qq = broker.quote(sym)
        return (qq["ask"] if side_n == "long" else qq["bid"]) or qq["mid"]

    from datetime import UTC, datetime

    out = run_ticket(t, acc, ses, rcfg, broker, journal, now=lambda: datetime.now(UTC).replace(tzinfo=None),
                     ask=ask_yes_no, show=_show_ticket, requote=requote)  # fmt: skip
    color = {"enviado": "green", "rechazado": "red", "deriva": "yellow"}.get(out.status, "white")
    console.print(f"[{color}]Resultado: {out.status.upper()}[/] {'; '.join(out.reasons)} {out.order_id or ''}")
    journal.close()


@app.command()
def positions() -> None:
    """Posiciones abiertas y estado del día en la cuenta PAPER."""
    cfg, rcfg, broker, journal, ses, now, today = _exec_ctx()
    acc = _acct(broker, journal, rcfg, today)
    pnl = acc.equity - acc.last_equity
    kind = "efectivo" if rcfg.account_type == "cash" else "margen"
    sim = f" (simulado, cuenta de {kind})" if rcfg.simulated_capital else ""
    if rcfg.account_type == "margin" and acc.equity < rcfg.pdt_equity_min:
        console.print(
            f"Regla PDT: {acc.day_trades_5d} / {rcfg.pdt_max_day_trades} day trades en las últimas 5 sesiones"
        )
    console.print(f"Capital{sim} ${acc.equity:,.2f} · PnL del día {pnl:+,.2f} ({pnl / acc.last_equity:+.2%}) · "
                  f"trades hoy {acc.trades_today}/{rcfg.max_trades_per_day} · kill switch en {-rcfg.daily_loss_limit:.0%}")  # fmt: skip
    for p in broker.positions():
        console.print(
            f"  {p['symbol']:6} {p['side']:5} {p['qty']:>8.0f} @ {p['avg_entry']:.2f}  PnL {p['unrealized_pl']:+,.2f}"
        )
    journal.close()


@app.command()
def guard() -> None:
    """Vigila la sesión: con tu autorización (y/n), cierra todo a la hora de flatten_et (15:50 ET)."""
    import time as _t
    from datetime import UTC, datetime
    from datetime import time as dtime
    from datetime import timedelta as _td

    from daytrader.execution.executor import ask_yes_no
    from daytrader.execution.sync import sync_day
    from daytrader.market_calendar import et_to_utc_naive

    cfg, rcfg, broker, journal, ses, now, today = _exec_ctx()
    if ses is None:
        console.print("Hoy no hay sesión.")
        return
    h, m = (int(x) for x in rcfg.flatten_et.split(":"))
    flat_at = min(et_to_utc_naive(today, dtime(h, m)), ses.close_utc - _td(minutes=10))
    ans = ask_yes_no(f"¿Autorizas cerrar TODAS las posiciones paper a las {rcfg.flatten_et} ET? (y/n): ", 120)
    if ans != "y":
        console.print(
            "[yellow]Sin autorización: guard solo vigilará; deberás cerrar manualmente con 'daytrader flatten'.[/]"
        )
    journal.event("guard_autorizacion", str(ans))
    last_entry = ses.close_utc - _td(minutes=rcfg.no_entries_last_minutes)
    cancelled = False
    while datetime.now(UTC).replace(tzinfo=None) < flat_at:
        if not cancelled and datetime.now(UTC).replace(tzinfo=None) >= last_entry:
            n = broker.cancel_pending_entries()  # una orden límite no debe ejecutarse en los últimos 15 min
            journal.event("cancelar_entradas_pendientes", str(n))
            if n:
                console.print(
                    f"[yellow]Canceladas {n} órdenes de entrada pendientes (última entrada {rcfg.no_entries_last_minutes} min antes del cierre).[/]"
                )
            cancelled = True
        _t.sleep(15)
    if ans == "y":
        broker.flatten()
        journal.event("flatten", f"cierre automático autorizado a las {rcfg.flatten_et} ET")
        console.print("[green]Posiciones cerradas.[/]")
    _t.sleep(20)
    console.print(f"Trades sincronizados: {sync_day(broker, journal, today)}")
    journal.close()


@app.command()
def flatten() -> None:
    """Cierra todas las posiciones paper y cancela órdenes (pide confirmación y/n)."""
    from daytrader.execution.executor import ask_yes_no

    cfg, rcfg, broker, journal, ses, now, today = _exec_ctx()
    if ask_yes_no("¿Cerrar TODAS las posiciones paper ahora? (y/n): ", 60) == "y":
        broker.flatten()
        journal.event("flatten", "manual")
        console.print("[green]Hecho.[/]")
    journal.close()


@app.command()
def objetivo(
    symbol: Annotated[str, typer.Argument(help="Ticker con posición abierta")],
    precio: Annotated[float, typer.Argument(help="Precio objetivo (techo para largos, piso para cortos)")],
) -> None:
    """Pone un objetivo a una posición abierta: OCO (objetivo límite + el mismo stop). Pide confirmación y/n."""
    import uuid

    from rich.table import Table

    from daytrader.execution.executor import ask_yes_no

    cfg, rcfg, broker, journal, ses, now, today = _exec_ctx()
    sym = symbol.upper()
    pos = next((p for p in broker.positions() if p["symbol"] == sym), None)
    info = broker.exit_info(sym) if pos else None
    if pos is None or info is None:
        console.print(f"[red]{sym}: no hay posición abierta con stop del sistema.[/]")
        journal.close()
        raise typer.Exit(1)
    d = 1 if pos["qty"] > 0 else -1
    q = broker.quote(sym)
    px = q["bid"] if d == 1 else q["ask"]
    entry, stop, qty = pos["avg_entry"], info["stop"], abs(pos["qty"])
    if (precio - px) * d <= 0:
        console.print(f"[red]El objetivo debe estar {'por encima' if d == 1 else 'por debajo'} del precio actual "
                      f"({px:.2f}); si quieres salir ya, usa flatten.[/]")  # fmt: skip
        journal.close()
        raise typer.Exit(1)
    risk = abs(entry - stop)
    tab = Table(title=f"OBJETIVO {sym} · CUENTA PAPER", show_header=False)
    for k, v in [("Posición", f"{'LARGO' if d == 1 else 'CORTO'} {qty:g} @ {entry:.2f}"),
                 ("Precio actual", f"{px:.2f} ({'bid' if d == 1 else 'ask'} IEX)"),
                 ("Stop (se mantiene)", f"{stop:.2f}"),
                 ("Objetivo nuevo", f"{precio:.2f}  → {(precio - entry) * d / risk:+.2f} R desde la entrada"),
                 ("Ganancia si lo toca", f"${(precio - entry) * d * qty:+,.2f}"),
                 ("Orden", "OCO: límite en el objetivo + stop; al ejecutarse una se cancela la otra")]:  # fmt: skip
        tab.add_row(k, v)
    console.print(tab)
    if ask_yes_no("¿Poner este objetivo en la cuenta PAPER? (y/n) [60s]: ", 60) != "y":
        console.print("No se cambió nada.")
        journal.close()
        return
    fp = info["fingerprint"] or "manual"
    coid = f"dx-{fp}-{uuid.uuid4().hex[:8]}"
    try:
        o = broker.set_target(sym, precio, coid)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]No se pudo poner el objetivo: {e}[/]. Revisa en Alpaca que el stop siga activo.")
        journal.close()
        raise typer.Exit(1) from e
    console.print(f"[green]Objetivo puesto[/]: {sym} límite {precio:.2f} · stop {stop:.2f} · orden {o.id}")
    if info["fingerprint"]:
        journal.note(info["fingerprint"], f"objetivo {precio:.2f} añadido (OCO {coid})")
    journal.close()


@app.command()
def sync(day: Annotated[str | None, typer.Option("--date")] = None) -> None:
    """Trae las ejecuciones de Alpaca paper al journal (precio real, R, slippage real)."""
    from daytrader.execution.sync import sync_day

    cfg, rcfg, broker, journal, ses, now, today = _exec_ctx()
    n = sync_day(broker, journal, date.fromisoformat(day) if day else today)
    console.print(f"Trades sincronizados: {n}")
    journal.close()


@app.command()
def journal(days: Annotated[int, typer.Option(help="Últimos N días")] = 30) -> None:
    """Resumen del journal: tickets, trades cerrados y métricas en R."""
    from daytrader.config import load_config as _lc
    from daytrader.execution.journal import Journal

    j = Journal(_lc().db_path.parent / "journal.duckdb")
    console.print(
        j.query(
            f"SELECT status, count(*) AS n FROM tickets WHERE created_at >= now() - INTERVAL {int(days)} DAY GROUP BY 1"
        )
    )
    t = j.query(f"SELECT * FROM trades WHERE session_date >= current_date - {int(days)} ORDER BY entry_ts")
    if t.is_empty():
        console.print("Sin trades cerrados en el periodo.")
    else:
        r = t["r_multiple"]
        wins, losses = r.filter(r > 0), r.filter(r <= 0)
        pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
        console.print(f"Trades {t.height} · win rate {(r > 0).mean():.1%} · R medio {r.mean():+.2f} · PF {pf:.2f} · "
                      f"slippage medio de entrada {t['entry_slippage_r'].mean():+.3f} R")  # fmt: skip
        console.print(t.select("session_date", "symbol", "side", "entry_px", "exit_px", "exit_reason", "r_multiple"))
    j.close()


@app.command()
def note(
    fingerprint: Annotated[str, typer.Argument(help="Huella del ticket (ver 'daytrader journal')")],
    text: Annotated[str, typer.Argument()],
    error: Annotated[bool, typer.Option("--error", help="Marcar como error cometido")] = False,
) -> None:
    """Añade una nota (o un 'error cometido') a un trade del journal."""
    from daytrader.config import load_config as _lc
    from daytrader.execution.journal import Journal

    j = Journal(_lc().db_path.parent / "journal.duckdb")
    j.note(fingerprint, text, "error" if error else "nota")
    console.print("Nota guardada.")
    j.close()


@app.command()
def historia(
    paso: Annotated[str, typer.Option(help="copiar, splits, diarias, benchmarks, universo, minutos o todo")] = "todo",
    top: Annotated[int, typer.Option(help="Tamaño del universo point-in-time por año")] = 100,
) -> None:
    """Fase 7: historia 2015–2025 en data/history.duckdb (incremental; no toca market.duckdb salvo para leer)."""
    from datetime import date as _d

    from daytrader.config import load_yaml
    from daytrader.data.alpaca_client import fetch_splits, make_bar_fetcher, make_multi_fetcher
    from daytrader.research import history10y as H
    from daytrader.scanner.universe import eligible_symbols, ingest_universe_daily

    logging.basicConfig(level=logging.WARNING)
    cfg, scfg = load_config(), load_yaml("scanner.yaml")["universe"]
    key, secret = Secrets().require_alpaca()
    pasos = ["copiar", "splits", "diarias", "benchmarks", "universo", "minutos"] if paso == "todo" else [paso]
    hist_path = cfg.db_path.parent / "history.duckdb"
    say = lambda m: console.print(f"[{datetime.now():%H:%M:%S}] {m}")  # noqa: E731
    with Store(hist_path, memory_limit=cfg.duckdb_memory_limit) as hist:
        if "copiar" in pasos:
            say(f"copiado desde market.duckdb: {H.copy_from_market(hist, str(cfg.db_path))}")
        if "splits" in pasos:
            n = hist.upsert_splits(fetch_splits(key, secret, None, H.DAILY_START, H.DAILY_COPY_FROM))
            say(f"splits 2015–2024: {n:,}")
        if "diarias" in pasos:
            syms = eligible_symbols(hist, scfg["exchanges"], include_inactive=True)
            fm = make_multi_fetcher(key, secret, cfg.data.feed, cfg.data.adjustment, cfg.data.max_requests_per_minute)
            last = [0]

            def on_batch(done, total):
                if done - last[0] >= 2000 or done == total:
                    last[0] = done
                    say(f"diarias {done:,}/{total:,} símbolos")

            rows, err = ingest_universe_daily(hist, fm, syms, H.DAILY_START, H.DAILY_COPY_FROM, cfg.data.feed,
                                              on_batch=on_batch)  # fmt: skip
            say(f"diarias: {rows:,} filas nuevas, {err} lotes con error")
        if "benchmarks" in pasos:  # ETF (SPY/QQQ/IWM): no están entre las acciones comunes
            fm = make_multi_fetcher(key, secret, cfg.data.feed, cfg.data.adjustment, cfg.data.max_requests_per_minute)
            rows, err = ingest_universe_daily(hist, fm, H.BENCHMARKS, H.DAILY_START, H.DAILY_COPY_FROM, cfg.data.feed)
            say(f"diarias de {', '.join(H.BENCHMARKS)}: {rows:,} filas, {err} errores")
        if "universo" in pasos:
            u = H.build_universe(hist, top)
            say(f"universo point-in-time: {u.height} filas, {u['symbol'].n_unique()} símbolos distintos")
        if "minutos" in pasos:
            from daytrader.data.ingest import ingest_parallel

            # 6 hilos × 15 llamadas/min = 90 llamadas/min (cada una ~2 páginas) < límite de 200/min de Alpaca
            fetchers = [make_bar_fetcher(key, secret, cfg.data.feed, cfg.data.adjustment, 15, cfg.data.max_retries)
                        for _ in range(6)]  # fmt: skip
            for y in range(H.FIRST_YEAR, H.LAST_YEAR + 1):
                syms = H.universe_for(hist, y)
                n_done = [0]

                def on_chunk(sym, c0, _c1, n, n_done=n_done, y=y, syms=syms):
                    n_done[0] += 1
                    if n_done[0] % 120 == 0:
                        say(f"1m {y}: {n_done[0]}/{len(syms) * 12} bloques (último {sym} {c0:%Y-%m})")

                s = ingest_parallel(hist, fetchers, syms, _d(y, 1, 1), _d(y + 1, 1, 1), "1m", cfg.data.feed,
                                    on_chunk=on_chunk)  # fmt: skip
                say(
                    f"1m {y}: {s.chunks_done} nuevos, {s.chunks_skipped} en caché, {s.rows:,} filas, {len(s.errors)} errores"
                )


@app.command()
def mediodia(
    n: Annotated[int, typer.Option(help="Cuántos tickers de la watchlist re-evaluar")] = 15,
) -> None:
    """Re-evalúa la watchlist de hoy con datos de ahora y propone 3 candidatos (luego: `daytrader contexto X`)."""
    from datetime import UTC, datetime, timedelta
    from datetime import time as dtime

    from rich.table import Table

    from daytrader.config import load_yaml
    from daytrader.data.alpaca_client import make_multi_fetcher
    from daytrader.execution.broker import PaperBroker
    from daytrader.execution.context import compute
    from daytrader.execution.journal import Journal
    from daytrader.execution.midday import evaluate, top3
    from daytrader.execution.risk import RiskConfig
    from daytrader.execution.simulated import from_broker
    from daytrader.market_calendar import ET, et_to_utc_naive, sessions

    cfg = load_config()
    key, secret = Secrets().require_alpaca()
    now = datetime.now(UTC).replace(tzinfo=None)
    today = datetime.now(UTC).astimezone(ET).date()
    s = sessions(today - timedelta(days=40), today)
    if s.is_empty() or s["session_date"][-1] != today:
        console.print("Hoy no hay sesión.")
        return
    open_utc, close_utc = s["open_utc"][-1], s["close_utc"][-1]
    with Store(cfg.db_path, read_only=True) as store:
        wl = store.query("SELECT * FROM watchlists WHERE session_date = ? ORDER BY rank LIMIT ?", [today, n])
    if wl.is_empty():
        console.print("No hay watchlist de hoy: corre `uv run daytrader watchlist --date " + str(today) + "`.")
        return
    syms = wl["symbol"].to_list()
    fetch = make_multi_fetcher(key, secret)
    until = min(now - timedelta(minutes=16), close_utc)  # SIP: el plan gratuito no da los últimos 15 min
    bars = fetch([*syms, "SPY", "QQQ"], "1m", et_to_utc_naive(today, dtime(4)), until)
    daily = fetch([*syms, "SPY", "QQQ"], "1d", et_to_utc_naive(s["session_date"][0], dtime(0)),
                  et_to_utc_naive(today, dtime(0)) - timedelta(minutes=1)).with_columns(
        pl.col("ts_utc").dt.replace_time_zone("UTC").dt.convert_time_zone("America/New_York").dt.date().alias("session_date"))  # fmt: skip
    daily = daily.filter(pl.col("session_date") < today)
    broker = PaperBroker(key, secret)
    rcfg = RiskConfig(**load_yaml("risk.yaml"))
    acc = from_broker(broker, Journal(cfg.db_path.parent / "journal.duckdb"), rcfg, today)
    elapsed = max(0.0, (until - open_utc).total_seconds() / (close_utc - open_utc).total_seconds())

    def ctx_for(x):
        q = broker.quote(x)
        price = q["mid"] or q["ask"] or q["bid"]
        return compute(x, bars.filter(pl.col("symbol") == x), daily.filter(pl.col("symbol") == x), price, open_utc), q

    rel = {}
    for r in ("SPY", "QQQ"):
        rc, _ = ctx_for(r)
        if rc.prev_close and rc.vwap:
            rel[r] = ((rc.price / rc.prev_close - 1) * 100, rc.price > rc.vwap)
    cands = []
    for row in wl.iter_rows(named=True):
        x = row["symbol"]
        try:
            c, q = ctx_for(x)
        except Exception as exc:  # sin cotización: se omite
            console.print(f"[dim]{x}: sin cotización ({exc})[/]")
            continue
        c.rel = rel
        b = bars.filter((pl.col("symbol") == x) & (pl.col("ts_utc") >= open_utc))
        dv = daily.filter(pl.col("symbol") == x).sort("session_date").tail(20)["volume"]
        cands.append(evaluate(c, row["gap"], row["catalyst"], float(dv.mean()) if dv.len() else None,
                              float(b["volume"].sum()), elapsed, q["bid"], q["ask"], acc.equity,
                              rcfg.risk_per_trade, rcfg.account_type != "cash"))  # fmt: skip
    best = {c.symbol for c in top3(cands)}
    tab = Table(
        title=f"Watchlist re-evaluada · {datetime.now(UTC).astimezone(ET):%H:%M} ET · capital ${acc.equity:,.0f}"
    )
    for h in ("", "ticker", "gap 09:25", "ahora vs ayer", "vol. relativo", "rango/ATR", "spread", "▲/▼", "precio",
              "acciones (1R)", "catalizador", "puntos", "avisos"):  # fmt: skip
        tab.add_column(h)
    pct = lambda v, d=1: "—" if v is None else f"{v:+.{d}%}"  # noqa: E731
    for c in sorted(cands, key=lambda c: c.score, reverse=True):
        tab.add_row("★" if c.symbol in best else "", c.symbol, pct(c.gap_am), pct(c.change),
                    "—" if c.rvol_rth is None else f"{c.rvol_rth:.1f}×", "—" if c.range_atr is None else f"{c.range_atr:.2f}",
                    "—" if c.spread_pct is None else f"{c.spread_pct:.2%}", f"{c.up}/{c.down} {c.lean}", f"{c.price:,.2f}",
                    str(c.shares_1r), c.catalyst or "", f"{c.score:.2f}", "; ".join(c.notes))  # fmt: skip
    console.print(tab)
    console.print(f"[dim]Barras SIP hasta {until.replace(tzinfo=UTC).astimezone(ET):%H:%M} ET. Volumen relativo aprox. "
                  "(el volumen diario incluye pre/post). Ranking descriptivo, no una señal probada.[/]")  # fmt: skip
    if rcfg.account_type == "margin" and acc.equity < rcfg.pdt_equity_min:
        console.print(
            f"Regla PDT: {acc.day_trades_5d} / {rcfg.pdt_max_day_trades} day trades usados en 5 sesiones"
            + ("." if rcfg.enforce_pdt else " (práctica: límite desactivado).")
        )
    console.print("Siguiente paso: [bold]uv run daytrader contexto TICKER[/] para cada candidato elegido.")


@app.command()
def round4() -> None:
    """Ronda 4 pre-registrada (fase 7) sobre data/history.duckdb → reports/ronda4.md"""
    import glob

    from daytrader.config import ROOT, load_yaml
    from daytrader.research.report4 import render
    from daytrader.research.round4 import prior_sharpes, run_round4
    from daytrader.scanner.premarket import parse_hhmm

    logging.basicConfig(level=logging.WARNING)
    cfg, bt, strat, scfg = (
        load_config(),
        load_yaml("backtest.yaml"),
        load_yaml("strategies.yaml"),
        load_yaml("scanner.yaml"),
    )
    say = lambda m: console.print(f"[{datetime.now():%H:%M:%S}] {m}")  # noqa: E731
    prior = prior_sharpes(sorted(glob.glob(str(ROOT / "data" / "backtests" / "*__*_2025-12-31.parquet")))
                          + sorted(glob.glob(str(ROOT / "data" / "backtests" / "r[23]_*.parquet"))))  # fmt: skip
    say(f"Sharpe de {len(prior)} intentos previos guardados (N total = 30)")
    with Store(cfg.db_path.parent / "history.duckdb", read_only=True) as hist:
        res = run_round4(hist, bt, strat, parse_hhmm(scfg["cutoff_et"]), prior, on_step=say)
    out_dir = ROOT / "data" / "backtests"
    for n in res["trials"]:
        t = res["rows"][n]["validacion"]["_trades"]
        if not t.is_empty():
            t.write_parquet(out_dir / f"r4_{n}.parquet")
    (cfg.reports_path / "ronda4.md").write_text(render(res))
    for n in res["trials"]:
        v = res["rows"][n]["validacion"]
        say(
            f"{n}: trades={v['trades']} R={v['R_neto'] or 0:+.3f} PF={v['profit_factor'] or 0:.2f} "
            f"DSR={v.get('dsr') or 0:.2f} {'PASA' if v['pasa'] else 'no pasa'}"
        )
    say(f"Reporte: {cfg.reports_path / 'ronda4.md'}")


@app.command()
def fase8() -> None:
    """Fase 8 pre-registrada: swing trading con barras diarias (data/history.duckdb) → reports/fase8_swing.md"""
    import glob

    from daytrader.config import ROOT
    from daytrader.research.fase8 import N_TRIALS, render, run_fase8, summary_lines
    from daytrader.research.round4 import prior_sharpes

    logging.basicConfig(level=logging.WARNING)
    cfg = load_config()
    say = lambda m: console.print(f"[{datetime.now():%H:%M:%S}] {m}")  # noqa: E731
    bt_dir = ROOT / "data" / "backtests"
    prior = prior_sharpes(sorted(glob.glob(str(bt_dir / "*__*_2025-12-31.parquet")))
                          + sorted(glob.glob(str(bt_dir / "r[234]_*.parquet"))))  # fmt: skip
    say(f"Sharpe de {len(prior)} intentos previos guardados (N total = {N_TRIALS})")
    with Store(cfg.db_path.parent / "history.duckdb", read_only=True) as hist:
        res = run_fase8(hist, prior, on_step=say)
    for n in ("S1", "S2", "S3", "S4"):
        t = res["runs"][n]["trades"]
        if not t.is_empty():
            t.write_parquet(bt_dir / f"f8_{n}_trades.parquet")
        res["runs"][n]["eq"].write_parquet(bt_dir / f"f8_{n}_equity.parquet")
    (cfg.reports_path / "fase8_swing.md").write_text(render(res))
    for line in summary_lines(res):
        say(line)
    say(f"Reporte: {cfg.reports_path / 'fase8_swing.md'}")


@app.command()
def momentum(
    top: Annotated[int, typer.Option(help="Cuántas acciones listar")] = 10,
) -> None:
    """Lista de práctica S1 (momentum 12−1, fase 8) con datos de hoy. SIN edge probado: solo observación/práctica."""
    from datetime import UTC, datetime, timedelta

    from rich.table import Table

    from daytrader.config import load_yaml
    from daytrader.data.alpaca_client import make_multi_fetcher
    from daytrader.market_calendar import ET
    from daytrader.research.fase8 import universe
    from daytrader.strategies import swing

    cfg = load_config()
    rcfg = load_yaml("risk.yaml")
    key, secret = Secrets().require_alpaca()
    today = datetime.now(UTC).astimezone(ET).date()
    with Store(cfg.db_path.parent / "history.duckdb", read_only=True) as hist:
        uni = universe(hist, years=range(today.year, today.year + 1))  # top 500 por $ volumen del año anterior
    syms = sorted(set(uni["symbol"].to_list()) | {"SPY"})
    fetch = make_multi_fetcher(key, secret, adjustment="split")
    start = datetime(today.year - 1, today.month, 1) - timedelta(days=330)  # 13+ meses y SMA200 de SPY
    end = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=16)
    console.print(f"Descargando diarias de {len(syms)} símbolos…")
    raw = pl.concat([fetch(syms[i : i + 100], "1d", start, end) for i in range(0, len(syms), 100)])
    daily = raw.with_columns(
        pl.col("ts_utc").dt.replace_time_zone("UTC").dt.convert_time_zone("America/New_York").dt.date()
        .alias("session_date")
    ).select("symbol", "session_date", "open", "high", "low", "close", "volume")  # fmt: skip
    ind = swing.indicators(daily)
    spy = ind.filter(pl.col("symbol") == "SPY")
    sessions = spy["session_date"].to_list()
    p = {"lookback_months": 12, "skip_months": 1, "top": top}
    tg = swing.s1_momentum(ind, uni, spy, sessions, p)
    if not tg:
        console.print("Sin datos suficientes.")
        return
    d = max(tg)
    srow = spy.filter(pl.col("session_date") == d).row(0, named=True)
    filt = srow["close"] > (srow["sma200"] or float("inf"))
    me = swing.month_ends(sessions)
    i = me.index(d)
    a, b = me[i - 1], me[i - 12]
    ca = ind.filter(pl.col("session_date") == a).select("symbol", pl.col("close").alias("ca"))
    cb = ind.filter(pl.col("session_date") == b).select("symbol", pl.col("close").alias("cb"))
    now = ind.filter(pl.col("session_date") == d).select("symbol", "close", "atr14")
    rank = (
        uni.select("symbol").join(now, on="symbol").join(ca, on="symbol").join(cb, on="symbol")
        .with_columns((pl.col("ca") / pl.col("cb") - 1).alias("mom"))
        .sort(["mom", "symbol"], descending=[True, False]).head(top)
    )  # fmt: skip
    cap = float(rcfg.get("simulated_capital", 100_000))
    tab = Table(title=f"S1 momentum 12−1 · ranking al {d} (retorno {b} → {a})")
    for col in ("#", "Símbolo", "Momentum", "Precio", "ATR %", f"Acciones (${cap / top:,.0f} c/u, fracc.)"):
        tab.add_column(col, justify="right")
    for k, r in enumerate(rank.iter_rows(named=True), 1):
        tab.add_row(str(k), r["symbol"], f"{r['mom']:+.0%}", f"{r['close']:,.2f}", f"{r['atr14'] / r['close']:.1%}",
                    f"{cap / top / r['close']:.2f}")  # fmt: skip
    console.print(tab)
    console.print(
        f"Filtro de mercado: SPY {srow['close']:.2f} vs SMA200 {srow['sma200'] or 0:.2f} → "
        + ("[green]encima: la regla compraría la lista[/]" if filt else "[red]debajo: la regla estaría en EFECTIVO[/]")
    )
    console.print(
        "[dim]Regla S1: se rebalancea el último día hábil de cada mes, entrada en la apertura siguiente, 1 mes. "
        "Fase 8: exceso vs SPY +1 %/año en validación, no significativo, drawdown −40 %. SIN edge probado: "
        "úsala como lista de observación y práctica, no como recomendación. Las posiciones swing no pasan por "
        "`daytrader trade` (el guard cierra todo a las 15:50).[/]"
    )


@app.command(name="is-session")
def is_session_cmd() -> None:
    """Sale con código 0 si hoy (hora de Nueva York) hay sesión NYSE; 1 si no (festivo o fin de semana)."""
    from datetime import UTC, datetime

    from daytrader.market_calendar import ET, is_session

    today = datetime.now(UTC).astimezone(ET).date()
    ok = is_session(today)
    console.print(f"{today}: {'hay sesión' if ok else 'sin sesión'}")
    raise typer.Exit(0 if ok else 1)


@app.command()
def dashboard(port: Annotated[int, typer.Option(help="Puerto local")] = 8501) -> None:
    """Abre el dashboard (Streamlit) en el navegador: operativa paper e investigación."""
    import subprocess
    import sys

    from daytrader.config import ROOT

    app_path = ROOT / "src" / "daytrader" / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port),
                    "--browser.gatherUsageStats", "false"], check=False)  # fmt: skip


@app.command()
def contexto(
    symbol: Annotated[str, typer.Argument(help="Ticker, p. ej. APP")],
    vs: Annotated[str, typer.Option(help="Referencias de mercado")] = "SPY,QQQ",
) -> None:
    """Contexto en vivo para decidir largo / corto / no operar: VWAP, rangos, tendencia, mercado y stops candidatos."""
    from datetime import UTC, datetime, timedelta
    from datetime import time as dtime

    from rich.table import Table

    from daytrader.data.alpaca_client import make_multi_fetcher
    from daytrader.execution.broker import PaperBroker
    from daytrader.execution.context import candidate_stops, compute, readings
    from daytrader.market_calendar import ET, et_to_utc_naive, sessions

    key, secret = Secrets().require_alpaca()
    sym = symbol.upper()
    refs = [r.strip().upper() for r in vs.split(",") if r.strip() and r.strip().upper() != sym]
    now = datetime.now(UTC).replace(tzinfo=None)
    today = datetime.now(UTC).astimezone(ET).date()
    s = sessions(today - timedelta(days=40), today)
    if s.is_empty() or s["session_date"][-1] != today:
        console.print("Hoy no hay sesión.")
        return
    open_utc = s["open_utc"][-1]
    fetch = make_multi_fetcher(key, secret)
    until = now - timedelta(minutes=16)  # SIP: el plan gratuito no da los últimos 15 min
    allsyms = [sym, *refs]
    bars = fetch(allsyms, "1m", et_to_utc_naive(today, dtime(4)), until)
    daily = fetch(allsyms, "1d", et_to_utc_naive(s["session_date"][0], dtime(0)),
                  et_to_utc_naive(today, dtime(0)) - timedelta(minutes=1)).with_columns(
        pl.col("ts_utc").dt.replace_time_zone("UTC").dt.convert_time_zone("America/New_York").dt.date().alias("session_date"))  # fmt: skip
    broker = PaperBroker(key, secret)

    def ctx_for(x):
        q = broker.quote(x)
        price = q["mid"] or q["ask"] or q["bid"]
        return compute(x, bars.filter(pl.col("symbol") == x), daily.filter(pl.col("session_date") < today)
                       .filter(pl.col("symbol") == x), price, open_utc)  # fmt: skip

    c = ctx_for(sym)
    for r in refs:
        rc = ctx_for(r)
        if rc.prev_close and rc.vwap:
            c.rel[r] = ((rc.price / rc.prev_close - 1) * 100, rc.price > rc.vwap)
    tab = Table(title=f"Contexto {sym} · {datetime.now(UTC).astimezone(ET):%H:%M} ET", show_header=False)
    f = lambda v: "—" if v is None else f"{v:,.2f}"  # noqa: E731
    for k, v in [("Precio actual (IEX)", f(c.price)), ("Cierre de ayer", f(c.prev_close)), ("VWAP del día", f(c.vwap)),
                 ("Pre-market máx / mín", f"{f(c.pm_high)} / {f(c.pm_low)}"),
                 ("Rango apertura 5 min", f"{f(c.or_low)} – {f(c.or_high)}"), ("Máx / mín del día", f"{f(c.day_high)} / {f(c.day_low)}"),
                 ("ATR 14 días", f"{f(c.atr14)} ({c.atr14 / c.price:.1%} del precio)" if c.atr14 else "—")]:  # fmt: skip
        tab.add_row(k, v)
    console.print(tab)
    if c.bars_until:
        console.print(
            f"[dim]Barras SIP hasta {c.bars_until.replace(tzinfo=UTC).astimezone(ET):%H:%M} ET (retraso de 15 min del plan gratuito)[/]"
        )
    rd = readings(c)
    console.print("\n[bold]Lecturas[/] (descriptivas, no señales probadas):")
    for text, lean in rd:
        mark = {1: "[green]▲ largo[/]", -1: "[red]▼ corto[/]", 0: "[dim]· neutral[/]"}[lean]
        console.print(f"  {mark}  {text}")
    up, dn = sum(1 for _, x in rd if x > 0), sum(1 for _, x in rd if x < 0)
    verdict = (
        "a favor del LARGO" if up - dn >= 2 else "a favor del CORTO" if dn - up >= 2 else "MIXTO: considera no operar"
    )
    console.print(f"\nBalance: {up} ▲ / {dn} ▼ → [bold]{verdict}[/]")
    for side, name in ((1, "largo"), (-1, "corto")):
        st_ = candidate_stops(c, side)
        if st_:
            txt = " · ".join(f"{n} {v:.2f} ({abs(v / c.price - 1):.2%})" for n, v in st_)
            console.print(f"  Stops candidatos si vas {name}: {txt}")
    from daytrader.config import load_yaml
    from daytrader.execution.context import live_patterns

    rth = bars.filter(
        (pl.col("symbol") == sym) & (pl.col("ts_utc") >= open_utc) & (pl.col("ts_utc") < s["close_utc"][-1])
    )
    pats = live_patterns(
        sym, rth, today, c.prev_close, c.atr14, open_utc, s["close_utc"][-1], load_yaml("strategies.yaml")
    )
    console.print("\n[bold]Patrones de hoy[/] (ronda 4 · práctica: SIN edge probado en 2017–2025):")
    if not pats:
        console.print("  [dim]Ninguna bandera ni doble suelo/techo confirmado hoy (10:00–15:00 ET, velas de 5 min).[/]")
    for p in pats:
        side = "[green]▲ largo[/]" if p["side"] == 1 else "[red]▼ corto[/]"
        hhmm = lambda t: t.replace(tzinfo=UTC).astimezone(ET).strftime("%H:%M")  # noqa: E731
        vigente = "vigente" if now < p["valid_until"] else "caducada"
        console.print(
            f"  {side} {p['pattern']} confirmado {hhmm(p['decided_at'])} ET · entrada stop {p['entry']:.2f} · "
            f"stop {p['stop']:.2f} · objetivo {p['target']:.2f} ({p['target_r']:.0f} R) · orden válida hasta "
            f"{hhmm(p['valid_until'])} ({vigente}) · salida por tiempo {p['max_hold_min']} min"
        )
    console.print(
        "[dim]Recuerda: el stop va donde tu idea queda invalidada; si no lo ves claro, no operar también es una decisión.[/]"
    )


if __name__ == "__main__":
    app()
