#!/usr/bin/env bash
# vpn-stack-heal: qbittorrent/sabnzbd/prowlarr/flaresolverr share gluetun's network
# namespace; a gluetun restart destroys it and leaves them running but networkless.
# This detects that (qbittorrent unreachable through gluetun's published port) and
# recreates the dependents, then keeps qbittorrent's listen port synced to gluetun's
# forwarded port.
#
# NAT-PMP watchdog: ProtonVPN's port-forward mapping can die silently while gluetun
# still reports healthy (the recurring stalled-torrents failure). Every run asks the
# gluetun control API for the forwarded port and public IP; if either is missing the
# tunnel's forwarding is dead -> restart gluetun (once per cooldown window) and
# recreate the dependents. Every run writes machine-readable state to
# /var/lib/vpn-stack-heal/status.json, which homelab-doctor picks up over SSH and
# flags in the homelab report.
#
# Also enforces a low-disk guardrail: < MIN_FREE_GB free on / pauses all torrents.
# Deployed to: /usr/local/bin/vpn-stack-heal.sh (root:root 700 — contains qbt password)
# Scheduled by: vpn-stack-heal.timer (every 2 min)
#
# Test hooks (env): CTRL=<control url> DRY_RUN=1 (log restarts instead of doing them)
set -u

LOG=/var/log/vpn-stack-heal.log
STATE_DIR=/var/lib/vpn-stack-heal
STATUS=$STATE_DIR/status.json
QBT=http://localhost:8081
CTRL=${CTRL:-http://localhost:8003}
DRY_RUN=${DRY_RUN:-0}
RESTART_COOLDOWN_MIN=30
DEPENDENTS="qbittorrent sabnzbd prowlarr flaresolverr mylar3"

mkdir -p "$STATE_DIR"
log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" | tee -a "$LOG"; }

# Accumulated for status.json — doctor turns non-ok status + actions into findings
STATUS_LEVEL=ok          # ok | warn | critical
ACTIONS=()
note() { ACTIONS+=("$1"); log "$1"; }
degrade() { [ "$STATUS_LEVEL" = critical ] || STATUS_LEVEL=$1; }

write_status() {
  local pf=${1:-null} qbt=${2:-null} pubip=${3:-} running=${4:-true}
  local acts; acts=$(printf '%s\n' "${ACTIONS[@]:-}" | python3 -c \
    'import json,sys; print(json.dumps([l for l in sys.stdin.read().splitlines() if l]))')
  printf '{"ts":"%s","status":"%s","gluetun_running":%s,"forwarded_port":%s,"qbt_listen_port":%s,"public_ip":"%s","actions":%s}\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$STATUS_LEVEL" "$running" "$pf" "$qbt" "$pubip" "$acts" \
    > "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"
}

CK=""
trap '[ -n "$CK" ] && rm -f "$CK"' EXIT
qbt_login() {
  CK=${CK:-$(mktemp)}
  curl -s -c "$CK" -X POST "$QBT/api/v2/auth/login" -H "Referer: $QBT" \
    --data-urlencode "username=admin" --data-urlencode "password=yams_qbt" >/dev/null
}

json_field() { python3 -c "import json,sys
try: v=json.load(sys.stdin).get('$1','')
except Exception: v=''
print(v)" 2>/dev/null; }

pf_port()   { curl -s -m 8 "$CTRL/v1/portforward" 2>/dev/null | json_field port; }
public_ip() { curl -s -m 8 "$CTRL/v1/publicip/ip" 2>/dev/null | json_field public_ip; }
# callers must qbt_login first, at the top level — $(...) runs in a subshell, so a
# login inside this function would never propagate its cookie back to the parent
qbt_port() {
  curl -s -b "$CK" -H "Referer: $QBT" "$QBT/api/v2/app/preferences" 2>/dev/null |
    json_field listen_port
}

recreate_dependents() {
  note "recreating netns dependents: $DEPENDENTS"
  if [ "$DRY_RUN" = 1 ]; then note "DRY_RUN: skipped recreate"; return; fi
  (cd /opt/yams && docker compose up -d --force-recreate $DEPENDENTS) >>"$LOG" 2>&1
  sleep 20
}

# --- low-disk guardrail: below MIN_FREE_GB on / -> pause all torrents (resume is manual) ---
MIN_FREE_GB=10
FREE_GB=$(( $(df --output=avail -B1G / | tail -1) ))
if [ "$FREE_GB" -lt "$MIN_FREE_GB" ]; then
  qbt_login
  curl -s -b "$CK" -X POST -H "Referer: $QBT" --data "hashes=all" "$QBT/api/v2/torrents/pause"
  degrade warn
  note "LOW DISK: ${FREE_GB}G free (< ${MIN_FREE_GB}G) — paused all torrents; free space then resume manually"
fi

# gluetun down is compose restart policy's problem — but the report should still see it
if [ "$(docker inspect -f '{{.State.Running}}' gluetun 2>/dev/null)" != "true" ]; then
  STATUS_LEVEL=critical
  note "gluetun container not running — compose restart policy owns recovery"
  write_status null null "" false
  exit 0
fi

code() { curl -s -m 5 -o /dev/null -w "%{http_code}" "$QBT/api/v2/app/version" 2>/dev/null; }

if [ "$(code)" = "000" ]; then
  sleep 10  # require two failures 10s apart before acting
  if [ "$(code)" = "000" ]; then
    degrade warn
    note "qbittorrent unreachable through gluetun — netns likely destroyed"
    recreate_dependents
  fi
fi

# --- NAT-PMP watchdog: forwarded port + public IP must both exist, else forwarding is dead ---
PF=$(pf_port)
PUBIP=$(public_ip)
if ! [[ "$PF" =~ ^[0-9]+$ ]] || [ "$PF" = 0 ] || [ -z "$PUBIP" ]; then
  sleep 10  # confirm — control API can blip during a reconnect
  PF=$(pf_port); PUBIP=$(public_ip)
fi

if ! [[ "$PF" =~ ^[0-9]+$ ]] || [ "$PF" = 0 ] || [ -z "$PUBIP" ]; then
  LAST_RESTART=$(cat "$STATE_DIR/last_restart" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  if (( NOW - LAST_RESTART < RESTART_COOLDOWN_MIN * 60 )); then
    STATUS_LEVEL=critical
    note "port forwarding still dead after restart $(( (NOW - LAST_RESTART) / 60 ))min ago (pf='$PF' ip='$PUBIP') — needs a human"
  else
    degrade warn
    note "port forwarding dead (pf='$PF' ip='$PUBIP') — restarting gluetun"
    if [ "$DRY_RUN" = 1 ]; then
      note "DRY_RUN: skipped gluetun restart"
    else
      echo "$NOW" > "$STATE_DIR/last_restart"
      docker restart gluetun >>"$LOG" 2>&1
      for _ in $(seq 1 30); do
        [ "$(docker inspect -f '{{.State.Health.Status}}' gluetun 2>/dev/null)" = "healthy" ] && break
        sleep 5
      done
      recreate_dependents
      PF=$(pf_port); PUBIP=$(public_ip)
      if [[ "$PF" =~ ^[0-9]+$ ]] && [ "$PF" != 0 ]; then
        note "gluetun restart restored forwarded port $PF"
      else
        STATUS_LEVEL=critical
        note "gluetun restart did NOT restore port forwarding — needs a human"
      fi
    fi
  fi
fi

# --- sync gluetun's forwarded port into qbittorrent (heals the startup race too) ---
QBT_PORT=""
if [[ "$PF" =~ ^[0-9]+$ ]] && [ "$PF" != 0 ]; then
  qbt_login
  QBT_PORT=$(qbt_port)
  if [[ "$QBT_PORT" =~ ^[0-9]+$ ]] && [ "$QBT_PORT" != "$PF" ]; then
    curl -s -b "$CK" -X POST "$QBT/api/v2/app/setPreferences" -H "Referer: $QBT" \
      --data-urlencode "json={\"listen_port\":$PF}"
    AFTER=$(qbt_port)
    if [ "$AFTER" = "$PF" ]; then
      degrade warn
      note "listen_port synced: $QBT_PORT -> $PF"
      QBT_PORT=$PF
    else
      STATUS_LEVEL=critical
      note "listen_port push FAILED: qbt still on ${AFTER:-?} (wanted $PF)"
    fi
  fi
fi

[[ "$PF" =~ ^[0-9]+$ ]] || PF=null
[[ "$QBT_PORT" =~ ^[0-9]+$ ]] || QBT_PORT=null
write_status "$PF" "$QBT_PORT" "$PUBIP" true
