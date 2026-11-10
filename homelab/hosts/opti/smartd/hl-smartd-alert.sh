#!/bin/sh
# hl-smartd-alert.sh — smartd's -M exec hook on opti (installed to /usr/local/bin).
#
# Source of truth: homelab/hosts/opti/smartd/, installed by .github/workflows/opti-deploy.yml.
# Replaces the hand-made /usr/local/bin/smartd-alert.sh, which posted to the PUBLIC
# ntfy.sh service rather than the homelab's own ntfy, so its alerts never reached the
# phone. This one pushes through homelab/tools/notify.py (ntfy on noblenumbat, Discord
# fallback).
#
# It calls notify.py directly instead of emitting a finding for ingest.py, the same
# exception the alerting convention makes for unit OnFailure= hooks: smartd is event
# driven and the point is to page within minutes of the disk reporting trouble, not on
# the next collector cycle.
#
# notify.py is run from /usr/local/lib/homelab/ (boot disk), NOT from the synced repo
# snapshot under /srv/red: when the disk failing is the pool disk, the pool may be the
# one thing that can no longer be read. For the same reason the unit points HL_DATA_DIR
# (notify.py's dedup state) at /var/lib/hl-smartd.
#
# smartd provides: SMARTD_DEVICE, SMARTD_DEVICESTRING, SMARTD_DEVICEINFO, SMARTD_FAILTYPE,
# SMARTD_MESSAGE (see smartd.conf(5), -M exec). Every warning type pages as urgent except
# the EmailTest that `-M test` sends, which is how the hook is tested without a failure.

NOTIFY=/usr/local/lib/homelab/notify.py
LOG=/var/log/hl-smartd-alert.log

dev=$(basename "${SMARTD_DEVICE:-unknown}")
type=${SMARTD_FAILTYPE:-unknown}
msg=${SMARTD_MESSAGE:-no message from smartd}

echo "$(date -Is) $type $dev: $msg" >> "$LOG" 2>/dev/null

if [ "$type" = "EmailTest" ]; then
    prio=default
    title="opti SMART alert test: $dev"
    body="Test from hl-smartd ($msg). If you see this, disk alerts reach your phone."
else
    prio=urgent
    title="opti disk problem: $dev ($type)"
    body="$msg. ${SMARTD_DEVICEINFO:-}
Action: run 'sudo smartctl -a $SMARTD_DEVICE' on opti. If this is the pool disk (WD40EFZZ), copy anything irreplaceable off red now; do not reboot or scrub."
fi

# --dedup per disk + problem type: smartd already warns once per problem, this only
# guards against a smartd restart loop re-sending the same thing.
/usr/bin/python3 "$NOTIFY" --title "$title" --priority "$prio" --tags warning,hard_drive \
    --dedup "smartd-$dev-$type" "$body" >> "$LOG" 2>&1 \
    || echo "$(date -Is) WARN: notify.py exited non-zero" >> "$LOG" 2>/dev/null

# Never fail: smartd logs a non-zero exit as a warning-delivery error and that is all.
exit 0
