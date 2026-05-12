#!/usr/bin/env bash
# setup-pi-cron.sh — Install homelab security tool cron jobs on the Raspberry Pi.
#
# Run on the Pi (or via SSH):
#   bash setup-pi-cron.sh
#   bash setup-pi-cron.sh --remove   # remove all HL-* cron jobs
#
# Jobs added:
#   */5  * * * *  arp-watch.py --report       (every 5 min)
#   0    0 * * *  geoip-log-mapper.py         (daily midnight)
#   0    9 * * 1  smb-null-session check      (weekly Monday 09:00)
#   0    6 * * *  http-security-header-checker (daily 06:00)

set -euo pipefail

TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORTS_DIR="/mnt/noblenumbat-fs/ptm/security-reports"
PYTHON="python3"
CRON_TAG="# HL-HOMELAB-SECURITY"

if [[ ! -d "$TOOLS_DIR" ]]; then
    echo "ERROR: Tools dir not found: $TOOLS_DIR" >&2
    exit 1
fi

# Create reports dir if it doesn't exist
mkdir -p "$REPORTS_DIR" 2>/dev/null || echo "Note: $REPORTS_DIR not accessible (Samba/NFS not mounted?)"

remove_jobs() {
    echo "Removing all HL homelab cron jobs..."
    crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab -
    echo "Done."
}

if [[ "${1:-}" == "--remove" ]]; then
    remove_jobs
    exit 0
fi

# Build new cron entries
NEW_JOBS=$(cat <<EOF

$CRON_TAG — DO NOT EDIT THIS BLOCK MANUALLY
# ARP spoof detection every 5 minutes
*/5 * * * * $PYTHON "$TOOLS_DIR/network/arp-watch.py" --report >> "$REPORTS_DIR/arp-watch-cron.log" 2>&1 $CRON_TAG
# GeoIP Nginx log mapper daily at midnight
0 0 * * * $PYTHON "$TOOLS_DIR/threat-intel/geoip-log-mapper.py" >> "$REPORTS_DIR/geoip-cron.log" 2>&1 $CRON_TAG
# HTTP security header checker daily at 06:00
0 6 * * * $PYTHON "$TOOLS_DIR/windows-security/http-security-header-checker.py" >> "$REPORTS_DIR/headers-cron.log" 2>&1 $CRON_TAG
EOF
)

# Remove old HL jobs, append new ones
current=$(crontab -l 2>/dev/null | grep -v "$CRON_TAG" | grep -v "^$" || true)

{
    echo "$current"
    echo "$NEW_JOBS"
} | crontab -

echo "Cron jobs installed:"
crontab -l | grep "$CRON_TAG" | grep -v "^$CRON_TAG"

echo ""
echo "Reports directory: $REPORTS_DIR"
echo ""
echo "First-run setup:"
echo "  $PYTHON $TOOLS_DIR/network/arp-watch.py --report    # seed initial ARP snapshot"
echo ""
echo "To remove all HL cron jobs: bash $0 --remove"
