#!/usr/bin/env python3
"""Run from the trusted workstation: package patching precedes root authorization."""
import argparse
import base64
import hashlib
from pathlib import Path
import re
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
HOSTS = {'opti': '192.168.1.11', 'rpi': '192.168.1.10', 'noblenumbat': '192.168.1.6'}
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8']

def remote(host, script, *args):
    # Binary stdin prevents Windows from translating LF back to CRLF.
    result = subprocess.run([*SSH, host, 'bash -s -- ' + ' '.join(map(shlex.quote, args))],
                            input=script.replace('\r\n', '\n').encode(), capture_output=True)
    if result.returncode:
        raise RuntimeError(f'{host}: {result.stderr.decode(errors="replace").strip()}')
    return result.stdout.decode()

def run(host, file, *args):
    print(remote(host, (HERE/file).read_text(encoding='utf-8'), *args), end='', flush=True)

def install_bridge_compat(host):
    source = (HERE/'bridge_compat.py').read_bytes().replace(b'\r\n', b'\n')
    encoded = base64.b64encode(source).decode()
    digest = hashlib.sha256(source).hexdigest()
    script = """set -euo pipefail
stage=$(mktemp)
trap 'rm -f "$stage"' EXIT
printf '%s' "$1" | base64 -d > "$stage"
printf '%s  %s\\n' "$2" "$stage" | sha256sum -c -
sudo -n install -d -m 755 /usr/local/libexec
if sudo -n test -f /usr/local/libexec/pertal-cockpit-bridge; then
  if ! sudo -n cmp -s "$stage" /usr/local/libexec/pertal-cockpit-bridge; then
    sudo -n install -d -m 700 /var/backups/pertal-cockpit/bridge-compat
    sudo -n cp -p /usr/local/libexec/pertal-cockpit-bridge "/var/backups/pertal-cockpit/bridge-compat/$(date -u +%Y%m%dT%H%M%SZ)"
  fi
fi
sudo -n install -o root -g root -m 755 "$stage" /usr/local/libexec/pertal-cockpit-bridge
sudo -n /usr/local/libexec/pertal-cockpit-bridge --version
"""
    print(remote(host, script, encoded, digest), end='', flush=True)


def setup(packages):
    if packages:
        subprocess.run(['scp', str(HERE/'Bookworm.Dockerfile'), 'opti:/var/tmp/Bookworm.Dockerfile'], check=True)
        remote('opti', 'set -eu\nsudo -n install -d /var/tmp/pertal-cockpit-build\nsudo -n cp /var/tmp/Bookworm.Dockerfile /var/tmp/pertal-cockpit-build/Bookworm.Dockerfile\n')
        run('opti', 'build-opti.sh')
        run('opti', 'upgrade-opti.sh')
        for host in ('rpi', 'noblenumbat'):
            run(host, 'upgrade-ubuntu.sh')
    # Even --keys refuses authorization when any host still serves vulnerable pages.
    host_keys = []
    for host, ip in HOSTS.items():
        version = '337-1~bpo12+pertal1' if host == 'opti' else '362-1~bpo24.04.1'
        remote(host, 'set -euo pipefail\n' +
               'test "$(dpkg-query -W -f=\'${Version}\' cockpit-bridge)" = "$1"\n' +
               'test "$(dpkg-query -W -f=\'${Version}\' cockpit-system)" = "$1"\n', version)
        key = remote(host, 'sudo -n cat /etc/ssh/ssh_host_ed25519_key.pub\n').strip().split()
        if len(key) < 2 or key[0] != 'ssh-ed25519' or not re.fullmatch(r'[A-Za-z0-9+/=]+', key[1]):
            raise RuntimeError(f'invalid trusted host key: {host}')
        host_keys.append(f'{ip} {key[0]} {key[1]}')
    print(remote('opti', "python3 - <<'VERIFY_BUNDLE'\n" +
                 (HERE/'verify_bookworm.py').read_text(encoding='utf-8') +
                 "\nVERIFY_BUNDLE\n"), end='')
    key = remote('opti', """set -euo pipefail
sudo -n install -d -m 700 /etc/pertal-cockpit
if ! sudo -n test -f /etc/pertal-cockpit/id_ed25519; then
  sudo -n ssh-keygen -q -t ed25519 -N '' -C pertal-cockpit -f /etc/pertal-cockpit/id_ed25519
fi
sudo -n chmod 600 /etc/pertal-cockpit/id_ed25519
sudo -n cat /etc/pertal-cockpit/id_ed25519.pub
""").strip()
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+ pertal-cockpit', key):
        raise RuntimeError('unexpected dedicated public key')
    known = '\n'.join(host_keys)
    remote('opti', "set -eu\n" +
           "if sudo -n test -f /etc/pertal-cockpit/known_hosts; then sudo -n cp -p /etc/pertal-cockpit/known_hosts /etc/pertal-cockpit/known_hosts.before-setup; fi\n" +
           "sudo -n tee /etc/pertal-cockpit/known_hosts >/dev/null <<'TRUSTED_HOST_KEYS'\n" + known +
           "\nTRUSTED_HOST_KEYS\nsudo -n chmod 600 /etc/pertal-cockpit/known_hosts\n")
    for host in HOSTS:
        install_bridge_compat(host)
        run(host, 'authorize-key.sh', key)
    run('opti', 'network.sh')
    print('Patched hosts and restricted keys ready. Run the loopback spike before rollout.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', action='store_true', help='build/upgrade approved packages before keys (requires apt network access)')
    args = parser.parse_args()
    setup(args.packages)
