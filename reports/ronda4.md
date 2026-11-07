# Ronda 4 (fase 7) — patrones de gráfico y re-evaluación con 10 años

Pre-registro: `docs/preregistro_ronda4.md`. Costos base del backtester; cartera $100.000, 1 % por trade.
Universo point-in-time: 232,542 símbolo-días. N = 30 intentos para el DSR.

## Decisión (periodo de validación 2022-01 → 2024-10)

| Hipótesis | trades | R neto | t | PF | DSR | R pesimista | max DD | R desarrollo | ¿Pasa? | motivos |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 bandera | 2869 | -0.064 | -2.85 | 0.89 | 0.00 | -0.214 | -88.8% | -0.141 | no | R neto no es > 0 con t ≥ 2; PF < 1,3; DSR < 0,95; R ≤ 0 con costos pesimistas; drawdown peor que −20 %; R ≤ 0 en desarrollo; R > 0 en menos de 2 de 3 años; menos de 3 de 4 vecinos con R > 0 |
| P2 doble suelo/techo | 4087 | -0.017 | -1.48 | 0.95 | 0.00 | -0.072 | -73.4% | -0.040 | no | R neto no es > 0 con t ≥ 2; PF < 1,3; DSR < 0,95; R ≤ 0 con costos pesimistas; drawdown peor que −20 %; R ≤ 0 en desarrollo; R > 0 en menos de 2 de 3 años; menos de 3 de 4 vecinos con R > 0 |
| H3' VWAP amplio | 6432 | -0.049 | -5.12 | 0.86 | 0.00 | -0.117 | -97.2% | -0.055 | no | R neto no es > 0 con t ≥ 2; PF < 1,3; DSR < 0,95; R ≤ 0 con costos pesimistas; drawdown peor que −20 %; R ≤ 0 en desarrollo; R > 0 en menos de 2 de 3 años |
| H5b' VWAP + HMM tranquilo | 3354 | -0.054 | -4.13 | 0.84 | 0.00 | -0.123 | -87.2% | -0.060 | no | R neto no es > 0 con t ≥ 2; PF < 1,3; DSR < 0,95; R ≤ 0 con costos pesimistas; drawdown peor que −20 %; R ≤ 0 en desarrollo; R > 0 en menos de 2 de 3 años |
| H4' meta-labeling LightGBM | 2112 | -0.038 | -2.34 | 0.89 | 0.00 | -0.096 | -59.8% | -0.075 | no | R neto no es > 0 con t ≥ 2; PF < 1,3; DSR < 0,95; R ≤ 0 con costos pesimistas; drawdown peor que −20 %; R ≤ 0 en desarrollo; R > 0 en menos de 2 de 3 años |

## Todos los periodos (R neto por trade · trades)

| Hipótesis | desarrollo | validacion | ya_visto | R bruto (sin costos) val. |
|---|---|---|---|---|
| P1 bandera | -0.141 · 4178 | -0.064 · 2869 | -0.049 · 1087 | +0.035 |
| P2 doble suelo/techo | -0.040 · 6281 | -0.017 · 4087 | -0.019 · 1517 | +0.021 |
| H3' VWAP amplio | -0.055 · 10383 | -0.049 · 6432 | -0.045 · 2590 | -0.005 |
| H5b' VWAP + HMM tranquilo | -0.060 · 6735 | -0.054 · 3354 | -0.041 · 1887 | -0.028 |
| H4' meta-labeling LightGBM | -0.075 · 5028 | -0.038 · 2112 | -0.110 · 484 | -0.002 |

## R neto por año

| Hipótesis | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 bandera | — | -0.28 | -0.09 | -0.21 | -0.10 | -0.09 | -0.07 | -0.08 | -0.18 | -0.03 |
| P2 doble suelo/techo | — | -0.06 | -0.05 | -0.04 | -0.02 | -0.04 | +0.02 | -0.04 | +0.02 | -0.03 |
| H3' VWAP amplio | — | -0.09 | -0.04 | -0.05 | -0.05 | -0.05 | -0.06 | -0.05 | -0.00 | -0.05 |
| H5b' VWAP + HMM tranquilo | — | -0.09 | -0.06 | -0.04 | -0.05 | -0.05 | -0.03 | -0.07 | -0.00 | -0.05 |
| H4' meta-labeling LightGBM | — | — | -0.10 | -0.04 | -0.06 | -0.09 | -0.03 | -0.06 | -0.23 | -0.10 |

## Estabilidad (vecinos, validación)

- P1 bandera: pole_atr0.3 -0.081 · pole_atr0.5 -0.054 · vol_ratio0.6 -0.107 · vol_ratio0.8 -0.084 → 0/4 positivos
- P2 doble suelo/techo: tol_atr0.05 -0.001 · tol_atr0.15 -0.032 · depth_atr0.2 -0.042 · depth_atr0.3 -0.032 → 0/4 positivos

## Conclusión

**Ninguna hipótesis pasa la regla pre-registrada.** El OOS 2026 sigue sellado.
