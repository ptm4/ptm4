set -euo pipefail
if sudo -n docker network inspect compose_cockpit_gw >/dev/null 2>&1; then
  test "$(sudo -n docker network inspect compose_cockpit_gw --format '{{(index .IPAM.Config 0).Subnet}}')" = 172.30.90.0/24
else
  sudo -n docker network inspect $(sudo -n docker network ls -q) | python3 -c '
import sys,json,ipaddress
target=ipaddress.ip_network("172.30.90.0/24")
for network in json.load(sys.stdin):
    for config in network["IPAM"]["Config"] or []:
        if config.get("Subnet") and target.overlaps(ipaddress.ip_network(config["Subnet"])):
            raise SystemExit("gateway subnet overlaps " + network["Name"])
'
  ip -j route show | python3 -c '
import sys,json,ipaddress
target=ipaddress.ip_network("172.30.90.0/24")
for route in json.load(sys.stdin):
    dest=route.get("dst", "default")
    if dest != "default" and target.overlaps(ipaddress.ip_network(dest,strict=False)):
        raise SystemExit("gateway subnet overlaps route " + dest)
'
  sudo -n docker network create --driver bridge --subnet 172.30.90.0/24 \
    --label com.docker.compose.project=compose --label com.docker.compose.network=cockpit_gw compose_cockpit_gw
fi
sudo -n ufw allow from 172.30.90.0/24 to any port 22 proto tcp comment 'cockpit-gw -> host sshd'
