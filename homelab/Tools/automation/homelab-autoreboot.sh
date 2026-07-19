#!/usr/bin/env bash
# homelab-autoreboot: reboot only if a package upgrade left /var/run/reboot-required.
# Deployed to: /usr/local/bin/homelab-autoreboot.sh on opti, rpi, noblenumbat
# Scheduled by: homelab-autoreboot.timer (daily, 03:00) — one hour after
# homelab-autoupdate.timer, so any upgrade from that run has already landed.
set -uo pipefail

LOGFILE=/var/log/homelab-autoupdate.log
log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" | tee -a "$LOGFILE"; }

if [ -f /var/run/reboot-required ]; then
  log "reboot-required present — rebooting now"
  systemctl reboot
else
  log "no reboot required — skipping"
fi
