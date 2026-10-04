set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
host=$1
case "$host" in rpi) ip=192.168.1.10;; opti) ip=192.168.1.11;; noblenumbat) ip=192.168.1.6;; *) exit 2;; esac
test ! "$(sudo -n docker ps -aq --filter name=^/pertal-cockpit-spike$)"
trap 'sudo -n docker rm -f pertal-cockpit-spike >/dev/null 2>&1 || true' EXIT
sudo -n docker run -d --name pertal-cockpit-spike --init --restart unless-stopped \
  --cap-drop ALL --security-opt no-new-privileges:true --network compose_cockpit_gw -p 127.0.0.1:19090:9090 \
  -v /etc/pertal-cockpit:/keys:ro -e "TARGET=ptm@$ip" -e "URL_ROOT=/cp-$host" \
  -e 'ORIGINS=https://webapp.lan:8444' pertal-cockpit-gw:362
for i in $(seq 1 15); do
  if sudo -n docker exec pertal-cockpit-spike python3 /opt/cockpit-gw/health.py; then break; fi
  sleep 2
done
python3 "$here/spike.py" "$host"

before=$(sudo -n docker inspect -f '{{.RestartCount}}' pertal-cockpit-spike)
python3 "$here/spike.py" "$host" logout | tail -5
for i in $(seq 1 25); do
  now=$(sudo -n docker inspect -f '{{.RestartCount}}' pertal-cockpit-spike)
  if [ "$now" -gt "$before" ] && sudo -n docker exec pertal-cockpit-spike python3 /opt/cockpit-gw/health.py; then break; fi
  sleep 2
done
test "$now" -gt "$before"
sudo -n docker exec pertal-cockpit-spike python3 /opt/cockpit-gw/health.py
echo 'logout recovery verified'
before=$now
sudo -n docker exec -i pertal-cockpit-spike python3 - <<'PY'
from pathlib import Path
import os,signal
for entry in Path('/proc').iterdir():
    if entry.name.isdigit():
        try:
            command=(entry/'cmdline').read_bytes().split(b'\0')[0]
            if command == b'ssh': os.kill(int(entry.name),signal.SIGTERM)
        except (OSError,ProcessLookupError): pass
PY
for i in $(seq 1 20); do
  now=$(sudo -n docker inspect -f '{{.RestartCount}}' pertal-cockpit-spike)
  if [ "$now" -gt "$before" ] && sudo -n docker exec pertal-cockpit-spike python3 /opt/cockpit-gw/health.py; then break; fi
  sleep 2
done
test "$now" -gt "$before"
sudo -n docker exec pertal-cockpit-spike python3 /opt/cockpit-gw/health.py
echo 'SSH loss recovery verified'
sudo -n docker stop -t 12 pertal-cockpit-spike >/dev/null
test "$(sudo -n docker inspect -f '{{.State.ExitCode}}' pertal-cockpit-spike)" = 0
sudo -n docker rm pertal-cockpit-spike >/dev/null
echo 'SIGTERM cleanup verified; loopback listener removed'
