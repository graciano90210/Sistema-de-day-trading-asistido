# Ronda 2 — resultados in-sample (pre-registrados)

Periodo 2024-12-03 → 2025-12-31. Pre-registro: `docs/preregistro_ronda2.md` (commit 71bff15, anterior a estos resultados). OOS 2026 sigue **sellado**.

## Calibración de la barra de entrada (trades tick SIP)

Barras de entrada ambiguas (tocan nivel y stop en el mismo minuto): 3404. Muestra resuelta con ticks: 200 de 200. **p = 69.5%** de los casos fueron "entrada y luego stop". El resultado calibrado (decisión) pondera las barras ambiguas con p; *cons* = siempre stop, *opt* = nunca.

## Resumen y regla de promoción

Pasa al OOS solo si: ≥100 trades, R neto > 0 con t ≥ 2, PF ≥ 1,2, DSR ≥ 0,95 (N = 13 intentos) y R > 0 en el escenario de costos pesimista.

| config | descripción | trades | win_rate | R_neto (cal) | R cons | R opt | R pesimista | t | PF | Sharpe | max_dd | DSR | PASA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | ORB 5 min en Stocks in Play (top 20 RVOL), stop 10% ATR, salida al cierre | 640 | 6.1% | -1.57 | -1.77 | -1.01 | -2.67 | -24.83 | 0.12 | -28.77 | -100.0% | 0.00 | no |
| H2 | Mecánica de H1 sobre la watchlist de gappers | 767 | 9.8% | -1.07 | -1.33 | -0.62 | -2.09 | -12.42 | 0.29 | -11.01 | -100.0% | 0.00 | no |
| H3_gappers | VWAP con stops amplios — gappers | 1735 | 47.0% | -0.05 | -0.05 | -0.05 | -0.14 | -2.14 | 0.89 | -1.96 | -68.9% | 0.00 | no |
| H3_control | VWAP con stops amplios — control (50 líquidos) | 2307 | 47.9% | -0.06 | -0.06 | -0.06 | -0.12 | -3.82 | 0.83 | -3.21 | -79.6% | 0.00 | no |
| H4 | Meta-labeling LightGBM sobre H1 ∪ H2 (walk-forward; tras 4 meses de entrenamiento) | 3 | 33.3% | -0.75 | -0.75 | -0.75 | -0.97 | -1.61 | 0.08 | -1.50 | -2.4% | 0.00 | no |
| H5a | H1 solo en días de régimen volátil (HMM) | 203 | 6.9% | -1.43 | -1.65 | -0.57 | -2.48 | -11.55 | 0.14 | -7.71 | -94.8% | 0.00 | no |
| H5b | H3 gappers solo en días de régimen tranquilo (HMM) | 1293 | 47.8% | -0.04 | -0.04 | -0.04 | -0.13 | -1.38 | 0.92 | -1.34 | -53.6% | 0.00 | no |

Régimen HMM: 75 de 270 sesiones clasificadas como volátiles (probabilidad predicha con información hasta el día anterior).

## Variantes informativas de H1 (no deciden)

- **H1 (cartera del paper)**: 2333 trades, R neto -1.299, PF 0.21, retorno -100.0%, max DD -100.0%
- **H1 (comisión $0,0035)**: 624 trades, R neto -1.621, PF 0.11, retorno -100.0%, max DD -100.0%


## H1 — ORB 5 min en Stocks in Play (top 20 RVOL), stop 10% ATR, salida al cierre

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 319 | 5.6% | -1.61 | -514.83 | 0.08 |
| largo | 321 | 6.5% | -1.53 | -489.98 | 0.15 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 11 | 90.9% | 5.84 | 64.21 | 652.39 |
| stop | 629 | 4.6% | -1.70 | -1069.03 | 0.06 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 43 | 9.3% | -1.44 | -62.07 | 0.11 |
| 2025-01 | 42 | 4.8% | -1.74 | -73.16 | 0.02 |
| 2025-02 | 43 | 4.7% | -1.87 | -80.35 | 0.05 |
| 2025-03 | 57 | 7.0% | -1.55 | -88.28 | 0.09 |
| 2025-04 | 74 | 10.8% | -1.11 | -82.50 | 0.21 |
| 2025-05 | 47 | 4.3% | -1.73 | -81.39 | 0.08 |
| 2025-06 | 46 | 4.3% | -1.71 | -78.56 | 0.03 |
| 2025-07 | 52 | 5.8% | -1.71 | -88.67 | 0.10 |
| 2025-08 | 46 | 4.3% | -1.93 | -88.84 | 0.03 |
| 2025-09 | 44 | 0.0% | -1.81 | -79.73 | 0.00 |
| 2025-10 | 57 | 7.0% | -1.50 | -85.37 | 0.17 |
| 2025-11 | 40 | 5.0% | -1.43 | -57.00 | 0.31 |
| 2025-12 | 49 | 8.2% | -1.20 | -58.91 | 0.27 |


## H2 — Mecánica de H1 sobre la watchlist de gappers

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 393 | 10.9% | -0.98 | -386.98 | 0.33 |
| largo | 374 | 8.6% | -1.15 | -429.94 | 0.25 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 39 | 100.0% | 6.11 | 238.24 | -inf |
| stop | 728 | 4.9% | -1.45 | -1055.16 | 0.08 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 47 | 0.0% | -1.72 | -80.97 | 0.00 |
| 2025-01 | 64 | 17.2% | -0.54 | -34.53 | 0.60 |
| 2025-02 | 64 | 14.1% | -1.07 | -68.63 | 0.26 |
| 2025-03 | 68 | 11.8% | -0.34 | -23.07 | 0.77 |
| 2025-04 | 77 | 18.2% | -0.43 | -33.45 | 0.62 |
| 2025-05 | 56 | 5.4% | -1.50 | -84.21 | 0.02 |
| 2025-06 | 47 | 4.3% | -1.55 | -72.88 | 0.08 |
| 2025-07 | 52 | 3.8% | -1.67 | -86.96 | 0.03 |
| 2025-08 | 51 | 7.8% | -1.16 | -59.27 | 0.28 |
| 2025-09 | 56 | 3.6% | -1.52 | -85.01 | 0.07 |
| 2025-10 | 68 | 5.9% | -1.20 | -81.41 | 0.23 |
| 2025-11 | 57 | 12.3% | -0.75 | -42.76 | 0.47 |
| 2025-12 | 60 | 15.0% | -1.06 | -63.77 | 0.27 |


## H3_gappers — VWAP con stops amplios — gappers

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 837 | 44.6% | -0.08 | -64.55 | 0.84 |
| largo | 898 | 49.2% | -0.02 | -19.58 | 0.95 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 57 | 52.6% | -0.00 | -0.21 | 0.98 |
| stop | 571 | 0.0% | -1.10 | -629.90 | 0.00 |
| target | 325 | 100.0% | 1.30 | 423.22 | -inf |
| time | 782 | 58.8% | 0.16 | 122.77 | 2.11 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 109 | 56.9% | 0.14 | 15.75 | 1.40 |
| 2025-01 | 111 | 36.9% | -0.13 | -14.35 | 0.71 |
| 2025-02 | 139 | 47.5% | -0.11 | -14.91 | 0.77 |
| 2025-03 | 115 | 50.4% | 0.07 | 7.87 | 1.19 |
| 2025-04 | 109 | 38.5% | -0.17 | -18.71 | 0.62 |
| 2025-05 | 150 | 52.0% | 0.03 | 4.39 | 1.07 |
| 2025-06 | 138 | 46.4% | -0.03 | -3.93 | 0.93 |
| 2025-07 | 155 | 51.6% | -0.01 | -1.92 | 0.97 |
| 2025-08 | 140 | 42.1% | -0.14 | -19.91 | 0.71 |
| 2025-09 | 140 | 50.0% | 0.02 | 2.12 | 1.04 |
| 2025-10 | 189 | 46.0% | -0.05 | -9.07 | 0.89 |
| 2025-11 | 130 | 50.8% | -0.06 | -7.26 | 0.87 |
| 2025-12 | 110 | 38.2% | -0.22 | -24.21 | 0.56 |


## H3_control — VWAP con stops amplios — control (50 líquidos)

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 1222 | 46.6% | -0.08 | -95.02 | 0.78 |
| largo | 1085 | 49.2% | -0.04 | -45.07 | 0.88 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 78 | 56.4% | 0.06 | 4.90 | 1.44 |
| stop | 522 | 0.0% | -1.07 | -559.78 | 0.00 |
| target | 320 | 100.0% | 1.15 | 367.10 | -inf |
| time | 1387 | 53.4% | 0.03 | 47.68 | 1.20 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 170 | 53.5% | 0.00 | 0.65 | 1.01 |
| 2025-01 | 190 | 49.5% | -0.02 | -2.90 | 0.95 |
| 2025-02 | 184 | 47.3% | -0.06 | -10.46 | 0.84 |
| 2025-03 | 180 | 37.8% | -0.15 | -26.74 | 0.60 |
| 2025-04 | 142 | 42.3% | -0.16 | -22.89 | 0.59 |
| 2025-05 | 184 | 52.7% | -0.04 | -7.90 | 0.87 |
| 2025-06 | 181 | 50.8% | -0.01 | -2.38 | 0.96 |
| 2025-07 | 192 | 53.6% | 0.00 | 0.91 | 1.01 |
| 2025-08 | 172 | 47.7% | -0.06 | -9.99 | 0.83 |
| 2025-09 | 188 | 49.5% | -0.07 | -12.91 | 0.80 |
| 2025-10 | 200 | 42.5% | -0.15 | -30.86 | 0.64 |
| 2025-11 | 167 | 45.5% | -0.07 | -11.47 | 0.82 |
| 2025-12 | 157 | 48.4% | -0.02 | -3.15 | 0.94 |


## H4 — Meta-labeling LightGBM sobre H1 ∪ H2 (walk-forward; tras 4 meses de entrenamiento)

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 3 | 33.3% | -0.75 | -2.24 | 0.08 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 1 | 100.0% | 0.18 | 0.18 | -inf |
| stop | 2 | 0.0% | -1.21 | -2.42 | 0.00 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2025-04 | 1 | 0.0% | -1.20 | -1.20 | 0.00 |
| 2025-05 | 1 | 0.0% | -1.23 | -1.23 | 0.00 |
| 2025-12 | 1 | 100.0% | 0.18 | 0.18 | -inf |


## H5a — H1 solo en días de régimen volátil (HMM)

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 119 | 6.7% | -1.47 | -175.16 | 0.08 |
| largo | 84 | 7.1% | -1.37 | -114.99 | 0.22 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 4 | 100.0% | 7.29 | 29.17 | -inf |
| stop | 199 | 5.0% | -1.60 | -319.31 | 0.06 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 8 | 0.0% | -1.81 | -14.47 | 0.00 |
| 2025-01 | 7 | 0.0% | -2.07 | -14.46 | 0.00 |
| 2025-02 | 12 | 0.0% | -1.82 | -21.89 | 0.00 |
| 2025-03 | 51 | 7.8% | -1.49 | -75.99 | 0.10 |
| 2025-04 | 74 | 10.8% | -1.11 | -82.50 | 0.21 |
| 2025-05 | 19 | 5.3% | -1.95 | -37.09 | 0.06 |
| 2025-10 | 12 | 0.0% | -1.83 | -21.99 | 0.00 |
| 2025-11 | 20 | 5.0% | -1.09 | -21.76 | 0.43 |


## H5b — H3 gappers solo en días de régimen tranquilo (HMM)

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 628 | 45.7% | -0.06 | -40.26 | 0.86 |
| largo | 665 | 49.8% | -0.01 | -7.11 | 0.97 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 39 | 51.3% | -0.02 | -0.75 | 0.90 |
| stop | 426 | 0.0% | -1.10 | -470.53 | 0.00 |
| target | 248 | 100.0% | 1.31 | 324.78 | -inf |
| time | 580 | 60.3% | 0.17 | 99.12 | 2.24 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 91 | 57.1% | 0.17 | 15.79 | 1.51 |
| 2025-01 | 87 | 37.9% | -0.11 | -9.64 | 0.74 |
| 2025-02 | 112 | 50.0% | -0.06 | -6.97 | 0.86 |
| 2025-03 | 9 | 55.6% | 0.23 | 2.10 | 1.84 |
| 2025-05 | 94 | 57.4% | 0.09 | 8.33 | 1.25 |
| 2025-06 | 138 | 46.4% | -0.03 | -3.93 | 0.93 |
| 2025-07 | 155 | 51.6% | -0.01 | -1.92 | 0.97 |
| 2025-08 | 140 | 42.1% | -0.14 | -19.91 | 0.71 |
| 2025-09 | 140 | 50.0% | 0.02 | 2.12 | 1.04 |
| 2025-10 | 139 | 46.0% | -0.04 | -5.62 | 0.91 |
| 2025-11 | 78 | 50.0% | -0.04 | -3.51 | 0.90 |
| 2025-12 | 110 | 38.2% | -0.22 | -24.21 | 0.56 |


---
Sharpe diarios de los 6 intentos de la ronda 1 usados en el DSR: -0.131, -0.313, -0.230, -0.321, -0.545, -0.381.
