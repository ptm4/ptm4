#!/usr/bin/env bash
# media-import: scan /mnt/opti-media for stable video files, move to /srv/media/staging,
# trigger Radarr DownloadedMoviesScan, log results.
# Deployed to: /usr/local/bin/media-import.sh on noblenumbat
# Scheduled by: media-import.timer (every 2 min)
set -euo pipefail

INBOX=/mnt/opti-media
STAGING=/srv/media/staging
RADARR_URL=http://localhost:7878
RADARR_KEY=f93e83c7f91e46319c73e6d0508e4ecd
LOGFILE=/var/log/media-import.log
MIN_AGE_SECONDS=120   # file must be stable (not modified) for 2 min before moving

log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" | tee -a "$LOGFILE"; }

mkdir -p "$STAGING"

if ! mountpoint -q "$INBOX"; then
  log "WARN: $INBOX not mounted, skipping"
  exit 0
fi

BLACKHOLE=/srv/media/blackhole

# .torrent files → blackhole (qBittorrent watch folder, /data/blackhole in-container)
while IFS= read -r -d '' t; do
  log "TORRENT: $t -> $BLACKHOLE/"
  mv "$t" "$BLACKHOLE/"
done < <(find "$INBOX" -maxdepth 2 -type f -iname '*.torrent' -print0)

# ── Pertal drop-offs: finished torrents in category "pertal" → opti (ptm/Downloads) ──
# Torrents added from Pertal's Downloads page land in qBittorrent's "pertal" category,
# which can only write to this box (/data = /srv/media in the container). Each finished
# one is copied to opti, then removed here and from the queue. Copy-then-delete rather
# than mv: mv across to CIFS tries to preserve ownership and can fail half-way.
DROP=/mnt/opti-downloads
# The LAN IP, not localhost: qBittorrent sits in gluetun's netns, so localhost reaches it
# from the Docker bridge — outside its WebUI whitelist (403). The LAN IP is whitelisted.
QBT_API=http://192.168.1.6:8081/api/v2
if mountpoint -q "$DROP"; then
  while IFS=$'\t' read -r hash src name; do
    if [ "$hash" = "ERR" ]; then log "WARN: pertal drop-offs: qBittorrent unreachable ($src)"; continue; fi
    if [ ! -e "$src" ]; then log "WARN: pertal drop-off missing on disk: $src"; continue; fi
    log "PERTAL: copying '$name' -> $DROP/"
    if cp -r --no-preserve=all "$src" "$DROP/"; then
      rm -rf "$src"
      curl -s -X POST "$QBT_API/torrents/delete" \
        --data-urlencode "hashes=$hash" --data "deleteFiles=false" >/dev/null || true
      log "PERTAL: '$name' is on opti; removed from qBittorrent"
    else
      log "ERROR: copying '$name' to opti failed; left in place for the next run"
    fi
  done < <(QBT_API="$QBT_API" python3 - <<'PY'
import json, os, urllib.request
try:
    ts = json.load(urllib.request.urlopen(
        os.environ["QBT_API"] + "/torrents/info?category=pertal&filter=completed", timeout=10))
except Exception as e:
    print(f"ERR\t{e}\t")
    raise SystemExit(0)
for t in ts:
    path = t.get("content_path") or ""
    if t.get("progress", 0) >= 1 and path.startswith("/data/"):
        print(f"{t['hash']}\t/srv/media/{path[len('/data/'):]}\t{t['name']}")
PY
)
else
  log "WARN: $DROP not mounted, pertal drop-offs wait for the next run"
fi

moved=0
while IFS= read -r -d '' f; do
  age=$(( $(date +%s) - $(stat -c %Y "$f") ))
  if [ "$age" -lt "$MIN_AGE_SECONDS" ]; then
    log "SKIP (still writing): $f (age ${age}s)"
    continue
  fi
  dest="$STAGING/$(basename "$f")"
  log "MOVE: $f -> $dest"
  mv "$f" "$dest"
  moved=$((moved+1))
done < <(find "$INBOX" -maxdepth 2 -type f \
  \( -iname '*.mkv' -o -iname '*.mp4' -o -iname '*.avi' -o -iname '*.m4v' \
     -o -iname '*.mov' -o -iname '*.wmv' -o -iname '*.mpg' -o -iname '*.mpeg' \
     -o -iname '*.ts' \) -print0)

if [ "$moved" -gt 0 ]; then
  log "Moved $moved file(s) to staging, triggering Radarr scan"
  curl -s -X POST "$RADARR_URL/api/v3/command" \
    -H "X-Api-Key: $RADARR_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"name":"DownloadedMoviesScan","path":"/data/staging"}' >/dev/null
  log "Radarr scan triggered"
else
  log "No new video files found"
fi
