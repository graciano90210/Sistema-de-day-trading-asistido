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
  # Red de seguridad: si faltan las diarias de la sesión anterior (PC apagado, corte), actualizarlas antes.
  "$UV" run daytrader data-fresh || { COLUMNS=120 "$UV" run daytrader ingest && COLUMNS=120 "$UV" run daytrader universe; }
  COLUMNS=140 "$UV" run daytrader watchlist --date "$D"
  echo "== fin $(date -Is) código $?"
} >> "$LOG" 2>&1
