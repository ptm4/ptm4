#!/usr/bin/env bash
# enforce-secret-perms: put secret files back to the owner and mode a manifest lists.
# Run by:   opti-deploy.yml and rpi-deploy.yml on every deploy, under sudo, against
#           homelab/hosts/<host>/secret-perms.conf.
# Why:      the 2026-11-09 audit found /etc/hl-agents.env, the Pi's compose .env, the live
#           Vaultwarden key and the TLS/CA private keys at 777/664. No deploy set those modes:
#           the old Pi's whole /srv/docker/compose tree was 777 and mode-preserving copies
#           (tar -p, rsync -a) carried it to opti. Nothing ships these files, so nothing would
#           ever have fixed them. This does, on every deploy.
#
# Manifest: one entry per line, `<owner:group> <octal mode> <path or glob>`; `#` comments and
#           blank lines are ignored. Paths must not contain spaces.
# Rules:    - non-recursive on purpose: a directory entry fixes that directory only, never
#             what is inside it (container data dirs underneath have their own owners);
#           - symlinks are skipped (chmod would follow them);
#           - a pattern that matches nothing is a warning, not a failure;
#           - exit 1 if any matched path does not end at exactly the listed owner and mode.
# Never reads or prints file contents.
set -uo pipefail

manifest=${1:?usage: enforce-secret-perms.sh <manifest>}
[ -r "$manifest" ] || { echo "::error::manifest not readable: $manifest"; exit 1; }

shopt -s nullglob dotglob
fail=0

while read -r owner mode pattern rest || [ -n "${owner:-}" ]; do
  owner=${owner%$'\r'}; mode=${mode%$'\r'}; pattern=${pattern%$'\r'}; rest=${rest%$'\r'}
  case "$owner" in ''|'#'*) continue ;; esac
  if [ -z "$pattern" ] || [ -n "$rest" ] || ! [[ "$mode" =~ ^0?[0-7]{3}$ ]] || ! [[ "$owner" == *:* ]]; then
    echo "::error::bad manifest line: $owner $mode $pattern $rest"; fail=1; continue
  fi
  want_mode=$(printf '%o' "$((8#$mode))")

  # shellcheck disable=SC2206  # word-split + glob expansion of the pattern is the point
  matches=( $pattern )
  found=0
  for p in "${matches[@]}"; do
    [ -e "$p" ] || continue
    if [ -L "$p" ]; then echo "::warning::skipping symlink $p"; continue; fi
    found=1
    chown "$owner" "$p" && chmod "$want_mode" "$p" || { echo "::error::could not set $owner $want_mode on $p"; fail=1; }
    got=$(stat -c '%U:%G %a' "$p")
    if [ "$got" = "$owner $want_mode" ]; then
      echo "ok    $got $p"
    else
      echo "::error::$p is $got, want $owner $want_mode"; fail=1
    fi
  done
  [ "$found" = 1 ] || echo "::warning::no match for $pattern"
done < "$manifest"

exit "$fail"
