// The scheduled runners (homelab-doctor, hardware, software, network, coldcopy…) —
// surfaced on the Reports page. "Runner" = a scheduled collector producing reports;
// "agent" = a per-host installed service (see routes/agents.js). Dispatcher agent keys
// (agents-state.json, agent-dispatcher.py) are deliberately NOT renamed — that's
// opti's control-plane vocabulary and touches the GH workflow too.
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR, enabledFor, attachControls } = require('../lib/controls');

// report name -> { label, agent (dispatcher key), cadence_h, home, order }
// `home: true` items are surfaced on the Home page, not in the runners list.
// `order` fixes the card display order (lower = first).
const CATALOG = {
  'homelab-doctor-latest': { label: 'Homelab Doctor',   agent: 'homelab-doctor',     cadence_h: 1,  order: 0 },
  'hardware-latest':       { label: 'Hardware Report',  agent: 'hardware-report',    cadence_h: 24, order: 1 },
  'software-latest':       { label: 'Software Inventory',agent: 'software-inventory', cadence_h: 24, order: 2 },
  'network-latest':        { label: 'Network',          agent: 'network-report',     cadence_h: 1,  order: 3 },
  'leetify-latest':        { label: 'Leetify CS2 Stats',agent: 'leetify-stats',      cadence_h: 24, home: true, manual: true },
  // Weekly cold-copy refresh of the ZFS pool onto the retired sda+sdb mergerfs pool.
  // cadence_h 168 => the stale badge appears after two missed weeks.
  'coldcopy-latest':       { label: 'Cold Copy Backup', agent: 'coldcopy',           cadence_h: 168, order: 4 },
  // Written by the discord-hltv bot, not a dispatcher agent — no run-now button and no
  // stale badge (manual).
  'hltv-watchlist':        { label: 'HLTV Watchlist',   agent: null,                 cadence_h: 168, manual: true, order: 5 },
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
    stale: !meta.manual && ageH > meta.cadence_h * 2,
    enabled: meta.agent ? enabledFor(meta.agent) : true,
  };
}

// ALERT badge: any critical/high finding or recommendation, or an overall critical status.
function hasAlertFlag(raw) {
  if (raw.status === 'critical') return true;
  const items = [...(raw.findings || []), ...(raw.recommendations || [])];
  return items.some(i => ['critical', 'high'].includes((i.severity || '').toLowerCase()));
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

module.exports = async function runnersRoutes(app) {
  // GET /api/runners — list homelab runners (excludes Home-only items like Leetify)
  app.get('/', async (req, reply) => {
    if (!fs.existsSync(AGENT_LOGS_DIR)) {
      return { runners: [], message: 'Agent logs directory not found' };
    }
    let files;
    try {
      files = fs.readdirSync(AGENT_LOGS_DIR).filter(f => f.endsWith('.json') && f !== 'agents-state.json');
    } catch (e) {
      return reply.code(500).send({ error: 'Cannot read agent logs directory' });
    }

    const all = files.map(describe);
    const runners = all.filter(a => !a.home);
    // Fixed display order; unknown runners fall to the end, tie-broken by label so
    // the layout is stable run to run.
    runners.sort((a, b) => (a.order - b.order) || a.label.localeCompare(b.label));
    return { runners, agent_logs_dir: AGENT_LOGS_DIR };
  });

  // Enable/disable + run-now (proxied to the opti dispatcher)
  attachControls(app);

  // GET /api/runners/:name/history — list dated report files for a runner, newest first.
  // Collectors write agent-logs/<name>/<YYYY-MM-DD>.json alongside <name>.json.
  app.get('/:name/history', async (req, reply) => {
    const base = req.params.name.replace(/\.json$/, '');
    const dir = path.join(AGENT_LOGS_DIR, base);
    // Path-traversal guard
    if (!dir.startsWith(AGENT_LOGS_DIR + path.sep)) {
      return reply.code(400).send({ error: 'Invalid runner name' });
    }
    if (!fs.existsSync(dir)) {
      return { name: base, history: [] };
    }
    let files;
    try {
      files = fs.readdirSync(dir).filter(f => DATE_RE.test(f.replace(/\.json$/, '')) && f.endsWith('.json'));
    } catch (_) {
      return { name: base, history: [] };
    }
    const history = files.map(f => {
      const full = path.join(dir, f);
      let size = 0, mtime = null;
      try { const s = fs.statSync(full); size = s.size; mtime = s.mtime.toISOString(); } catch (_) {}
      return { date: f.replace(/\.json$/, ''), filename: f, size, mtime };
    }).sort((a, b) => b.date.localeCompare(a.date));
    return { name: base, history };
  });

  // GET /api/runners/:name/report/:date — a specific dated report
  app.get('/:name/report/:date', async (req, reply) => {
    const base = req.params.name.replace(/\.json$/, '');
    if (!DATE_RE.test(req.params.date)) {
      return reply.code(400).send({ error: 'Bad date' });
    }
    const dir = path.join(AGENT_LOGS_DIR, base);
    const full = path.join(dir, `${req.params.date}.json`);
    // Path-traversal guard
    if (!full.startsWith(dir + path.sep)) {
      return reply.code(400).send({ error: 'Invalid path' });
    }
    if (!fs.existsSync(full)) {
      return reply.code(404).send({ error: 'Report not found' });
    }
    try {
      return JSON.parse(fs.readFileSync(full, 'utf8'));
    } catch (e) {
      console.error(`Failed to parse report ${full}: ${e.message}`);
      return reply.code(500).send({ error: 'Could not parse report file', detail: e.message });
    }
  });

  // GET /api/runners/:name/log — tail of the runner's own log file, for the live
  // drawer after a Run-now. The dispatcher writes <name>.log beside the reports;
  // no dispatcher change was needed for this.
  app.get('/:name/log', async (req, reply) => {
    const base = req.params.name.replace(/\.json$/, '');
    const file = path.join(AGENT_LOGS_DIR, `${base}.log`);
    if (!file.startsWith(AGENT_LOGS_DIR + path.sep)) {
      return reply.code(400).send({ error: 'Invalid runner name' });
    }
    if (!fs.existsSync(file)) {
      return { name: base, exists: false, lines: [], size: 0 };
    }
    const lines = Math.min(parseInt(req.query.lines, 10) || 200, 2000);
    try {
      const stat = fs.statSync(file);
      // Read at most the last 256KB — a runaway log must not be slurped whole.
      const start = Math.max(0, stat.size - 256 * 1024);
      const fd = fs.openSync(file, 'r');
      const buf = Buffer.alloc(stat.size - start);
      fs.readSync(fd, buf, 0, buf.length, start);
      fs.closeSync(fd);
      const all = buf.toString('utf8').split('\n');
      return {
        name: base,
        exists: true,
        size: stat.size,
        mtime: stat.mtime.toISOString(),
        lines: all.slice(-lines),
      };
    } catch (e) {
      return reply.code(500).send({ error: 'could not read log', detail: e.message });
    }
  });

  // GET /api/runners/:name — full JSON report (also serves the Leetify data)
  app.get('/:name', async (req, reply) => {
    const filename = req.params.name.endsWith('.json')
      ? req.params.name
      : `${req.params.name}.json`;
    const fullPath = path.join(AGENT_LOGS_DIR, filename);

    if (!fullPath.startsWith(AGENT_LOGS_DIR)) {
      return reply.code(400).send({ error: 'Invalid runner name' });
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
