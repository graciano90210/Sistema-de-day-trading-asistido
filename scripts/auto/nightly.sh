#!/usr/bin/env bash
# Rutina nocturna (20:30 ET, lun–vie): actualiza datos si hoy hubo sesión. Log en reports/auto/.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
UV="${UV:-$HOME/.local/bin/uv}"
D=$(TZ=America/New_York date +%F)
LOG="reports/auto/nightly_${D}.log"; mkdir -p reports/auto
{
  echo "== nightly $D $(date -Is)"
  "$UV" run daytrader is-session || { echo "sin sesión: nada que hacer"; exit 0; }
  COLUMNS=120 "$UV" run daytrader ingest && COLUMNS=120 "$UV" run daytrader universe
  echo "== fin $(date -Is) código $?"
} >> "$LOG" 2>&1
