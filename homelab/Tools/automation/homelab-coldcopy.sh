#!/usr/bin/env bash
# homelab-coldcopy: refresh the cold second copy of the live ZFS pool.
# Deployed to: /usr/local/bin/homelab-coldcopy.sh on opti (only)
# Scheduled by: homelab-coldcopy.timer (weekly, Sun 04:00)
#
#   sudo cp homelab-coldcopy.sh /usr/local/bin/ && sudo chmod +x /usr/local/bin/homelab-coldcopy.sh
#   sudo cp homelab-coldcopy.service homelab-coldcopy.timer /etc/systemd/system/
#   sudo systemctl daemon-reload && sudo systemctl enable --now homelab-coldcopy.timer
#
# Direction is ALWAYS  /srv/red/fs  ->  /srv/attic  and is hardcoded, never a parameter.
#
# The cold copy is the old sda+sdb mergerfs pool. It is `noauto`, so /srv/attic does not
# exist except during this run — that is the structural reason a stray writer cannot land
# in a tree that is about to be --delete'd. The sdb branch is additionally mounted `ro` in
# steady state; we flip it rw only for our window and always restore it via the EXIT trap.
#
# The genuinely dangerous direction is an EMPTY source: if the pool failed to import and we
# synced /srv/red/fs (empty) -> attic with --delete, we would erase the last copy. Interlock 2
# exists for exactly that and is the most important line in this file.
set -uo pipefail

SRC=/srv/red/fs
ATTIC=/srv/attic
SDB_MNT=/srv/dev-disk-by-uuid-C682C2DE82C2D1DB
POOL=red

LOGFILE=/var/log/homelab-coldcopy.log
LOCKFILE=/var/lock/homelab-coldcopy.lock

AGENT_LOGS_DIR="${HL_AGENT_LOGS_DIR:-/srv/red/fs/ptm/agent-logs}"
DATA_DIR="${HL_DATA_DIR:-$AGENT_LOGS_DIR/.state}"
REPORT="$AGENT_LOGS_DIR/coldcopy-latest.json"
STATE="$DATA_DIR/coldcopy-state.json"

MIN_BYTES=$((500 * 1024 * 1024 * 1024))   # 500 GiB source floor
MIN_ROOT_FREE_GB=40                        # mfs placement can target sda, which is /
MAX_DELETE_FILES=500
MAX_DELETE_PCT=5

RUN_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
STATUS=ok
SUMMARY=""
FINDINGS=()

log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" | tee -a "$LOGFILE"; }

# finding <severity> <message>
finding() {
  local sev="$1"; shift
  local msg="$*"
  FINDINGS+=("{\"severity\":\"$sev\",\"detail\":$(printf '%s' "$msg" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}")
  log "[$sev] $msg"
}

write_report() {
  mkdir -p "$AGENT_LOGS_DIR" "$DATA_DIR" 2>/dev/null
  local joined
  joined=$(IFS=,; echo "${FINDINGS[*]:-}")
  cat > "$REPORT" <<EOF
{
  "run_at": "$RUN_AT",
  "status": "$STATUS",
  "summary": $(printf '%s' "$SUMMARY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
  "findings": [$joined]
}
EOF
  # dated history copy, matching the other runners
  local daydir="$AGENT_LOGS_DIR/coldcopy-latest"
  mkdir -p "$daydir" 2>/dev/null && cp "$REPORT" "$daydir/$(date -u '+%Y-%m-%d').json" 2>/dev/null
  log "report written: $REPORT (status=$STATUS)"
}

# Always leave the cold copy read-only and unmounted, however we exit.
cleanup() {
  local rc=$?
  if mountpoint -q "$ATTIC" 2>/dev/null; then
    umount "$ATTIC" 2>/dev/null && log "unmounted $ATTIC" || log "WARN: could not unmount $ATTIC"
  fi
  if findmnt -n -o OPTIONS "$SDB_MNT" 2>/dev/null | grep -q '^rw'; then
    umount "$SDB_MNT" 2>/dev/null
  fi
  if ! findmnt -n "$SDB_MNT" >/dev/null 2>&1; then
    # fstab carries ro for this mntent, so a plain re-mount restores read-only.
    # Retried because the mergerfs teardown can hold the branch for a moment.
    # Mount via the systemd unit, NOT mount(8): a FUSE mount started by this script
    # puts the ntfs-3g daemon in our service cgroup, and systemd kills it (and thereby
    # the mount) the moment the oneshot service exits. The .mount unit owns it instead.
    sdb_unit=$(systemd-escape -p --suffix=mount "$SDB_MNT")
    restored=""
    for _ in 1 2 3 4 5; do
      systemctl start "$sdb_unit" 2>/dev/null && restored=1 && break
      sleep 3
    done
    if [ -n "$restored" ]; then
      log "restored $SDB_MNT to ro"
    else
      STATUS=degraded
      finding high "could not restore $SDB_MNT to read-only — do this by hand"
    fi
  fi
  write_report
  exit $rc
}

abort() {
  STATUS="${2:-critical}"
  SUMMARY="$1"
  finding "${3:-high}" "$1"
  log "ABORT: $1"
  exit 1
}

log "=== homelab-coldcopy start ==="
trap cleanup EXIT

# ── Interlock 5: no overlapping runs ──────────────────────────────────────────
exec 9>"$LOCKFILE"
flock -n 9 || { log "another run holds the lock; exiting"; trap - EXIT; exit 0; }

# ── Interlock 1: the SOURCE is a healthy, really-mounted pool ─────────────────
zpool list -H "$POOL" >/dev/null 2>&1 || abort "zpool $POOL not imported — refusing to sync"
health=$(zpool list -H -o health "$POOL" 2>/dev/null)
[ "$health" = "ONLINE" ] || finding high "pool $POOL health is $health (expected ONLINE)"

mountpoint -q "$SRC" || abort "$SRC is not a mountpoint — pool may have failed to mount"

# fsid must differ from / : catches the "mounted over an empty dir on root" case
src_fsid=$(stat -f -c %i "$SRC" 2>/dev/null)
root_fsid=$(stat -f -c %i / 2>/dev/null)
[ "$src_fsid" != "$root_fsid" ] || abort "$SRC resolves to the root filesystem — pool not mounted"

# ── Interlock 2: source floor. THE line that prevents wiping the cold copy ────
src_files=$(find "$SRC" -xdev -type f 2>/dev/null | wc -l)
src_bytes=$(du -sb "$SRC" 2>/dev/null | cut -f1)
: "${src_bytes:=0}"

[ "$src_bytes" -ge "$MIN_BYTES" ] || \
  abort "source is only $((src_bytes/1024/1024/1024))GiB, below the ${MIN_BYTES}B floor — refusing to sync"

if [ -f "$STATE" ]; then
  prev_files=$(python3 -c "import json;print(json.load(open('$STATE')).get('files',0))" 2>/dev/null || echo 0)
  if [ "${prev_files:-0}" -gt 0 ]; then
    floor=$(( prev_files * 90 / 100 ))
    [ "$src_files" -ge "$floor" ] || \
      abort "source has $src_files files, below 90% of last successful run ($prev_files) — refusing to sync"
  fi
fi
log "source: $src_files files, $((src_bytes/1024/1024/1024))GiB"

# ── Interlock 4: root filesystem headroom (mfs can place onto sda == /) ───────
root_free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[ "${root_free_gb:-0}" -ge "$MIN_ROOT_FREE_GB" ] || \
  abort "root filesystem has only ${root_free_gb}G free (need ${MIN_ROOT_FREE_GB}G)"

# ── Mount the cold copy for our window ────────────────────────────────────────
mountpoint -q "$SDB_MNT" || abort "$SDB_MNT is not mounted — cold copy is incomplete"

# ntfs-3g cannot remount in place: cycle the mount with explicit rw options.
umount "$SDB_MNT" 2>/dev/null || abort "could not umount $SDB_MNT for the rw window"
mount -t ntfs-3g -o rw,big_writes /dev/disk/by-uuid/C682C2DE82C2D1DB "$SDB_MNT"   || abort "could not mount $SDB_MNT read-write — cannot refresh the cold copy"
findmnt -n -o OPTIONS "$SDB_MNT" | grep -q '^rw' || abort "$SDB_MNT did not come back read-write"
log "mounted $SDB_MNT rw for the sync window"

mount "$ATTIC" 2>/dev/null || abort "could not mount $ATTIC (mergerfs cold copy)"
mountpoint -q "$ATTIC" || abort "$ATTIC did not mount"

# ── Interlock 3: BOTH mergerfs branches must be present ───────────────────────
# A mergerfs pool with a missing branch mounts happily and looks like a half-empty
# destination, which --delete would then "correct" by deleting ~274G.
branches=$(getfattr --only-values -n user.mergerfs.branches "$ATTIC/.mergerfs" 2>/dev/null)
branch_count=$(printf '%s' "$branches" | tr ':' '\n' | grep -c '/')
if [ "${branch_count:-0}" -ne 2 ]; then
  abort "cold copy has $branch_count mergerfs branches, expected 2 — a disk is missing"
fi
log "cold copy mounted with $branch_count branches"

# ── Interlock 6: dry run first; a big deletion count means something broke ────
dry=$(rsync -rltDn --delete --modify-window=1 --numeric-ids \
        --exclude='.Trash-1000/' --itemize-changes \
        "$SRC/" "$ATTIC/" 2>/dev/null)
del_count=$(printf '%s\n' "$dry" | grep -c '^\*deleting' || true)
del_pct=0
[ "$src_files" -gt 0 ] && del_pct=$(( del_count * 100 / src_files ))

if [ "$del_count" -gt "$MAX_DELETE_FILES" ] || [ "$del_pct" -gt "$MAX_DELETE_PCT" ]; then
  printf '%s\n' "$dry" | grep '^\*deleting' | head -50 > /tmp/coldcopy-deletions.txt
  abort "dry run would delete $del_count files (${del_pct}%) — over threshold, refusing. See /tmp/coldcopy-deletions.txt"
fi
log "dry run: $del_count deletions (${del_pct}%) — within threshold"

# ── The real sync ─────────────────────────────────────────────────────────────
log "syncing $SRC -> $ATTIC"
rsync_out=$(ionice -c3 nice -n19 rsync -rltDvh --delete \
  --numeric-ids --modify-window=1 \
  --exclude='.Trash-1000/' \
  "$SRC/" "$ATTIC/" 2>&1)
rc=$?

# ── Interlock 8: classify rsync's exit code, never swallow it ─────────────────
case "$rc" in
  0)  SUMMARY="cold copy refreshed: $src_files files, $((src_bytes/1024/1024/1024))GiB" ;;
  24) SUMMARY="cold copy refreshed; some source files vanished during transfer (benign)" ;;
  23)
      # Partial transfer. On ZFS->NTFS this is usually filenames legal on ZFS and illegal
      # on NTFS ( : ? * | < > " , trailing dot/space ) — common in release names.
      STATUS=degraded
      skipped=$(printf '%s\n' "$rsync_out" | grep -iE 'failed|cannot|invalid|Invalid argument' | head -30)
      SUMMARY="cold copy incomplete — some files could not be written to the NTFS branch"
      finding high "rsync exit 23 (partial transfer). Skipped paths follow:"
      while IFS= read -r line; do [ -n "$line" ] && finding high "skipped: $line"; done <<< "$skipped"
      ;;
  *)
      STATUS=critical
      SUMMARY="cold copy FAILED (rsync exit $rc)"
      finding high "rsync exited $rc: $(printf '%s\n' "$rsync_out" | tail -5)"
      ;;
esac
log "rsync exit $rc"

# ── Interlock 9: did reading/writing sdb make it worse? ───────────────────────
smart=$(smartctl -A /dev/sdb 2>/dev/null)
realloc=$(printf '%s\n' "$smart" | awk '/Reallocated_Sector_Ct/ {print $10}')
pending=$(printf '%s\n' "$smart" | awk '/Current_Pending_Sector/ {print $10}')
log "sdb SMART: reallocated=$realloc pending=$pending"
if [ "${pending:-0}" -gt 0 ]; then
  STATUS=${STATUS/ok/degraded}
  finding high "sdb has $pending pending sectors — the cold copy disk is failing, plan a replacement"
fi
if [ "${realloc:-0}" -gt 3 ]; then
  finding high "sdb reallocated sectors rose to $realloc (was 3 at migration) — disk is degrading"
fi

# Persist the file count for next run's Interlock 2 floor — only on a good run.
if [ "$STATUS" = "ok" ]; then
  mkdir -p "$DATA_DIR" 2>/dev/null
  printf '{"files":%s,"bytes":%s,"run_at":"%s"}\n' "$src_files" "$src_bytes" "$RUN_AT" > "$STATE"
fi

log "=== homelab-coldcopy done (status=$STATUS) ==="
# cleanup() runs on EXIT: unmounts attic, restores sdb to ro, writes the report.
