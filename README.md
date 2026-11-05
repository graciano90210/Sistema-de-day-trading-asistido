# Sistema de day trading asistido

Sistema de investigación y **paper trading** intradía para acciones de EE. UU. Inspirado en
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill), con más rigor estadístico:
datos SIP de 1 minuto, cero lookahead verificado con tests, costos realistas y validación out-of-sample.

> ⚠️ Solo paper trading. No existe camino en el código hacia una cuenta real (ver `tests/test_safety.py`).
> Nada de esto es consejo financiero.

## Estado por fases
| Fase | Contenido | Estado |
|---|---|---|
| 1 | Repo, entorno, tests base, **data-ingest** (DuckDB) | ✅ |
| 2 | Scanner + catalysts | ✅ |
| 3 | Strategies + backtester + 3 rondas pre-registradas (25 intentos) | ✅ — sin edge intradía |
| 4 | Validación: walk-forward, DSR, costos calibrados; OOS 2026 sellado (nada que validar) | ✅ |
| 5 | Risk-manager + paper-executor (y/n) + journal | ✅ |
| 6 | Dashboard Streamlit | ⏳ |

## Puesta en marcha
```bash
uv sync
cp .env.example .env        # pon tus keys de la cuenta PAPER de Alpaca
uv run pytest               # tests (no requieren red ni keys)
uv run daytrader ingest     # descarga 2 años de barras 1m + 1d (incremental, reanudable)
uv run daytrader quality    # reports/data_quality.md
uv run daytrader info

# Operativa paper (fase 5): tú propones, el sistema dimensiona, verifica y pide y/n
uv run daytrader trade NVDA largo --stop 182.5 --objetivo 190
uv run daytrader positions && uv run daytrader journal
```

## Estructura
```
config/            settings.yaml, universe.yaml (y luego strategies/*.yaml)
src/daytrader/     paquete Python (toda la lógica)
  market_calendar.py   sesiones NYSE, half-days, pre/rth/post
  data/                alpaca_client, store (DuckDB), ingest, quality, access (point-in-time)
.claude/skills/    una skill por módulo (SKILL.md + scripts/ que llaman al paquete)
tests/             safety, calendario, store/ingesta, calidad, no-lookahead
data/              market.duckdb (ignorado por git)
reports/           reportes generados
```

## Convenciones anti-lookahead
- `ts_utc` = inicio de la barra; `available_at` = cuándo se puede conocer (1m: +1 min; 1d: 20:00 ET).
- Toda lectura de datos en estrategias pasa por `daytrader.data.access` con un `as_of` explícito.
- `resample()` descarta buckets que aún no han cerrado.

## Conclusión de la investigación (fase 3)
Tres rondas pre-registradas (`docs/preregistro_ronda*.md`), 25 configuraciones: ORB 5/15, reversión a VWAP,
ORB en *stocks in play* (réplica de Zarattini et al. 2024), filtros HMM, meta-labeling LightGBM y órdenes límite.
Ninguna tiene expectancy neta positiva; sin costos, ninguna es distinta de cero. Ver `reports/`.

## Limitaciones conocidas
- **Sesgo de supervivencia**: el universo de 50 tickers se eligió con información de 2026.
- Las barras de 1 min solo existen si hubo operaciones en ese minuto.
- Barras SIP vía plan gratuito de Alpaca: históricas OK; sin los últimos 15 minutos.
