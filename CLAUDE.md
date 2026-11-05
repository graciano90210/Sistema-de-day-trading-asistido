# Sistema de day trading asistido — reglas del proyecto

Sistema de trading intradía para acciones de EE. UU. Investigación y paper trading únicamente.

## Reglas no negociables (aplican a todo el código y a toda sesión)
1. **SOLO paper trading** (Alpaca paper API, `https://paper-api.alpaca.markets`). Nunca enviar órdenes reales.
   Si algún código pudiera tocar una cuenta real: detenerse y avisar. `daytrader.config.assert_paper_url`
   es el único punto de entrada permitido para URLs de trading; `tests/test_safety.py` lo vigila.
2. Toda orden requiere confirmación explícita del usuario en consola (y/n), incluso en paper.
3. Los números los calcula Python, nunca el LLM "a ojo". El LLM interpreta y explica.
4. API keys solo en `.env` (ignorado por git). Nunca en código, YAML, tests ni commits.
5. Cero lookahead bias: toda señal usa solo datos con `available_at <= t`.
   Acceder a barras SIEMPRE vía `daytrader.data.access` (point-in-time), nunca leyendo tablas a mano en estrategias.
6. Trabajo por fases: al terminar cada fase, detenerse, mostrar resultados y esperar OK.

## Convenciones de datos
- Timestamps en DuckDB: `TIMESTAMP` naive en **UTC**. `ts_utc` = **inicio** de la barra (convención Alpaca).
- Barra de 1 min con `ts_utc = 09:30 ET` está disponible a las 09:31 ET → `available_at = ts_utc + 1 min`.
- Barra diaria de la sesión D: `available_at = D 20:00 ET` (fin del post-market, conservador).
- Precios almacenados **raw** (sin ajustar). Splits en la tabla `splits`.
- Feed: SIP. `session` ∈ {pre, rth, post, closed}; `session_date` = fecha ET.
- Barra diaria de Alpaca (verificado en fase 1 sobre 25.100 días): OHLC = solo horario regular
  (open/close ≈ subastas oficiales), pero **volume incluye extended hours**. Para volumen relativo
  intradía, usar sumas de barras de 1 min filtradas por `session`, no el volumen diario.
- Splits en el periodo: LCID 1:10 (2025-09-02), NFLX 10:1 (2025-11-17), CVNA 5:1 (2026-05-08).
  Cualquier cálculo multi-día (ATR, gaps, medias) debe ajustar por splits.

## Stack
Python 3.12 + uv · alpaca-py · polars/pandas · DuckDB (`data/market.duckdb`) · pytest · Streamlit (fase 6).
Lógica en `src/daytrader/`; las skills en `.claude/skills/<nombre>/` son wrappers delgados (SKILL.md + scripts/).

## Estado
Fases 1–6 cerradas. Búsqueda de estrategias intradía cerrada sin edge (25 intentos, ver README).
OOS 2026 sigue sellado. Operativa paper discrecional vía `daytrader trade` (el usuario confirma y/n).

## Comandos
- `uv run pytest` — tests
- `uv run daytrader ingest` — descarga/actualiza datos (incremental, reanudable)
- `uv run daytrader quality` — reporte de calidad en `reports/data_quality.md`
