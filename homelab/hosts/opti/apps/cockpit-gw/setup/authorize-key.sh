set -euo pipefail
public_key=$1
[[ "$public_key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+\ pertal-cockpit$ ]]
test "$(id -un)" = ptm
sudo -n test -x /usr/local/libexec/pertal-cockpit-bridge
install -d -m 700 "$HOME/.ssh"
file="$HOME/.ssh/authorized_keys"
touch "$file"
chmod 600 "$file"
# Migrate only the exact previously approved restricted entry. Duplicate or
# conflicting entries fail; every unrelated key is retained byte for byte.
python3 - "$file" "$public_key" <<'PY'
from pathlib import Path
import datetime, os, shutil, sys, tempfile
file = Path(sys.argv[1])
key = sys.argv[2]
blob = key.split()[1]
old = 'command="sudo -n /usr/bin/cockpit-bridge",restrict ' + key
new = 'command="sudo -n /usr/local/libexec/pertal-cockpit-bridge",restrict ' + key
body = file.read_bytes().decode('utf-8')
lines = body.splitlines(keepends=True)
matching = [index for index, line in enumerate(lines) if blob in line]
if matching:
    if len(matching) != 1 or lines[matching[0]].rstrip('\r\n') not in (old, new):
        raise SystemExit('conflicting dedicated key authorization; left unchanged')
    if lines[matching[0]].rstrip('\r\n') == new:
        print('restricted bridge key already authorized')
        raise SystemExit(0)
    lines[matching[0]] = new + '\n'
    updated = ''.join(lines)
else:
    updated = body + ('\n' if body and not body.endswith('\n') else '') + new + '\n'
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
shutil.copy2(file, str(file) + '.before-pertal-cockpit-' + stamp)
fd, temp = tempfile.mkstemp(dir=file.parent, prefix='.pertal-cockpit-')
try:
    with os.fdopen(fd, 'w', newline='') as target:
        target.write(updated)
    os.chmod(temp, 0o600)
    os.replace(temp, file)
finally:
    if os.path.exists(temp): os.unlink(temp)
print('restricted compatibility bridge key authorized')
PY
