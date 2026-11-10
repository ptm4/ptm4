#!/bin/bash
set +e
LOG=/var/log/opti-health.log
TOPIC_FILE=/etc/opti-ntfy-topic
TOPIC=$(cat "$TOPIC_FILE" 2>/dev/null || echo "opti-fallback-topic")
TS=$(date -Is)
degraded=0
report=""
for dev in /dev/sda /dev/sdb; do
  verdict=$(smartctl -H "$dev" 2>/dev/null | grep -oE "PASSED|FAILED" | head -1)
  [ -z "$verdict" ] && verdict="UNKNOWN"
  realloc=$(smartctl -A "$dev" 2>/dev/null | awk '/Reallocated_Sector_Ct/ {print $10}' | head -1)
  pending=$(smartctl -A "$dev" 2>/dev/null | awk '/Current_Pending_Sector/ {print $10}' | head -1)
  temp=$(smartctl -A "$dev" 2>/dev/null | awk '/Temperature_Celsius/ {print $10}' | head -1)
  report+="$dev: $verdict | realloc=${realloc:-?} | pending=${pending:-?} | temp=${temp:-?}C"$'\n'
  [ "$verdict" != "PASSED" ] && degraded=1
  [ "${pending:-0}" -gt 0 ] 2>/dev/null && degraded=1
done
pool=$(df -h /srv/red/fs 2>/dev/null | tail -1)
report+="Pool: $pool"$'\n'
for br in /srv/red/fs /srv/red; do
  used_pct=$(df --output=pcent "$br" 2>/dev/null | tail -1 | tr -d '% ')
  if [ "${used_pct:-0}" -gt 80 ] 2>/dev/null; then
    degraded=1
    report+="WARN: $br is ${used_pct}% full"$'\n'
  fi
done
failed=$(systemctl --failed --no-legend 2>/dev/null | wc -l)
if [ "$failed" -gt 0 ]; then
  degraded=1
  report+="WARN: $failed failed systemd units"$'\n'
fi
{
  echo "===== $TS opti daily health digest ====="
  echo "$report"
} >> "$LOG"
if [ "$degraded" -gt 0 ]; then
  curl -fsSL \
    -H "Title: opti daily digest - DEGRADED" \
    -H "Priority: high" \
    -H "Tags: warning" \
    -d "$report" \
    "https://ntfy.sh/$TOPIC" >/dev/null 2>&1 || true
fi
exit 0
