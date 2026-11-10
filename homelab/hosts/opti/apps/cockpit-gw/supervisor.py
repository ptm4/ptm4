"""Wire Cockpit's local-session stream to a restricted SSH root bridge."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from health import healthy

TARGETS = {'/cp-opti': 'ptm@192.168.1.11', '/cp-rpi': 'ptm@192.168.1.10',
           '/cp-noblenumbat': 'ptm@192.168.1.6'}
ALLOWED_ORIGINS = {f'https://{host}:{port}' for host in
                   ('webapp.lan', 'webapp.rpi.lan', '192.168.1.11') for port in (8443, 8444)}

def configuration():
    target, root = os.environ['TARGET'], os.environ['URL_ROOT']
    origins = os.environ['ORIGINS'].split()
    if TARGETS.get(root) != target or not origins or not set(origins) <= ALLOWED_ORIGINS:
        raise ValueError('invalid target, URL root, or origins')
    for name in ('id_ed25519', 'known_hosts'):
        if not Path('/keys', name).is_file():
            raise ValueError(f'missing /keys/{name}; run host setup first')
    config = Path('/etc/pertal-cockpit/cockpit')
    config.mkdir(parents=True, exist_ok=True)
    (config / 'cockpit.conf').write_text(
        '[WebService]\n' + f'UrlRoot = {root}\nOrigins = {" ".join(origins)}\n'
        'ProtocolHeader = X-Forwarded-Proto\nAllowUnencrypted = true\nLoginTo = false\n')
    os.environ['XDG_CONFIG_DIRS'] = '/etc/pertal-cockpit'
    return target, root

def reachable(host, port=22):
    try:
        socket.create_connection((host, port), timeout=5).close()
        return True
    except OSError:
        return False

def wait_for_target(target, stopping, first=5, cap=30, remind=1800):
    """Wait quietly, with capped backoff, until the target's SSH port answers.

    An offline host used to make ssh fail in seconds, exit the container and
    restart it about once a minute for the whole outage. Returns False if a
    stop signal arrives while waiting.
    """
    host = target.rsplit('@', 1)[1]
    delay, started, reminded = first, None, None
    while not stopping():
        if reachable(host):
            if started is not None:
                print(f'gateway: {host}:22 reachable after '
                      f'{int(time.monotonic() - started)}s', file=sys.stderr)
            return True
        now = time.monotonic()
        if started is None:
            started = reminded = now
            print(f'gateway: {host}:22 unreachable; waiting (retry {first}s..{cap}s)',
                  file=sys.stderr)
        elif now - reminded >= remind:
            reminded = now
            print(f'gateway: {host}:22 still unreachable after {int(now - started)}s',
                  file=sys.stderr)
        deadline = now + delay
        while not stopping() and time.monotonic() < deadline:
            time.sleep(0.25)
        delay = min(delay * 2, cap)
    return False

def run():
    target, root = configuration()
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if not wait_for_target(target, lambda: stopping):
        return 0
    children = []
    failed = False
    try:
        ssh = subprocess.Popen(['ssh', '-T', '-i', '/keys/id_ed25519',
            '-o', 'UserKnownHostsFile=/keys/known_hosts', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=2', '-o', 'IdentitiesOnly=yes', target],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        children.append(ssh)
        ws = subprocess.Popen(['/usr/lib/cockpit/cockpit-ws', '--no-tls', '--port', '9090',
                               '--local-session=-'], stdin=ssh.stdout, stdout=ssh.stdin)
        children.append(ws)
        ssh.stdout.close()
        ssh.stdin.close()
        next_check = time.monotonic() + 15
        failures = 0
        while not stopping:
            if any(child.poll() is not None for child in children):
                print('gateway transport exited; restarting', file=sys.stderr)
                failed = True
                break
            if time.monotonic() >= next_check:
                failures = 0 if healthy(root) else failures + 1
                next_check = time.monotonic() + 15
                if failures >= 2:
                    print('gateway manifests failed twice; restarting', file=sys.stderr)
                    failed = True
                    break
            time.sleep(0.25)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    if failed:
        deadline = time.monotonic() + 5
        while not stopping and time.monotonic() < deadline:
            time.sleep(0.25)
    return 1 if failed else 0

if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--check-config']:
            configuration()
            raise SystemExit(0)
        if sys.argv[1:]:
            raise ValueError('unknown gateway argument')
        raise SystemExit(run())
    except (KeyError, ValueError, OSError) as error:
        print(f'gateway: {error}', file=sys.stderr)
        raise SystemExit(1)
