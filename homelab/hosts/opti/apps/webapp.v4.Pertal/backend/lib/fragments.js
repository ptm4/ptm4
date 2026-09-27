// Architecture fragments — the full per-host inventory hl-arch-agent pushes daily to
// POST /api/architecture/ingest. Same contract and storage as v3 (the agents are
// configured with that URL), so cutover needs no agent change.
'use strict';
const fs = require('fs');
const path = require('path');
const { ARCH_DATA_DIR } = require('./paths');

const FRAGMENTS_DIR = path.join(ARCH_DATA_DIR, 'fragments');
const HOST_ID_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

function writeFragment(host, body) {
  if (!HOST_ID_RE.test(host)) throw new Error(`bad host id '${host}'`);
  fs.mkdirSync(FRAGMENTS_DIR, { recursive: true });
  const file = path.join(FRAGMENTS_DIR, `${host}.json`);
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify({ ...body, received_at: new Date().toISOString() }, null, 2));
  fs.renameSync(tmp, file);
}

function readFragment(host) {
  if (!HOST_ID_RE.test(host)) return null;
  try { return JSON.parse(fs.readFileSync(path.join(FRAGMENTS_DIR, `${host}.json`), 'utf8')); } catch (_) { return null; }
}

module.exports = { FRAGMENTS_DIR, HOST_ID_RE, writeFragment, readFragment };
