# Pre-registro — Ronda 4 (fase 7): patrones de gráfico y re-evaluación con 10 años de historia

**Fecha de registro:** 2026-11-05, ANTES de descargar las barras de 1 minuto 2016–2024 y antes de cualquier resultado.
**Aprobado por:** el usuario ("aprovato fase"). Todo lo de abajo queda fijo; cualquier cambio posterior se reporta
como desviación y cuenta como un intento más.

## Datos
- Base aparte `data/history.duckdb` (Alpaca SIP, precios raw, splits aplicados point-in-time).
- **Universo point-in-time por año Y:** las 100 acciones comunes (activas o deslistadas) con mayor $ volumen medio
  diario en el año Y−1, con ≥ 200 sesiones en Y−1 y último cierre ≥ $5; más SPY, QQQ, IWM. Se reconstruye con
  datos del año anterior únicamente (mitiga el sesgo de supervivencia de la lista fija de 50).
- Barras de 1 min RTH, remuestreadas a **5 min** (solo velas completas) para detectar patrones; la simulación usa 1 min.

## Periodos
| Periodo | Fechas | Uso |
|---|---|---|
| Desarrollo | 2016-01-04 → 2021-12-31 | historia para HMM y meta-labeling; reporte informativo |
| **Validación (decide)** | **2022-01-03 → 2024-10-31** | nunca usado en rondas 1–3 |
| Ya visto | 2024-11-01 → 2025-12-31 | usado en rondas 1–3 (con otras reglas); solo informativo |
| OOS sellado | ≥ 2026-01-01 | solo si algo pasa la validación, y con OK del usuario |

## Hipótesis (5 intentos nuevos → N acumulado = 30 para el Deflated Sharpe)

### P1 — Bandera (alcista → largo; bajista → corto, espejo)
Decisión al cierre de cada vela de 5 min entre 10:00 y 15:00 ET:
- **Bandera** = últimas F velas, F ∈ {3,…,8} (la primera F que cumpla).
- **Mástil** = hasta 6 velas antes de la bandera; H = máximo de la última vela del mástil; L = mínimo del mástil.
  Mástil = H − L ≥ **0,40 × ATR14 diario**.
- Ninguna vela de la bandera supera H; mínimo de la bandera ≥ H − **0,5 × mástil**.
- Volumen medio de la bandera ≤ **0,7 ×** volumen medio del mástil.
- **Entrada:** orden stop de compra en máximo de la bandera + $0,01, válida 15 min.
- **Stop:** mínimo de la bandera − $0,01 (distancia fija desde el precio ejecutado). Distancia ≥ 0,2 % del precio.
- **Objetivo:** 2 R. Stop por tiempo: 120 min. Cierre forzado 15:50 ET.
- 1 señal por símbolo y día (la primera, en cualquier dirección).

### P2 — Doble suelo (→ largo) / doble techo (→ corto, espejo)
- Pivote mínimo en la vela i: mínimo estrictamente menor que las 3 velas anteriores y ≤ que las 3 siguientes;
  **confirmado al cierre de la vela i+3** (no antes).
- Al confirmarse un pivote j, se busca el pivote anterior i más reciente con 4 ≤ j − i ≤ 30 velas que cumpla:
  |L_j − L_i| ≤ **0,10 × ATR14**; cuello N = máximo entre i y j; profundidad N − min(L_i, L_j) ≥ **0,25 × ATR14**;
  caída previa: máximo de las 12 velas anteriores a i ≥ L_i + profundidad; ningún cierre entre j y la decisión > N.
- **Entrada:** orden stop de compra en N + $0,01, válida 30 min. **Stop:** min(L_i, L_j) − $0,01 (≥ 0,2 % del precio).
- **Objetivo:** 1 R (movimiento medido clásico). Stop por tiempo 120 min. Cierre 15:50 ET. Ventana 10:00–15:00 ET.
- 1 señal por símbolo y día.

### H3' — Reversión a VWAP amplia (`h3_vwap_wide`, parámetros idénticos a la ronda 2) sobre el universo point-in-time.
### H5b' — H3' solo en días tranquilos: HMM de 2 estados sobre SPY diario **reentrenado cada mes** con toda la historia desde 2015 (P(volátil) < 0,5).
### H4' — Meta-labeling LightGBM sobre las señales de P1 ∪ P2 ∪ H3'
Hiperparámetros de la ronda 2 (sin tuning). Walk-forward expansivo mensual, embargo 1 día, 12 meses de warm-up.
Variables: lado, gap, |gap|, ATR %, precio, log $ volumen medio, minutos desde la apertura, día de la semana,
P(volátil), retorno de SPY desde la apertura hasta la señal, retorno del símbolo desde la apertura en ATR, estrategia.
Etiqueta: R neto > 0. Se toma la señal si p ≥ 0,5.

## Ejecución y costos (sin cambios)
Modelo de la fase 3: slippage calibrado (k = 0,10 sobre el rango de 1 min, relativo, se adapta a cada época),
stops ×1,5, objetivo límite solo si se supera, barra ambigua = stop (conservador), tasas SEC/TAF, cartera de $100.000,
1 % de riesgo, 5 posiciones, 10 trades/día, kill switch −3 %.

## Regla de promoción (en VALIDACIÓN, costos base)
Todas: ≥ 100 trades; R neto > 0 con t ≥ 2; **PF ≥ 1,3**; DSR ≥ 0,95 con N = 30; R > 0 con costos pesimistas;
max drawdown ≥ −20 %; R > 0 también en desarrollo; R > 0 en al menos 2 de los 3 años de validación;
**estabilidad:** al menos 3 de 4 vecinos con R > 0 en validación (P1: mástil 0,30/0,50 ATR, volumen 0,6/0,8;
P2: tolerancia 0,05/0,15 ATR, profundidad 0,20/0,30 ATR; H3'/H5'/H4': sin vecinos, ya son configuraciones fijas).
Los vecinos solo pueden vetar, nunca reemplazar a la configuración registrada.

Si nada pasa: se informa con la misma claridad que en las rondas 1–3 y el OOS 2026 sigue sellado.
