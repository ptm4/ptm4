// Mission-control Home read-model — three read-only endpoints that reshape data the
// container already has on disk. No SSH, no new collection: doctor/software reports
// come off /agent-logs (opti pool, :ro), security reports off /reports (:ro), and the
// per-host architecture-agent fragments via routes/architecture.js's readFragments.
//
//   GET /api/containers    — fleet table: doctor containers ⋈ fragments ⋈ image_updates
//   GET /api/activity      — unified feed: findings + vpn watchdog + autoupdate + backups
//   GET /api/trends        — daily series from the dated doctor history (pool %, disk %)
//
// Everything degrades: a missing report or fragment shrinks the answer, it never 500s.
// (opti down = the mounts hang; see the skill's caveat — hence every read is try/catch
// and the frontend renders "unavailable" tiles.)
const express = require('express');
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR } = require('./controls');
const architectureRouter = require('./architecture');

const router = express.Router();

const REPORTS_DIR = fs.existsSync('/reports')
  ? '/reports'
  : path.join(__dirname, '..', '..', '..', '..', '..', 'security-reports');

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) { return null; }
}
const readReport = (name) => readJson(path.join(AGENT_LOGS_DIR, `${name}.json`));

// ── GET /api/containers ──────────────────────────────────────────────────────
// Doctor rows are the freshest truth for up/down (30-min cadence); fragments add the
// rich fields (image, since, compose project); software's image_updates flags staleness.
// Union by name — a container only one source knows about still gets a row.
router.get('/containers', (req, res) => {
  const doctor = readReport('homelab-doctor-latest');
  const software = readReport('software-latest');
  const fragments = architectureRouter.readFragments();

  const updatesByHost = {};
  (software?.hosts || []).forEach(h => {
    const set = new Set();
    (h.metrics?.image_updates || []).forEach(u => {
      (u.containers || []).forEach(c => set.add(c));
    });
    updatesByHost[h.host] = set;
  });

  const hosts = [];
  const hostNames = new Set([
    ...(doctor?.hosts || []).map(h => h.host),
    ...Object.keys(fragments),
  ]);
  // android is a phone, not a container host — a permanent empty row is noise
  hostNames.delete('android');

  for (const name of ['rpi', 'opti', 'noblenumbat', ...hostNames]) {
    if (!hostNames.has(name)) continue;
    hostNames.delete(name);

    const doc = (doctor?.hosts || []).find(h => h.host === name);
    const frag = fragments[name];
    const updates = updatesByHost[name] || new Set();

    const byName = {};
    (doc?.metrics?.containers || []).forEach(c => {
      byName[c.name] = { name: c.name, status: c.status || null };
    });
    ((frag?.docker || {}).containers || []).forEach(c => {
      const row = (byName[c.name] ||= { name: c.name, status: null });
      row.state = c.state ?? null;
      row.status_since = c.status_since ?? null;
      row.image = c.image ?? null;
      row.compose_project = c.compose_project ?? null;
      row.ports = c.ports ?? [];
    });

    const containers = Object.values(byName).map(c => ({
      ...c,
      up: c.state === 'running' || /^up/i.test(c.status || ''),
      update_available: updates.has(c.name),
    })).sort((a, b) => a.name.localeCompare(b.name));

    hosts.push({
      host: name,
      doctor_at: doctor?.run_at || null,
      fragment_at: frag?.collected_at || null,
      agent_version: frag?.agent_version || null,
      containers,
    });
  }

  res.json({ hosts, generated_at: new Date().toISOString() });
});

// ── GET /api/timers ──────────────────────────────────────────────────────────
// systemd timers from the fragments — collected since day one, surfaced here first.
// The fragment's pre-split `unit` field is unreliable; parse the `raw` list-timers
// line instead: NEXT / LEFT / LAST / PASSED are fixed columns, unit ends in ".timer".
const TIMER_RE = /^(.*?\S)\s{2,}(\S.*?ago|-|n\/a)\s+(\S+\.timer)\s+(\S+)?\s*$/;
function parseTimerRaw(raw) {
  // e.g. "Sat 2026-07-25 12:05:44 EDT  1min 14s Sat 2026-07-25 12:03:34 EDT  55s ago vpn-stack-heal.timer vpn-stack-heal.service"
  const unitMatch = raw.match(/(\S+\.timer)/);
  if (!unitMatch) return null;
  const unit = unitMatch[1];
  const before = raw.slice(0, raw.indexOf(unit)).trim();
  // "…EDT  <left> …EDT  <passed> " — grab the two relative fields between the
  // absolute timestamps; tolerate '-' for never-run timers.
  const passed = (before.match(/(\S[\w\s]*?ago|-)\s*$/) || [])[1] || null;
  const next = (before.match(/^(\w{3} \d{4}-\d{2}-\d{2} [\d:]+ \w+)/) || [])[1] || null;
  return { unit, next, passed, raw };
}

router.get('/timers', (req, res) => {
  const fragments = architectureRouter.readFragments();
  const hosts = [];
  for (const [host, frag] of Object.entries(fragments)) {
    const timers = (frag.timers || [])
      .map(t => parseTimerRaw(t.raw || ''))
      .filter(Boolean)
      // systemd's own housekeeping timers aren't homelab signal
      .filter(t => !/^(apt-daily|dpkg-db-backup|e2scrub|fstrim|logrotate|man-db|motd-news|phpsessionclean|sysstat|systemd-tmpfiles|update-notifier|fwupd|snapd)/.test(t.unit));
    hosts.push({ host, collected_at: frag.collected_at || null, timers });
  }
  hosts.sort((a, b) => a.host.localeCompare(b.host));
  res.json({ hosts, generated_at: new Date().toISOString() });
});

// ── GET /api/activity ────────────────────────────────────────────────────────
const RUNNER_SOURCES = [
  'homelab-doctor-latest', 'hardware-latest', 'software-latest',
  'network-latest', 'coldcopy-latest',
];

function sevRank(s) {
  return { critical: 0, high: 0, crit: 0, warn: 1, warning: 1, medium: 1 }[
    (s || '').toLowerCase()
  ] ?? 2;
}

router.get('/activity', (req, res) => {
  const limit = Math.min(parseInt(req.query.limit, 10) || 50, 200);
  const events = [];
  const push = (e) => { if (e.message) events.push(e); };

  for (const name of RUNNER_SOURCES) {
    const rep = readReport(name);
    if (!rep) continue;
    const source = name.replace('-latest', '');
    const ts = rep.run_at || null;
    [...(rep.findings || []), ...(rep.recommendations || [])].forEach(f => {
      const msg = f.message || f.detail || (typeof f === 'string' ? f : null);
      if (!msg) return;
      // collectors prefix host as "[opti] …" — lift it into a field
      const m = msg.match(/^\[(\w[\w-]*)\]\s*(.*)$/);
      push({
        ts, source,
        severity: (f.severity || 'info').toLowerCase(),
        host: f.host || (m ? m[1] : null),
        message: m ? m[2] : msg,
      });
    });

    if (name === 'homelab-doctor-latest') {
      (rep.hosts || []).forEach(h => {
        const vpn = h.metrics?.vpn;
        (vpn?.actions || []).forEach(a => push({
          ts: (a && a.ts) || vpn.ts || ts, source: 'vpn-watchdog', severity: 'warn',
          host: h.host,
          message: typeof a === 'string' ? a : (a.action || a.message || JSON.stringify(a)),
        }));
        const au = h.metrics?.autoupdate;
        if (au?.last_run && au.result && au.result !== 'ok') push({
          ts: au.last_run, source: 'autoupdate', severity: 'warn', host: h.host,
          message: `unattended-upgrades: ${au.result}${au.detail ? ' — ' + au.detail : ''}`,
        });
      });
    }
    if (name === 'coldcopy-latest' && rep.status) {
      push({
        ts, source: 'coldcopy',
        severity: rep.status === 'ok' ? 'info' : 'warn',
        host: 'opti', message: rep.summary || `backup ${rep.status}`,
      });
    }
  }

  // security agents — the three *-latest.json in /reports
  try {
    fs.readdirSync(REPORTS_DIR).filter(f => f.endsWith('-latest.json')).forEach(f => {
      const rep = readJson(path.join(REPORTS_DIR, f));
      if (!rep) return;
      push({
        ts: rep.run_at || null, source: f.replace('-latest.json', ''),
        severity: rep.status === 'critical' ? 'critical' : rep.status === 'warn' ? 'warn' : 'info',
        host: null, message: rep.summary || null,
      });
    });
  } catch (_) { /* /reports unavailable — feed just has fewer sources */ }

  events.sort((a, b) =>
    String(b.ts || '').localeCompare(String(a.ts || '')) || sevRank(a.severity) - sevRank(b.severity));
  res.json({ events: events.slice(0, limit), generated_at: new Date().toISOString() });
});

// ── GET /api/trends ──────────────────────────────────────────────────────────
// Daily-resolution series from the dated doctor snapshots ("<name>-latest/<date>.json").
// Correct for slow-moving numbers (pool fill, disk fill); sub-daily lives in /api/vitals.
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

router.get('/trends', (req, res) => {
  const days = Math.min(parseInt(req.query.days, 10) || 30, 120);
  const dir = path.join(AGENT_LOGS_DIR, 'homelab-doctor-latest');
  let dates = [];
  try {
    dates = fs.readdirSync(dir)
      .map(f => f.replace(/\.json$/, ''))
      .filter(d => DATE_RE.test(d))
      .sort()
      .slice(-days);
  } catch (_) { /* no history yet */ }

  const pool = [];
  const disks = {};
  for (const date of dates) {
    const rep = readJson(path.join(dir, `${date}.json`));
    if (!rep) continue;
    (rep.hosts || []).forEach(h => {
      if (h.host === 'opti' && h.metrics?.pool?.used_pct != null) {
        pool.push({ date, used_pct: Math.round(h.metrics.pool.used_pct * 10) / 10 });
      }
      if (h.metrics?.disk_used_pct != null) {
        (disks[h.host] ||= []).push({ date, used_pct: h.metrics.disk_used_pct });
      }
    });
  }
  res.json({ days: dates.length, pool, disks, generated_at: new Date().toISOString() });
});

module.exports = router;
