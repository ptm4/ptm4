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
