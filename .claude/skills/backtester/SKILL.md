---
name: backtester
description: Backtester intradía con ejecuciones conservadoras, slippage calibrado con NBBO real, tasas regulatorias, simulación de cartera (1% de riesgo, límites, kill switch) y reporte de métricas (expectancy, profit factor, Sharpe, drawdown, win rate, R) vs. SPY, con la muestra OOS sellada. Úsala para correr o interpretar backtests y para calibrar costos.
---

# backtester

Código en `src/daytrader/backtest/`. Config en `config/backtest.yaml`.

## Comandos
```bash
uv run python .claude/skills/backtester/scripts/backtest.py                      # IS completo, 3 variantes, 2 universos
uv run python .claude/skills/backtester/scripts/backtest.py --strategies orb_15 --universes gappers
uv run daytrader backfill                                                         # watchlists históricas (requisito de "gappers")
```
Salidas: `reports/backtest_IS.md`, trades en `data/backtests/*.parquet`.

## Reglas de ejecución (engine.py)
Entrada a la apertura de la barra siguiente ± slippage · stop a mercado: peor entre stop y apertura
(gaps) con slippage ×1.5 · objetivo límite solo si se SUPERA · stop y objetivo en la misma barra → stop ·
cierre forzado 15:50 ET · R neto = PnL neto / riesgo planificado.

## Costos
Medio spread = k × mediana(rango 1 min de las 30 barras previas), k calibrado contra NBBO SIP
(`backtest/calibrate.py`). Impacto ∝ σ·precio·√(acciones/volumen). SEC + FINRA TAF en ventas.
El reporte incluye escenarios optimista/base/pesimista.

## Muestra OOS sellada
`holdout_start` (2026-01-01). El runner lanza `HoldoutSealed` si el periodo lo toca, salvo `--unseal-oos`
(solo fase 4). Nunca ajustar parámetros después de ver OOS.

## Al interpretar
- Mirar primero **R bruto**: si ≈ 0, no hay ventaja que los costos puedan destruir o salvar.
- Un t-stat < 2 con cientos de trades = indistinguible de ruido.
- Las métricas de cartera (retorno, DD) amplifican la expectancy: con R neto negativo y 1% por trade, el
  capital se destruye rápido. Eso es información, no un bug.
