#!/usr/bin/env bash
# Instala (o con --uninstall, quita) los temporizadores systemd de USUARIO de la rutina diaria.
#   daytrader-nightly: lun–vie 20:30 ET → ingest + universe
#   daytrader-morning: lun–vie 09:40 ET → watchlist del día (cutoff 09:25 ET)
# Persistent=true: si el PC estaba apagado a esa hora, se ejecuta al encender. En festivos no hace nada.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now daytrader-nightly.timer daytrader-morning.timer 2>/dev/null || true
  rm -f "$UNIT_DIR"/daytrader-{nightly,morning}.{service,timer}
  systemctl --user daemon-reload
  echo "Temporizadores eliminados."
  exit 0
fi

mkdir -p "$UNIT_DIR"
for job in nightly morning; do
  case $job in
    nightly) when="Mon..Fri 20:30 America/New_York"; desc="actualiza datos de mercado" ;;
    morning) when="Mon..Fri 09:40 America/New_York"; desc="genera la watchlist del día" ;;
  esac
  cat > "$UNIT_DIR/daytrader-$job.service" <<EOF
[Unit]
Description=Day trading asistido: $desc

[Service]
Type=oneshot
ExecStart=/usr/bin/bash "$REPO/scripts/auto/$job.sh"
Nice=10
EOF
  cat > "$UNIT_DIR/daytrader-$job.timer" <<EOF
[Unit]
Description=Day trading asistido: $desc ($when)

[Timer]
OnCalendar=$when
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
EOF
done
systemctl --user daemon-reload
systemctl --user enable --now daytrader-nightly.timer daytrader-morning.timer
systemctl --user list-timers 'daytrader-*' --no-pager
