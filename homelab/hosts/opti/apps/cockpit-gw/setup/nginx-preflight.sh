#!/usr/bin/env bash
set -euo pipefail
candidate=$(realpath "$1")
test -f "$candidate"
image=$(docker inspect -f '{{.Config.Image}}' nginx-webapp)
docker run --rm --network compose_internal \
  -v "$candidate:/etc/nginx/conf.d/default.conf:ro" \
  -v /srv/red/fs/ptm/certs/webapp.rpi.lan.pem:/etc/ssl/certs/webapp.crt:ro \
  -v /srv/red/fs/ptm/certs/webapp.rpi.lan-key.pem:/etc/ssl/private/webapp.key:ro \
  --entrypoint nginx "$image" -t
