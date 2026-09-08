// Notification center — turns findings that already exist in the reports into an
// inbox with acknowledge state.
//
// Why: doctor and security findings were only visible if you remembered to open
// the right report page. Everything here is a reshape of data already on disk;
// the only new state is which fingerprints have been acknowledged, stored in the
// UI dir alongside boards.
//
// Fingerprint = source + severity + message, hashed. Deliberately NOT including
// the timestamp: the same finding recurring on the next run stays acknowledged,
// which is what makes the inbox usable. A finding whose text changes is new.
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR } = require('../lib/controls');
const { REPORTS_DIR } = require('../lib/paths');
const store = require('../lib/store');

const ACKS_PATH = path.join(store.UI_DIR, 'acks.json');
const MAX_ACKS = 500;

const RUNNER_SOURCES = [
  'homelab-doctor-latest', 'hardware-latest', 'software-latest',
  'network-latest', 'coldcopy-latest',
];

const readJson = (p) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; } };

const fingerprint = (source, severity, message) =>
  crypto.createHash('sha1').update(`${source}|${severity}|${message}`).digest('hex').slice(0, 16);

const SEV_RANK = { critical: 0, high: 0, warn: 1, warning: 1, medium: 1 };
const sevRank = (s) => SEV_RANK[(s || '').toLowerCase()] ?? 2;

// Only actionable severities become notifications — an info line is feed material,
// not something to acknowledge.
const NOTIFY_SEVERITIES = new Set(['critical', 'high', 'warn', 'warning', 'medium']);

function collect() {
  const items = [];

  for (const name of RUNNER_SOURCES) {
    const rep = readJson(path.join(AGENT_LOGS_DIR, `${name}.json`));
    if (!rep) continue;
    const source = name.replace('-latest', '');
    for (const f of [...(rep.findings || []), ...(rep.recommendations || [])]) {
      const message = f.message || f.detail || (typeof f === 'string' ? f : null);
      if (!message) continue;
      const severity = (f.severity || 'info').toLowerCase();
      if (!NOTIFY_SEVERITIES.has(severity)) continue;
      const m = message.match(/^\[(\w[\w-]*)\]\s*(.*)$/);   // collectors prefix "[opti] …"
      items.push({
        id: fingerprint(source, severity, message),
        source,
        severity,
        host: f.host || (m ? m[1] : null),
        message: m ? m[2] : message,
        ts: rep.run_at || null,
      });
    }
  }

  try {
    for (const file of fs.readdirSync(REPORTS_DIR).filter((f) => f.endsWith('-latest.json'))) {
      const rep = readJson(path.join(REPORTS_DIR, file));
      if (!rep) continue;
      const source = file.replace('-latest.json', '');
      for (const f of rep.findings || []) {
        const message = f.message || f.detail;
        if (!message) continue;
        const severity = (f.severity || 'info').toLowerCase();
        if (!NOTIFY_SEVERITIES.has(severity)) continue;
        items.push({
          id: fingerprint(source, severity, message),
          source, severity, host: f.host || null, message, ts: rep.run_at || null,
        });
      }
      if (rep.status === 'critical' || rep.status === 'warn') {
        const message = rep.summary || `${source} reported ${rep.status}`;
        items.push({
          id: fingerprint(source, rep.status, message),
          source, severity: rep.status, host: null, message, ts: rep.run_at || null,
        });
      }
    }
  } catch (_) { /* /reports unavailable — fewer sources, never an error */ }

  // De-dupe by fingerprint (the same finding can appear in findings AND recommendations)
  const byId = new Map();
  for (const it of items) if (!byId.has(it.id)) byId.set(it.id, it);

  return [...byId.values()].sort(
    (a, b) => sevRank(a.severity) - sevRank(b.severity) || (Date.parse(b.ts || '') || 0) - (Date.parse(a.ts || '') || 0),
  );
}

const readAcks = () => store.readJson(ACKS_PATH) || {};

function writeAcks(acks) {
  // Keep the file bounded: oldest acks fall off once findings stop recurring.
  const entries = Object.entries(acks).sort((a, b) => (b[1].at || '').localeCompare(a[1].at || ''));
  store.ensureDirs();
  store.writeJsonAtomic(ACKS_PATH, Object.fromEntries(entries.slice(0, MAX_ACKS)));
}

module.exports = async function notificationRoutes(app) {
  // GET /api/notifications — every actionable finding, with its ack state.
  app.get('/', async (req) => {
    const acks = readAcks();
    const all = collect().map((n) => ({ ...n, acked: !!acks[n.id], acked_at: acks[n.id]?.at || null }));
    const includeAcked = req.query.all === '1';
    const items = includeAcked ? all : all.filter((n) => !n.acked);
    return {
      items,
      unacked: all.filter((n) => !n.acked).length,
      total: all.length,
      generated_at: new Date().toISOString(),
    };
  });

  // POST /api/notifications/:id/ack — acknowledge (or un-acknowledge) one finding.
  app.post('/:id/ack', {
    schema: {
      params: { type: 'object', properties: { id: { type: 'string', pattern: '^[a-f0-9]{16}$' } } },
      body: { type: 'object', properties: { acked: { type: 'boolean' } } },
    },
  }, async (req) => {
    const acks = readAcks();
    const acked = req.body?.acked !== false;
    if (acked) acks[req.params.id] = { at: new Date().toISOString() };
    else delete acks[req.params.id];
    writeAcks(acks);
    return { ok: true, id: req.params.id, acked };
  });

  // POST /api/notifications/ack-all — acknowledge everything currently open.
  app.post('/ack-all', async () => {
    const acks = readAcks();
    const at = new Date().toISOString();
    let n = 0;
    for (const item of collect()) {
      if (!acks[item.id]) { acks[item.id] = { at }; n++; }
    }
    writeAcks(acks);
    return { ok: true, acked: n };
  });
};
