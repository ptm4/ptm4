// Two independent things share this file:
//
// 1. GET /live — status for the Map tab's Sync button. Reads the same already-collected
//    runner reports the Reports tab uses — no new SSH round trip.
//
// 2. POST /ingest + GET /data — the architecture agent's push target and the merge
//    engine (the engine itself lives in lib/arch-data.js now). The curated facts live
//    in the static frontend-legacy/architecture/data.json and are NEVER written by
//    this route; per-host agent fragments land in the writable volume and are merged
//    at read time.
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR } = require('../lib/controls');
const { HOST_ID_RE, writeFragment, buildMergedData } = require('../lib/arch-data');

const INGEST_TOKEN = process.env.HL_ARCH_INGEST_TOKEN || '';

function readReport(name) {
  try {
    return JSON.parse(fs.readFileSync(path.join(AGENT_LOGS_DIR, `${name}.json`), 'utf8'));
  } catch (_) {
    return null;
  }
}

module.exports = async function architectureRoutes(app) {
  // GET /api/architecture/live — { hosts: { <host>: {...} }, run_at, synced_at }
  app.get('/live', async () => {
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

    return {
      hosts,
      run_at: doctor?.run_at || hardware?.run_at || null,
      doctor_summary: doctor?.summary || null,
      synced_at: new Date().toISOString(),
    };
  });

  // POST /api/architecture/ingest — a per-host fragment from hl-arch-agent.py.
  // Body is the whole fragment; the only field this route trusts as a filename is
  // `host`, and it's validated against HOST_ID_RE first — never interpolated raw.
  // The 5MB bodyLimit in app.js exists for exactly this route.
  app.post('/ingest', async (req, reply) => {
    if (INGEST_TOKEN) {
      const auth = req.headers['authorization'] || '';
      if (auth !== `Bearer ${INGEST_TOKEN}`) {
        return reply.code(401).send({ error: 'unauthorized' });
      }
    }

    const host = req.body?.host;
    if (typeof host !== 'string' || !HOST_ID_RE.test(host)) {
      return reply.code(400).send({ error: 'body.host must match ' + HOST_ID_RE });
    }

    try {
      writeFragment(host, req.body);
    } catch (e) {
      console.error(`[architecture] failed to write fragment for ${host}: ${e.message}`);
      return reply.code(500).send({ error: 'could not store fragment', detail: e.message });
    }

    const containers = (req.body?.docker?.containers || []).length;
    return { ok: true, host, containers, received_at: new Date().toISOString() };
  });

  // GET /api/architecture/data — curated data.json decorated with live agent facts.
  // The frontend fetches this first and falls back to the static data.json on any
  // failure, so a broken merge (or an ARCH_DATA_DIR that doesn't exist yet on a fresh
  // deploy) never blanks the page — it just shows the curated baseline with no drift.
  app.get('/data', async (req, reply) => {
    try {
      return buildMergedData();
    } catch (e) {
      console.error(`[architecture] merge failed: ${e.message}`);
      return reply.code(500).send({ error: 'merge failed', detail: e.message });
    }
  });
};
