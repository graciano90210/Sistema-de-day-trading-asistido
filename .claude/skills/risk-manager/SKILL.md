---
name: risk-manager
description: Reglas de riesgo del sistema (1% por trade, kill switch diario −3%, máximo de trades y posiciones, stop obligatorio, sin entradas en los últimos 15 min, cierre a las 15:50 ET, poder de compra) y tamaño de posición. Úsala para explicar por qué una orden fue rechazada, calcular un tamaño o cambiar límites en config/risk.yaml.
---

# risk-manager

Código: `src/daytrader/execution/risk.py` (lógica pura, sin red). Límites: `config/risk.yaml`.

- `size_position`: acciones = floor(1% del capital / riesgo por acción), recortado por nocional máximo.
- `check`: devuelve OK solo si se cumplen TODAS las reglas; si no, la lista de motivos (en español).
- Kill switch: PnL del día (equity − last_equity de Alpaca, realizado + flotante) ≤ −3% → sin nuevas entradas.
- Huella (`OrderTicket.fingerprint`): el ejecutor solo envía el ticket exacto que el usuario aprobó.

Al cambiar límites: editar `config/risk.yaml` y correr `uv run pytest tests/test_execution.py`.
Nunca relajar una regla para "dejar pasar" una orden concreta.
