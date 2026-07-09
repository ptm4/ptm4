#!/usr/bin/env bash
# vpn-stack-heal: qbittorrent/sabnzbd share gluetun's network namespace; a gluetun
# restart destroys it and leaves them running but networkless. This detects that
# (qbittorrent unreachable through gluetun's published port) and recreates the
# dependents, then keeps qbittorrent's listen port synced to gluetun's forwarded port.
# Also enforces a low-disk guardrail: < MIN_FREE_GB free on / pauses all torrents.
# Deployed to: /usr/local/bin/vpn-stack-heal.sh (root:root 700 — contains qbt password)
# Scheduled by: vpn-stack-heal.timer (every 2 min)
set -u

LOG=/var/log/vpn-stack-heal.log
QBT=http://localhost:8081

log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" | tee -a "$LOG"; }

CK=""
trap '[ -n "$CK" ] && rm -f "$CK"' EXIT
qbt_login() {
  CK=${CK:-$(mktemp)}
  curl -s -c "$CK" -X POST "$QBT/api/v2/auth/login" -H "Referer: $QBT" \
    --data-urlencode "username=admin" --data-urlencode "password=yams_qbt" >/dev/null
}

# --- low-disk guardrail: below MIN_FREE_GB on / -> pause all torrents (resume is manual) ---
MIN_FREE_GB=10
FREE_GB=$(( $(df --output=avail -B1G / | tail -1) ))
if [ "$FREE_GB" -lt "$MIN_FREE_GB" ]; then
  qbt_login
  curl -s -b "$CK" -X POST -H "Referer: $QBT" --data "hashes=all" "$QBT/api/v2/torrents/pause"
  log "LOW DISK: ${FREE_GB}G free (< ${MIN_FREE_GB}G) — paused all torrents; free space then resume manually"
fi

# gluetun down is its own problem — compose restart policy owns it, nothing to heal here
[ "$(docker inspect -f '{{.State.Running}}' gluetun 2>/dev/null)" = "true" ] || exit 0

code() { curl -s -m 5 -o /dev/null -w "%{http_code}" "$QBT/api/v2/app/version" 2>/dev/null; }

if [ "$(code)" = "000" ]; then
  sleep 10  # require two failures 10s apart before acting
  if [ "$(code)" = "000" ]; then
    log "qbittorrent unreachable through gluetun — recreating dependents"
    (cd /opt/yams && docker compose up -d --force-recreate qbittorrent sabnzbd) >>"$LOG" 2>&1
    sleep 20
  fi
fi

# sync gluetun's forwarded port into qbittorrent (heals the startup race too)
PORT=$(docker exec gluetun cat /tmp/gluetun/forwarded_port 2>/dev/null)
case "$PORT" in '' | *[!0-9]*) exit 0 ;; esac

qbt_login
CUR=$(curl -s -b "$CK" -H "Referer: $QBT" "$QBT/api/v2/app/preferences" |
  python3 -c "import json,sys; print(json.load(sys.stdin).get('listen_port',''))" 2>/dev/null)
if [ -n "$CUR" ] && [ "$CUR" != "$PORT" ]; then
  curl -s -b "$CK" -X POST "$QBT/api/v2/app/setPreferences" -H "Referer: $QBT" \
    --data-urlencode "json={\"listen_port\":$PORT}"
  log "listen_port synced: $CUR -> $PORT"
fi
