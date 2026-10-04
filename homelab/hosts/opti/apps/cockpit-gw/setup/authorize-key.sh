set -euo pipefail
public_key=$1
[[ "$public_key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+\ pertal-cockpit$ ]]
test "$(id -un)" = ptm
install -d -m 700 "$HOME/.ssh"
file="$HOME/.ssh/authorized_keys"
touch "$file"
chmod 600 "$file"
blob=$(printf '%s' "$public_key" | cut -d' ' -f2)
if grep -Fq "$blob" "$file"; then
  grep -F "$blob" "$file" | grep -Fxq "command=\"sudo -n /usr/bin/cockpit-bridge\",restrict $public_key"
else
  cp -p "$file" "$file.before-pertal-cockpit-$(date -u +%Y%m%dT%H%M%SZ)"
  printf '\ncommand="sudo -n /usr/bin/cockpit-bridge",restrict %s\n' "$public_key" >> "$file"
fi
sudo -n test -x /usr/bin/cockpit-bridge
echo 'restricted bridge key authorized'
