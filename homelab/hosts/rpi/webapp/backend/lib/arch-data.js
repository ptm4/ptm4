// Fragment store + curated/live merge engine, shared by /api/architecture (its own
// endpoints), /api/agents (per-host drift counts) and the /api dashboard read-models.
// In v1 this lived on routes/architecture.js as router properties, which meant routes
// requiring routes; it is a library now.
//
// The curated facts (hosts, nodes, notes, flows, observations — everything a probe
// can't produce) live in the static frontend-legacy/architecture/data.json, built by
// homelab/tools/architecture/build-arch-data.py, and are NEVER written here. Per-host
// agent fragments land in the writable volume and are merged at read time, so a bad
// or stale agent push can only ever add `_live` decoration and `drift` entries — it
// cannot corrupt or overwrite the curated baseline.
const fs = require('fs');
const path = require('path');
const { ARCH_DATA_DIR, LEGACY_DIR } = require('./paths');

const FRAGMENTS_DIR = path.join(ARCH_DATA_DIR, 'fragments');
const CURATED_PATH = process.env.CURATED_ARCH_PATH
  || path.join(LEGACY_DIR, 'architecture', 'data.json');

const HOST_ID_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

function fragmentPath(host) {
  return path.join(FRAGMENTS_DIR, `${host}.json`);
}

// Overwrite-in-place, atomically: Force Sync always means "now", so unlike the
// runners there is no dated history to keep.
function writeFragment(host, body) {
  fs.mkdirSync(FRAGMENTS_DIR, { recursive: true });
  const tmp = fragmentPath(host) + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(body));
  fs.renameSync(tmp, fragmentPath(host));
}

function readFragments() {
  let files;
  try {
    files = fs.readdirSync(FRAGMENTS_DIR).filter(f => f.endsWith('.json'));
  } catch (_) {
    return {};
  }
  const byHost = {};
  for (const f of files) {
    try {
      const frag = JSON.parse(fs.readFileSync(path.join(FRAGMENTS_DIR, f), 'utf8'));
      if (frag && typeof frag.host === 'string') byHost[frag.host] = frag;
    } catch (_) { /* one bad fragment shouldn't break the merge */ }
  }
  return byHost;
}

// Merge curated (source of truth for meaning) with the newest agent fragments (source
// of truth for "what's actually running"). Fragments only ever ADD `_live` to a node
// and populate `live_merge` — a missing or malformed fragment degrades to "no live
// data for that host", never a corrupted page.
function buildMergedData() {
  const curated = JSON.parse(fs.readFileSync(CURATED_PATH, 'utf8'));
  const fragmentsByHost = readFragments();

  const matched = new Set();   // "<host>::<container>" pairs described AND detected
  for (const node of curated.nodes || []) {
    if (!node.container) continue;
    const frag = fragmentsByHost[node.host];
    const live = frag?.docker?.containers?.find(c => c.name === node.container);
    if (live) {
      matched.add(`${node.host}::${node.container}`);
      node._live = {
        state: live.state,
        image: live.image,
        ports: live.ports,
        mounts: live.mounts,
        network_mode: live.network_mode,
        compose_project: live.compose_project,
        compose_service: live.compose_service,
        collected_at: frag.collected_at,
      };
    }
  }

  // Drift, in both directions — things running that no one has described yet, and
  // things described that no longer are.
  const undescribed = [];
  for (const [host, frag] of Object.entries(fragmentsByHost)) {
    for (const c of frag?.docker?.containers || []) {
      if (!matched.has(`${host}::${c.name}`)) {
        undescribed.push({ host, container: c.name, image: c.image, state: c.state });
      }
    }
  }
  const missing = [];
  for (const node of curated.nodes || []) {
    if (!node.container) continue;
    const frag = fragmentsByHost[node.host];
    if (!frag) continue;   // no fragment for this host at all — not evidence of removal
    if (!matched.has(`${node.host}::${node.container}`)) {
      missing.push({ host: node.host, container: node.container, node: node.id, label: node.label });
    }
  }

  const ingested = {};
  for (const [host, frag] of Object.entries(fragmentsByHost)) {
    ingested[host] = {
      collected_at: frag.collected_at,
      agent_version: frag.agent_version,
      containers: (frag.docker?.containers || []).length,
      errors: frag.errors || {},
    };
  }

  curated.live_merge = {
    ingested,
    drift: { undescribed, missing },
    generated_at: new Date().toISOString(),
  };
  return curated;
}

module.exports = { FRAGMENTS_DIR, CURATED_PATH, HOST_ID_RE, writeFragment, readFragments, buildMergedData };
