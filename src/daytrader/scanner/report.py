"""Reporte Markdown de la watchlist diaria."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import polars as pl

from daytrader.scanner.scan import ScanResult

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _fmt_m(x: float | None) -> str:
    return "—" if x is None else f"{x / 1e6:,.1f}M"


def _et(ts) -> str:
    return ts.replace(tzinfo=UTC).astimezone(ET).strftime("%m-%d %H:%M")


def render_watchlist(res: ScanResult, names: dict[str, str], catalysts: pl.DataFrame, news: pl.DataFrame) -> str:
    cutoff_et = res.cutoff_utc.replace(tzinfo=UTC).astimezone(ET)
    wl = res.watchlist.join(catalysts, on="symbol", how="left") if not res.watchlist.is_empty() else res.watchlist
    lines = [
        f"# Watchlist {res.session_date} — scan a las {cutoff_et:%H:%M} ET\n",
        "Point-in-time: solo barras con `available_at <= cutoff`, barras diarias de sesiones anteriores "
        "(ajustadas por split), noticias publicadas antes del cutoff y acciones en circulación publicadas "
        "en EDGAR antes de la sesión.\n",
        "## Embudo\n",
        "| paso | símbolos |",
        "|---|---|",
        *[f"| {name} | {n:,} |" for name, n in res.funnel],
        "",
        "## Watchlist\n",
    ]
    if wl.is_empty():
        lines.append("_Ningún símbolo pasó todos los filtros._\n")
    else:
        lines += [
            "| # | símbolo | gap | pre-mkt | cierre ant. | vol PM | RVOL | $ PM | ATR | ATR% | ADV $ | acciones circ. | catalizador | noticias (rel.) |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in wl.iter_rows(named=True):
            rvol = "∞" if r["rvol"] == float("inf") else f"{r['rvol']:.1f}"
            lines.append(
                f"| {r['rank']} | **{r['symbol']}** | {r['gap']:+.1%} | {r['pm_last']:.2f} | {r['prev_close']:.2f} | "
                f"{_fmt_m(r['pm_volume'])} | {rvol} | {_fmt_m(r['pm_dollar_volume'])} | {r['atr14']:.2f} | "
                f"{r['atr_pct']:.1%} | {_fmt_m(r['adv_usd'])} | {_fmt_m(r.get('shares_out'))} | "
                f"{r.get('catalyst') or 'sin_catalizador'} | {r.get('n_news') or 0} ({r.get('n_relevant') or 0}) |"
            )
        lines.append("\n## Noticias por símbolo (relevantes, más recientes primero)\n")
        for r in wl.iter_rows(named=True):
            sym = r["symbol"]
            lines.append(f"### {sym} — {names.get(sym, '')}\n")
            sub = news.filter((pl.col("symbol") == sym) & pl.col("relevant")).head(4) if not news.is_empty() else news
            if sub.is_empty():
                lines.append("_Sin noticias relevantes entre el cierre anterior y el cutoff._\n")
                continue
            for n in sub.iter_rows(named=True):
                summ = (n["summary"] or "")[:220]
                lines.append(f"- `{_et(n['created_at'])} ET` **[{n['label']}]** {n['headline']}  \n  {summ}")
            lines.append("")
    lines.append(
        "\n---\nColumnas: gap = último precio pre-market / cierre anterior − 1 · RVOL = volumen pre-market hasta el "
        "cutoff / media de las 20 sesiones previas a la misma hora · $ PM = dólares negociados en pre-market · "
        "ADV $ = media 20 sesiones de cierre×volumen · ATR = media simple 14 sesiones del true range."
    )
    return "\n".join(lines) + "\n"
