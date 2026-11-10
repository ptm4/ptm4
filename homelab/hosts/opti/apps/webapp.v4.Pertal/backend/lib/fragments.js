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

function readFragments() {
  let files;
  try { files = fs.readdirSync(FRAGMENTS_DIR).filter((f) => f.endsWith('.json')); } catch (_) { return {}; }
  const byHost = {};
  for (const f of files) {
    try {
      const frag = JSON.parse(fs.readFileSync(path.join(FRAGMENTS_DIR, f), 'utf8'));
      if (frag && typeof frag.host === 'string') byHost[frag.host] = frag;
    } catch (_) { /* one bad fragment shouldn't break the merge */ }
  }
  return byHost;
}

// GET /api/architecture/data, ported verbatim from v3's lib/arch-data.js: the curated
// data.json (the architecture map's build-arch-data.py output, never written here)
// decorated with each node's live container (`_live`) plus drift in both directions.
// homelab-db's ingest and the nightly gen-agentic-docs read this, so the shape is a
// contract. The curated file comes from PERTAL_ARCH_DATA (see docker-compose.apps.yml).
function buildMergedData(curatedPath = process.env.CURATED_ARCH_PATH || process.env.PERTAL_ARCH_DATA) {
  if (!curatedPath) throw new Error('PERTAL_ARCH_DATA is not set');
  const curated = JSON.parse(fs.readFileSync(curatedPath, 'utf8'));
  const fragmentsByHost = readFragments();

  const matched = new Set();
  for (const node of curated.nodes || []) {
    if (!node.container) continue;
    const frag = fragmentsByHost[node.host];
    const live = frag?.docker?.containers?.find((c) => c.name === node.container);
    if (live) {
      matched.add(`${node.host}::${node.container}`);
      node._live = {
        state: live.state, image: live.image, ports: live.ports, mounts: live.mounts,
        network_mode: live.network_mode, compose_project: live.compose_project,
        compose_service: live.compose_service, collected_at: frag.collected_at,
      };
    }
  }
  const undescribed = [];
  for (const [host, frag] of Object.entries(fragmentsByHost)) {
    for (const c of frag?.docker?.containers || []) {
      if (!matched.has(`${host}::${c.name}`)) undescribed.push({ host, container: c.name, image: c.image, state: c.state });
    }
  }
  const missing = [];
  for (const node of curated.nodes || []) {
    if (!node.container) continue;
    if (!fragmentsByHost[node.host]) continue; // no fragment for this host: not evidence of removal
    if (!matched.has(`${node.host}::${node.container}`)) missing.push({ host: node.host, container: node.container, node: node.id, label: node.label });
  }
  const ingested = {};
  for (const [host, frag] of Object.entries(fragmentsByHost)) {
    ingested[host] = {
      collected_at: frag.collected_at, agent_version: frag.agent_version,
      containers: (frag.docker?.containers || []).length, errors: frag.errors || {},
    };
  }
  curated.live_merge = { ingested, drift: { undescribed, missing }, generated_at: new Date().toISOString() };
  return curated;
}

module.exports = { FRAGMENTS_DIR, HOST_ID_RE, writeFragment, readFragment, readFragments, buildMergedData };
