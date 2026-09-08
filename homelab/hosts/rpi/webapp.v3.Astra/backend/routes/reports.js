// Security reports (/reports mount = opti's security-reports dir, :ro).
const fs = require('fs');
const path = require('path');
const { REPORTS_DIR } = require('../lib/paths');
const { enabledFor, attachControls } = require('../lib/controls');

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

module.exports = async function reportsRoutes(app) {
  // GET /api/reports — list security reports with metadata
  app.get('/', async (req, reply) => {
    if (!fs.existsSync(REPORTS_DIR)) {
      return { reports: [], message: 'Reports directory not found' };
    }
    let files;
    try {
      files = fs.readdirSync(REPORTS_DIR).filter(f => f.endsWith('.json'));
    } catch (e) {
      return reply.code(500).send({ error: 'Cannot read reports directory' });
    }

    const reports = files.map(describe);
    const order = { critical: 0, warn: 1, ok: 2, unknown: 3 };
    reports.sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));
    return { reports, reports_dir: REPORTS_DIR };
  });

  // Enable/disable + run-now (proxied to the opti dispatcher)
  attachControls(app);

  // GET /api/reports/:name — return full JSON report
  app.get('/:name', async (req, reply) => {
    const filename = req.params.name.endsWith('.json')
      ? req.params.name
      : `${req.params.name}.json`;
    const fullPath = path.join(REPORTS_DIR, filename);

    if (!fullPath.startsWith(REPORTS_DIR)) {
      return reply.code(400).send({ error: 'Invalid report name' });
    }
    if (!fs.existsSync(fullPath)) {
      return reply.code(404).send({ error: 'Report not found' });
    }
    try {
      return JSON.parse(fs.readFileSync(fullPath, 'utf8'));
    } catch (e) {
      console.error(`Failed to parse report ${fullPath}: ${e.message}`);
      return reply.code(500).send({ error: 'Could not parse report file', detail: e.message });
    }
  });
};
