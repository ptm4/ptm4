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
  # Exiting non-zero here is the alert: the unit's OnFailure= pages ntfy.
  if command -v zpool >/dev/null 2>&1 && zpool list >/dev/null 2>&1; then
    # newest *bootable* kernel (GRUB_DEFAULT=0 boots it); leftover /lib/modules dirs of
    # purged kernels have no vmlinuz and must not count
    next_kernel=$(for k in $(ls -1 /lib/modules); do if [ -e "/boot/vmlinuz-$k" ]; then echo "$k"; fi; done | sort -V | tail -1)
    # Debian compresses modules: the file is zfs.ko.xz, so check both forms
    if ! ls "/lib/modules/$next_kernel/updates/dkms/"zfs.ko* >/dev/null 2>&1 && \
       ! modinfo -k "$next_kernel" zfs >/dev/null 2>&1; then
      log "ABORT reboot: no zfs module for kernel $next_kernel — install linux-headers-amd64 (opti-deploy.yml does this) so DKMS builds it, check 'dkms status'"
      exit 1
    fi
  fi
  log "reboot-required present — rebooting now"
  systemctl reboot
else
  log "no reboot required — skipping"
fi
