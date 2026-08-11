// Parity tests for the Express→Fastify port — everything that can be proven without
// a LAN: route mounting, local validation, file-backed read models against fixtures,
// and the two compatibility shims (empty JSON bodies, authored 502 passthrough).
// Runs via `npm test` (node --test); CI runs it on every push.
const { test, before, after } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

// Fixture dirs must exist BEFORE lib/paths.js is required (it resolves at import).
const FIX = fs.mkdtempSync(path.join(os.tmpdir(), 'webapp-parity-'));
const AGENT_LOGS = path.join(FIX, 'agent-logs');
const REPORTS = path.join(FIX, 'reports');
const ARCH_DATA = path.join(FIX, 'arch-data');
fs.mkdirSync(AGENT_LOGS, { recursive: true });
fs.mkdirSync(REPORTS, { recursive: true });
fs.mkdirSync(ARCH_DATA, { recursive: true });

process.env.AGENT_LOGS_DIR = AGENT_LOGS;
process.env.REPORTS_DIR = REPORTS;
process.env.ARCH_DATA_DIR = ARCH_DATA;
process.env.VITALS_DISABLED = '1';
process.env.CURATED_ARCH_PATH = path.join(FIX, 'curated.json');
delete process.env.HL_ARCH_INGEST_TOKEN;
delete process.env.DISPATCHER_URL;

// ── fixtures ─────────────────────────────────────────────────────────────────
const NOW = new Date().toISOString();

fs.writeFileSync(path.join(AGENT_LOGS, 'homelab-doctor-latest.json'), JSON.stringify({
  status: 'ok', summary: '4/4 services up', run_at: NOW,
  findings: [{ severity: 'warn', message: '[opti] pool at 61%' }],
  hosts: [
    { host: 'rpi', status: 'ok', metrics: { containers: [{ name: 'pihole', status: 'Up 3 days' }] } },
    { host: 'opti', status: 'ok', metrics: { pool: { used_pct: 61.2, pool_name: 'red' }, disk_used_pct: 40 } },
  ],
}));
fs.writeFileSync(path.join(AGENT_LOGS, 'agents-state.json'), JSON.stringify({
  'homelab-doctor': { enabled: true },
}));
const doctorHist = path.join(AGENT_LOGS, 'homelab-doctor-latest');
fs.mkdirSync(doctorHist, { recursive: true });
fs.writeFileSync(path.join(doctorHist, '2026-08-09.json'), JSON.stringify({
  hosts: [{ host: 'opti', metrics: { pool: { used_pct: 61.0, pool_name: 'red' }, disk_used_pct: 40 } }],
}));

fs.writeFileSync(path.join(REPORTS, 'journal-hunt-latest.json'), JSON.stringify({
  status: 'ok', summary: 'nothing suspicious', run_at: NOW, findings: [],
}));

fs.writeFileSync(process.env.CURATED_ARCH_PATH, JSON.stringify({
  nodes: [
    { id: 'n-pihole', host: 'rpi', container: 'pihole', label: 'Pi-hole' },
    { id: 'n-ghost', host: 'rpi', container: 'ghost', label: 'Removed thing' },
  ],
}));

const buildApp = require('../app');

let app;
before(async () => {
  app = await buildApp({ logger: false });
  await app.ready();
});
after(async () => { await app.close(); });

// ── basics ───────────────────────────────────────────────────────────────────
test('GET /api/health', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/health' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.equal(b.status, 'ok');
  assert.equal(b.host, 'webapp.rpi.lan');
  assert.equal(typeof b.uptime, 'number');
});

test('GET /legacy redirects to /legacy/', async () => {
  const r = await app.inject({ method: 'GET', url: '/legacy' });
  assert.equal(r.statusCode, 301);
  assert.equal(r.headers.location, '/legacy/');
});

test('empty JSON body accepted (Express contract)', async () => {
  // Deliberately an endpoint whose validation reads the body: {} → 400 "content
  // must be a string" proves the parser produced {} rather than erroring at 400
  // FST_ERR_CTP_EMPTY_JSON_BODY (whose message would differ).
  const r = await app.inject({
    method: 'POST', url: '/api/samba/validate',
    headers: { 'content-type': 'application/json' }, body: '',
  });
  assert.equal(r.statusCode, 400);
  assert.equal(r.json().error, 'content must be a string');
});

test('bare POST with no content-type accepted', async () => {
  const r = await app.inject({ method: 'POST', url: '/api/agents/rpi/restart-container' });
  assert.equal(r.statusCode, 400);
  assert.equal(r.json().error, 'body.container is required');
});

// ── file-backed read models against fixtures ────────────────────────────────
test('GET /api/reports lists fixture report with catalog metadata', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/reports' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.equal(b.reports.length, 1);
  assert.equal(b.reports[0].name, 'journal-hunt-latest');
  assert.equal(b.reports[0].label, 'Journal Threat & Health Hunter');
  assert.equal(b.reports[0].enabled, true);
});

test('GET /api/reports/:name returns the raw report', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/reports/journal-hunt-latest' });
  assert.equal(r.statusCode, 200);
  assert.equal(r.json().summary, 'nothing suspicious');
});

test('GET /api/reports/:name 404s on missing', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/reports/nope' });
  assert.equal(r.statusCode, 404);
});

test('GET /api/runners lists and sorts, excludes home-only', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/runners' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.equal(b.runners[0].name, 'homelab-doctor-latest');
  assert.equal(b.runners[0].label, 'Homelab Doctor');
  assert.ok(!b.runners.some((x) => x.home));
});

test('GET /api/runners/:name/history reads dated snapshots', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/runners/homelab-doctor-latest/history' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.equal(b.history.length, 1);
  assert.equal(b.history[0].date, '2026-08-09');
});

test('GET /api/runners/:name/report/:date validates date', async () => {
  const bad = await app.inject({ method: 'GET', url: '/api/runners/homelab-doctor-latest/report/evil' });
  assert.equal(bad.statusCode, 400);
  const ok = await app.inject({ method: 'GET', url: '/api/runners/homelab-doctor-latest/report/2026-08-09' });
  assert.equal(ok.statusCode, 200);
});

// ── architecture ingest + merge ──────────────────────────────────────────────
test('POST /api/architecture/ingest validates host and stores fragment', async () => {
  const bad = await app.inject({
    method: 'POST', url: '/api/architecture/ingest',
    payload: { host: '../evil' },
  });
  assert.equal(bad.statusCode, 400);

  const ok = await app.inject({
    method: 'POST', url: '/api/architecture/ingest',
    payload: {
      host: 'rpi', collected_at: NOW, agent_version: '0.4.0',
      docker: { containers: [
        { name: 'pihole', state: 'running', image: 'pihole/pihole' },
        { name: 'mystery', state: 'running', image: 'x/y' },
      ] },
      timers: [{ raw: 'Sat 2026-08-09 12:05:44 EDT 1min Sat 2026-08-09 12:03:34 EDT 55s ago vpn-stack-heal.timer vpn-stack-heal.service' }],
    },
  });
  assert.equal(ok.statusCode, 200);
  assert.equal(ok.json().containers, 2);
  assert.ok(fs.existsSync(path.join(ARCH_DATA, 'fragments', 'rpi.json')));
});

test('GET /api/architecture/data merges fragments and reports drift both ways', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/architecture/data' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  const pihole = b.nodes.find((n) => n.id === 'n-pihole');
  assert.equal(pihole._live.state, 'running');
  assert.deepEqual(b.live_merge.drift.undescribed.map((d) => d.container), ['mystery']);
  assert.deepEqual(b.live_merge.drift.missing.map((d) => d.container), ['ghost']);
});

test('GET /api/architecture/live reads runner reports', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/architecture/live' });
  assert.equal(r.statusCode, 200);
  assert.equal(r.json().hosts.opti.pool.pool_name, 'red');
});

// ── dashboard read models ────────────────────────────────────────────────────
test('GET /api/containers joins doctor and fragments', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/containers' });
  assert.equal(r.statusCode, 200);
  const rpi = r.json().hosts.find((h) => h.host === 'rpi');
  const pihole = rpi.containers.find((c) => c.name === 'pihole');
  assert.equal(pihole.up, true);
  assert.equal(pihole.image, 'pihole/pihole');
  assert.ok(rpi.containers.some((c) => c.name === 'mystery'));
});

test('GET /api/timers parses raw systemd lines', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/timers' });
  assert.equal(r.statusCode, 200);
  const rpi = r.json().hosts.find((h) => h.host === 'rpi');
  assert.equal(rpi.timers[0].unit, 'vpn-stack-heal.timer');
  assert.equal(rpi.timers[0].passed, '55s ago');
});

test('GET /api/activity lifts [host] prefixes into fields', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/activity' });
  assert.equal(r.statusCode, 200);
  const ev = r.json().events.find((e) => e.source === 'homelab-doctor');
  assert.equal(ev.host, 'opti');
  assert.equal(ev.message, 'pool at 61%');
});

test('GET /api/trends reads dated doctor history', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/trends' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.equal(b.pool.length, 1);
  assert.equal(b.pool[0].pool_name, 'red');
});

// ── vitals (poller disabled — read side only) ────────────────────────────────
test('GET /api/vitals serves per-host rollup', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/vitals' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.deepEqual(Object.keys(b.hosts).sort(), ['noblenumbat', 'opti', 'rpi']);
  assert.equal(b.interval_s, 30);
});

test('GET /api/vitals/:host 404s on unknown host', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/vitals/android' });
  assert.equal(r.statusCode, 404);
});

test('vitals range param: short ranges 30s, long ranges 5min, bad ranges 400', async () => {
  const short = await app.inject({ method: 'GET', url: '/api/vitals/rpi?range=3h' });
  assert.equal(short.statusCode, 200);
  assert.equal(short.json().interval_s, 30);
  assert.equal(short.json().range, '3h');

  const long = await app.inject({ method: 'GET', url: '/api/vitals/rpi?range=48h' });
  assert.equal(long.statusCode, 200);
  assert.equal(long.json().interval_s, 300);

  const bad = await app.inject({ method: 'GET', url: '/api/vitals/rpi?range=1w' });
  assert.equal(bad.statusCode, 400);

  // legacy ?points= callers keep the old contract
  const legacy = await app.inject({ method: 'GET', url: '/api/vitals/rpi?points=60' });
  assert.equal(legacy.statusCode, 200);
  assert.equal(legacy.json().interval_s, 30);
  assert.equal(legacy.json().range, null);
});

// ── local validation on control routes ───────────────────────────────────────
test('agents routes 404 unknown hosts and 400 bad bodies', async () => {
  assert.equal((await app.inject({ method: 'POST', url: '/api/agents/nope/sync' })).statusCode, 404);
  assert.equal((await app.inject({ method: 'POST', url: '/api/agents/rpi/update-container', payload: {} })).statusCode, 400);
  assert.equal((await app.inject({ method: 'POST', url: '/api/agents/rpi/restart-service', payload: {} })).statusCode, 400);
  assert.equal((await app.inject({ method: 'POST', url: '/api/agents/rpi/wake' })).statusCode, 404); // only opti is a wake target
});

test('dispatcher-backed routes 503 without DISPATCHER_URL', async () => {
  assert.equal((await app.inject({ method: 'GET', url: '/api/samba/status' })).statusCode, 503);
  assert.equal((await app.inject({ method: 'POST', url: '/api/runners/homelab-doctor/run' })).statusCode, 503);
});

test('samba shape checks', async () => {
  assert.equal((await app.inject({ method: 'POST', url: '/api/samba/config', payload: { content: '' } })).statusCode, 400);
  assert.equal((await app.inject({ method: 'POST', url: '/api/samba/rollback', payload: { stamp: 'nope' } })).statusCode, 400);
});

test('agentic validation', async () => {
  assert.equal((await app.inject({ method: 'POST', url: '/api/agentic/wire/vim' })).statusCode, 400);
  assert.equal((await app.inject({ method: 'POST', url: '/api/agentic/proposal/frob/skill-x' })).statusCode, 400);
  assert.equal((await app.inject({ method: 'POST', url: '/api/agentic/proposal/promote/EVIL' })).statusCode, 400);
});

test('llama chat requires messages[]', async () => {
  const r = await app.inject({ method: 'POST', url: '/api/llama/chat', payload: {} });
  assert.equal(r.statusCode, 400);
  assert.equal(r.json().error, 'missing messages[]');
});

test('weather geocode / sports teams param validation', async () => {
  assert.equal((await app.inject({ method: 'GET', url: '/api/weather/geocode' })).statusCode, 400);
  assert.equal((await app.inject({ method: 'GET', url: '/api/sports/teams?q=x' })).statusCode, 400);
});

test('streams POSTs refuse to run without HL_STREAM_TOKEN', async () => {
  const r = await app.inject({ method: 'POST', url: '/api/streams/start', payload: {} });
  assert.equal(r.statusCode, 500);
  assert.match(r.json().error, /HL_STREAM_TOKEN/);
});

test('pihole 503s without PIHOLE_WEB_PASSWORD', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/pihole/summary' });
  assert.equal(r.statusCode, 503);
});

test('uptime 503s without KUMA_API_KEY', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/uptime' });
  assert.equal(r.statusCode, 503);
});

// ── board engine (/api/ui) ───────────────────────────────────────────────────
test('GET /api/ui/boards seeds the two protected boards', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/ui/boards' });
  assert.equal(r.statusCode, 200);
  const slugs = r.json().boards.map((b) => b.slug);
  assert.ok(slugs.includes('home'));
  assert.ok(slugs.includes('dashboard'));
  assert.ok(r.json().boards.every((b) => b.protected));
});

test('GET /api/ui/boards/dashboard reseeds with bento-parity widgets', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/ui/boards/dashboard' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  const types = b.widgets.map((w) => w.type);
  for (const t of ['host-vitals', 'containers', 'pihole', 'activity', 'stat', 'quick-links']) {
    assert.ok(types.includes(t), `dashboard preset is missing ${t}`);
  }
  assert.equal(b.layouts.lg.length, b.widgets.length);
});

test('PUT /api/ui/boards/:slug bumps rev and persists geometry', async () => {
  const cur = (await app.inject({ method: 'GET', url: '/api/ui/boards/home' })).json();
  const layouts = JSON.parse(JSON.stringify(cur.layouts));
  layouts.lg[0].x = 5;
  const r = await app.inject({
    method: 'PUT', url: '/api/ui/boards/home',
    payload: { rev: cur.rev, widgets: cur.widgets, layouts },
  });
  assert.equal(r.statusCode, 200);
  assert.equal(r.json().rev, cur.rev + 1);
  assert.equal(r.json().layouts.lg[0].x, 5);
});

test('PUT with a stale rev 409s and returns the current document', async () => {
  const cur = (await app.inject({ method: 'GET', url: '/api/ui/boards/home' })).json();
  const r = await app.inject({
    method: 'PUT', url: '/api/ui/boards/home',
    payload: { rev: cur.rev - 1, widgets: cur.widgets, layouts: cur.layouts },
  });
  assert.equal(r.statusCode, 409);
  assert.equal(r.json().current.rev, cur.rev);
});

test('board CRUD: create, list, delete; protected boards refuse deletion', async () => {
  const made = await app.inject({ method: 'POST', url: '/api/ui/boards', payload: { name: 'Test Board' } });
  assert.equal(made.statusCode, 200);
  assert.equal(made.json().slug, 'test-board');

  const dup = await app.inject({ method: 'POST', url: '/api/ui/boards', payload: { name: 'Test Board' } });
  assert.equal(dup.statusCode, 409);

  const prot = await app.inject({ method: 'DELETE', url: '/api/ui/boards/home' });
  assert.equal(prot.statusCode, 400);

  const gone = await app.inject({ method: 'DELETE', url: '/api/ui/boards/test-board' });
  assert.equal(gone.statusCode, 200);
  assert.equal((await app.inject({ method: 'GET', url: '/api/ui/boards/test-board' })).statusCode, 404);
});

test('board writes reject bad slugs and malformed payloads', async () => {
  assert.equal((await app.inject({ method: 'GET', url: '/api/ui/boards/..%2Fevil' })).statusCode, 400);
  const bad = await app.inject({
    method: 'PUT', url: '/api/ui/boards/home',
    payload: { rev: 1, widgets: [{ type: 'clock' }], layouts: {} },   // widget without id
  });
  assert.equal(bad.statusCode, 400);
});

test('settings round-trip with defaults filled in', async () => {
  const initial = (await app.inject({ method: 'GET', url: '/api/ui/settings' })).json();
  assert.equal(initial.default_board, 'home');
  const put = await app.inject({ method: 'PUT', url: '/api/ui/settings', payload: { reduce_glass: true } });
  assert.equal(put.statusCode, 200);
  assert.equal(put.json().reduce_glass, true);
  assert.equal(put.json().default_board, 'home');   // untouched keys survive
});

test('wallpaper upload rejects non-images by magic bytes', async () => {
  const boundary = '----webappTest';
  const body = [
    `--${boundary}`,
    'Content-Disposition: form-data; name="file"; filename="evil.png"',
    'Content-Type: image/png',
    '',
    'not really a png',
    `--${boundary}--`, '',
  ].join('\r\n');
  const r = await app.inject({
    method: 'POST', url: '/api/ui/wallpapers',
    headers: { 'content-type': `multipart/form-data; boundary=${boundary}` },
    payload: body,
  });
  assert.equal(r.statusCode, 400);
  assert.match(r.json().error, /PNG, JPEG or WebP/);
});

test('wallpaper delete rejects path traversal', async () => {
  const r = await app.inject({ method: 'DELETE', url: '/api/ui/wallpapers/..%2F..%2Fetc%2Fpasswd' });
  assert.equal(r.statusCode, 400);
});

// ── notifications + updates (v2 integrations) ────────────────────────────────
test('GET /api/notifications surfaces actionable findings only', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/notifications' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  // The doctor fixture carries one warn finding; info-level lines must not appear.
  assert.equal(b.items.length, 1);
  assert.equal(b.items[0].severity, 'warn');
  assert.equal(b.items[0].host, 'opti');
  assert.equal(b.items[0].message, 'pool at 61%');
  assert.match(b.items[0].id, /^[a-f0-9]{16}$/);
  assert.equal(b.unacked, 1);
});

test('acknowledging a finding removes it from the open list and survives a refetch', async () => {
  const before = (await app.inject({ method: 'GET', url: '/api/notifications' })).json();
  const id = before.items[0].id;

  const ack = await app.inject({ method: 'POST', url: `/api/notifications/${id}/ack`, payload: { acked: true } });
  assert.equal(ack.statusCode, 200);

  const after = (await app.inject({ method: 'GET', url: '/api/notifications' })).json();
  assert.equal(after.unacked, 0);
  assert.equal(after.items.length, 0);

  // The fingerprint ignores timestamps, so the same finding on the next run stays acked.
  const withAcked = (await app.inject({ method: 'GET', url: '/api/notifications?all=1' })).json();
  assert.equal(withAcked.items.length, 1);
  assert.equal(withAcked.items[0].acked, true);

  const unack = await app.inject({ method: 'POST', url: `/api/notifications/${id}/ack`, payload: { acked: false } });
  assert.equal(unack.statusCode, 200);
  assert.equal((await app.inject({ method: 'GET', url: '/api/notifications' })).json().unacked, 1);
});

test('ack-all clears the inbox', async () => {
  const r = await app.inject({ method: 'POST', url: '/api/notifications/ack-all' });
  assert.equal(r.statusCode, 200);
  assert.equal((await app.inject({ method: 'GET', url: '/api/notifications' })).json().unacked, 0);
});

test('notification ack rejects a malformed id', async () => {
  const r = await app.inject({ method: 'POST', url: '/api/notifications/not-a-fingerprint/ack', payload: {} });
  assert.equal(r.statusCode, 400);
});

test('GET /api/updates aggregates images and packages', async () => {
  fs.writeFileSync(path.join(AGENT_LOGS, 'software-latest.json'), JSON.stringify({
    run_at: NOW,
    hosts: [{
      host: 'rpi',
      metrics: {
        pending_count: 4, security_count: 1, reboot_required: true, reboot_pkgs: 'linux-image',
        image_updates: [{ image: 'pihole/pihole:latest', containers: ['pihole'] }],
      },
    }],
  }));
  const r = await app.inject({ method: 'GET', url: '/api/updates' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.equal(b.counts.images, 1);
  assert.equal(b.images[0].container, 'pihole');
  assert.equal(b.images[0].host, 'rpi');
  assert.equal(b.images[0].running, true);        // joined against the fragment
  assert.equal(b.counts.packages, 4);
  assert.equal(b.counts.security, 1);
  assert.equal(b.counts.reboots, 1);
});

test('GET /api/runners/:name/log tails a runner log, or reports absence', async () => {
  const missing = await app.inject({ method: 'GET', url: '/api/runners/homelab-doctor-latest/log' });
  assert.equal(missing.statusCode, 200);
  assert.equal(missing.json().exists, false);

  fs.writeFileSync(path.join(AGENT_LOGS, 'homelab-doctor-latest.log'),
    Array.from({ length: 50 }, (_, i) => `line ${i}`).join('\n'));
  const r = await app.inject({ method: 'GET', url: '/api/runners/homelab-doctor-latest/log?lines=10' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.equal(b.exists, true);
  assert.equal(b.lines.length, 10);
  assert.equal(b.lines.at(-1), 'line 49');
});

test('pihole allow validates the domain shape', async () => {
  const bad = await app.inject({ method: 'POST', url: '/api/pihole/allow', payload: { domain: 'evil;rm -rf /' } });
  assert.equal(bad.statusCode, 400);
  // A well-formed domain gets past validation and fails at the (unconfigured) upstream.
  const ok = await app.inject({ method: 'POST', url: '/api/pihole/allow', payload: { domain: 'example.com' } });
  assert.equal(ok.statusCode, 503);
});

// ── static serving (legacy at root while dist is absent) ─────────────────────
test('GET / serves the era-appropriate shell', async () => {
  // Before the Vite build exists, root is the untouched v1 app; after, the v2 app.
  const haveDist = fs.existsSync(path.join(__dirname, '..', '..', 'frontend', 'dist', 'index.html'));
  const r = await app.inject({ method: 'GET', url: '/' });
  assert.equal(r.statusCode, 200);
  assert.match(r.headers['content-type'], /text\/html/);
  assert.match(r.body, haveDist ? /id="root"/ : /app\.js\?v=/);
});

test('GET /legacy/ serves the same shell', async () => {
  const r = await app.inject({ method: 'GET', url: '/legacy/' });
  assert.equal(r.statusCode, 200);
  assert.match(r.body, /app\.js\?v=/);
});

test('GET /tokens.css serves the legacy tokens', async () => {
  const r = await app.inject({ method: 'GET', url: '/tokens.css' });
  assert.equal(r.statusCode, 200);
  assert.match(r.body, /--ok/);
});

test('GET /architecture redirects to /architecture/ and serves it', async () => {
  const redir = await app.inject({ method: 'GET', url: '/architecture' });
  assert.ok([301, 302].includes(redir.statusCode));
  const page = await app.inject({ method: 'GET', url: '/architecture/' });
  assert.equal(page.statusCode, 200);
  assert.match(page.headers['content-type'], /text\/html/);
});
