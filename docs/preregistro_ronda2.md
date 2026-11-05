# Pre-registro — Ronda 2 de hipótesis (fase 3)

**Fecha de registro:** 2026-11-04 (commit de este archivo, anterior a cualquier resultado de la ronda 2).
**Aprobado por:** el usuario (Juan Fernando Graciano), 2026-11-04.
**Regla:** estas especificaciones no se modifican después de ver resultados. Cualquier cambio posterior se
registra como una hipótesis nueva y cuenta como un intento adicional.

## Contexto

Ronda 1 (commit 289788c): ORB 5, ORB 15 y reversión a VWAP sobre gappers y control → ninguna con
expectancy neta positiva en el periodo de desarrollo, en ningún escenario de costos.
Hallazgos que motivan la ronda 2: (a) en ORB, las salidas al cierre ganaban (+0,19 R) y los stops destruían
el resultado; (b) en VWAP, ventaja bruta +0,06 R anulada por costos sobre stops estrechos; (c) se aplicaron
las estrategias sin distinguir el régimen del día.

## Marco común (todas las hipótesis)

| Elemento | Especificación |
|---|---|
| Periodo de evaluación | Desarrollo (IS): 2024-12-03 → 2025-12-31. OOS 2026 **sellado** (fase 4) |
| Datos | Barras SIP de 1 min, point-in-time (`available_at`), splits ajustados |
| Costos | Modelo calibrado con NBBO (k = 0,10; impacto 0,5; stops ×1,5) + SEC/TAF. Comisión $0 (Alpaca). Se reportan además: comisión $0,0035/acción (la del paper) y escenarios optimista/pesimista |
| Cartera (decisión) | Reglas del proyecto: 1% de riesgo por trade, máx. 5 posiciones, 10 trades/día, kill switch −3%, 4× |
| Salida forzada | 15:50 ET (regla del proyecto; el paper usa 16:00) |
| Entradas | Nunca en los últimos 15 min de la sesión |

### Ejecución de órdenes *stop* de entrada (H1, H2)
- Orden stop colocada a las 09:35 ET en el máximo (largos) o mínimo (cortos) de la vela 09:30–09:35; válida hasta 15:45.
- Se ejecuta en la primera barra de 1 min cuyo high (largo) / low (corto) alcanza el nivel. Precio = peor entre el
  nivel y la apertura de esa barra (gaps) ± slippage del modelo.
- Stop de pérdida = precio ejecutado ∓ 0,10 × ATR(14).
- **Barra de entrada** (no se sabe con barras de 1 min si el stop se tocó antes o después de entrar):
  - *Conservador*: si el rango de la barra de entrada alcanza el stop → stop.
  - *Optimista*: solo si la barra **cierra** más allá del stop.
  - *Calibrado* (**el que decide**): se toma una muestra aleatoria de ≥ 200 barras de entrada ambiguas y se
    determina con los trades tick de Alpaca (SIP) el orden real; la proporción p de casos "entrada y luego stop"
    se aplica como probabilidad a las barras ambiguas (resultado esperado). Conservador y optimista se reportan como cotas.

## Hipótesis

### H1 — ORB 5 min en *Stocks in Play* (réplica de Zarattini, Barbon y Aziz 2024, §4)
- Universo diario (con datos de sesiones previas): apertura > $5; volumen medio 14 d ≥ 1.000.000; ATR(14) > $0,50.
- RVOL = volumen 09:30–09:35 / media de esa vela en las 14 sesiones previas (≥ 10 sesiones con dato). RVOL ≥ 1.
- Top 20 por RVOL. Dirección = color de la vela 09:30–09:35; doji → sin orden.
- Entrada por orden stop (ver arriba); stop 10% ATR; salida al cierre forzado; sin objetivo.
- Cartera secundaria (solo informativa): la del paper (hasta 20 posiciones, 4×, sin kill switch).

### H2 — Mecánica de H1 sobre la watchlist de gappers (ronda 1)
- Universo: watchlist diaria de gappers (09:25 ET), ya reconstruida.
- Mismas reglas de dirección, entrada stop, stop 10% ATR y salida al cierre que H1.

### H3 — Reversión a VWAP con stops amplios
- Igual que `vwap_rev` de la ronda 1 salvo: k_sigma = 2,5; stop_buffer_atr = 0,25; min_rr = 1,0; max_hold = 90 min.
- Se evalúa en gappers y en control (2 intentos).

### H4 — Meta-labeling con LightGBM sobre las señales de H1 ∪ H2
- Etiqueta: r_neto > 0 (con el supuesto de ejecución calibrado).
- Variables (todas conocidas en el momento de la entrada): RVOL, gap de pre-market, |gap|, dirección,
  rango de apertura / ATR, ATR %, precio, log volumen medio, minutos desde la apertura hasta la entrada,
  gap y retorno 09:30–09:35 de SPY, día de la semana, catalizador (gappers; "n/d" en H1),
  probabilidad de régimen volátil de H5.
- Validación walk-forward: ventana expansiva, reentrenamiento mensual, los primeros 4 meses solo entrenan,
  embargo de 1 día. Solo se evalúan predicciones fuera de la ventana de entrenamiento.
- Hiperparámetros fijos (sin tuning): num_leaves 15, min_data_in_leaf 50, learning_rate 0,05, 200 árboles,
  feature_fraction 0,8, semilla 7. Se opera la señal si p ≥ 0,5.

### H5 — Filtro de régimen con HMM (aprendizaje dinámico)
- HMM gaussiano de 2 estados sobre SPY diario: [log-retorno, log(high/low)], datos desde 2016.
- Reajuste mensual con datos hasta el mes anterior; para la sesión d se usa la probabilidad **predicha**
  del estado volátil con información hasta d−1 (sin lookahead). Estado volátil = el de mayor varianza de retorno.
- H5a: H1 solo en días con P(volátil) ≥ 0,5 (la rentabilidad del ORB crece con la volatilidad; Lundström 2017).
- H5b: H3 (gappers) solo en días con P(volátil) < 0,5.

## Cuenta de intentos y corrección por múltiples pruebas

Ronda 1: 6 configuraciones. Ronda 2: H1, H2, H3 ×2, H4, H5a, H5b = 7. **Total N = 13.**
Se reporta el *Deflated Sharpe Ratio* (Bailey y López de Prado, 2014) con N = 13 sobre los retornos diarios de cartera.

## Regla de promoción al OOS (fase 4) — fijada aquí

Una configuración pasa al OOS solo si, en el periodo de desarrollo, con costos base y ejecución calibrada:
1. ≥ 100 trades;
2. R neto medio > 0 con t-stat ≥ 2,0;
3. profit factor ≥ 1,2;
4. DSR ≥ 0,95;
5. sigue con R neto > 0 en el escenario de costos pesimista.

Si ninguna pasa, se informa así y no se abre el OOS para estrategias sin evidencia en desarrollo.

## Referencias
- Zarattini, C.; Barbon, A.; Aziz, A. (2024). *A Profitable Day Trading Strategy For The U.S. Equity Market*. SFI Research Paper 24-98.
- Bailey, D. H.; López de Prado, M. (2014). The Deflated Sharpe Ratio. *Journal of Portfolio Management*, 40(5).
- Lundström, C. (2017). Day trading returns across volatility states (citado en Zarattini et al. 2024, ref. [16]).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley (meta-labeling, embargo).
