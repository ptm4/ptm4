#!/bin/bash
# Runs before Apache starts.
# 1. Generates WordPress auth keys/salts once and persists them to the uploads share.
#    On every subsequent start the same keys are reloaded — no manual intervention needed.
# 2. Symlinks plugin subdirectories that require runtime write access to the persistent
#    uploads share so writes survive container restarts and new image deploys.
set -euo pipefail

UPLOADS=/var/www/html/wp-content/uploads
PLUGINS=/var/www/html/wp-content/plugins
KEYS_FILE="${UPLOADS}/.wp-keys/auth-keys.env"

# ── Auth keys ────────────────────────────────────────────────────────────────
# Generate once on first start and persist to the uploads share as an env file.
# Exported as WORDPRESS_AUTH_KEY etc. so the official WordPress image reads them
# via getenv_docker() before defining the constants — avoiding the "already defined"
# conflict that occurs when injecting via WORDPRESS_CONFIG_EXTRA require_once.
# To rotate: delete .wp-keys/auth-keys.env from the uploads share and restart.
mkdir -p "$(dirname "${KEYS_FILE}")"

if [ ! -f "${KEYS_FILE}" ]; then
  echo "Generating WordPress auth keys (first start)..."
  php -r "
    \$names = [
      'WORDPRESS_AUTH_KEY','WORDPRESS_SECURE_AUTH_KEY','WORDPRESS_LOGGED_IN_KEY','WORDPRESS_NONCE_KEY',
      'WORDPRESS_AUTH_SALT','WORDPRESS_SECURE_AUTH_SALT','WORDPRESS_LOGGED_IN_SALT','WORDPRESS_NONCE_SALT'
    ];
    foreach (\$names as \$n) {
      echo \$n . '=\"' . base64_encode(random_bytes(48)) . '\"' . PHP_EOL;
    }
  " > "${KEYS_FILE}"
  chown www-data:www-data "${KEYS_FILE}"
  echo "Auth keys written to ${KEYS_FILE}"
fi

# shellcheck source=/dev/null
set -a; source "${KEYS_FILE}"; set +a

# ── Plugin writable dirs ──────────────────────────────────────────────────────
# Subdirectory names inside plugin folders that require persistent write access.
# Symlinks are always pre-created — this covers both dirs bundled in the image
# and dirs that plugins create at runtime (which would fail on read-only layers).
# Add a name here if a new plugin uses a different convention.
WRITABLE_NAMES=("storage" "data" "cache" "tmp" "backups" "logs")

for plugin_dir in "${PLUGINS}"/*/; do
  [ -d "${plugin_dir}" ] || continue
  plugin_slug=$(basename "${plugin_dir}")
  for name in "${WRITABLE_NAMES[@]}"; do
    src="${plugin_dir}${name}"
    target="${UPLOADS}/.plugin-data/${plugin_slug}/${name}"
    mkdir -p "${target}"
    chown www-data:www-data "${target}"
    if [ -d "${src}" ] && [ ! -L "${src}" ]; then
      rm -rf "${src}"
    fi
    ln -sfn "${target}" "${src}"
  done
done

exec docker-entrypoint.sh apache2-foreground
