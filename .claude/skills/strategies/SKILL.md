---
name: strategies
description: Estrategias intradía documentadas (Opening Range Breakout 5/15 min y reversión a VWAP) como funciones puras point-in-time con parámetros en config/strategies.yaml. Úsala para entender, modificar o añadir una estrategia o variante, o para explicar por qué una señal se generó.
---

# strategies

Código en `src/daytrader/strategies/`. Parámetros en `config/strategies.yaml` (cada clave = una variante).

## Contrato (no romper)
- Firma: `fn(bars, ctx, params) -> list[Signal]`; `bars` = barras RTH de 1 min de un símbolo-día.
- **Invariante a prefijos**: la señal decidida en `t` debe salir igual con solo las barras
  `available_at <= t`. `tests/test_strategies.py` lo comprueba con datos aleatorios y barras trampa.
- `Signal.decided_at` = `available_at` de la barra de señal. La entrada la simula el backtester en la
  **apertura de la barra siguiente**, nunca al cierre de la barra de señal.
- Sin entradas en los últimos 15 min de la sesión (`ctx.last_entry`, respeta medias sesiones).

## Estrategias
- **orb**: rango de los primeros N min; señal = primera barra que cierra fuera del rango en la dirección
  permitida (`with_gap` = a favor del gap de pre-market). Stop = extremo opuesto (o mitad). Objetivo = R×.
- **vwap_reversion**: barra previa a ≥ k·σ del VWAP de sesión (σ expansiva de close−VWAP) y barra de
  giro; objetivo = VWAP; stop = extremo reciente; stop por tiempo.

## Añadir una variante
1. Nueva clave en `config/strategies.yaml` con `type: orb|vwap_reversion` y parámetros.
2. `uv run daytrader backtest --strategies <clave>` (solo in-sample; el OOS está sellado).
Cambiar parámetros mirando el OOS invalida la validación: no hacerlo.
