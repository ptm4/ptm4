#!/usr/bin/env bash
# Issue (or reissue) a leaf certificate signed by the ptm Homelab CA.
#
# The CA lives on opti's pool: <certs>/ca/hl-ca.crt + hl-ca-key.pem (created
# 2026-08-02, valid to 2036). Leaves are capped at 825 days — the maximum
# validity Android/iOS accept for locally-trusted certs — so expect to rerun
# this roughly every two years (webapp cert next expires 2028-11-04).
#
# Usage:
#   issue-cert.sh <basename> <san>[,<san>...]
#   issue-cert.sh webapp.rpi.lan DNS:webapp.rpi.lan,DNS:webapp.rpi,IP:192.168.1.10
#
# Writes <certs>/<basename>.pem and <certs>/<basename>-key.pem, backing up any
# existing pair. nginx on rpi bind-mounts these paths, so after reissuing:
#   ssh rpi 'docker restart nginx-webapp'
set -euo pipefail

CERTS_DIR="${CERTS_DIR:-/home/ptm/opti/ptm/certs}"   # tux view of opti:/srv/red/fs/ptm/certs
CA_CRT="$CERTS_DIR/ca/hl-ca.crt"
CA_KEY="$CERTS_DIR/ca/hl-ca-key.pem"

name="${1:?usage: issue-cert.sh <basename> <san>[,<san>...]}"
sans="${2:?missing SAN list, e.g. DNS:foo.lan,IP:192.168.1.10}"

cn="${sans%%,*}"; cn="${cn#DNS:}"; cn="${cn#IP:}"
tmp="$(mktemp -d)"
trap 'rm -f "$tmp"/*; rmdir "$tmp"' EXIT

openssl genrsa -out "$tmp/key.pem" 2048
openssl req -new -key "$tmp/key.pem" -subj "/CN=$cn" -out "$tmp/req.csr"
printf 'basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\n' "$sans" > "$tmp/ext.cnf"
openssl x509 -req -in "$tmp/req.csr" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
  -days 825 -sha256 -extfile "$tmp/ext.cnf" -out "$tmp/crt.pem"

stamp="$(date +%F)"
for f in "$CERTS_DIR/$name.pem" "$CERTS_DIR/$name-key.pem"; do
  [ -f "$f" ] && cp "$f" "$f.bak-$stamp"
done
cp "$tmp/crt.pem" "$CERTS_DIR/$name.pem"
cp "$tmp/key.pem" "$CERTS_DIR/$name-key.pem"

openssl x509 -in "$CERTS_DIR/$name.pem" -noout -subject -dates -ext subjectAltName
openssl verify -CAfile "$CA_CRT" "$CERTS_DIR/$name.pem"
