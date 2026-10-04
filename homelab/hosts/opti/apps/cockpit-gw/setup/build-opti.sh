set -euo pipefail
sudo -n install -d -m 755 /var/tmp/pertal-cockpit-build
sudo -n docker build --progress=plain -t pertal-cockpit-bookworm:337-security -f /var/tmp/pertal-cockpit-build/Bookworm.Dockerfile /var/tmp/pertal-cockpit-build > /var/tmp/pertal-cockpit-build.log 2>&1 || { tail -90 /var/tmp/pertal-cockpit-build.log; exit 1; }
tail -25 /var/tmp/pertal-cockpit-build.log
cid=$(sudo -n docker create pertal-cockpit-bookworm:337-security)
trap 'sudo -n docker rm "$cid" >/dev/null' EXIT
sudo -n docker cp "$cid:/build/." /var/tmp/pertal-cockpit-build/packages
sudo -n find /var/tmp/pertal-cockpit-build/packages -maxdepth 1 -name '*.deb' -printf '%f\n'
