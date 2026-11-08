# Fase 8 — swing trading (2 a 20 días) con barras diarias

Pre-registro: `docs/preregistro_fase8_swing.md`. Universo point-in-time: top 500 por $ volumen del año anterior (826 símbolos distintos 2017–2025). Ejecución en la apertura siguiente a la señal. N = 34 intentos para el DSR. Datos hasta 2025-12-31 (OOS 2026 sellado).

## Decisión (validación 2022-01 → 2024-10, costos base)

| Hipótesis | trades / rebal. | retorno anual | Sharpe | exceso anual vs SPY | Sharpe exceso | DSR | R neto (t, PF) | exceso pesimista | max DD | exceso desarrollo | ¿Pasa? | motivos |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 momentum 12−1 | 34 | +9.0% | 0.29 | +1.0% | 0.04 | 0.00 | — | -0.2% | -39.8% | -4.2% | no | DSR < 0,95; exceso ≤ 0 con costos pesimistas; drawdown peor que −25 %; exceso ≤ 0 en desarrollo; menos de 3 de 4 vecinos con exceso > 0 |
| S2 reversión semanal | 147 | +4.0% | 0.09 | -3.9% | -0.11 | 0.00 | — | -18.6% | -50.2% | +11.2% | no | no le gana a SPY (exceso ≤ 0); DSR < 0,95; exceso ≤ 0 con costos pesimistas; drawdown peor que −25 %; exceso > 0 en menos de 2 de 3 años; menos de 3 de 4 vecinos con exceso > 0 |
| S3 deriva tras shock de volumen | 648 | -1.0% | -0.12 | -9.0% | -0.41 | 0.00 | -0.007 (t -0.19, PF 0.98) | -14.6% | -14.2% | -23.1% | no | no le gana a SPY (exceso ≤ 0); DSR < 0,95; R neto no es > 0 con t ≥ 2; PF < 1,3; exceso ≤ 0 con costos pesimistas; exceso ≤ 0 en desarrollo; exceso > 0 en menos de 2 de 3 años; menos de 3 de 4 vecinos con exceso > 0 |
| S4 RSI(2) en tendencia | 1720 | -3.2% | -0.29 | -11.2% | -0.82 | 0.00 | -0.008 (t -0.61, PF 0.96) | -24.7% | -24.6% | -17.4% | no | no le gana a SPY (exceso ≤ 0); DSR < 0,95; R neto no es > 0 con t ≥ 2; PF < 1,3; exceso ≤ 0 con costos pesimistas; exceso ≤ 0 en desarrollo; exceso > 0 en menos de 2 de 3 años; menos de 3 de 4 vecinos con exceso > 0 |

## Referencias (mismo periodo)

| Referencia | periodo | retorno anual | Sharpe | max DD |
|---|---|---|---|---|
| SPY | desarrollo | +16.8% | 0.91 | -34.2% |
| SPY | validacion | +7.9% | 0.45 | -25.4% |
| SPY | ya_visto | +17.5% | 0.93 | -19.0% |
| Universo igual-ponderado | desarrollo | +17.1% | 0.81 | -39.2% |
| Universo igual-ponderado | validacion | +3.7% | 0.17 | -28.8% |
| Universo igual-ponderado | ya_visto | +14.9% | 0.77 | -19.9% |

## Todos los periodos (exceso anual vs SPY · retorno anual · trades)

| Hipótesis | desarrollo | validación | ya visto | R bruto val. (S3/S4) |
|---|---|---|---|---|
| S1 momentum 12−1 | -4.2% · +12.6% · 60 | +1.0% · +9.0% · 34 | +31.5% · +48.9% · 14 | — |
| S2 reversión semanal | +11.2% · +28.0% · 261 | -3.9% · +4.0% · 147 | +6.7% · +24.2% · 62 | — |
| S3 deriva tras shock de volumen | -23.1% · -6.3% · 1148 | -9.0% · -1.0% · 648 | -35.1% · -17.6% · 271 | +0.021 |
| S4 RSI(2) en tendencia | -17.4% · -0.6% · 3292 | -11.2% · -3.2% · 1720 | -22.9% · -5.4% · 741 | +0.026 |

## Exceso anual vs SPY por año

| Hipótesis | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|---|
| S1 momentum 12−1 | -17% | +13% | -10% | +40% | -47% | +0% | -38% | +56% | +21% |
| S2 reversión semanal | -1% | +16% | -2% | +66% | -22% | -21% | +33% | -19% | +4% |
| S3 deriva tras shock de volumen | -24% | -21% | -30% | -13% | -27% | +13% | -20% | -20% | -39% |
| S4 RSI(2) en tendencia | -15% | -8% | -28% | -8% | -27% | -5% | -11% | -20% | -23% |

## Estabilidad (vecinos, exceso anual en validación)

- S1 momentum 12−1: top5 +13.1% · top20 -5.5% · lb6 -13.0% · lb9 -2.1% → 1/4 positivos
- S2 reversión semanal: top5 -4.9% · top20 -1.1% · w3 +3.4% · w10 -22.2% → 1/4 positivos
- S3 deriva tras shock de volumen: vol2.5 -12.6% · vol4 -8.8% · atr1.25 -9.3% · atr2 -10.5% → 0/4 positivos
- S4 RSI(2) en tendencia: rsi5 -15.7% · rsi15 -12.9% · hold5 -11.0% · hold15 -11.2% → 0/4 positivos

## Conclusión

**Ninguna hipótesis pasa la regla pre-registrada.** El OOS 2026 sigue sellado.

## Notas de verificación (revisión posterior, no cambian ninguna regla)

- **Dividendo especial KDP (2018-07):** la fusión Keurig–Dr Pepper pagó $103/acción; como los precios son raw (sin
  dividendos), S3 registra un falso −38 R. Está en **desarrollo**, no en validación: no afecta la decisión.
- **S3 y S4 no están invertidos todo el tiempo** (≈ 6–7 posiciones de 10 con ~10 % del capital cada una), así que el
  exceso vs SPY los penaliza en años alcistas. Aun así el criterio por trade es claro: R neto ≈ 0 (t −0,19 y −0,61) y
  R bruto apenas +0,02 — no hay ventaja por trade que el exceso esté ocultando.
- **S1 en "ya visto" (+31,5 % de exceso, 2024-11 → 2025)** es informativo: ese periodo no decide, y en validación y
  desarrollo S1 no le gana a SPY de forma consistente (años de −47 % a +56 % de exceso).
