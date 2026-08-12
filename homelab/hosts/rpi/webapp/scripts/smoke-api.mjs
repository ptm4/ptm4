#!/usr/bin/env node
// API smoke — proves every endpoint of the webapp backend is mounted and answering
// with the expected shape, without side effects.
//
//   node smoke-api.mjs --base https://192.168.1.10:8443 --insecure --capture baseline.json
//   node smoke-api.mjs --base http://127.0.0.1:3000 --compare baseline.json
//
// GETs are exercised for real. Mutating routes are probed ONLY with deliberately
// invalid payloads (a 4xx proves the route exists, is mounted at the right path and
// validates — without rebooting the house). Endpoints that need upstream services
// declare every status they may legitimately answer with, so the same manifest works
// against live rpi (everything configured) and an off-box instance (fixtures only).
//
// Compare mode: statuses must be allowed; when both runs answered 200, the new
// response's top-level keys must be a superset of the baseline's.
import fs from 'node:fs';
import process from 'node:process';

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? dflt : (args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : true);
};
const BASE = opt('base', 'http://127.0.0.1:3000');
const CAPTURE = opt('capture', null);
const COMPARE = opt('compare', null);
if (opt('insecure', false)) process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

// { method, path, expect: [ok statuses], body?, note? }
// `expect` lists every status that means "the route is healthy in this environment".
const MANIFEST = [
  // own health
  { method: 'GET', path: '/api/health', expect: [200] },

  // reports + runners (file-backed; 200 even when dirs are empty)
  { method: 'GET', path: '/api/reports', expect: [200] },
  { method: 'GET', path: '/api/reports/journal-hunt-latest', expect: [200, 404] },
  { method: 'GET', path: '/api/runners', expect: [200] },
  { method: 'GET', path: '/api/runners/homelab-doctor-latest', expect: [200, 404] },
  { method: 'GET', path: '/api/runners/homelab-doctor-latest/history', expect: [200] },

  // dashboard read models
  { method: 'GET', path: '/api/containers', expect: [200] },
  { method: 'GET', path: '/api/timers', expect: [200] },
  { method: 'GET', path: '/api/activity?limit=5', expect: [200] },
  { method: 'GET', path: '/api/trends?days=7', expect: [200] },
  { method: 'GET', path: '/api/linkcheck', expect: [200] },

  // vitals
  { method: 'GET', path: '/api/vitals', expect: [200] },
  { method: 'GET', path: '/api/vitals/rpi', expect: [200] },
  { method: 'GET', path: '/api/vitals/android', expect: [404], note: 'android is not a vitals host' },

  // agents (LAN fan-out — reachable agents required for 200)
  { method: 'GET', path: '/api/agents', expect: [200] },
  { method: 'POST', path: '/api/agents/nope/sync', expect: [404] },
  { method: 'POST', path: '/api/agents/rpi/restart-container', body: {}, expect: [400] },
  { method: 'POST', path: '/api/agents/rpi/update-container', body: {}, expect: [400] },
  { method: 'POST', path: '/api/agents/rpi/restart-service', body: {}, expect: [400] },
  { method: 'POST', path: '/api/agents/rpi/wake', expect: [404], note: 'only opti is a wake target' },
  { method: 'GET', path: '/api/agents/rpi/apt-status', expect: [200, 502] },

  // architecture
  { method: 'GET', path: '/api/architecture/live', expect: [200] },
  { method: 'GET', path: '/api/architecture/data', expect: [200, 500], note: '500 only if curated data.json is absent' },
  { method: 'POST', path: '/api/architecture/ingest', body: { host: '../evil' }, expect: [400, 401], note: '401 when the ingest token is enforced' },

  // pihole / uptime (config-dependent)
  { method: 'GET', path: '/api/pihole/summary', expect: [200, 502, 503] },
  { method: 'GET', path: '/api/pihole/blocking', expect: [200, 502, 503] },
  { method: 'GET', path: '/api/uptime', expect: [200, 502, 503] },

  // samba (dispatcher-dependent)
  { method: 'GET', path: '/api/samba/status', expect: [200, 502, 503] },
  { method: 'GET', path: '/api/samba/config', expect: [200, 502, 503] },
  { method: 'GET', path: '/api/samba/backups', expect: [200, 502, 503] },
  { method: 'POST', path: '/api/samba/validate', body: {}, expect: [400] },
  { method: 'POST', path: '/api/samba/config', body: { content: '' }, expect: [400] },
  { method: 'POST', path: '/api/samba/rollback', body: { stamp: 'x' }, expect: [400] },

  // agentic (workspace-mount dependent)
  { method: 'GET', path: '/api/agentic', expect: [200, 503] },
  { method: 'POST', path: '/api/agentic/wire/vim', expect: [400] },
  { method: 'POST', path: '/api/agentic/proposal/frob/skill-x', expect: [400] },

  // streams (GETs proxy to nn; POST guard is local)
  { method: 'GET', path: '/api/streams/status', expect: [200, 502] },
  { method: 'GET', path: '/api/streams/presets', expect: [200, 502] },

  // llama (android is intermittent by design)
  { method: 'GET', path: '/api/llama/status', expect: [200, 502] },
  { method: 'GET', path: '/api/llama/models', expect: [200, 502] },
  { method: 'GET', path: '/api/llama/runbooks', expect: [200, 502] },
  { method: 'POST', path: '/api/llama/chat', body: {}, expect: [400] },

  // bots (docker-network dependent — 502 off-box)
  { method: 'GET', path: '/api/weather/status', expect: [200, 502] },
  { method: 'GET', path: '/api/weather/config', expect: [200, 502] },
  { method: 'GET', path: '/api/weather/geocode', expect: [400], note: 'missing ?q= is local validation' },
  { method: 'GET', path: '/api/healthdigest/status', expect: [200, 502] },
  { method: 'GET', path: '/api/jellyfin/status', expect: [200, 502] },
  { method: 'GET', path: '/api/sports/status', expect: [200, 502] },
  { method: 'GET', path: '/api/sports/teams?q=x', expect: [400], note: 'missing ?league= is local validation' },
  { method: 'GET', path: '/api/hltv/status', expect: [200, 502] },
  { method: 'GET', path: '/api/hltv/vrs', expect: [200, 502] },
  { method: 'GET', path: '/api/hltv/day', expect: [200, 502] },

  // static contract
  { method: 'GET', path: '/', expect: [200], html: true },
  { method: 'GET', path: '/legacy/', expect: [200], html: true },
  { method: 'GET', path: '/tokens.css', expect: [200] },
  { method: 'GET', path: '/architecture/', expect: [200], html: true },
  { method: 'GET', path: '/streams/', expect: [200], html: true },
];

async function run() {
  const baseline = COMPARE ? JSON.parse(fs.readFileSync(COMPARE, 'utf8')) : null;
  const results = {};
  let failures = 0;

  for (const e of MANIFEST) {
    const url = `${BASE}${e.path}`;
    const id = `${e.method} ${e.path}`;
    let status = null, keys = null, err = null;
    try {
      const res = await fetch(url, {
        method: e.method,
        headers: e.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
        body: e.body !== undefined ? JSON.stringify(e.body) : undefined,
        signal: AbortSignal.timeout(30000),
      });
      status = res.status;
      const text = await res.text();
      if (!e.html) {
        try { keys = Object.keys(JSON.parse(text)).sort(); } catch (_) { keys = null; }
      }
    } catch (ex) {
      err = ex.message;
    }

    let ok = err === null && e.expect.includes(status);
    let detail = err || `HTTP ${status}`;

    if (ok && baseline) {
      const b = baseline[id];
      if (b && b.status === 200 && status === 200 && b.keys && keys) {
        const missing = b.keys.filter((k) => !keys.includes(k));
        if (missing.length) {
          ok = false;
          detail = `missing keys vs baseline: ${missing.join(', ')}`;
        }
      }
    }

    results[id] = { status, keys };
    if (!ok) failures++;
    console.log(`${ok ? ' ok ' : 'FAIL'}  ${id}  ${detail}${e.note && !ok ? `  (${e.note})` : ''}`);
  }

  if (CAPTURE) {
    fs.writeFileSync(CAPTURE, JSON.stringify(results, null, 2));
    console.log(`\nbaseline written to ${CAPTURE}`);
  }
  console.log(`\n${MANIFEST.length - failures}/${MANIFEST.length} passed against ${BASE}`);
  process.exit(failures ? 1 : 0);
}

run();
