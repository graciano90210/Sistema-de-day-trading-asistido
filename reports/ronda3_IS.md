# Ronda 3 — VWAP con órdenes límite (pre-registrada)

Periodo 2024-12-03 → 2025-12-31. Pre-registro `docs/preregistro_ronda3.md` (commit 80b1ec2). OOS 2026 **sellado**.

## Resultado que decide: ajuste walk-forward

Cada mes se opera con la configuración que mejor funcionó en los meses ANTERIORES (los 3 primeros solo historia). Este es el único resultado que cuenta para la regla de promoción.

- Trades: **1793** · win rate 46.7% · R neto **-0.048** (t = -2.34) · PF **0.88** · Sharpe -2.20 · max DD -63.9%
- R con costos pesimistas: -0.093 · R con supuesto conservador: -0.048
- DSR (N = 25 intentos): **0.00** · **¿Pasa la regla?: NO**

### Configuración elegida cada mes

| mes | config | R_hist |
|---|---|---|
| 2025-03 | m0.5_w5 · ninguno | -0.017 |
| 2025-04 | m0.5_w5 · ninguno | -0.021 |
| 2025-05 | m0.5_w5 · ninguno | -0.032 |
| 2025-06 | m1.0_w5 · tranquilo | -0.016 |
| 2025-07 | m1.0_w5 · tranquilo | 0.002 |
| 2025-08 | m1.0_w5 · tranquilo | 0.002 |
| 2025-09 | m1.0_w5 · tranquilo | -0.006 |
| 2025-10 | m1.0_w2 · tranquilo | -0.004 |
| 2025-11 | m0.5_w5 · tranquilo | -0.016 |
| 2025-12 | m0.0_w5 · tranquilo | -0.017 |

## Referencia: misma señal con entrada a mercado

2490 trades · R neto -0.064 · PF 0.84.

## Ejecución en la barra de entrada

Trades con barra de entrada ambigua: 0.0%. ≤5% ambiguas: supuesto conservador

## Rejilla completa (informativa: in-sample, optimista por selección)

| config | trades | tasa_ejecución | win_rate | R_neto | t | PF | Sharpe | max_dd |
|---|---|---|---|---|---|---|---|---|
| m0.5_w5 · tranquilo | 1815 | 94.1% | 48.5% | -0.02 | -1.17 | 0.94 | -1.04 | -56.6% |
| m0.0_w2 · tranquilo | 1815 | 93.4% | 48.9% | -0.02 | -1.19 | 0.94 | -1.08 | -55.9% |
| m0.5_w2 · tranquilo | 1813 | 90.9% | 48.8% | -0.03 | -1.23 | 0.93 | -1.12 | -58.7% |
| m0.0_w5 · tranquilo | 1819 | 95.6% | 48.4% | -0.03 | -1.36 | 0.93 | -1.19 | -58.7% |
| m1.0_w2 · tranquilo | 1797 | 85.6% | 47.6% | -0.03 | -1.59 | 0.92 | -1.43 | -61.2% |
| m1.0_w5 · tranquilo | 1798 | 90.7% | 47.6% | -0.03 | -1.64 | 0.91 | -1.42 | -63.0% |
| m0.5_w2 · ninguno | 2497 | 91.0% | 48.0% | -0.04 | -2.09 | 0.91 | -1.82 | -72.9% |
| m0.5_w5 · ninguno | 2500 | 94.2% | 47.6% | -0.04 | -2.11 | 0.91 | -1.81 | -72.4% |
| m1.0_w2 · ninguno | 2468 | 85.7% | 47.1% | -0.04 | -2.24 | 0.90 | -1.94 | -72.5% |
| m0.0_w2 · ninguno | 2493 | 93.4% | 47.9% | -0.04 | -2.36 | 0.90 | -2.03 | -74.3% |
| m1.0_w5 · ninguno | 2474 | 90.7% | 47.0% | -0.04 | -2.33 | 0.90 | -1.96 | -74.2% |
| m0.0_w5 · ninguno | 2501 | 95.6% | 47.5% | -0.04 | -2.45 | 0.89 | -2.08 | -75.5% |

## Walk-forward por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 927 | 44.4% | -0.07 | -62.55 | 0.84 |
| largo | 866 | 49.2% | -0.03 | -24.30 | 0.93 |

## Walk-forward por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 28 | 75.0% | 0.20 | 5.62 | 3.91 |
| stop | 535 | 0.0% | -1.05 | -562.63 | 0.00 |
| target | 282 | 100.0% | 1.33 | 374.31 | -inf |
| time | 948 | 56.4% | 0.10 | 95.84 | 1.65 |

## Walk-forward por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2025-03 | 195 | 41.0% | -0.12 | -22.79 | 0.70 |
| 2025-04 | 176 | 43.2% | -0.11 | -19.42 | 0.71 |
| 2025-05 | 200 | 51.5% | 0.01 | 1.89 | 1.03 |
| 2025-06 | 191 | 49.7% | -0.02 | -2.94 | 0.96 |
| 2025-07 | 206 | 52.4% | 0.08 | 16.53 | 1.21 |
| 2025-08 | 193 | 46.6% | -0.06 | -12.38 | 0.84 |
| 2025-09 | 198 | 46.0% | -0.07 | -13.45 | 0.84 |
| 2025-10 | 159 | 40.3% | -0.16 | -26.19 | 0.67 |
| 2025-11 | 91 | 54.9% | 0.06 | 5.84 | 1.16 |
| 2025-12 | 184 | 44.0% | -0.08 | -13.94 | 0.80 |
