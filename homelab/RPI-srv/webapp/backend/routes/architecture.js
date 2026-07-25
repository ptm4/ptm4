// Two independent things share this file:
//
// 1. GET /live — status for the Map tab's Sync button. Reads the same already-collected
//    runner reports the Reports tab uses (hardware/software/homelab-doctor latest) — no
//    new SSH round trip, just the freshest snapshot already sitting in AGENT_LOGS_DIR.
//
// 2. POST /ingest + GET /data — the architecture agent's push target and the merge
//    engine. Added 2026-07-25. The curated facts (hosts, nodes, notes, flows,
//    observations — everything a probe can't produce) live in the static
//    frontend/architecture/data.json, built by
//    homelab/Tools/architecture/build-arch-data.py, and are NEVER written by this
//    route. Per-host agent fragments land in a writable volume and are merged in at
//    read time, so a bad or stale agent push can only ever add `_live` decoration and
//    `drift` entries — it cannot corrupt or overwrite the curated baseline. See
//    homelab/Tools/arch-agent/hl-arch-agent.py for what a fragment contains.
const express = require('express');
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR } = require('./controls');

const router = express.Router();

// Writable — every other mount in this container is :ro (see docker-compose.yml's
// arch_data volume). Fragments are overwrite-in-place: Force Sync always means "now",
// so unlike the runners there is no dated history to keep.
const ARCH_DATA_DIR = fs.existsSync('/arch-data')
  ? '/arch-data'
  : path.join(__dirname, '..', '..', '..', '..', '..', 'arch-data-dev');
const FRAGMENTS_DIR = path.join(ARCH_DATA_DIR, 'fragments');

const CURATED_PATH = path.join(__dirname, '..', '..', 'frontend', 'architecture', 'data.json');

const INGEST_TOKEN = process.env.HL_ARCH_INGEST_TOKEN || '';

const HOST_ID_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

function readReport(name) {
  try {
    return JSON.parse(fs.readFileSync(path.join(AGENT_LOGS_DIR, `${name}.json`), 'utf8'));
  } catch (_) {
    return null;
  }
}

// GET /api/architecture/live — { hosts: { <host>: {...} }, run_at, synced_at }
router.get('/live', (req, res) => {
  const hardware = readReport('hardware-latest');
  const software = readReport('software-latest');
  const doctor = readReport('homelab-doctor-latest');

  const hosts = {};
  const host = (name) => (hosts[name] ||= { host: name });

  (hardware?.hosts || []).forEach(h => {
    const t = host(h.host);
    t.status = h.status;
    t.summary = h.summary;
    t.uptime = h.metrics?.uptime ?? null;
    t.disk_used_pct = h.metrics?.disks?.[0]?.used_pct ?? null;
  });

  (doctor?.hosts || []).forEach(h => {
    const t = host(h.host);
    t.doctor_status = h.status;
    t.containers = (h.metrics?.containers || []).map(c => ({ name: c.name, status: c.status }));
    t.pool = h.metrics?.pool || null;
  });

  (software?.hosts || []).forEach(h => {
    const t = host(h.host);
    t.pending_updates = h.metrics?.pending_count ?? null;
  });

  res.json({
    hosts,
    run_at: doctor?.run_at || hardware?.run_at || null,
    doctor_summary: doctor?.summary || null,
    synced_at: new Date().toISOString(),
  });
});

// ── ingest ─────────────────────────────────────────────────────────────────────
function checkToken(req, res) {
  if (!INGEST_TOKEN) return true;   // matches the dispatcher's optional-token pattern
  const auth = req.get('Authorization') || '';
  if (auth === `Bearer ${INGEST_TOKEN}`) return true;
  res.status(401).json({ error: 'unauthorized' });
  return false;
}

function fragmentPath(host) {
  return path.join(FRAGMENTS_DIR, `${host}.json`);
}

// POST /api/architecture/ingest — a per-host fragment from hl-arch-agent.py.
// Body is the whole fragment; the only field this route trusts as a filename is
// `host`, and it's validated against HOST_ID_RE first — never interpolated raw.
// Body is parsed by the global express.json() in index.js (limit raised there for
// exactly this route — a per-route parser here would be a silent no-op after it).
router.post('/ingest', (req, res) => {
  if (!checkToken(req, res)) return;

  const host = req.body?.host;
  if (typeof host !== 'string' || !HOST_ID_RE.test(host)) {
    return res.status(400).json({ error: 'body.host must match ' + HOST_ID_RE });
  }

  try {
    fs.mkdirSync(FRAGMENTS_DIR, { recursive: true });
    const tmp = fragmentPath(host) + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(req.body));
    fs.renameSync(tmp, fragmentPath(host));
  } catch (e) {
    console.error(`[architecture] failed to write fragment for ${host}: ${e.message}`);
    return res.status(500).json({ error: 'could not store fragment', detail: e.message });
  }

  const containers = (req.body?.docker?.containers || []).length;
  res.json({ ok: true, host, containers, received_at: new Date().toISOString() });
});

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
// and populate `live_merge` — the curated arrays themselves are never mutated in place
// beyond that decoration, so a missing or malformed fragment degrades to "no live data
// for that host", never a corrupted page.
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

  // Drift, in both directions — this is the TODO list the plan promised: things
  // running that no one has described yet, and things described that no longer are.
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

// GET /api/architecture/data — curated data.json decorated with live agent facts.
// The frontend fetches this first and falls back to the static data.json on any
// failure, so a broken merge (or an ARCH_DATA_DIR that doesn't exist yet on a fresh
// deploy) never blanks the page — it just shows the curated baseline with no drift.
router.get('/data', (req, res) => {
  try {
    res.json(buildMergedData());
  } catch (e) {
    console.error(`[architecture] merge failed: ${e.message}`);
    res.status(500).json({ error: 'merge failed', detail: e.message });
  }
});

// Express routers are plain functions, so attaching a property is a legitimate way to
// share this one piece of logic with routes/agents.js (the Agents config page's
// per-host drift counts) without duplicating the merge or standing up a second HTTP
// round trip just to read data this process already has on disk.
router.buildMergedData = buildMergedData;

module.exports = router;
