// Findings as a library — the collector and ack store that routes/notifications.js
// has always used, lifted out so routes/incidents.js can correlate the same items
// without a second implementation. Shapes and fingerprints are unchanged: an ack
// made through either route is visible through both.
//
// Fingerprint = source + severity + message, hashed. Deliberately NOT including
// the timestamp: the same finding recurring on the next run stays acknowledged,
// which is what makes the inbox usable. A finding whose text changes is new.
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR } = require('./controls');
const { REPORTS_DIR } = require('./paths');
const store = require('./store');

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

  // v3: alert-rule hits (lib/rules.js writes ui/rule-hits.json every poller tick).
  // A rule's message includes its measured value, so the fingerprint changes as the
  // value moves — an acknowledged "disk at 85%" comes back when it reaches 86%.
  // That is deliberate: a threshold breach that keeps growing deserves a second look.
  try {
    const hits = store.readJson(path.join(store.UI_DIR, 'rule-hits.json'));
    for (const h of hits?.hits || []) {
      const source = `rule:${h.rule_id}`;
      items.push({
        id: fingerprint(source, h.severity, h.message),
        source, severity: h.severity, host: h.host || null, message: h.message,
        ts: h.since || hits.evaluated_at || null,
        rule: h.rule,
      });
    }
  } catch (_) { /* no rule hits yet */ }

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

module.exports = { collect, fingerprint, sevRank, readAcks, writeAcks, ACKS_PATH, RUNNER_SOURCES };
