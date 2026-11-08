# Pre-registro — Fase 8: swing trading (2 a 20 días) con barras diarias

**Fecha de registro:** 2026-11-08, ANTES de escribir el código de las hipótesis y antes de cualquier resultado.
**Estado:** APROBADO por el usuario ("aprovado", 2026-11-08). Queda fijo; cualquier cambio posterior se
reporta como desviación y cuenta como un intento más.

## Por qué swing
Rondas 1–4 (30 intentos): todas las señales intradía tienen R bruto ≈ 0 y los costos (0,05–0,15 R por trade) las
vuelven negativas. En horizontes de días, el movimiento esperado es mucho mayor que el costo de ejecución, y existen
efectos documentados en la literatura (momentum, reversión de corto plazo, deriva tras eventos de volumen).

## Datos
- `data/history.duckdb`, tabla `bars_1d` (Alpaca SIP, precios raw, 2016-01-04 → hoy, 5.870 símbolos incluidos
  deslistados). Todo cálculo multi-día **ajustado por splits** point-in-time (`daytrader.data.adjust`).
- Barra diaria de la sesión D disponible a las D 20:00 ET (convención del proyecto). Las señales se calculan con el
  cierre de D y se **ejecutan en la apertura de D+1**. Cero lookahead; tests de invariancia a prefijos.
- **Dividendos no incluidos** (precios raw): subestima los largos (conservador); para cortos se resta el dividendo
  como costo en el escenario pesimista (ver costos).
- **Deslistados:** si un símbolo deja de cotizar con una posición abierta, se cierra al último cierre disponible.

## Universo point-in-time (por año Y)
Las **500** acciones comunes (activas o deslistadas) con mayor $ volumen medio diario en Y−1, con ≥ 200 sesiones en
Y−1 y último cierre ≥ $5 (mismo constructor que la ronda 4, `pit_universe(n=500)`). Benchmarks: SPY y el promedio
igual-ponderado del universo.

## Periodos
| Periodo | Fechas | Uso |
|---|---|---|
| Desarrollo | 2017-01-03 → 2021-12-31 | implementar, depurar, reporte informativo |
| **Validación (decide)** | **2022-01-03 → 2024-10-31** | aplica la regla de promoción |
| Ya visto | 2024-11-01 → 2025-12-31 | informativo |
| OOS sellado | ≥ 2026-01-01 | solo si algo pasa la validación, y con OK del usuario |

## Hipótesis (4 intentos nuevos → N acumulado = 34 para el Deflated Sharpe)

### S1 — Momentum de 12−1 meses (cartera, solo largos)
- Último día hábil de cada mes: ranking del universo por retorno de los meses t−12 a t−1 (se salta el último mes).
- Se compran las **10** de mayor momentum, igual peso (10 % c/u), en la apertura del día siguiente; se mantienen un mes.
- **Filtro de mercado:** si SPY cierra ≤ su media de 200 sesiones el día del ranking, ese mes queda en efectivo.
- Sin stops (es una cartera rotativa).

### S2 — Reversión semanal (cartera, solo largos)
- Cada viernes (o último día hábil de la semana): las **10** acciones del universo con peor retorno de 5 sesiones,
  con precio ≥ $10 y que **no** hayan caído más de 30 % (evita quiebras/fraudes).
- Igual peso, entrada en la apertura del lunes, salida en la apertura del lunes siguiente.

### S3 — Deriva tras shock de volumen (eventos, largos y cortos)
Proxy de deriva post-anuncio (la mayoría de estos días son earnings u otras noticias), sin depender de fechas de earnings.
- Evento en la sesión D: volumen ≥ **3 ×** su media de 50 sesiones (hasta D−1) **y** |retorno cierre a cierre| ≥
  **1,5 × ATR14 %** (ATR hasta D−1).
- Dirección = signo del retorno de D. Fuerza del cierre: largo solo si el cierre está en el 30 % superior del rango
  de D; corto solo si está en el 30 % inferior.
- Entrada en la apertura de D+1. **Stop:** 2 × ATR14 desde la entrada. **Salida:** al cierre de la 10.ª sesión
  (D+10) si no saltó el stop. Sin objetivo.

### S4 — Retroceso en tendencia, RSI(2) (eventos, solo largos)
Regla popular entre traders minoristas (Connors); se prueba tal cual.
- Señal en el cierre de D: cierre > media de 200 sesiones **y** RSI(2) < **10**.
- Entrada en la apertura de D+1. **Salida:** primer cierre por encima de la media de 5 sesiones, o al cierre de la
  10.ª sesión. **Stop:** 2,5 × ATR14 desde la entrada.

## Riesgo y cartera (S3 y S4)
Capital de referencia $100.000; **0,5 % de riesgo por trade** (la distancia al stop define el tamaño), máximo
**10 posiciones** simultáneas y 25 % del capital por posición; si hay más señales que huecos se toman por mayor
$ volumen medio (regla fija, no por resultado). 1 posición por símbolo.
Stop con gap: si la apertura ya está más allá del stop, se ejecuta en la apertura (no en el stop) — conservador.
Stops evaluados con máximo/mínimo diario; si en el mismo día se tocan stop y salida, cuenta el stop.

## Costos
| Escenario | Spread + slippage por lado | Préstamo de cortos | Dividendos en cortos |
|---|---|---|---|
| Base | 10 pb (0,10 %) | 0,5 %/año | ignorados |
| Pesimista | 25 pb | 3 %/año | −2 %/año sobre el nocional corto |
Más tasas SEC/TAF del modelo actual. (Universo top-500 por liquidez: el spread típico es 1–5 pb; 10 pb ya es holgado.)

## Métricas
- Por trade (S3, S4): R neto, t, profit factor, win rate, duración media.
- Por cartera (las 4): retorno anual, volatilidad, Sharpe diario anualizado, max drawdown, y **exceso sobre SPY**
  (retorno diario de la estrategia − SPY) con su Sharpe y DSR.

## Regla de promoción (en VALIDACIÓN, costos base) — todas deben cumplirse
1. ≥ 100 trades (S3, S4) o ≥ 30 rebalanceos (S1: 34 meses; S2: ~145 semanas).
2. Sharpe del **exceso sobre SPY** > 0 y **DSR ≥ 0,95 con N = 34**.
3. S3/S4: R neto > 0 con t ≥ 2 y **PF ≥ 1,3**.
4. Exceso sobre SPY > 0 también con **costos pesimistas**.
5. Max drawdown de la estrategia ≥ −25 %.
6. Exceso sobre SPY > 0 en **desarrollo** y en al menos 2 de los 3 años de validación.
7. **Estabilidad:** al menos 3 de 4 vecinos con exceso > 0 en validación (pueden vetar, nunca reemplazar):
   S1: top 5 / top 20, lookback 6−1 / 9−1 meses · S2: top 5 / top 20, ventana 3 / 10 sesiones ·
   S3: volumen 2,5× / 4×, umbral 1,25 / 2 ATR · S4: RSI < 5 / < 15, salida máx. 5 / 15 sesiones.

Nota honesta: 34 meses de validación es poco para que una cartera mensual (S1) alcance DSR ≥ 0,95 aunque el efecto
exista; si S1 muestra exceso positivo en todos los periodos pero no llega al DSR, se informa como "no probado",
no como "pasa".

Si nada pasa: se informa con la misma claridad que en las rondas 1–4 y el OOS 2026 sigue sellado.

## Plan de implementación (tras el OK)
1. `strategies/swing.py`: señales puras S1–S4 con datos ajustados por splits; tests de invariancia a prefijos.
2. `backtest/daily.py`: motor diario (apertura D+1, stops con gap, salidas por tiempo/media, costos y préstamo).
3. `research/fase8.py` + reporte `reports/fase8_swing.md`; caché por año (reanudable).
4. Detenerse, mostrar resultados y esperar OK.
