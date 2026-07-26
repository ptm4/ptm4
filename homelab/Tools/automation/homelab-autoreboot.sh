#!/usr/bin/env bash
# homelab-autoreboot: reboot only if a package upgrade left /var/run/reboot-required.
# Deployed to: /usr/local/bin/homelab-autoreboot.sh on opti, rpi, noblenumbat
# Scheduled by: homelab-autoreboot.timer (daily, 03:00) — one hour after
# homelab-autoupdate.timer, so any upgrade from that run has already landed.
set -uo pipefail

LOGFILE=/var/log/homelab-autoupdate.log
log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" | tee -a "$LOGFILE"; }

if [ -f /var/run/reboot-required ]; then
  # ZFS guard (opti): never reboot into a kernel the zfs DKMS module did not build
  # for — the pool (and the \\opti\\red share for four hosts) would not come back.
  # Only applies where zfs is in use; hosts without zpool skip straight through.
  if command -v zpool >/dev/null 2>&1 && zpool list >/dev/null 2>&1; then
    next_kernel=$(ls -1 /lib/modules | sort -V | tail -1)
    if [ ! -e "/lib/modules/$next_kernel/updates/dkms/zfs.ko" ] && \
       ! modinfo -k "$next_kernel" zfs >/dev/null 2>&1; then
      log "ABORT reboot: no zfs module for kernel $next_kernel — fix DKMS first"
      exit 1
    fi
  fi
  log "reboot-required present — rebooting now"
  systemctl reboot
else
  log "no reboot required — skipping"
fi
