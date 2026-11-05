---
name: dashboard
description: Dashboard Streamlit del proyecto con dos vistas — operativa paper del usuario (journal: curva de capital, drawdown, distribución de R, métricas por setup, hora y ticker, slippage real) e investigación (los backtests de las 3 rondas frente a SPY). Úsala para abrir el dashboard, explicar sus gráficos o añadir una vista.
---

# dashboard

Código: `src/daytrader/dashboard/` — `data.py` (funciones puras, testeadas en `tests/test_dashboard.py`) y `app.py` (solo dibuja).

```bash
uv run daytrader dashboard            # abre http://localhost:8501
```

## Vistas
- **Mi operativa (paper)**: lee `data/journal.duckdb` (tras `daytrader sync`). KPIs con IC 95% del R medio, curva de capital,
  drawdown, distribución de R, R por hora/ticker/setup, slippage real de entrada, tickets y notas/errores.
- **Investigación (backtests)**: lee `data/backtests/*.parquet` (rondas 1–3). Selector de configuración, curva vs SPY, tabla resumen.
- **Cómo leer esto**: glosario (R, expectancy, profit factor, drawdown).

## Reglas de visualización
Paleta validada (guía dataviz): azul = estrategia/ganancias, naranja = SPY, rojo = pérdidas/drawdown; un solo eje Y por gráfico;
tablas desplegables como vista accesible. Los números se calculan en `data.py`, nunca en la UI ni "a ojo".
Con < 100 trades el dashboard lo advierte: no sacar conclusiones de edge.
