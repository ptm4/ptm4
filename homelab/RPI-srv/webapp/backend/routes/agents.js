const express = require('express');
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR, enabledFor, attachControls } = require('./controls');

const router = express.Router();

// report name -> { label, agent (dispatcher key), cadence_h, home, order }
// `home: true` items are surfaced on the Home page, not in the #agents list.
// `order` fixes the card display order on the #agents page (lower = first):
// Homelab Doctor → Hardware → Software → Network.
const CATALOG = {
  'homelab-doctor-latest': { label: 'Homelab Doctor',   agent: 'homelab-doctor',     cadence_h: 1,  order: 0 },
  'hardware-latest':       { label: 'Hardware Report',  agent: 'hardware-report',    cadence_h: 24, order: 1 },
  'software-latest':       { label: 'Software Inventory',agent: 'software-inventory', cadence_h: 24, order: 2 },
  'network-latest':        { label: 'Network',          agent: 'network-report',     cadence_h: 1,  order: 3 },
  'leetify-latest':        { label: 'Leetify CS2 Stats',agent: 'leetify-stats',      cadence_h: 24, home: true },
};

function describe(filename) {
  const name = filename.replace('.json', '');
  const meta = CATALOG[name] || { label: name, agent: null, cadence_h: 24 };
  const fullPath = path.join(AGENT_LOGS_DIR, filename);
  const stat = fs.statSync(fullPath);

  let status = 'unknown', summary = '', runAt = null, hasAlert = false;
  try {
    const raw = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
    status = raw.status || 'unknown';
    summary = raw.summary || '';
    runAt = raw.run_at || null;
    hasAlert = hasAlertFlag(raw);
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
    has_alert: hasAlert,
    mtime: stat.mtime.toISOString(),
    cadence_hours: meta.cadence_h,
    order: meta.order ?? 99,
    stale: ageH > meta.cadence_h * 2,
    enabled: meta.agent ? enabledFor(meta.agent) : true,
  };
}

// ALERT badge: any critical/high finding or recommendation, or an overall critical status.
function hasAlertFlag(raw) {
  if (raw.status === 'critical') return true;
  const items = [...(raw.findings || []), ...(raw.recommendations || [])];
  return items.some(i => ['critical', 'high'].includes((i.severity || '').toLowerCase()));
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
  // Fixed display order (Doctor → Hardware → Software → Network); unknown agents fall
  // to the end, tie-broken by label so the layout is stable run to run.
  agents.sort((a, b) => (a.order - b.order) || a.label.localeCompare(b.label));
  res.json({ agents, agent_logs_dir: AGENT_LOGS_DIR });
});

// Enable/disable + run-now (proxied to the opti dispatcher)
attachControls(router);

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

// GET /api/agents/:name/history — list dated report files for an agent, newest first.
// Collectors write agent-logs/<name>/<YYYY-MM-DD>.json alongside <name>.json (the latest pointer).
router.get('/:name/history', (req, res) => {
  const base = req.params.name.replace(/\.json$/, '');
  const dir = path.join(AGENT_LOGS_DIR, base);
  // Path-traversal guard
  if (!dir.startsWith(AGENT_LOGS_DIR + path.sep)) {
    return res.status(400).json({ error: 'Invalid agent name' });
  }
  if (!fs.existsSync(dir)) {
    return res.json({ name: base, history: [] });
  }
  let files;
  try {
    files = fs.readdirSync(dir).filter(f => DATE_RE.test(f.replace(/\.json$/, '')) && f.endsWith('.json'));
  } catch (_) {
    return res.json({ name: base, history: [] });
  }
  const history = files.map(f => {
    const full = path.join(dir, f);
    let size = 0, mtime = null;
    try { const s = fs.statSync(full); size = s.size; mtime = s.mtime.toISOString(); } catch (_) {}
    return { date: f.replace(/\.json$/, ''), filename: f, size, mtime };
  }).sort((a, b) => b.date.localeCompare(a.date));
  res.json({ name: base, history });
});

// GET /api/agents/:name/report/:date — a specific dated report
router.get('/:name/report/:date', (req, res) => {
  const base = req.params.name.replace(/\.json$/, '');
  if (!DATE_RE.test(req.params.date)) {
    return res.status(400).json({ error: 'Bad date' });
  }
  const dir = path.join(AGENT_LOGS_DIR, base);
  const full = path.join(dir, `${req.params.date}.json`);
  // Path-traversal guard
  if (!full.startsWith(dir + path.sep)) {
    return res.status(400).json({ error: 'Invalid path' });
  }
  if (!fs.existsSync(full)) {
    return res.status(404).json({ error: 'Report not found' });
  }
  try {
    res.json(JSON.parse(fs.readFileSync(full, 'utf8')));
  } catch (e) {
    console.error(`Failed to parse report ${full}: ${e.message}`);
    res.status(500).json({ error: 'Could not parse report file', detail: e.message });
  }
});

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
    console.error(`Failed to parse report ${fullPath}: ${e.message}`);
    res.status(500).json({ error: 'Could not parse report file', detail: e.message });
  }
});

module.exports = router;
