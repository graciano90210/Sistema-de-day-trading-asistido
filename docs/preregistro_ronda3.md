# Pre-registro — Ronda 3: ejecución con órdenes límite (VWAP)

**Fecha de registro:** 2026-11-04, antes de cualquier resultado de la ronda 3. **Aprobado por:** el usuario.
**Motivación (ronda 2, commit b11aade):** la causa raíz común es el costo de cruzar el spread con órdenes a
mercado. La reversión a VWAP con stops amplios es la configuración más cercana a cero (H3 −0,05 R; H5b −0,04 R).
Hipótesis: entrar **pasivamente** con órdenes límite (cobrando el spread en lugar de pagarlo) vuelve positiva la
expectancy, a pesar de la selección adversa (las órdenes límite se ejecutan más a menudo cuando el precio sigue en contra).

## Señal (fija, sin cambios)
`h3_vwap_wide` (k_sigma 2,5; stop = extremo de 10 barras ± 0,25·ATR; objetivo = VWAP en la señal; max_hold 90 min;
entradas 10:00–15:00 ET; 1 por símbolo y día). Universo: gappers ∪ control (50 líquidos). Periodo: 2024-12-03 → 2025-12-31.

## Ejecución de la entrada (lo que se prueba)
- Orden límite colocada en `decided_at` (cierre de la barra de señal) a precio
  **L = cierre_señal − lado × m × medio_spread_estimado** (medio spread del modelo calibrado, k = 0,10, barras previas).
- Válida durante **W** minutos; si no se ejecuta, se cancela (sin trade).
- **Ejecución solo por "trade-through"** (conservador): compra si alguna barra de la ventana tiene low < L (estricto);
  venta si high > L. Precio = L, o la apertura si la barra abrió más allá de L (gap a favor). Sin slippage de entrada.
- Stop: orden a mercado con slippage ×1,5 (igual que siempre). Objetivo: límite en el VWAP, solo si se supera.
  Stop por tiempo: 90 min desde la ejecución. Cierre forzado 15:50 ET.
- Barra de ejecución que también toca el stop: supuesto conservador (stop). Si > 5% de los trades son ambiguos, se
  calibra con trades tick como en la ronda 2 y decide el resultado calibrado.

## Rejilla de configuraciones (12)
| Parámetro | Valores |
|---|---|
| m (desplazamiento en medios spreads) | 0 · 0,5 · 1,0 |
| W (validez, minutos) | 2 · 5 |
| Filtro de régimen HMM | ninguno · solo días tranquilos (P(volátil) < 0,5) |

## Ajuste walk-forward (el resultado que decide)
- Meses del periodo: dic-2024 … dic-2025. Los 3 primeros solo sirven de historia.
- Para cada mes M ≥ 4.º: se elige la configuración con mayor R neto medio por trade en todos los meses < M
  (exigiendo ≥ 100 trades en esa historia; si ninguna llega, se usa m = 0,5, W = 5, sin filtro).
- Se opera el mes M con la configuración elegida. La concatenación de esos meses es la estrategia evaluada.
- Las 12 configuraciones evaluadas sobre el periodo completo se reportan solo como información (in-sample, optimistas).

## Regla de promoción al OOS (misma que la ronda 2)
Sobre el resultado walk-forward, con costos base: ≥ 100 trades; R neto > 0 con t ≥ 2; PF ≥ 1,2;
DSR ≥ 0,95 con **N = 25** intentos (13 previos + 12 de la rejilla); R > 0 con costos pesimistas.

Si no pasa, se cierra la búsqueda de estrategias intradía con este conjunto de datos y se pasa a las fases 5–6.
