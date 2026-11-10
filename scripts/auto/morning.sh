#!/usr/bin/env bash
# Rutina de mañana (09:40 ET, lun–vie): watchlist del día (cutoff 09:25 ET; el plan gratuito exige 15 min de retraso).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
UV="${UV:-$HOME/.local/bin/uv}"
D=$(TZ=America/New_York date +%F)
LOG="reports/auto/morning_${D}.log"; mkdir -p reports/auto
{
  echo "== morning $D $(date -Is)"
  "$UV" run daytrader is-session || { echo "sin sesión: nada que hacer"; exit 0; }
  # Red de seguridad (2026-11-10): si la rutina nocturna de la sesión anterior no terminó, actualizar diarias ahora.
  for i in 1 2 3; do P=$(date -d "$D -$i day" +%F); [ "$(date -d "$P" +%u)" -le 5 ] && break; done
  if ! grep -q "código 0" "reports/auto/nightly_${P}.log" 2>/dev/null; then
    echo "nightly ${P} incompleto: actualizo datos antes de la watchlist"
    COLUMNS=120 "$UV" run daytrader ingest && COLUMNS=120 "$UV" run daytrader universe
  fi
  COLUMNS=140 "$UV" run daytrader watchlist --date "$D"
  echo "== fin $(date -Is) código $?"
} >> "$LOG" 2>&1
