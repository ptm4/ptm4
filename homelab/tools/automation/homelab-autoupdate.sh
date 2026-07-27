#!/usr/bin/env bash
# homelab-autoupdate: apt update && full apt upgrade, unattended.
# Deployed to: /usr/local/bin/homelab-autoupdate.sh on opti, rpi, noblenumbat
# Scheduled by: homelab-autoupdate.timer (daily, 02:00)
# Companion: homelab-autoreboot.timer (03:00) reboots only if this run left
# /var/run/reboot-required behind.
set -uo pipefail

LOGFILE=/var/log/homelab-autoupdate.log
log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" | tee -a "$LOGFILE"; }

log "=== homelab-autoupdate start ==="

export DEBIAN_FRONTEND=noninteractive

if ! apt-get update >>"$LOGFILE" 2>&1; then
  log "ERROR: apt-get update failed, aborting upgrade"
  exit 1
fi

if apt-get -y upgrade >>"$LOGFILE" 2>&1; then
  log "apt-get upgrade completed"
else
  log "ERROR: apt-get upgrade failed"
  exit 1
fi

apt-get -y autoremove >>"$LOGFILE" 2>&1 || log "WARN: autoremove failed (non-fatal)"

if [ -f /var/run/reboot-required ]; then
  log "reboot required — homelab-autoreboot.timer will reboot at 03:00"
else
  log "no reboot required"
fi

log "=== homelab-autoupdate done ==="
