// Live status for the Architecture page's Sync button. Reads the same already-collected
// agent reports the #agents tab uses (hardware/software/homelab-doctor latest) — no new
// SSH round trip, just the freshest snapshot already sitting in AGENT_LOGS_DIR.
const express = require('express');
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR } = require('./controls');

const router = express.Router();

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

module.exports = router;
