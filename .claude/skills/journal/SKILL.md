---
name: journal
description: Journal de operaciones paper en DuckDB (data/journal.duckdb): tickets con su estado (enviado, rechazado, declinado, caducado, deriva), trades cerrados con R y slippage real, notas y errores cometidos. Úsala para revisar el desempeño del usuario, añadir notas o comparar el slippage real con el modelo del backtester.
---

# journal

Código: `src/daytrader/execution/journal.py` y `sync.py`.

```bash
uv run daytrader journal --days 30                      # resumen: win rate, R medio, PF, slippage real
uv run daytrader note <huella> "entré tarde" --error      # registrar un error cometido
uv run daytrader sync --date 2026-11-05                   # sincronizar ejecuciones de un día
```

## Al analizar
- Los números salen de SQL/Python; Claude interpreta.
- Con menos de ~100 trades cerrados, cualquier conclusión sobre "edge" es ruido: decirlo.
- `entry_slippage_r` frente al modelo del backtester (~0,03–0,07 R ida y vuelta en VWAP) valida o corrige el modelo de costos.
