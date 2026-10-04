set -euo pipefail
test "$(. /etc/os-release; echo "$VERSION_CODENAME")" = bookworm
if dpkg-query -W -f='${Version}\n' cockpit-bridge cockpit-system cockpit-ws | awk '$0 != "337-1~bpo12+pertal1" { bad=1 } END { exit bad }'; then
  echo 'Cockpit already at the approved revision'; exit 0
fi
backup=/var/backups/pertal-cockpit/$(date -u +%Y%m%dT%H%M%SZ)
sudo -n install -d -m 700 "$backup/packages"
if test -d /etc/cockpit; then sudo -n cp -a /etc/cockpit "$backup/"; fi
dpkg-query -W -f='${binary:Package} ${Version} ${db:Status-Status}\n' 'cockpit*' | awk '$3 == "installed"' | sudo -n tee "$backup/installed.txt" >/dev/null
download_dir=$(mktemp -d /var/tmp/pertal-cockpit-download.XXXXXX)
packages=()
while read -r name version status; do
  (cd "$download_dir" && apt-get download "$name=$version" && sudo -n mv ./*.deb "$backup/packages/")
  file=$(find /var/tmp/pertal-cockpit-build/packages -maxdepth 1 -name "${name%%:*}_337-1~bpo12+pertal1_*.deb")
  test -n "$file"
  packages+=("$file")
done < <(sudo -n cat "$backup/installed.txt")
sudo -n apt-get --no-install-recommends --no-remove -s install "${packages[@]}" | sudo -n tee "$backup/simulation.txt"
while read -r name version; do
  (cd "$download_dir" && apt-get download "$name=$version" && sudo -n mv ./*.deb "$backup/packages/")
done < <(sudo -n awk '/^Inst / && $3 ~ /^\[/ {gsub(/[\[\]]/, "", $3); print $2, $3}' "$backup/simulation.txt")
sudo -n env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get -y --no-install-recommends --no-remove install "${packages[@]}"
if ! sudo -n systemctl is-active --quiet cockpit.socket; then
  sudo -n systemctl reset-failed cockpit.socket
  sudo -n systemctl start cockpit.socket
fi
dpkg-query -W -f='${binary:Package} ${Version}\n' cockpit-bridge cockpit-system cockpit-ws
sudo -n systemctl is-active cockpit.socket
curl -sk --max-time 8 -o /dev/null -w 'stock cockpit HTTP %{http_code}\n' https://127.0.0.1:9090/
echo "Rollback saved in $backup"
