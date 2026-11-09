#!/bin/bash
# Nightly consistent dump of Vaultwarden (bitwarden.rpi.lan, runs on opti since 2026-09-10).
#
# Run by homelab-vault-dump.service / .timer (homelab/hosts/opti/systemd/), which the
# opti-deploy workflow installs and enables. Runs from the deployed snapshot at
# /srv/red/fs/ptm/repo/ptm4/homelab/hosts/opti/bin/ — edit this repo copy, never that one.
#
# What one archive holds (vaultwarden-YYYY-MM-DD.tar.gz):
#   vaultwarden/vaultwarden.sql   mariadb-dump --single-transaction: an online, consistent
#                                 snapshot of the InnoDB tables; no lock, no downtime
#   vaultwarden/rsa_key.pem       signs login tokens; without it every client must re-login
#   vaultwarden/{rsa_key.pub.pem,config.json,attachments/,sends/}   when they exist
#   vaultwarden/SHA256SUMS
# Credentials come from the DB container's own environment (MYSQL_USER/MYSQL_PASSWORD) via
# MYSQL_PWD, so no secret lives in this file or on a command line.
#
# Archives are root:root 0600 in a 0700 dir. The vault data inside is still encrypted with
# each user's master password, but the dump is the whole vault: treat it as a secret.
#
# Restore (runbook 10, "Vaultwarden dump and restore"):
#   tar -xzf vaultwarden-<date>.tar.gz -C /tmp/vw && cd /tmp/vw/vaultwarden && sha256sum -c SHA256SUMS
#   docker stop bitwarden
#   docker exec -i bitwarden-db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mariadb -u"$MYSQL_USER" "$MYSQL_DATABASE"' < vaultwarden.sql
#   cp rsa_key.pem /srv/docker/compose/vaultwarden-data/ && docker start bitwarden
set -euo pipefail
umask 077

DB_CONTAINER=${DB_CONTAINER:-bitwarden-db}
DATA_DIR=${DATA_DIR:-/srv/docker/compose/vaultwarden-data}
DEST=${DEST:-/srv/docker/backups/vaultwarden}
KEEP_DAYS=${KEEP_DAYS:-90}

out="$DEST/vaultwarden-$(date +%F).tar.gz"

fail() { echo "FATAL: $*" >&2; exit 1; }

mkdir -p "$DEST"
chown root:root "$DEST"
chmod 700 "$DEST"

[ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null)" = true ] \
  || fail "container $DB_CONTAINER is not running"
[ -f "$DATA_DIR/rsa_key.pem" ] || fail "$DATA_DIR/rsa_key.pem missing"

# Build inside DEST so the final mv is an atomic rename on the same filesystem.
work=$(mktemp -d "$DEST/.work-XXXXXX")
trap 'rm -rf "$work"' EXIT
stage="$work/vaultwarden"
mkdir "$stage"

docker exec "$DB_CONTAINER" sh -c \
  'MYSQL_PWD="$MYSQL_PASSWORD" exec mariadb-dump -u"$MYSQL_USER" --single-transaction --routines --triggers "$MYSQL_DATABASE"' \
  > "$stage/vaultwarden.sql"

tail -n1 "$stage/vaultwarden.sql" | grep -q '^-- Dump completed' || fail "dump is truncated (no 'Dump completed' trailer)"
grep -q 'CREATE TABLE `ciphers`' "$stage/vaultwarden.sql" || fail "dump has no ciphers table"

# --no-preserve=mode: the live files may carry loose modes; under umask 077 the copies get 0600/0700.
for f in rsa_key.pem rsa_key.pub.pem config.json attachments sends; do
  if [ -e "$DATA_DIR/$f" ]; then
    cp -r --no-preserve=mode,ownership "$DATA_DIR/$f" "$stage/"
  fi
done

(cd "$stage" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)

tar -C "$work" -czf "$work/archive.tar.gz" vaultwarden
gzip -t "$work/archive.tar.gz" || fail "archive failed gzip -t"
chmod 600 "$work/archive.tar.gz"
mv -f "$work/archive.tar.gz" "$out"

# Retention runs only after today's archive is safely in place.
find "$DEST" -maxdepth 1 -type f -name 'vaultwarden-*.tar.gz' -mtime +"$KEEP_DAYS" -print -delete

echo "ok $out $(stat -c %s "$out") bytes; $(find "$DEST" -maxdepth 1 -name 'vaultwarden-*.tar.gz' | wc -l) archives kept (${KEEP_DAYS}d)"
