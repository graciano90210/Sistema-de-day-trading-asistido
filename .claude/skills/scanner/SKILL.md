---
name: scanner
description: Genera la watchlist diaria de gappers de pre-market (gap, volumen relativo, ATR, liquidez, acciones en circulación) sobre todo el mercado de acciones comunes de EE. UU., point-in-time a las 09:25 ET, con catalizadores de noticias. Úsala para "¿qué se mueve hoy / ese día?", para revisar la watchlist de una fecha histórica o para ajustar los filtros del scanner.
---

# scanner

Wrapper sobre `src/daytrader/scanner/`. Todos los números los calcula Python; Claude solo interpreta.

## Comandos
```bash
uv run python .claude/skills/scanner/scripts/watchlist.py --date 2026-11-03            # → reports/watchlist_2026-11-03.md
uv run python .claude/skills/scanner/scripts/watchlist.py --date 2026-11-03 --cutoff 09:00 --top 10
uv run daytrader universe      # actualizar lista de acciones, splits y barras diarias de todo el mercado
```
Parámetros en `config/scanner.yaml`.

## Cómo funciona (dos etapas, sin lookahead)
1. **Universo líquido** (barras diarias de sesiones *anteriores*, ajustadas por split):
   acciones comunes NYSE/Nasdaq/AMEX/ARCA/BATS, activas e inactivas; precio, ADV $, ATR(14), ATR%.
2. **Gappers** al `cutoff_et` de D: resumen del pre-market con barras `available_at <= cutoff`:
   gap vs. cierre anterior, volumen pre-market, RVOL a la misma hora vs. 20 sesiones previas.
   Ranking por |gap| × dólares negociados en pre-market.
3. Acciones en circulación (SEC EDGAR, publicadas antes de D) y noticias (publicadas antes del cutoff).

## Al interpretar una watchlist
- Gap con `sin_catalizador` suele ser movimiento sectorial/macro o noticia no capturada: decirlo.
- `offering` (dilución) en un gap alcista es señal de alerta; en gap bajista explica el movimiento.
- RVOL = ∞ significa que no hubo volumen pre-market en las 20 sesiones previas (ticker poco seguido).
- Recordar el sesgo de supervivencia residual: tickers reutilizados o sin datos en Alpaca.
- Nunca recomendar órdenes desde aquí: la watchlist es un input para strategies/backtester.
