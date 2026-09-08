// Alert rules — the dashboard's own thresholds, evaluated every feed-poller tick
// against state the backend already holds (vitals rings, containers, the latest
// doctor/hardware reports, updates). Hits are written to ui/rule-hits.json and
// picked up by lib/findings.collect() as source "rule:<name>", so a firing rule is
// a finding like any other: it reaches the bell, the incidents page and the feed,
// and acknowledging it works the same way.
//
// Rule shape (ui/rules.json):
//   { id, name, enabled, kind, host, container, op, threshold, for_min, severity }
//   kind ∈ disk | pool | cpu | mem | temp | load | host_down | container_down |
//          updates | reboot_required | stream_stalled
//   host: null = every host; container: for container_down (null = any)
//   op: '>' | '<' (numeric kinds); threshold: number; for_min: sustain before firing
//   severity: 'warn' | 'critical'
const path = require('path');
const crypto = require('crypto');
const store = require('./store');

const RULES_PATH = path.join(store.UI_DIR, 'rules.json');
const HITS_PATH = path.join(store.UI_DIR, 'rule-hits.json');
const STATE_PATH = path.join(store.UI_DIR, 'rule-state.json');

const KINDS = ['disk', 'pool', 'cpu', 'mem', 'temp', 'load', 'host_down', 'container_down', 'updates', 'reboot_required', 'stream_stalled'];
const NUMERIC = new Set(['disk', 'pool', 'cpu', 'mem', 'temp', 'load', 'updates']);

const DEFAULT_RULES = [
  { id: 'disk-warn', name: 'Root disk above 80%', enabled: true, kind: 'disk', host: null, op: '>', threshold: 80, for_min: 0, severity: 'warn' },
  { id: 'disk-crit', name: 'Root disk above 90%', enabled: true, kind: 'disk', host: null, op: '>', threshold: 90, for_min: 0, severity: 'critical' },
  { id: 'pool-warn', name: 'ZFS pool above 80%', enabled: true, kind: 'pool', host: 'opti', op: '>', threshold: 80, for_min: 0, severity: 'warn' },
  { id: 'temp-warn', name: 'CPU temperature above 75°C', enabled: true, kind: 'temp', host: null, op: '>', threshold: 75, for_min: 5, severity: 'warn' },
  { id: 'mem-warn', name: 'Memory above 90%', enabled: true, kind: 'mem', host: null, op: '>', threshold: 90, for_min: 10, severity: 'warn' },
  { id: 'host-down', name: 'Host unreachable', enabled: true, kind: 'host_down', host: null, for_min: 3, severity: 'critical' },
  { id: 'container-down', name: 'Container down', enabled: true, kind: 'container_down', host: null, container: null, for_min: 2, severity: 'warn' },
  { id: 'reboot', name: 'Reboot required', enabled: true, kind: 'reboot_required', host: null, for_min: 0, severity: 'warn' },
  { id: 'stream-stalled', name: 'Stream slot stalled', enabled: true, kind: 'stream_stalled', host: null, op: '>', threshold: 30, for_min: 0, severity: 'warn' },
];

const newId = () => crypto.randomBytes(4).toString('hex');

function readRules() {
  const doc = store.readJson(RULES_PATH);
  if (!doc || !Array.isArray(doc.rules)) return { rules: DEFAULT_RULES.map((r) => ({ ...r })), seeded: true };
  return { rules: doc.rules, seeded: false };
}
function writeRules(rules) { store.ensureDirs(); store.writeJsonAtomic(RULES_PATH, { rules, updated_at: new Date().toISOString() }); }
const readHits = () => store.readJson(HITS_PATH) || { hits: [], evaluated_at: null };
const readState = () => store.readJson(STATE_PATH) || {};

function validateRule(r) {
  if (!r || typeof r !== 'object') return 'rule must be an object';
  if (!KINDS.includes(r.kind)) return `kind must be one of ${KINDS.join(', ')}`;
  if (typeof r.name !== 'string' || !r.name.trim()) return 'name is required';
  if (!['warn', 'critical'].includes(r.severity)) return "severity must be 'warn' or 'critical'";
  if (NUMERIC.has(r.kind) || r.kind === 'stream_stalled') {
    if (!['>', '<'].includes(r.op)) return "op must be '>' or '<'";
    if (typeof r.threshold !== 'number') return 'threshold must be a number';
  }
  if (r.for_min != null && (typeof r.for_min !== 'number' || r.for_min < 0 || r.for_min > 1440)) return 'for_min must be 0–1440';
  return null;
}

const cmp = (op, v, t) => (op === '<' ? v < t : v > t);

// Evaluate every enabled rule against a snapshot; returns candidate hits (before the
// for_min sustain check).
function evaluate(rules, snap) {
  const out = [];
  const hostsOf = (r, all) => (r.host ? [r.host] : all);
  const vitalsHosts = Object.keys(snap.vitals || {});
  const liveHosts = Object.keys(snap.live?.hosts || {});
  const allHosts = [...new Set([...vitalsHosts, ...liveHosts])];

  for (const r of rules) {
    if (!r.enabled) continue;
    const push = (host, value, message, key = '') => out.push({
      key: `${r.id}|${host || 'fleet'}|${key}`, rule_id: r.id, rule: r.name, kind: r.kind, severity: r.severity,
      host: host || null, value, message,
    });
    switch (r.kind) {
      case 'cpu': case 'mem': case 'temp': case 'load': {
        const field = { cpu: 'cpu_pct', mem: 'mem_pct', temp: 'temp_c', load: 'load1' }[r.kind];
        const unit = { cpu: '%', mem: '%', temp: '°C', load: '' }[r.kind];
        for (const h of hostsOf(r, vitalsHosts)) {
          const v = snap.vitals?.[h]?.latest?.[field];
          if (v != null && cmp(r.op, v, r.threshold)) push(h, v, `${h}: ${r.kind === 'load' ? 'load' : r.kind} ${Math.round(v * 10) / 10}${unit} (${r.op} ${r.threshold}${unit})`);
        }
        break;
      }
      case 'disk': case 'pool': {
        for (const h of hostsOf(r, liveHosts)) {
          const lv = snap.live?.hosts?.[h];
          const v = r.kind === 'disk' ? lv?.disk_used_pct : lv?.pool?.used_pct;
          if (v != null && cmp(r.op, v, r.threshold)) push(h, v, `${h}: ${r.kind === 'disk' ? 'root disk' : (lv?.pool?.pool_name || 'pool')} at ${Math.round(v)}% (${r.op} ${r.threshold}%)`);
        }
        break;
      }
      case 'host_down': {
        for (const h of hostsOf(r, vitalsHosts)) {
          const st = snap.vitals?.[h];
          if (st && (st.error || !st.latest)) push(h, null, `${h}: no vitals — ${st.error || 'no samples'}`);
        }
        break;
      }
      case 'container_down': {
        for (const hh of snap.containers?.hosts || []) {
          if (r.host && hh.host !== r.host) continue;
          for (const c of hh.containers || []) {
            if (r.container && c.name !== r.container) continue;
            if (!c.up) push(hh.host, null, `${hh.host}: container ${c.name} is ${c.state || c.status || 'down'}`, c.name);
          }
        }
        break;
      }
      case 'updates': {
        for (const p of snap.updates?.packages || []) {
          if (r.host && p.host !== r.host) continue;
          if (cmp(r.op, p.pending, r.threshold)) push(p.host, p.pending, `${p.host}: ${p.pending} packages pending${p.security ? ` (${p.security} security)` : ''}`);
        }
        break;
      }
      case 'reboot_required': {
        for (const p of snap.updates?.packages || []) {
          if (r.host && p.host !== r.host) continue;
          if (p.reboot_required) push(p.host, null, `${p.host}: reboot required${Array.isArray(p.reboot_pkgs) && p.reboot_pkgs.length ? ` (${p.reboot_pkgs.slice(0, 3).join(', ')})` : ''}`);
        }
        break;
      }
      case 'stream_stalled': {
        for (const s of snap.streams?.slots || []) {
          if (s.state === 'running' && s.last_segment_age_s != null && cmp(r.op, s.last_segment_age_s, r.threshold)) {
            push('noblenumbat', s.last_segment_age_s, `stream slot ${s.slot} (${s.channel || s.url}) stalled — last segment ${Math.round(s.last_segment_age_s)}s ago`, String(s.slot));
          }
        }
        break;
      }
      default: break;
    }
  }
  return out;
}

// Apply for_min: a candidate has to persist across ticks for that long before it
// fires. State remembers when each key was first seen; keys that disappear reset.
function settle(candidates, rules, state, now = Date.now()) {
  const byId = Object.fromEntries(rules.map((r) => [r.id, r]));
  const next = {};
  const hits = [];
  for (const c of candidates) {
    const first = state[c.key]?.first_seen || new Date(now).toISOString();
    next[c.key] = { first_seen: first };
    const waitMs = (byId[c.rule_id]?.for_min || 0) * 60_000;
    if (now - Date.parse(first) >= waitMs) hits.push({ ...c, since: first });
  }
  return { hits, state: next };
}

async function run(app) {
  const { rules } = readRules();
  const inject = async (url) => { try { const r = await app.inject({ method: 'GET', url }); return r.statusCode === 200 ? r.json() : null; } catch (_) { return null; } };
  const snap = {
    vitals: app.vitals?.state ? Object.fromEntries(Object.entries(app.vitals.state).map(([h, st]) => [h, { latest: st.samples[st.samples.length - 1] || null, error: st.lastError }])) : {},
    live: await inject('/api/architecture/live'),
    containers: await inject('/api/containers'),
    updates: await inject('/api/updates'),
    streams: await inject('/api/streams/status'),
  };
  const { hits, state } = settle(evaluate(rules, snap), rules, readState());
  const prev = readHits();
  store.ensureDirs();
  store.writeJsonAtomic(STATE_PATH, state);
  const doc = { hits, evaluated_at: new Date().toISOString() };
  store.writeJsonAtomic(HITS_PATH, doc);
  const changed = JSON.stringify(prev.hits.map((h) => h.key).sort()) !== JSON.stringify(hits.map((h) => h.key).sort());
  return { ...doc, changed };
}

module.exports = { KINDS, NUMERIC, DEFAULT_RULES, RULES_PATH, HITS_PATH, readRules, writeRules, readHits, validateRule, evaluate, settle, run, newId };
