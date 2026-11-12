#!/usr/bin/env bash
# Rutina nocturna (00:30 ET, mar–sáb): Alpaca (plan gratuito) entrega la barra diaria de una sesión recién
# después de la medianoche ET (a las 20:30 ET respondía "recent SIP data"). Si ya está al día, no hace nada.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
UV="${UV:-$HOME/.local/bin/uv}"
D=$(TZ=America/New_York date +%F)
LOG="reports/auto/nightly_${D}.log"; mkdir -p reports/auto
{
  echo "== nightly $D $(date -Is)"
  "$UV" run daytrader data-fresh && { echo "datos al día: nada que hacer"; exit 0; }
  COLUMNS=120 "$UV" run daytrader ingest && COLUMNS=120 "$UV" run daytrader universe
  echo "== fin $(date -Is) código $?"
} >> "$LOG" 2>&1
