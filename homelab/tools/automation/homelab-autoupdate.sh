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

# Maintenance hold (dashboard Settings → Maintenance, via hl-arch-agent POST /autoupdate).
# The agent also disables the timer, but opti-deploy.yml re-runs `enable --now` on every
# push — so THIS check is what makes "disabled" hold. A manual "Upgrade now" from the
# dashboard drops a one-shot override in /run (tmpfs, so it can never outlive a boot).
# hl-arch-agent greps for the marker below to report whether a host's script honors it.
# HONORS_AUTOUPDATE_FLAG
AUTOUPDATE_FLAG=/etc/homelab/autoupdate.disabled
AUTOUPDATE_FORCE_ONCE=/run/homelab/autoupdate.force-once
if [ -f "$AUTOUPDATE_FLAG" ]; then
  if [ -f "$AUTOUPDATE_FORCE_ONCE" ]; then
    rm -f "$AUTOUPDATE_FORCE_ONCE"
    log "auto-updates are disabled, but a manual run was requested — proceeding once"
  else
    log "SKIPPED: auto-updates disabled on this host ($(tr -d '\n' < "$AUTOUPDATE_FLAG" | head -c 300))"
    log "=== homelab-autoupdate done (skipped) ==="
    exit 0
  fi
fi

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
