const express = require('express');
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR, enabledFor, attachControls } = require('./controls');

const router = express.Router();

// report name -> { label, agent (dispatcher key), cadence_h, home }
// `home: true` items are surfaced on the Home page, not in the #agents list.
const CATALOG = {
  'hardware-latest':       { label: 'Hardware Report',  agent: 'hardware-report',    cadence_h: 24 },
  'software-latest':       { label: 'Software Inventory',agent: 'software-inventory', cadence_h: 24 },
  'homelab-doctor-latest': { label: 'Homelab Doctor',   agent: 'homelab-doctor',     cadence_h: 1 },
  'network-latest':        { label: 'Network',          agent: 'network-report',     cadence_h: 1 },
  'leetify-latest':        { label: 'Leetify CS2 Stats',agent: 'leetify-stats',      cadence_h: 24, home: true },
};

function describe(filename) {
  const name = filename.replace('.json', '');
  const meta = CATALOG[name] || { label: name, agent: null, cadence_h: 24 };
  const fullPath = path.join(AGENT_LOGS_DIR, filename);
  const stat = fs.statSync(fullPath);

  let status = 'unknown', summary = '', runAt = null;
  try {
    const raw = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
    status = raw.status || 'unknown';
    summary = raw.summary || '';
    runAt = raw.run_at || null;
  } catch (_) {}

  const ageH = (Date.now() - stat.mtimeMs) / 3600000;
  return {
    name,
    label: meta.label,
    agent: meta.agent,
    home: !!meta.home,
    filename,
    status,
    summary,
    run_at: runAt,
    mtime: stat.mtime.toISOString(),
    cadence_hours: meta.cadence_h,
    stale: ageH > meta.cadence_h * 2,
    enabled: meta.agent ? enabledFor(meta.agent) : true,
  };
}

// GET /api/agents — list homelab agents (excludes Home-only items like Leetify)
router.get('/', (req, res) => {
  if (!fs.existsSync(AGENT_LOGS_DIR)) {
    return res.json({ agents: [], message: 'Agent logs directory not found' });
  }
  let files;
  try {
    files = fs.readdirSync(AGENT_LOGS_DIR).filter(f => f.endsWith('.json') && f !== 'agents-state.json');
  } catch (e) {
    return res.status(500).json({ error: 'Cannot read agent logs directory' });
  }

  const all = files.map(describe);
  const agents = all.filter(a => !a.home);
  const order = { critical: 0, warn: 1, ok: 2, unknown: 3 };
  agents.sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));
  res.json({ agents, agent_logs_dir: AGENT_LOGS_DIR });
});

// Enable/disable + run-now (proxied to the opti dispatcher)
attachControls(router);

// GET /api/agents/:name — full JSON report (also serves the Home Leetify card)
router.get('/:name', (req, res) => {
  const filename = req.params.name.endsWith('.json')
    ? req.params.name
    : `${req.params.name}.json`;
  const fullPath = path.join(AGENT_LOGS_DIR, filename);

  if (!fullPath.startsWith(AGENT_LOGS_DIR)) {
    return res.status(400).json({ error: 'Invalid agent name' });
  }
  if (!fs.existsSync(fullPath)) {
    return res.status(404).json({ error: 'Report not found' });
  }
  try {
    res.json(JSON.parse(fs.readFileSync(fullPath, 'utf8')));
  } catch (e) {
    res.status(500).json({ error: 'Could not parse report file' });
  }
});

module.exports = router;
