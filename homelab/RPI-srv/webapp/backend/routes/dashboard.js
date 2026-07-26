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
const http = require('http');
const https = require('https');
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
// systemd timers from the fragments — collected since day one, surfaced first in the
// Home "Services & upkeep" tile. The fragment's pre-split `unit` field is unreliable;
// parse the `raw` list-timers line instead: unit is the token ending in ".timer".
function parseTimerRaw(raw) {
  // e.g. "Sat 2026-07-25 12:05:44 EDT  1min 14s Sat 2026-07-25 12:03:34 EDT  55s ago vpn-stack-heal.timer vpn-stack-heal.service"
  const unitMatch = raw.match(/(\S+\.timer)/);
  if (!unitMatch) return null;
  const unit = unitMatch[1];
  const before = raw.slice(0, raw.indexOf(unit)).trim();

  // PASSED is the duration-token run immediately before "ago" ("55s ago",
  // "4min 27s ago"). Walk back from "ago" collecting digit-led tokens only — a lazy
  // regex here used to swallow the tail of the preceding timestamp and produce
  // garbage like ":05 EDT 20h ago".
  const toks = before.split(/\s+/);
  let passed = null;
  if (toks[toks.length - 1] === 'ago') {
    const dur = [];
    for (let i = toks.length - 2; i >= 0 && /^\d/.test(toks[i]) && !toks[i].includes(':'); i--) {
      dur.unshift(toks[i]);
    }
    if (dur.length) passed = dur.join(' ') + ' ago';
  } else if (toks[toks.length - 1] === '-') {
    passed = '-';   // never fired
  }

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

  // Parse timestamps rather than string-comparing them: sources mix "…Z" and
  // "…+00:00" ISO flavors, and lexicographic order breaks on ties.
  const t = (e) => Date.parse(e.ts || '') || 0;
  events.sort((a, b) => t(b) - t(a) || sevRank(a.severity) - sevRank(b.severity));
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
        // pool_name marks the storage era (mergerfs → zpool "red"); the chart breaks
        // its line when it changes rather than drawing a fake cliff between regimes.
        pool.push({ date, used_pct: Math.round(h.metrics.pool.used_pct * 10) / 10,
                    pool_name: h.metrics.pool.pool_name || null });
      }
      if (h.metrics?.disk_used_pct != null) {
        (disks[h.host] ||= []).push({ date, used_pct: h.metrics.disk_used_pct });
      }
    });
  }
  res.json({ days: dates.length, pool, disks, generated_at: new Date().toISOString() });
});

// ── GET /api/linkcheck ───────────────────────────────────────────────────────
// Server-side reachability for the Quick Links page. The browser cannot do this
// itself: the dashboard is https, the LAN services are http, and fetch() from a
// secure page to an insecure origin is blocked as mixed content before the request
// leaves. Probing from Node also lets the self-signed-https services (Cockpit,
// Vaultwarden) get a real answer, which a browser page never could.
//
// The probe list is FIXED here — never taken from the request — so this endpoint
// cannot be used as an SSRF proxy. One entry per ORIGIN (a 302 from / proves the
// server is up regardless of which path a bookmark deep-links), and the frontend
// matches its links to results by origin too — so both Vaultwarden links share one
// probe. Keep in sync with LINK_GROUPS in frontend/app.js (external links only;
// internal /pages are same-origin and the frontend probes those itself).
// `key` is the origin exactly as LINK_GROUPS writes it (what the frontend matches on);
// `target` is what this container actually dials when that differs. It differs for the
// services on THIS rpi: inside the container `rpi.lan` resolves to ::1 (docker's
// embedded DNS answers from the host's own view of its name), so those are dialed by
// LAN IP. Every other host's name resolves correctly via Pi-hole.
const PROBE_ORIGINS = [
  { key: 'http://192.168.1.1' },                                          // router — no DNS name
  { key: 'http://rpi.lan', target: 'http://192.168.1.10' },               // Pi-hole admin
  { key: 'https://rpi.lan:9090', target: 'https://192.168.1.10:9090' },   // Cockpit (self-signed)
  { key: 'https://bitwarden.rpi.lan' },                                   // Vaultwarden — name resolves via nginx SNI, keep hostname
  { key: 'http://opti.lan' },                                             // OpenMediaVault
  { key: 'http://jellyfin.lan:8096' },
  { key: 'http://comics.lan:5000' },                                      // Kavita
  { key: 'http://noblenumbat.lan:9000' },                                 // Portainer
  { key: 'http://noblenumbat.lan:8989' },                                 // Sonarr
  { key: 'http://noblenumbat.lan:7878' },                                 // Radarr
  { key: 'http://noblenumbat.lan:8686' },                                 // Lidarr
  { key: 'http://noblenumbat.lan:6767' },                                 // Bazarr
  { key: 'http://noblenumbat.lan:8090' },                                 // Mylar3
  { key: 'http://noblenumbat.lan:9696' },                                 // Prowlarr
  { key: 'http://noblenumbat.lan:8081' },                                 // qBittorrent
];

// Any HTTP response counts as "up" — a 401 from the router or a 302 from Jellyfin is
// a service answering. Only connect errors and timeouts are "down".
function probe({ key, target }) {
  return new Promise((resolve) => {
    const url = (target || key) + '/';
    const mod = url.startsWith('https') ? https : http;
    const req = mod.request(url, {
      method: 'HEAD',
      timeout: 4000,
      rejectUnauthorized: false,   // LAN self-signed certs are the norm here
    }, (res) => {
      res.resume();
      resolve({ origin: key, up: true, status: res.statusCode });
    });
    req.on('timeout', () => { req.destroy(); resolve({ origin: key, up: false, error: 'timeout' }); });
    req.on('error', (e) => resolve({ origin: key, up: false, error: e.code || e.message }));
    req.end();
  });
}

let linkCache = { at: 0, data: null };
const LINKCHECK_CACHE_MS = 30_000;

router.get('/linkcheck', async (req, res) => {
  if (Date.now() - linkCache.at < LINKCHECK_CACHE_MS && linkCache.data) {
    return res.json(linkCache.data);
  }
  const results = await Promise.all(PROBE_ORIGINS.map(probe));
  const origins = {};
  for (const r of results) origins[r.origin] = r;
  const data = { origins, checked_at: new Date().toISOString() };
  linkCache = { at: Date.now(), data };
  res.json(data);
});

module.exports = router;
