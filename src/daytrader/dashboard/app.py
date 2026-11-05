"""Dashboard (fase 6): uv run streamlit run src/daytrader/dashboard/app.py

Pestañas: operativa paper (journal), investigación (backtests de las 3 rondas) y ayuda.
Todos los números salen de daytrader.dashboard.data; aquí solo se dibuja.
"""

from __future__ import annotations

import plotly.graph_objects as go
import polars as pl
import streamlit as st

from daytrader.config import ROOT
from daytrader.dashboard import data as D

st.set_page_config(page_title="Day trading asistido · paper", page_icon="📈", layout="wide")

# Paleta validada (guía dataviz): categórica slots 1–2; divergente azul↔rojo; neutros.
try:
    DARK = st.context.theme.type == "dark"
except Exception:  # versiones sin st.context.theme
    DARK = False
C = {
    "s1": "#3987e5" if DARK else "#2a78d6",  # estrategia / ganancias
    "s2": "#d95926" if DARK else "#eb6834",  # SPY
    "neg": "#e66767" if DARK else "#e34948",  # pérdidas (brazo rojo del divergente)
    "grid": "#383835" if DARK else "#e7e6e1",
    "muted": "#898781",
    "neg_fill": "rgba(230,103,103,0.22)" if DARK else "rgba(227,73,72,0.16)",
}


def base_layout(fig: go.Figure, title: str, y_title: str = "", height: int = 320, pct: bool = False) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0, "font": {"size": 15}}, height=height, margin={"l": 10, "r": 10, "t": 40, "b": 10},
        hovermode="x unified", legend={"orientation": "h", "y": 1.12, "x": 1, "xanchor": "right"},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )  # fmt: skip
    fig.update_xaxes(showgrid=False, linecolor=C["grid"])
    fig.update_yaxes(gridcolor=C["grid"], zeroline=False, title=y_title, tickformat=".0%" if pct else None)
    return fig


def equity_fig(eq: pl.DataFrame, spy: pl.DataFrame | None, name: str) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=eq["session_date"], y=eq["equity"], name=name, line={"color": C["s1"], "width": 2},
                    hovertemplate="%{y:$,.0f}")  # fmt: skip
    if spy is not None and not spy.is_empty():
        fig.add_scatter(x=spy["session_date"], y=spy["equity"], name="SPY comprar y mantener",
                        line={"color": C["s2"], "width": 2}, hovertemplate="%{y:$,.0f}")  # fmt: skip
    fig.add_hline(y=100_000, line={"color": C["muted"], "width": 1, "dash": "dot"})
    return base_layout(fig, "Curva de capital", "Capital ($)")


def drawdown_fig(eq: pl.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=eq["session_date"], y=eq["drawdown"], fill="tozeroy", fillcolor=C["neg_fill"], name="Drawdown",
                    line={"color": C["neg"], "width": 2}, hovertemplate="%{y:.1%}", showlegend=False)  # fmt: skip
    return base_layout(fig, "Drawdown desde el máximo", pct=True, height=240)


def r_hist_fig(t: pl.DataFrame) -> go.Figure:
    r = t["r"].clip(-4, 8)
    fig = go.Figure()
    fig.add_histogram(x=r.filter(r > 0), name="Ganadoras", marker={"color": C["s1"], "line": {"width": 1, "color": "rgba(0,0,0,0)"}},
                      xbins={"size": 0.25}, hovertemplate="%{x} R: %{y} trades<extra></extra>")  # fmt: skip
    fig.add_histogram(x=r.filter(r <= 0), name="Perdedoras", marker={"color": C["neg"]}, xbins={"size": 0.25},
                      hovertemplate="%{x} R: %{y} trades<extra></extra>")  # fmt: skip
    fig.add_vline(x=float(t["r"].mean()), line={"color": C["muted"], "dash": "dash"},
                  annotation_text=f"media {t['r'].mean():+.2f} R", annotation_position="top")  # fmt: skip
    fig.update_layout(barmode="overlay", bargap=0.08, hovermode="closest")
    return base_layout(fig, "Distribución de R por trade (recortada a [−4, 8])", "Trades")


def bars_fig(df: pl.DataFrame, x: str, title: str) -> go.Figure:
    colors = [C["s1"] if v > 0 else C["neg"] for v in df["R_medio"].to_list()]
    fig = go.Figure(go.Bar(
        x=df[x], y=df["R_medio"], marker={"color": colors, "cornerradius": 4},
        customdata=df.select("trades", "win_rate").to_numpy(),
        hovertemplate="%{x}<br>R medio %{y:+.2f}<br>%{customdata[0]} trades · win %{customdata[1]:.0%}<extra></extra>",
    ))  # fmt: skip
    fig.add_hline(y=0, line={"color": C["muted"], "width": 1})
    fig.update_layout(hovermode="closest")
    return base_layout(fig, title, "R medio", height=280)


def kpi_row(k: dict, t: pl.DataFrame) -> None:
    lo, hi = D.r_ci(t)
    c = st.columns(6)
    c[0].metric("Trades", f"{k['trades']}")
    c[1].metric("Win rate", f"{k['win_rate']:.1%}")
    c[2].metric("R medio (expectancy)", f"{k['avg_r']:+.3f}", help=f"IC 95%: {lo:+.3f} a {hi:+.3f}")
    c[3].metric("Profit factor", f"{k['profit_factor']:.2f}")
    c[4].metric("Retorno", f"{k['retorno']:+.1%}", help=f"PnL ${k['pnl']:,.0f}")
    c[5].metric("Max drawdown", f"{k['max_dd']:.1%}")
    if k["trades"] < 100:
        st.info(
            f"Solo {k['trades']} trades: con menos de ~100, el R medio no es concluyente (IC 95% {lo:+.2f} a {hi:+.2f})."
        )
    elif lo > 0:
        st.success("El IC 95% del R medio está por encima de cero.")
    elif hi < 0:
        st.error("El IC 95% del R medio está por debajo de cero: hay evidencia de expectancy negativa.")


def breakdowns(t: pl.DataFrame, extra: str | None = None) -> None:
    t = D.with_entry_hour(t)
    a, b = st.columns(2)
    h = D.by(t, "hora_et")
    if not h.is_empty():
        a.plotly_chart(bars_fig(h, "hora_et", "R medio por hora de entrada (ET)"), width="stretch")
    tk = D.by(t, "symbol", min_trades=3)
    if not tk.is_empty():
        tk = pl.concat([tk.sort("R_total").head(8), tk.sort("R_total").tail(8)]).unique(maintain_order=True)
        b.plotly_chart(bars_fig(tk.sort("R_medio"), "symbol", "Tickers: 8 peores y 8 mejores (≥3 trades)"),
                       width="stretch")  # fmt: skip
    if extra and extra in t.columns:
        e = D.by(t, extra)
        if not e.is_empty() and e.height > 1:
            st.plotly_chart(bars_fig(e, extra, f"R medio por {extra}"), width="stretch")
    with st.expander("Ver tablas (vista accesible)"):
        st.dataframe(D.by(t, "hora_et"), width="stretch")
        st.dataframe(D.by(t, "symbol").sort("trades", descending=True), width="stretch")


# ================================================================== UI
st.title("Day trading asistido")
st.caption("Cuenta **PAPER** · ningún dato de esta página es dinero real · los números se calculan en Python")
tab0, tabw, tab1, tab2, tab3 = st.tabs(
    [":material/bolt: Hoy, en vivo", ":material/list: Watchlist", ":material/person: Mi operativa (paper)",
     ":material/science: Investigación (backtests)", ":material/help: Cómo leer esto"]
)  # fmt: skip


@st.cache_resource
def _broker():
    from daytrader.config import Secrets
    from daytrader.execution.broker import PaperBroker

    k, s = Secrets().require_alpaca()
    return PaperBroker(k, s)


@st.fragment(run_every="20s")
def live_view() -> None:
    from datetime import UTC, datetime, time, timedelta

    from daytrader.market_calendar import ET, et_to_utc_naive, sessions

    try:
        b = _broker()
        acc = b.client.get_account()
        positions = b.positions()
    except Exception as exc:  # sin red o sin keys: la página sigue funcionando
        st.warning(f"No se pudo leer la cuenta paper: {exc}")
        return
    _, tickets, _ = D.load_journal(ROOT / "data" / "journal.duckdb")
    now = datetime.now(UTC).replace(tzinfo=None)
    today = datetime.now(UTC).astimezone(ET).date()
    ses = sessions(today, today)
    eq, last = float(acc.equity), float(acc.last_equity)
    pnl = eq - last
    sent_today = 0 if tickets.is_empty() else tickets.filter(
        (pl.col("session_date") == today) & (pl.col("status") == "enviado")).height  # fmt: skip
    with st.container(horizontal=True):
        st.metric("Capital paper", f"${eq:,.2f}", f"{pnl:+,.2f} hoy", border=True)
        st.metric("Hasta el kill switch (−3%)", f"${pnl + 0.03 * last:,.0f}", border=True,
                  help="Pérdida adicional del día antes de bloquear nuevas entradas")  # fmt: skip
        st.metric("Trades hoy", f"{sent_today} / 5", border=True)
        st.metric("Posiciones abiertas", f"{len(positions)} / 3", border=True)
        if ses.height:
            flat = min(et_to_utc_naive(today, time(15, 50)), ses["close_utc"][0] - timedelta(minutes=10))
            mins = D.minutes_to(flat, now)
            st.metric("Cierre forzado", "15:50 ET" if mins > 0 else "pasado",
                      f"en {mins:.0f} min" if mins > 0 else None, delta_color="off", border=True)  # fmt: skip
    lp = D.live_positions(positions, tickets)
    if lp.is_empty():
        st.info("Sin posiciones abiertas.", icon=":material/check_circle:")
    else:
        st.dataframe(
            lp, hide_index=True,
            column_config={
                "entrada": st.column_config.NumberColumn(format="%.2f"), "precio": st.column_config.NumberColumn(format="%.2f"),
                "PnL $": st.column_config.NumberColumn(format="%+.2f"), "R actual": st.column_config.NumberColumn(format="%+.2f R"),
                "stop": st.column_config.NumberColumn(format="%.2f"), "objetivo": st.column_config.NumberColumn(format="%.2f"),
                "a stop (R)": st.column_config.NumberColumn(format="%.2f R", help="Cuánto falta para tocar el stop, en R"),
                "progreso": st.column_config.ProgressColumn("stop → objetivo", min_value=0.0, max_value=1.0,
                                                           help="0 = en el stop, 100% = en el objetivo"),
            },
        )  # fmt: skip
    st.caption(f"Se actualiza cada 20 s · {datetime.now(UTC).astimezone(ET):%H:%M:%S} ET · precios de Alpaca paper")


with tab0:
    live_view()

with tabw:
    files = sorted((ROOT / "reports").glob("watchlist_*.md"), reverse=True)
    if not files:
        st.info("Aún no hay watchlists. Se generan con `uv run daytrader watchlist --date AAAA-MM-DD` "
                "o automáticamente a las 09:40 ET.")  # fmt: skip
    else:
        pick = st.selectbox("Día", [f.stem.replace("watchlist_", "") for f in files])
        st.markdown((ROOT / "reports" / f"watchlist_{pick}.md").read_text())
        st.caption("Para el contexto en vivo de un ticker: `uv run daytrader contexto TICKER`")

with tab1:
    trades, tickets, notes = D.load_journal(ROOT / "data" / "journal.duckdb")
    t = D.journal_as_trades(trades)
    if t.is_empty():
        st.info("Aún no hay trades cerrados en el journal. Opera en paper con `uv run daytrader trade …`, "
                "luego `uv run daytrader sync`, y vuelve aquí.")  # fmt: skip
    else:
        kpi_row(D.kpis(t), t)
        st.plotly_chart(equity_fig(D.equity_curve(t), None, "Mi cuenta paper"), width="stretch")
        st.plotly_chart(drawdown_fig(D.equity_curve(t)), width="stretch")
        st.plotly_chart(r_hist_fig(t), width="stretch")
        breakdowns(t, extra="setup")
        s = t["entry_slippage_r"].drop_nulls()
        if s.len():
            st.subheader("Slippage real de entrada")
            st.write(f"Mediana **{s.median():+.3f} R** por entrada (el backtester modela ~0,01–0,04 R por lado en VWAP). "
                     "Si el real es mayor, el modelo de costos es optimista.")  # fmt: skip
    if not tickets.is_empty():
        with st.expander("Tickets (todas las propuestas, incluidas rechazadas)"):
            st.dataframe(tickets.select("created_at", "symbol", "side", "qty", "ref_price", "stop_price",
                                        "target_price", "status", "reasons"), width="stretch")  # fmt: skip
    if not notes.is_empty():
        with st.expander("Notas y errores cometidos"):
            st.dataframe(notes, width="stretch")

with tab2:
    runs = D.list_backtests(ROOT / "data" / "backtests")
    if not runs:
        st.warning("No hay backtests guardados en data/backtests.")
    else:
        choice = st.selectbox("Configuración", list(runs), index=0)
        t = D.load_backtest(runs[choice])
        st.caption(
            "Periodo de desarrollo 2024-12-03 → 2025-12-31 · costos calibrados con NBBO · 2026 sellado (no evaluado)"
        )
        k = D.kpis(t)
        kpi_row(k, t)
        eq = D.equity_curve(t)
        spy_path = ROOT / "data" / "spy_daily_2016.parquet"
        spy = None
        if spy_path.exists() and not eq.is_empty():
            spy = D.spy_curve(pl.read_parquet(spy_path).select("session_date", "close"),
                              eq["session_date"].min(), eq["session_date"].max())  # fmt: skip
        st.plotly_chart(equity_fig(eq, spy, choice), width="stretch")
        st.plotly_chart(drawdown_fig(eq), width="stretch")
        st.plotly_chart(r_hist_fig(t), width="stretch")
        breakdowns(t)
        st.subheader("Resumen de las 3 rondas")
        rows = []
        for name, path in runs.items():
            tt = D.load_backtest(path)
            kk = D.kpis(tt)
            lo, hi = D.r_ci(tt)
            rows.append({"configuración": name, "trades": kk["trades"], "R medio": kk.get("avg_r"),
                         "IC95 bajo": lo, "IC95 alto": hi, "PF": kk.get("profit_factor"), "max DD": kk.get("max_dd")})  # fmt: skip
        cc = st.column_config
        st.dataframe(
            pl.DataFrame(rows).with_columns(pl.col("max DD") * 100),
            width="stretch", hide_index=True,
            column_config={
                "R medio": cc.NumberColumn(format="%+.3f"), "IC95 bajo": cc.NumberColumn(format="%+.3f"),
                "IC95 alto": cc.NumberColumn(format="%+.3f"), "PF": cc.NumberColumn(format="%.2f"),
                "max DD": cc.NumberColumn(format="%.1f%%"),
            },
        )  # fmt: skip
        st.caption(
            "R1–R3 = rondas 1–3 (ver docs/preregistro_ronda*.md). Ninguna configuración pasó la regla de promoción."
        )

with tab3:
    st.markdown("""
**R** = ganancia o pérdida medida en unidades de riesgo. 1 R = lo que pierdes si salta el stop (1% del capital).
Un trade de +2 R ganó el doble de lo arriesgado.

**R medio (expectancy)**: lo que ganas en promedio por trade, en R. Es la métrica central: si es negativo,
operar más solo pierde más rápido. Mira siempre su **intervalo de confianza**: con pocos trades es muy ancho.

**Profit factor** = suma de ganancias / suma de pérdidas. > 1 gana; el criterio del proyecto exige > 1,3 fuera de muestra.

**Drawdown**: caída desde el máximo anterior del capital.

**Conclusión de la investigación**: 25 configuraciones probadas con pre-registro; ninguna con expectancy neta positiva
(ver `README.md` y `reports/`). La pestaña de operativa paper mide **tus** decisiones con el mismo rigor.
""")
