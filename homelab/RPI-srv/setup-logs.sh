#!/usr/bin/env bash
# Run once on the Pi to set up persistent log streaming to the Samba share.
# Logs will be accessible at \\192.168.1.10\ptm\logging (\\rpi.lan\ptm\logging)
# Usage: sudo bash setup-logs.sh

set -euo pipefail

COMPOSE_FILE="/srv/docker/compose/docker-compose.yml"
LOG_DIR="/mnt/noblenumbat-fs/ptm/logging"
SERVICE="docker-stack-logs"

mkdir -p "$LOG_DIR"
chown ptm:ptm "$LOG_DIR"

# ── Systemd service: stream all container stdout/stderr to stack.log ─────────
cat > /etc/systemd/system/${SERVICE}.service <<EOF
[Unit]
Description=Stream docker compose logs to ${LOG_DIR}/stack.log
After=docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=/bin/bash -c 'docker compose -f ${COMPOSE_FILE} logs -f --no-color >> ${LOG_DIR}/stack.log 2>&1'
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

# ── Logrotate: size-based so a log burst never fills the SD card ──────────────
# stack.log caps at 5 × 20 MB = 100 MB total
# deploy-*.log caps at 10 × 5 MB = 50 MB total
cat > /etc/logrotate.d/docker-stack <<EOF
${LOG_DIR}/stack.log {
    size 20M
    rotate 5
    compress
    missingok
    notifempty
    copytruncate
}

${LOG_DIR}/deploy-*.log {
    size 5M
    rotate 10
    compress
    missingok
    notifempty
}
EOF

systemctl daemon-reload
systemctl enable --now ${SERVICE}

echo ""
echo "Done."
echo "  Live logs : ${LOG_DIR}/stack.log"
echo "  Deploy logs: ${LOG_DIR}/deploy-*.log"
echo "  Max disk   : ~150 MB total before rotation kicks in"
echo ""
echo "  Windows path: \\\\192.168.1.10\\ptm\\logging\\"
echo "  From Pi:  tail -f ${LOG_DIR}/stack.log"
