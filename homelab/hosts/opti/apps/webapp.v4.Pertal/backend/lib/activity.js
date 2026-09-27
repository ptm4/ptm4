// Activity — what changed, when. Fed by the snapshot stream (container state changes,
// data sources failing and recovering) and merged with jobs at read time, so one feed
// answers "what happened?" whether it was a button press, a crash or a flaky upstream.
//
// Persisted as monthly JSONL under ARCH_DATA_DIR/pertal/activity (append-only, like the
// job audit) and reloaded at boot, so history survives restarts and deploys.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { ARCH_DATA_DIR } = require('./paths');

const DIR = path.join(ARCH_DATA_DIR, 'pertal', 'activity');
const MAX_RESIDENT = 1000;
const monthFile = (d = new Date()) =>
  path.join(DIR, `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}.jsonl`);

function createActivity({ emit = () => {}, log = console, persist = true } = {}) {
  const ring = [];
  const lastContainers = new Map(); // host -> Map(name -> "state/health")
  const lastOk = new Map();         // snapshot key -> boolean

  function load() {
    if (!persist) return;
    const files = [];
    const now = new Date();
    files.push(monthFile(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1))), monthFile(now));
    for (const f of files) {
      let text;
      try { text = fs.readFileSync(f, 'utf8'); } catch (_) { continue; }
      for (const line of text.split('\n')) {
        if (!line.trim()) continue;
        try { ring.unshift(JSON.parse(line)); } catch (_) { /* skip a torn line */ }
      }
    }
    ring.sort((a, b) => String(b.at).localeCompare(String(a.at)));
    ring.length = Math.min(ring.length, MAX_RESIDENT);
  }

  function add(item) {
    const entry = { id: crypto.randomBytes(6).toString('hex'), at: new Date().toISOString(), ...item };
    ring.unshift(entry);
    if (ring.length > MAX_RESIDENT) ring.length = MAX_RESIDENT;
    if (persist) {
      try {
        fs.mkdirSync(DIR, { recursive: true });
        fs.appendFileSync(monthFile(), `${JSON.stringify(entry)}\n`, 'utf8');
      } catch (err) {
        log.warn?.(`activity append failed: ${err.message}`);
      }
    }
    try { emit(entry); } catch (_) { /* bus optional */ }
    return entry;
  }

  // Called for every snapshot refresh. Only transitions produce entries; the first
  // reading after boot establishes a baseline silently.
  function observe(key, snap) {
    const m = snap?.meta;
    if (!m || m.ok === null) return;

    const prevOk = lastOk.get(key);
    lastOk.set(key, m.ok);
    if (prevOk !== undefined && prevOk !== m.ok) {
      add({
        type: 'source', severity: m.ok ? 'ok' : 'warn', source: key, host: m.group,
        text: m.ok ? `${m.label} recovered` : `${m.label} failing: ${m.error}`,
      });
    }

    if (key.startsWith('containers:') && m.ok && snap.data?.containers) {
      const host = key.slice('containers:'.length);
      const cur = new Map(snap.data.containers.map((c) => [c.name, `${c.state}${c.health ? `/${c.health}` : ''}`]));
      const prev = lastContainers.get(host);
      lastContainers.set(host, cur);
      if (!prev) return;
      for (const [name, state] of cur) {
        const before = prev.get(name);
        if (before === undefined) {
          add({ type: 'container', severity: 'ok', host, resource_id: `${host}:${name}`, text: `${name} appeared (${state})` });
        } else if (before !== state) {
          const bad = !state.startsWith('running') || state.endsWith('/unhealthy');
          add({ type: 'container', severity: bad ? 'crit' : 'ok', host, resource_id: `${host}:${name}`, text: `${name}: ${before} → ${state}` });
        }
      }
      for (const name of prev.keys()) {
        if (!cur.has(name)) add({ type: 'container', severity: 'warn', host, resource_id: `${host}:${name}`, text: `${name} disappeared` });
      }
    }
  }

  const list = ({ limit = 100, resource = null, host = null } = {}) =>
    ring.filter((e) => (!resource || e.resource_id === resource) && (!host || e.host === host)).slice(0, limit);

  load();
  return { add, observe, list };
}

module.exports = { createActivity };
