#!/bin/bash
set -euo pipefail
REPO=/mnt/nob-backup/borg-repo
TOPIC_FILE=/etc/opti-ntfy-topic
TOPIC=$(cat "$TOPIC_FILE" 2>/dev/null || echo "opti-fallback")
LOG=/var/log/opti-backup.log
PASSPHRASE_FILE=/etc/borg-passphrase

if [ ! -f "$PASSPHRASE_FILE" ]; then
  echo "$(date -Is) FATAL: $PASSPHRASE_FILE missing. Initialize Borg first." >> "$LOG"
  curl -fsSL -H "Title: opti backup not configured" -H "Priority: high" \
    -d "Borg passphrase file missing. Phase 2 setup incomplete." \
    "https://ntfy.sh/$TOPIC" >/dev/null 2>&1 || true
  exit 1
fi

if ! mountpoint -q /srv/red/fs; then
  echo "$(date -Is) FATAL: /srv/red/fs not mounted — refusing to archive an empty source." >> "$LOG"
  curl -fsSL -H "Title: opti backup source not mounted" -H "Priority: high" \
    -d "ZFS pool red is not mounted at /srv/red/fs. Backup skipped rather than archiving nothing." \
    "https://ntfy.sh/$TOPIC" >/dev/null 2>&1 || true
  exit 1
fi

if ! mountpoint -q /mnt/nob-backup; then
  echo "$(date -Is) FATAL: /mnt/nob-backup not mounted." >> "$LOG"
  curl -fsSL -H "Title: opti backup target offline" -H "Priority: high" \
    -d "/mnt/nob-backup is not mounted. Check noblenumbat NFS." \
    "https://ntfy.sh/$TOPIC" >/dev/null 2>&1 || true
  exit 1
fi

export BORG_PASSPHRASE_FD=3
exec 3< "$PASSPHRASE_FILE"

TS=$(date +%Y-%m-%d_%H-%M-%S)

notify() {
  local title="$1"; local body="$2"; local priority="${3:-default}"
  curl -fsSL -H "Title: $title" -H "Priority: $priority" -d "$body" \
    "https://ntfy.sh/$TOPIC" >/dev/null 2>&1 || true
}

{
  echo "===== $TS opti-backup START ====="

  # Pool data snapshot
  borg create --stats --compression zstd,6 \
    --exclude '/srv/red/fs/.deleted' \
    "$REPO::pool-$TS" /srv/red/fs/

  # Config snapshot
  CFG=/tmp/opti-config-$TS
  rm -rf "$CFG"; mkdir -p "$CFG"
  cp -a /etc/openmediavault "$CFG/openmediavault" 2>/dev/null || true
  cp -a /etc/fstab "$CFG/fstab"
  cp -a /etc/network/interfaces "$CFG/interfaces" 2>/dev/null || true
  cp -a /etc/samba "$CFG/samba" 2>/dev/null || true
  cp -a /etc/sudoers.d "$CFG/sudoers.d" 2>/dev/null || true
  cp -a /etc/ssh "$CFG/ssh" 2>/dev/null || true
  cp -a /etc/smartd.conf "$CFG/smartd.conf" 2>/dev/null || true
  cp -a /root "$CFG/root" 2>/dev/null || true
  cp -a /home/ptm/.ssh "$CFG/ptm-ssh" 2>/dev/null || true
  dpkg --get-selections > "$CFG/dpkg-selections.txt"
  apt-mark showmanual > "$CFG/apt-manual.txt"
  omv-confdbadm read conf.system.filesystem.mountpoint > "$CFG/omv-mountpoints.json" 2>/dev/null || true
  omv-rpc -u admin 'SMB' 'getShareList' '{"start":0,"limit":-1}' > "$CFG/omv-smb-shares.json" 2>/dev/null || true
  omv-rpc -u admin 'ShareMgmt' 'enumerateSharedFolders' > "$CFG/omv-shared-folders.json" 2>/dev/null || true

  borg create --stats --compression zstd,6 "$REPO::config-$TS" "$CFG"
  rm -rf "$CFG"

  # Retention
  borg prune --stats --keep-daily=7 --keep-weekly=4 --keep-monthly=6 \
    --glob-archives 'pool-*' "$REPO"
  borg prune --stats --keep-daily=14 --keep-weekly=4 --keep-monthly=6 \
    --glob-archives 'config-*' "$REPO"

  borg compact "$REPO"
  borg check --last 1 "$REPO"

  echo "===== $TS opti-backup OK ====="
  notify "opti backup OK" "Pool + config archived at $TS" "low"
} >> "$LOG" 2>&1 || {
  notify "opti BACKUP FAILED" "See /var/log/opti-backup.log on opti" "urgent"
  exit 1
}
