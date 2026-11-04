---
name: data-ingest
description: Descarga y cachea en DuckDB barras históricas de 1 minuto y diarias (Alpaca, feed SIP, precios raw) y genera el reporte de calidad de datos. Úsala cuando haya que poblar o actualizar data/market.duckdb, añadir tickers al universo o revisar la calidad/cobertura de los datos.
---

# data-ingest

Wrapper delgado sobre `src/daytrader/data/`. Toda la lógica y los números los calcula Python.

## Cuándo usarla
- Poblar la DB por primera vez o ponerla al día (la ingesta es incremental y reanudable).
- Añadir símbolos: editar `config/universe.yaml` y volver a ejecutar la ingesta.
- Auditar los datos antes de hacer backtests.

## Requisitos
- `.env` con `ALPACA_API_KEY` y `ALPACA_SECRET_KEY` de la cuenta **paper** (ver `.env.example`).
- Esta skill solo usa la API de **datos**; no puede enviar órdenes.

## Comandos
```bash
uv run python .claude/skills/data-ingest/scripts/ingest.py                 # universo completo, 1d + 1m
uv run python .claude/skills/data-ingest/scripts/ingest.py --symbols SPY,AAPL --timeframe 1m
uv run python .claude/skills/data-ingest/scripts/quality_report.py         # → reports/data_quality.md
uv run daytrader info                                                      # estado de la caché
```

## Contrato de datos (no romper)
- `ts_utc`: inicio de la barra, naive UTC. `available_at`: primer instante en que la barra es conocible
  (1m: `ts_utc + 1 min`; 1d: 20:00 ET de su sesión).
- Las estrategias leen SIEMPRE vía `daytrader.data.access.get_bars(..., as_of=t)` y `resample(..., as_of=t)`.
- `session` ∈ {pre, rth, post, closed} (1m) o `day` (1d). `session_date` = fecha ET.
- Precios raw; los splits están en la tabla `splits`.

## Cómo interpretar el reporte
- **Integridad** debe estar en OK (0 violaciones). Si no, no hacer backtests hasta resolverlo.
- **Cobertura RTH** < 100% es normal en minutos sin operaciones; para tickers muy líquidos debería ser ~100%.
  Días con cobertura baja suelen ser halts, medias sesiones mal etiquetadas o huecos del proveedor.
- **Sesgo de supervivencia**: el universo se eligió con información actual; decirlo al reportar resultados.
