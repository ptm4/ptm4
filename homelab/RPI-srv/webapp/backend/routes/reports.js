const express = require('express');
const fs = require('fs');
const path = require('path');

const router = express.Router();

// /reports is the Docker volume mount: /mnt/noblenumbat-fs/ptm/security-reports
// Falls back to a local dev path if the mount isn't present
const REPORTS_DIR = fs.existsSync('/reports')
  ? '/reports'
  : path.join(__dirname, '..', '..', '..', '..', 'security-reports');

const TOOL_LABELS = {
  'arp-watch-latest':            'ARP Watch',
  'rogue-ap-latest':             'Rogue AP Hunter',
  'event-log-latest':            'Event Log Hunter',
  'sched-tasks-latest':          'Scheduled Task Auditor',
  'registry-persist-latest':     'Registry Persist Checker',
  'http-headers-latest':         'HTTP Header Checker',
  'geoip-latest':                'GeoIP Log Mapper',
  'linkedin-jobs-latest':        'LinkedIn Job Watcher',
};

// GET /api/reports — list all available reports with metadata
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

  const reports = files.map(filename => {
    const fullPath = path.join(REPORTS_DIR, filename);
    const stat = fs.statSync(fullPath);
    const name = filename.replace('.json', '');

    let status = 'unknown', summary = '', runAt = null;
    try {
      const raw = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
      status  = raw.status  || 'unknown';
      summary = raw.summary || '';
      runAt   = raw.run_at  || null;
    } catch (_) {}

    const hasMap = filename === 'geoip-latest.json' &&
                   fs.existsSync(path.join(REPORTS_DIR, 'geoip-latest.html'));

    return {
      name,
      label:     TOOL_LABELS[name] || name,
      filename,
      status,
      summary,
      run_at:    runAt,
      mtime:     stat.mtime.toISOString(),
      has_map:   hasMap,
    };
  });

  // Sort: critical first, then warn, then ok
  const order = { critical: 0, warn: 1, ok: 2, unknown: 3 };
  reports.sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));

  res.json({ reports, reports_dir: REPORTS_DIR });
});

// GET /api/reports/:name — return full JSON report
router.get('/:name', (req, res) => {
  const filename = req.params.name.endsWith('.json')
    ? req.params.name
    : `${req.params.name}.json`;

  const fullPath = path.join(REPORTS_DIR, filename);

  // Path traversal guard
  if (!fullPath.startsWith(REPORTS_DIR)) {
    return res.status(400).json({ error: 'Invalid report name' });
  }

  if (!fs.existsSync(fullPath)) {
    return res.status(404).json({ error: 'Report not found' });
  }

  try {
    const data = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
    res.json(data);
  } catch (e) {
    res.status(500).json({ error: 'Could not parse report file' });
  }
});

// GET /api/reports/geoip/map — serve the interactive HTML map
router.get('/geoip/map', (req, res) => {
  const mapPath = path.join(REPORTS_DIR, 'geoip-latest.html');
  if (!fs.existsSync(mapPath)) {
    return res.status(404).send('<p>GeoIP map not yet generated. Run geoip-log-mapper.py first.</p>');
  }
  res.setHeader('Content-Type', 'text/html');
  res.sendFile(mapPath);
});

module.exports = router;
