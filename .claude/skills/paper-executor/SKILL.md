---
name: paper-executor
description: Envía órdenes bracket a la cuenta PAPER de Alpaca solo tras confirmación explícita y/n del usuario en consola, con re-verificación de precio y reglas, cierre forzado autorizado y sincronización de ejecuciones al journal. Úsala cuando el usuario quiera operar en paper, ver posiciones o cerrar todo.
---

# paper-executor

Código: `src/daytrader/execution/` (único paquete autorizado a usar TradingClient; siempre paper).

## Comandos (los ejecuta el USUARIO en su terminal: la confirmación y/n es suya)
```bash
uv run daytrader trade NVDA largo --stop 182.50 --objetivo 190 --setup ORB --catalizador earnings
uv run daytrader trade TSLA corto --stop 251 --limite 248.5
uv run daytrader positions          # capital, PnL del día, posiciones, contador de trades
uv run daytrader guard              # pide autorización y cierra todo a las 15:50 ET
uv run daytrader flatten            # cierre manual inmediato (pide y/n)
uv run daytrader sync               # trae ejecuciones reales al journal
```

## Reglas para Claude
- NUNCA responder "y" por el usuario ni ejecutar `trade`/`flatten` con la entrada redirigida a "y".
- Nunca crear ni usar keys de la cuenta live (prefijo AK). Si aparecen, detenerse y avisar.
- La confirmación caduca (60 s) y se cancela si el precio se movió > 0,25 R.
- Datos en vivo: cotización IEX (el plan gratuito no da SIP en tiempo real).
