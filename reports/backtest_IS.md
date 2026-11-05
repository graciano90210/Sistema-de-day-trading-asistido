# Backtest 2024-12-03 → 2025-12-31

Periodo **2024-12-03 → 2025-12-31** (in-sample). Muestra OOS **sellada desde 2026-01-01**: no evaluada.

R = PnL por acción / riesgo planificado (entrada de referencia − stop). *Bruto* = antes de slippage y tasas; *neto* = después. Cartera: 1% de riesgo por trade sobre el capital vigente, límites de posiciones, trades/día, kill switch −3% y poder de compra 4×.

## Resumen

| estrategia | universo | trades | win_rate | R_medio_bruto | R_medio_neto | profit_factor | expectancy_usd | t_stat | retorno | sharpe | max_dd |
|---|---|---|---|---|---|---|---|---|---|---|---|
| orb_5 | gappers | 979 | 36.4% | -0.12 | -0.20 | 0.64 | -88.94 | -6.09 | -87.1% | -5.10 | -87.1% |
| orb_15 | gappers | 762 | 40.2% | -0.11 | -0.16 | 0.63 | -94.00 | -5.36 | -71.6% | -4.97 | -71.7% |
| vwap_rev | gappers | 1665 | 34.2% | 0.06 | -0.22 | 0.74 | -58.81 | -5.53 | -97.9% | -6.05 | -98.0% |
| orb_5 | control | 1546 | 39.7% | -0.03 | -0.12 | 0.78 | -56.14 | -4.30 | -86.8% | -3.65 | -87.4% |
| orb_15 | control | 1579 | 43.3% | -0.00 | -0.06 | 0.85 | -42.91 | -2.70 | -67.8% | -2.08 | -69.5% |
| vwap_rev | control | 1666 | 36.3% | -0.02 | -0.27 | 0.66 | -59.50 | -8.05 | -99.1% | -8.65 | -99.2% |

**SPY buy & hold** en el mismo periodo: retorno 13.0%, Sharpe 0.69, max DD -19.0%.

Criterio de éxito (se juzga en OOS, fase 4): ≥100 trades, profit factor > 1.3, drawdown aceptable, estabilidad ante cambios de parámetros.

## Sensibilidad a costos

Mismas señales; cambia solo el modelo de costos (optimista: k=0.05; base: k=0.10 calibrado con NBBO; pesimista: k=0.20, impacto ×2 y $0.005/acción de comisión).

| estrategia | universo | escenario | trades | R_medio_neto | profit_factor | retorno |
|---|---|---|---|---|---|---|
| orb_15 | control | base | 1579 | -0.06 | 0.85 | -67.8% |
| orb_15 | control | optimista | 1581 | -0.04 | 0.90 | -52.4% |
| orb_15 | control | pesimista | 1579 | -0.13 | 0.72 | -88.4% |
| orb_15 | gappers | base | 762 | -0.16 | 0.63 | -71.6% |
| orb_15 | gappers | optimista | 762 | -0.14 | 0.67 | -66.3% |
| orb_15 | gappers | pesimista | 762 | -0.22 | 0.53 | -81.8% |
| orb_5 | control | base | 1546 | -0.12 | 0.78 | -86.8% |
| orb_5 | control | optimista | 1546 | -0.08 | 0.84 | -75.6% |
| orb_5 | control | pesimista | 1530 | -0.23 | 0.64 | -97.3% |
| orb_5 | gappers | base | 979 | -0.20 | 0.64 | -87.1% |
| orb_5 | gappers | optimista | 979 | -0.16 | 0.69 | -81.0% |
| orb_5 | gappers | pesimista | 979 | -0.29 | 0.53 | -94.8% |
| vwap_rev | control | base | 1666 | -0.27 | 0.66 | -99.1% |
| vwap_rev | control | optimista | 1731 | -0.19 | 0.74 | -96.7% |
| vwap_rev | control | pesimista | 1402 | -0.54 | 0.46 | -100.0% |
| vwap_rev | gappers | base | 1665 | -0.22 | 0.74 | -97.9% |
| vwap_rev | gappers | optimista | 1727 | -0.10 | 0.87 | -85.4% |
| vwap_rev | gappers | pesimista | 1430 | -0.54 | 0.50 | -100.0% |


## orb_5 · gappers

Cartera: retorno -87.1% · CAGR -85.2% · Sharpe -5.10 · Sortino -7.74 · max DD -87.1% (270 sesiones). Trades descartados por la cartera: 92.

Costos medios: slippage $0.083/acción · R bruto→neto -0.119 → -0.201.

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 452 | 39.4% | -0.16 | -70.98 | 0.70 |
| largo | 527 | 33.8% | -0.24 | -125.97 | 0.60 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 449 | 57.2% | 0.19 | 84.35 | 2.17 |
| stop | 431 | 0.0% | -1.10 | -474.51 | 0.00 |
| target | 99 | 100.0% | 1.95 | 193.20 | -inf |

### Por hora de entrada (ET)

| hora_entrada_et | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 09:00 | 842 | 35.6% | -0.21 | -172.62 | 0.65 |
| 10:00 | 111 | 41.4% | -0.18 | -19.55 | 0.59 |
| 11:00 | 7 | 14.3% | -0.42 | -2.93 | 0.17 |
| 12:00 | 11 | 36.4% | -0.18 | -1.96 | 0.49 |
| 13:00 | 4 | 50.0% | -0.17 | -0.70 | 0.30 |
| 14:00 | 4 | 75.0% | 0.20 | 0.80 | 4.23 |

### Por |gap|

| gap_abs | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 3-5% | 337 | 37.7% | -0.21 | -70.33 | 0.61 |
| 5-10% | 402 | 35.3% | -0.22 | -88.93 | 0.62 |
| >10% | 240 | 36.2% | -0.16 | -37.70 | 0.72 |

### Por catalizador

| catalyst | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| analyst | 38 | 23.7% | -0.44 | -16.61 | 0.38 |
| analyst_pt | 41 | 36.6% | -0.20 | -8.34 | 0.63 |
| contract | 25 | 36.0% | -0.12 | -2.96 | 0.80 |
| earnings | 211 | 40.8% | -0.14 | -30.20 | 0.72 |
| fda_clinical | 23 | 30.4% | -0.15 | -3.55 | 0.69 |
| guidance | 13 | 30.8% | -0.21 | -2.73 | 0.61 |
| legal_regulatory | 6 | 66.7% | 0.46 | 2.79 | 2.25 |
| m&a | 41 | 36.6% | -0.13 | -5.17 | 0.76 |
| offering | 47 | 29.8% | -0.33 | -15.66 | 0.42 |
| sin_catalizador | 266 | 36.5% | -0.21 | -56.30 | 0.63 |
| sin_noticias | 264 | 35.6% | -0.23 | -60.84 | 0.60 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 59 | 33.9% | -0.25 | -14.98 | 0.55 |
| 2025-01 | 71 | 49.3% | 0.15 | 10.66 | 1.44 |
| 2025-02 | 79 | 31.6% | -0.19 | -14.83 | 0.67 |
| 2025-03 | 86 | 30.2% | -0.37 | -31.74 | 0.42 |
| 2025-04 | 91 | 41.8% | -0.10 | -8.97 | 0.83 |
| 2025-05 | 72 | 31.9% | -0.29 | -20.80 | 0.51 |
| 2025-06 | 59 | 40.7% | -0.13 | -7.68 | 0.74 |
| 2025-07 | 73 | 31.5% | -0.27 | -19.53 | 0.56 |
| 2025-08 | 70 | 45.7% | -0.00 | -0.22 | 0.99 |
| 2025-09 | 93 | 36.6% | -0.22 | -20.61 | 0.59 |
| 2025-10 | 93 | 29.0% | -0.36 | -33.80 | 0.44 |
| 2025-11 | 72 | 40.3% | -0.28 | -19.87 | 0.54 |
| 2025-12 | 61 | 32.8% | -0.24 | -14.60 | 0.60 |


## orb_15 · gappers

Cartera: retorno -71.6% · CAGR -69.1% · Sharpe -4.97 · Sortino -6.97 · max DD -71.7% (270 sesiones). Trades descartados por la cartera: 48.

Costos medios: slippage $0.052/acción · R bruto→neto -0.111 → -0.161.

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 343 | 46.1% | -0.10 | -33.35 | 0.74 |
| largo | 419 | 35.3% | -0.21 | -89.62 | 0.55 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 492 | 55.7% | 0.14 | 67.81 | 1.91 |
| stop | 238 | 0.0% | -1.07 | -253.83 | 0.00 |
| target | 32 | 100.0% | 1.97 | 63.05 | -inf |

### Por hora de entrada (ET)

| hora_entrada_et | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 09:00 | 418 | 38.8% | -0.19 | -78.05 | 0.61 |
| 10:00 | 254 | 42.1% | -0.15 | -38.46 | 0.64 |
| 11:00 | 38 | 42.1% | -0.06 | -2.16 | 0.79 |
| 12:00 | 24 | 33.3% | -0.15 | -3.60 | 0.46 |
| 13:00 | 14 | 35.7% | -0.14 | -2.00 | 0.21 |
| 14:00 | 12 | 50.0% | 0.09 | 1.10 | 1.81 |
| 15:00 | 2 | 100.0% | 0.10 | 0.21 | -inf |

### Por |gap|

| gap_abs | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 3-5% | 309 | 38.8% | -0.20 | -61.25 | 0.54 |
| 5-10% | 298 | 41.3% | -0.12 | -36.75 | 0.71 |
| >10% | 155 | 40.6% | -0.16 | -24.97 | 0.64 |

### Por catalizador

| catalyst | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| analyst | 28 | 39.3% | -0.26 | -7.28 | 0.46 |
| analyst_pt | 24 | 45.8% | -0.14 | -3.24 | 0.67 |
| contract | 15 | 53.3% | 0.11 | 1.59 | 1.28 |
| earnings | 136 | 48.5% | -0.01 | -1.96 | 0.96 |
| fda_clinical | 13 | 30.8% | -0.16 | -2.06 | 0.70 |
| guidance | 10 | 40.0% | -0.24 | -2.42 | 0.23 |
| legal_regulatory | 6 | 83.3% | 0.36 | 2.14 | 3.08 |
| m&a | 29 | 31.0% | -0.30 | -8.59 | 0.43 |
| offering | 43 | 34.9% | -0.32 | -13.57 | 0.32 |
| sin_catalizador | 216 | 38.0% | -0.20 | -42.54 | 0.55 |
| sin_noticias | 240 | 37.5% | -0.19 | -46.38 | 0.58 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 45 | 28.9% | -0.28 | -12.45 | 0.42 |
| 2025-01 | 59 | 40.7% | -0.15 | -8.87 | 0.59 |
| 2025-02 | 67 | 26.9% | -0.35 | -23.39 | 0.37 |
| 2025-03 | 57 | 42.1% | -0.28 | -15.86 | 0.44 |
| 2025-04 | 73 | 46.6% | -0.08 | -5.53 | 0.82 |
| 2025-05 | 44 | 47.7% | -0.01 | -0.45 | 0.97 |
| 2025-06 | 53 | 43.4% | -0.10 | -5.07 | 0.71 |
| 2025-07 | 55 | 40.0% | -0.04 | -2.25 | 0.90 |
| 2025-08 | 56 | 50.0% | -0.03 | -1.70 | 0.92 |
| 2025-09 | 74 | 37.8% | -0.14 | -10.65 | 0.64 |
| 2025-10 | 77 | 40.3% | -0.17 | -13.22 | 0.62 |
| 2025-11 | 56 | 42.9% | -0.26 | -14.65 | 0.46 |
| 2025-12 | 46 | 34.8% | -0.19 | -8.88 | 0.56 |


## vwap_rev · gappers

Cartera: retorno -97.9% · CAGR -97.3% · Sharpe -6.05 · Sortino -10.46 · max DD -98.0% (265 sesiones). Trades descartados por la cartera: 1246.

Costos medios: slippage $0.060/acción · R bruto→neto +0.059 → -0.219.

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 784 | 36.0% | -0.15 | -114.17 | 0.82 |
| largo | 881 | 32.6% | -0.28 | -250.89 | 0.67 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 1 | 0.0% | -0.05 | -0.05 | 0.00 |
| stop | 1019 | 0.0% | -1.33 | -1354.44 | 0.00 |
| target | 405 | 100.0% | 2.08 | 844.24 | -inf |
| time | 240 | 68.3% | 0.60 | 145.19 | 5.06 |

### Por hora de entrada (ET)

| hora_entrada_et | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 10:00 | 1324 | 34.9% | -0.19 | -257.96 | 0.76 |
| 11:00 | 197 | 34.5% | -0.18 | -35.06 | 0.79 |
| 12:00 | 90 | 25.6% | -0.53 | -47.79 | 0.43 |
| 13:00 | 32 | 28.1% | -0.63 | -20.23 | 0.32 |
| 14:00 | 22 | 31.8% | -0.18 | -4.02 | 0.75 |

### Por |gap|

| gap_abs | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 3-5% | 423 | 33.6% | -0.28 | -116.34 | 0.68 |
| 5-10% | 666 | 32.9% | -0.24 | -163.16 | 0.71 |
| >10% | 576 | 36.1% | -0.15 | -85.56 | 0.82 |

### Por catalizador

| catalyst | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| analyst | 43 | 48.8% | 0.24 | 10.13 | 1.37 |
| analyst_pt | 46 | 26.1% | -0.49 | -22.62 | 0.45 |
| contract | 43 | 23.3% | -0.51 | -21.79 | 0.52 |
| earnings | 483 | 32.7% | -0.21 | -101.15 | 0.75 |
| fda_clinical | 52 | 25.0% | -0.50 | -25.91 | 0.47 |
| guidance | 14 | 35.7% | -0.21 | -2.97 | 0.74 |
| legal_regulatory | 9 | 33.3% | -0.20 | -1.77 | 0.76 |
| m&a | 77 | 44.2% | 0.03 | 2.02 | 1.04 |
| offering | 66 | 36.4% | -0.12 | -7.77 | 0.85 |
| sin_catalizador | 441 | 34.2% | -0.19 | -84.67 | 0.76 |
| sin_noticias | 390 | 35.4% | -0.28 | -107.43 | 0.68 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 99 | 34.3% | -0.26 | -25.79 | 0.69 |
| 2025-01 | 106 | 25.5% | -0.44 | -46.32 | 0.52 |
| 2025-02 | 151 | 37.7% | -0.15 | -22.18 | 0.81 |
| 2025-03 | 113 | 36.3% | -0.29 | -32.36 | 0.67 |
| 2025-04 | 116 | 34.5% | -0.39 | -44.74 | 0.55 |
| 2025-05 | 140 | 36.4% | -0.17 | -23.40 | 0.79 |
| 2025-06 | 130 | 34.6% | -0.20 | -26.35 | 0.76 |
| 2025-07 | 132 | 35.6% | -0.17 | -22.71 | 0.81 |
| 2025-08 | 114 | 29.8% | -0.45 | -50.86 | 0.48 |
| 2025-09 | 137 | 37.2% | 0.03 | 4.08 | 1.04 |
| 2025-10 | 188 | 35.1% | -0.11 | -19.86 | 0.87 |
| 2025-11 | 120 | 35.0% | -0.15 | -17.62 | 0.82 |
| 2025-12 | 119 | 28.6% | -0.31 | -36.95 | 0.62 |


## orb_5 · control

Cartera: retorno -86.8% · CAGR -84.9% · Sharpe -3.65 · Sortino -5.91 · max DD -87.4% (269 sesiones). Trades descartados por la cartera: 4892.

Costos medios: slippage $0.096/acción · R bruto→neto -0.029 → -0.122.

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 658 | 39.7% | -0.12 | -76.52 | 0.79 |
| largo | 888 | 39.6% | -0.13 | -112.72 | 0.77 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 654 | 61.2% | 0.24 | 158.60 | 2.67 |
| stop | 679 | 0.0% | -1.12 | -762.01 | 0.00 |
| target | 213 | 100.0% | 1.94 | 414.17 | -inf |

### Por hora de entrada (ET)

| hora_entrada_et | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 09:00 | 1330 | 39.6% | -0.12 | -163.36 | 0.79 |
| 10:00 | 145 | 41.4% | -0.12 | -16.83 | 0.72 |
| 11:00 | 38 | 42.1% | -0.10 | -3.72 | 0.71 |
| 12:00 | 14 | 21.4% | -0.23 | -3.20 | 0.29 |
| 13:00 | 5 | 20.0% | -0.39 | -1.97 | 0.11 |
| 14:00 | 5 | 60.0% | 0.06 | 0.32 | 1.52 |
| 15:00 | 9 | 33.3% | -0.05 | -0.48 | 0.36 |

### Por |gap|

| gap_abs | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 3-5% | 1503 | 39.3% | -0.13 | -195.12 | 0.77 |
| 5-10% | 38 | 50.0% | 0.18 | 6.65 | 1.40 |
| >10% | 5 | 60.0% | -0.15 | -0.77 | 0.65 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 115 | 36.5% | -0.22 | -25.67 | 0.60 |
| 2025-01 | 115 | 33.0% | -0.23 | -26.50 | 0.61 |
| 2025-02 | 113 | 38.1% | -0.21 | -23.70 | 0.66 |
| 2025-03 | 122 | 46.7% | 0.00 | 0.22 | 1.00 |
| 2025-04 | 120 | 42.5% | -0.10 | -11.82 | 0.83 |
| 2025-05 | 123 | 42.3% | -0.06 | -6.81 | 0.89 |
| 2025-06 | 120 | 44.2% | 0.00 | 0.36 | 1.01 |
| 2025-07 | 125 | 36.0% | -0.11 | -13.45 | 0.79 |
| 2025-08 | 110 | 47.3% | -0.04 | -3.87 | 0.92 |
| 2025-09 | 121 | 35.5% | -0.12 | -14.49 | 0.78 |
| 2025-10 | 136 | 34.6% | -0.25 | -34.31 | 0.58 |
| 2025-11 | 113 | 45.1% | 0.01 | 1.43 | 1.02 |
| 2025-12 | 113 | 34.5% | -0.27 | -30.62 | 0.55 |


## orb_15 · control

Cartera: retorno -67.8% · CAGR -65.2% · Sharpe -2.08 · Sortino -3.52 · max DD -69.5% (269 sesiones). Trades descartados por la cartera: 4674.

Costos medios: slippage $0.072/acción · R bruto→neto -0.005 → -0.064.

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 683 | 44.5% | -0.05 | -33.39 | 0.88 |
| largo | 896 | 42.3% | -0.08 | -68.21 | 0.83 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 962 | 57.3% | 0.17 | 163.34 | 2.12 |
| stop | 485 | 0.0% | -1.08 | -523.55 | 0.00 |
| target | 132 | 100.0% | 1.96 | 258.61 | -inf |

### Por hora de entrada (ET)

| hora_entrada_et | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 09:00 | 1248 | 43.5% | -0.05 | -67.04 | 0.88 |
| 10:00 | 179 | 40.2% | -0.13 | -22.89 | 0.70 |
| 11:00 | 73 | 50.7% | -0.06 | -4.62 | 0.78 |
| 12:00 | 37 | 35.1% | -0.14 | -5.24 | 0.52 |
| 13:00 | 20 | 40.0% | -0.02 | -0.41 | 0.90 |
| 14:00 | 15 | 53.3% | -0.05 | -0.79 | 0.73 |
| 15:00 | 7 | 28.6% | -0.09 | -0.62 | 0.31 |

### Por |gap|

| gap_abs | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 3-5% | 1534 | 43.1% | -0.07 | -109.19 | 0.83 |
| 5-10% | 40 | 45.0% | 0.08 | 3.03 | 1.17 |
| >10% | 5 | 80.0% | 0.91 | 4.56 | 17.91 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 108 | 36.1% | -0.19 | -20.46 | 0.60 |
| 2025-01 | 116 | 37.1% | -0.20 | -22.74 | 0.56 |
| 2025-02 | 117 | 43.6% | -0.07 | -8.18 | 0.84 |
| 2025-03 | 126 | 49.2% | 0.05 | 6.38 | 1.12 |
| 2025-04 | 116 | 48.3% | 0.08 | 8.73 | 1.17 |
| 2025-05 | 124 | 41.9% | -0.04 | -5.43 | 0.90 |
| 2025-06 | 123 | 50.4% | 0.08 | 9.53 | 1.21 |
| 2025-07 | 134 | 41.8% | -0.03 | -4.51 | 0.92 |
| 2025-08 | 119 | 37.8% | -0.12 | -14.41 | 0.72 |
| 2025-09 | 126 | 42.9% | -0.05 | -6.17 | 0.86 |
| 2025-10 | 139 | 46.8% | -0.11 | -15.12 | 0.75 |
| 2025-11 | 111 | 48.6% | 0.01 | 0.88 | 1.02 |
| 2025-12 | 120 | 36.7% | -0.25 | -30.10 | 0.46 |


## vwap_rev · control

Cartera: retorno -99.1% · CAGR -98.8% · Sharpe -8.65 · Sortino -14.09 · max DD -99.2% (268 sesiones). Trades descartados por la cartera: 11126.

Costos medios: slippage $0.059/acción · R bruto→neto -0.018 → -0.274.

### Por dirección

| direccion | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| corto | 820 | 36.5% | -0.24 | -197.19 | 0.70 |
| largo | 846 | 36.1% | -0.31 | -259.68 | 0.62 |

### Por motivo de salida

| exit_reason | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| eod | 1 | 100.0% | 1.99 | 1.99 | -inf |
| stop | 993 | 0.0% | -1.31 | -1298.76 | 0.00 |
| target | 474 | 100.0% | 1.59 | 753.68 | -inf |
| time | 198 | 65.2% | 0.44 | 86.21 | 3.59 |

### Por hora de entrada (ET)

| hora_entrada_et | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 10:00 | 1185 | 37.8% | -0.24 | -283.63 | 0.69 |
| 11:00 | 271 | 33.6% | -0.34 | -92.94 | 0.60 |
| 12:00 | 125 | 30.4% | -0.44 | -54.48 | 0.50 |
| 13:00 | 52 | 25.0% | -0.46 | -23.94 | 0.47 |
| 14:00 | 31 | 41.9% | -0.08 | -2.62 | 0.88 |
| 15:00 | 2 | 50.0% | 0.37 | 0.75 | 1.61 |

### Por |gap|

| gap_abs | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 3-5% | 1565 | 36.9% | -0.26 | -406.25 | 0.67 |
| 5-10% | 87 | 26.4% | -0.54 | -47.28 | 0.41 |
| >10% | 14 | 28.6% | -0.24 | -3.35 | 0.68 |

### Por mes

| mes | trades | win_rate | avg_r | sum_r | profit_factor |
|---|---|---|---|---|---|
| 2024-12 | 119 | 35.3% | -0.30 | -35.72 | 0.63 |
| 2025-01 | 126 | 37.3% | -0.26 | -32.65 | 0.67 |
| 2025-02 | 106 | 34.0% | -0.35 | -37.37 | 0.57 |
| 2025-03 | 141 | 30.5% | -0.45 | -64.14 | 0.47 |
| 2025-04 | 171 | 35.1% | -0.28 | -47.06 | 0.66 |
| 2025-05 | 125 | 36.8% | -0.23 | -28.44 | 0.72 |
| 2025-06 | 116 | 41.4% | -0.17 | -20.25 | 0.76 |
| 2025-07 | 122 | 38.5% | -0.17 | -21.30 | 0.78 |
| 2025-08 | 105 | 36.2% | -0.35 | -36.64 | 0.57 |
| 2025-09 | 117 | 29.1% | -0.41 | -48.44 | 0.53 |
| 2025-10 | 140 | 31.4% | -0.40 | -55.58 | 0.54 |
| 2025-11 | 135 | 38.5% | -0.19 | -25.03 | 0.76 |
| 2025-12 | 143 | 46.9% | -0.03 | -4.26 | 0.96 |


---
Configuración usada:

```yaml
strategies:
  orb_5:
    type: orb
    or_minutes: 5
    direction: with_gap
    stop: or_opposite
    target_r: 2.0
    min_range_atr: 0.05
    max_range_atr: 1.0
    min_or_bars: 3
    last_entry_et: '15:45'
  orb_15:
    type: orb
    or_minutes: 15
    direction: with_gap
    stop: or_opposite
    target_r: 2.0
    min_range_atr: 0.05
    max_range_atr: 1.0
    min_or_bars: 8
    last_entry_et: '15:45'
  vwap_rev:
    type: vwap_reversion
    k_sigma: 2.0
    min_bars: 30
    lookback_extreme: 10
    stop_buffer_atr: 0.02
    min_rr: 1.0
    max_hold_minutes: 60
    first_entry_et: '10:00'
    last_entry_et: '15:00'
    direction: both
    max_trades_per_symbol: 1
holdout_start: '2026-01-01'
in_sample_start: '2024-12-03'
account:
  initial_equity: 100000
  risk_per_trade: 0.01
  max_positions: 5
  max_trades_per_day: 10
  daily_loss_limit: 0.03
  buying_power_mult: 4.0
execution:
  eod_exit_et: '15:50'
  stop_slippage_mult: 1.5
cost_scenarios:
  optimista:
    half_spread_k: 0.05
    impact_k: 0.25
  pesimista:
    half_spread_k: 0.2
    impact_k: 1.0
    commission_per_share: 0.005
costs:
  commission_per_share: 0.0
  sec_fee_rate: 2.78e-05
  taf_per_share: 0.000166
  taf_max: 8.3
  min_half_spread: 0.005
  half_spread_k: 0.1
  impact_k: 0.5
  lookback_bars: 30

```
