const express = require('express');
const fs = require('fs');
const path = require('path');
const { enabledFor, attachControls } = require('./controls');

const router = express.Router();

// /reports is the Docker volume mount: /mnt/opti-fs/ptm/security-reports
// Falls back to a local dev path if the mount isn't present
const REPORTS_DIR = fs.existsSync('/reports')
  ? '/reports'
  : path.join(__dirname, '..', '..', '..', '..', 'security-reports');

// report name (filename minus .json) -> { label, agent (dispatcher key), cadence_h }
const CATALOG = {
  'journal-hunt-latest':     { label: 'Journal Threat & Health Hunter', agent: 'journald-hunter',     cadence_h: 24 },
  'persistence-audit-latest':{ label: 'Persistence Auditor',            agent: 'persistence-auditor', cadence_h: 24 },
  // LinkedIn watcher is on hold — kept so any legacy report still renders, no controls.
  'linkedin-jobs-latest':    { label: 'LinkedIn Job Watcher',           agent: null,                  cadence_h: 24 },
};

function describe(filename) {
  const name = filename.replace('.json', '');
  const meta = CATALOG[name] || { label: name, agent: null, cadence_h: 24 };
  const fullPath = path.join(REPORTS_DIR, filename);
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

// GET /api/reports — list security reports with metadata
router.get('/', (req, res) => {
  if (!fs.existsSync(REPORTS_DIR)) {
    return res.json({ reports: [], message: 'Reports directory not found' });
  }
  let files;
  try {
    files = fs.readdirSync(REPORTS_DIR).filter(f => f.endsWith('.json'));
  } catch (e) {
    return res.status(500).json({ error: 'Cannot read reports directory' });
  }

  const reports = files.map(describe);
  const order = { critical: 0, warn: 1, ok: 2, unknown: 3 };
  reports.sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));
  res.json({ reports, reports_dir: REPORTS_DIR });
});

// Enable/disable + run-now (proxied to the opti dispatcher)
attachControls(router);

// GET /api/reports/:name — return full JSON report
router.get('/:name', (req, res) => {
  const filename = req.params.name.endsWith('.json')
    ? req.params.name
    : `${req.params.name}.json`;
  const fullPath = path.join(REPORTS_DIR, filename);

  if (!fullPath.startsWith(REPORTS_DIR)) {
    return res.status(400).json({ error: 'Invalid report name' });
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
