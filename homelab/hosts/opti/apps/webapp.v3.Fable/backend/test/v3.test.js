// v3 additions — the event bus, the SSE status route, the feed poller's diffing and
// the fleet model. Same fixture discipline as parity.test.js: everything provable
// without a LAN, via fastify.inject().
const { test, before, after } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const FIX = fs.mkdtempSync(path.join(os.tmpdir(), 'webapp-v3-'));
const AGENT_LOGS = path.join(FIX, 'agent-logs');
const REPORTS = path.join(FIX, 'reports');
const ARCH_DATA = path.join(FIX, 'arch-data');
fs.mkdirSync(AGENT_LOGS, { recursive: true });
fs.mkdirSync(REPORTS, { recursive: true });
fs.mkdirSync(ARCH_DATA, { recursive: true });

process.env.AGENT_LOGS_DIR = AGENT_LOGS;
process.env.REPORTS_DIR = REPORTS;
process.env.ARCH_DATA_DIR = ARCH_DATA;
process.env.VITALS_DISABLED = '1';     // also disables the feed poller's timer — we tick it by hand
process.env.CURATED_ARCH_PATH = path.join(FIX, 'curated.json');
delete process.env.HL_ARCH_INGEST_TOKEN;
delete process.env.DISPATCHER_URL;

const NOW = new Date().toISOString();
const writeDoctor = (containers) => fs.writeFileSync(path.join(AGENT_LOGS, 'homelab-doctor-latest.json'), JSON.stringify({
  status: 'ok', summary: 'fixture', run_at: NOW,
  findings: [{ severity: 'warn', message: '[opti] pool at 61%' }],
  hosts: [{ host: 'rpi', status: 'ok', metrics: { containers } }],
}));
writeDoctor([{ name: 'pihole', status: 'Up 3 days' }]);
fs.writeFileSync(path.join(AGENT_LOGS, 'agents-state.json'), JSON.stringify({ 'homelab-doctor': { enabled: true } }));
fs.writeFileSync(process.env.CURATED_ARCH_PATH, JSON.stringify({ nodes: [] }));

const buildApp = require('../app');

let app;
before(async () => {
  app = await buildApp({ logger: false });
  await app.ready();
});
after(async () => { await app.close(); });

test('GET /api/events/status describes the bus', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/events/status' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.equal(b.enabled, true);
  assert.equal(typeof b.clients, 'number');
  assert.ok(Array.isArray(b.events) && b.events.includes('vitals'));
  assert.equal(typeof b.seq, 'number');
  assert.ok('last' in b);
});

test('event bus records the last emit per event', async () => {
  const before = app.events.seq();
  app.events.emit('vitals', app.vitals.rollup());
  assert.equal(app.events.seq(), before + 1);
  const r = await app.inject({ method: 'GET', url: '/api/events/status' });
  assert.ok(r.json().last.vitals?.at);
});

test('feed poller emits containers only when the fleet changes', async () => {
  const got = [];
  const on = (p) => got.push(p);
  app.events.on('containers', on);
  await app.feedPoller.tick();          // baseline
  await app.feedPoller.tick();          // unchanged → nothing
  assert.equal(got.length, 0);
  writeDoctor([{ name: 'pihole', status: 'Exited (1) 2 minutes ago' }]);
  await app.feedPoller.tick();          // pihole went down → one event, the full document
  app.events.off('containers', on);
  assert.equal(got.length, 1);
  const rpi = got[0].hosts.find((h) => h.host === 'rpi');
  assert.equal(rpi.containers[0].name, 'pihole');
  assert.equal(rpi.containers[0].up, false);
});

test('GET /api/hosts lists the fleet with static facts + live joins', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/hosts' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  const names = b.hosts.map((h) => h.name);
  for (const n of ['opti', 'rpi', 'noblenumbat', 'android', 'tux']) assert.ok(names.includes(n), n);
  const rpi = b.hosts.find((h) => h.name === 'rpi');
  assert.equal(rpi.ip, '192.168.1.10');
  assert.equal(rpi.agent, true);
  assert.equal(rpi.spof, 'dns');
  assert.equal(rpi.vitals, null);      // VITALS_DISABLED — no samples, key still present
  assert.ok(Array.isArray(b.depends) && b.depends.length > 0);
  assert.equal(b.gateway.ip, '192.168.1.1');
});

test('GET /api/incidents correlates findings by host + window; ack/mute round-trip', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/incidents' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.ok(Array.isArray(b.incidents));
  for (const k of ['open', 'muted', 'acked', 'generated_at']) assert.ok(k in b, k);
  const opti = b.incidents.find((i) => i.host === 'opti');
  assert.ok(opti, 'the [opti] doctor finding becomes an opti incident');
  assert.equal(opti.status, 'open');
  assert.equal(opti.severity, 'warn');
  assert.equal(opti.count, 1);
  assert.match(opti.title, /pool at 61%/);
  assert.ok(Array.isArray(opti.changes));   // key present even with homelab-db unconfigured

  // mute → status muted, hidden from the bell? no — mute is incident-level only
  const m = await app.inject({ method: 'POST', url: `/api/incidents/${opti.id}/mute`, payload: { days: 7 } });
  assert.equal(m.statusCode, 200);
  assert.ok(m.json().muted_until);
  const after = (await app.inject({ method: 'GET', url: '/api/incidents' })).json();
  assert.equal(after.incidents.find((i) => i.id === opti.id).status, 'muted');
  const cleared = await app.inject({ method: 'POST', url: `/api/incidents/${opti.id}/mute`, payload: { clear: true } });
  assert.equal(cleared.json().muted_until, null);

  // ack → every member finding is acked in the notifications store too
  const a = await app.inject({ method: 'POST', url: `/api/incidents/${opti.id}/ack`, payload: {} });
  assert.equal(a.statusCode, 200);
  assert.equal(a.json().items, 1);
  const notif = (await app.inject({ method: 'GET', url: '/api/notifications' })).json();
  assert.equal(notif.unacked, 0);
  const listed = (await app.inject({ method: 'GET', url: '/api/incidents?all=1' })).json();
  assert.equal(listed.incidents.find((i) => i.id === opti.id).status, 'acked');
  const hidden = (await app.inject({ method: 'GET', url: '/api/incidents' })).json();
  assert.ok(!hidden.incidents.find((i) => i.id === opti.id), 'acked incidents are hidden by default');
  // un-ack restores it
  await app.inject({ method: 'POST', url: `/api/incidents/${opti.id}/ack`, payload: { acked: false } });
  assert.equal((await app.inject({ method: 'GET', url: '/api/notifications' })).json().unacked, 1);
});

test('GET /api/services joins the catalog with probes + container state', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/services' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.ok(b.services.length > 25);
  const pihole = b.services.find((s) => s.id === 'pihole');
  assert.ok(pihole);
  assert.ok(['up', 'down', 'unknown'].includes(pihole.state));
  assert.ok(b.categories.includes('Media'));
  assert.ok(b.services.find((s) => s.id === 'streams'));
});

test('alert rules: defaults seed, evaluation fires on the fixture, hits reach notifications', async () => {
  const list = await app.inject({ method: 'GET', url: '/api/rules' });
  assert.equal(list.statusCode, 200);
  assert.ok(list.json().rules.find((x) => x.id === 'disk-warn'));

  // Give the fixture an 85% root disk on opti via the doctor report the /live route reads.
  fs.writeFileSync(path.join(AGENT_LOGS, 'hardware-latest.json'), JSON.stringify({
    status: 'ok', run_at: NOW,
    hosts: [{ host: 'opti', status: 'ok', metrics: { uptime: '42 days', disks: [{ mount: '/', used_pct: 85 }] } }],
  }));
  const ev = await app.inject({ method: 'POST', url: '/api/rules/evaluate' });
  assert.equal(ev.statusCode, 200);
  const hits = ev.json().hits;
  const disk = hits.find((h) => h.rule_id === 'disk-warn' && h.host === 'opti');
  assert.ok(disk, 'disk-warn fires for opti at 85%');
  assert.ok(!hits.find((h) => h.rule_id === 'disk-crit'), 'disk-crit (90%) does not fire at 85%');

  const notif = (await app.inject({ method: 'GET', url: '/api/notifications' })).json();
  assert.ok(notif.items.find((n) => n.source === 'rule:disk-warn' && n.host === 'opti'), 'rule hit is a notification');

  // CRUD
  const created = await app.inject({ method: 'POST', url: '/api/rules', payload: { name: 'opti hot', kind: 'temp', host: 'opti', op: '>', threshold: 60, severity: 'warn' } });
  assert.equal(created.statusCode, 200);
  const id = created.json().id;
  const bad = await app.inject({ method: 'POST', url: '/api/rules', payload: { name: 'x', kind: 'nope', severity: 'warn' } });
  assert.equal(bad.statusCode, 400);
  const upd = await app.inject({ method: 'PUT', url: `/api/rules/${id}`, payload: { enabled: false } });
  assert.equal(upd.json().enabled, false);
  const del = await app.inject({ method: 'DELETE', url: `/api/rules/${id}` });
  assert.equal(del.statusCode, 200);
});

test('GET /api/streams/guide: reports evidence, never manufactures it', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/streams/guide' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  // The station is addressed by LAN IP, so on a LAN dev box it may actually answer.
  assert.equal(typeof b.station.ok, 'boolean');
  assert.ok(Array.isArray(b.station.slots));
  assert.ok(b.channels.length >= 5, 'channel directory (station presets or fallback)');
  assert.ok(b.channels.find((c) => c.channel === 'blastpremier'));
  // No live inference on directory channels — only what our own station plays.
  for (const c of b.channels) {
    assert.ok(!('on_air' in c), 'directory channels carry no live inference');
    assert.ok('watching_slot' in c && 'listed_matches' in c);
  }
  assert.deepEqual(b.matches, []);
  assert.equal(b.hltv.ok, false);
  assert.equal(b.vrs.known, false);
  assert.equal(b.vrs.system, 'Valve Regional Standings, via HLTV');
  assert.ok(typeof b.coverage === 'string' && b.coverage.length > 0);
});

test('guide match model: ranks from VRS, no derived tier, no organizer fallback', async () => {
  const { FALLBACK_PRESETS, channelFromUrl, isPremier, normTeam } = require('../lib/stream-catalog');

  // A tier is never invented from HLTV's star rating.
  assert.equal(channelFromUrl('https://twitch.tv/blastpremier').channel, 'blastpremier');
  assert.equal(channelFromUrl('https://www.twitch.tv/videos/12345'), null, 'reserved twitch path is not a channel');
  assert.equal(channelFromUrl('http://twitch.tv/blastpremier'), null, 'http is refused');
  assert.equal(channelFromUrl('https://user:pw@twitch.tv/x'), null, 'credentials are refused');
  assert.equal(channelFromUrl('https://www.youtube.com/watch?v=abc').type, 'url', 'youtube passes through as a URL');
  assert.equal(channelFromUrl(undefined), null, 'a match with no stream yields no channel');

  // "Premier series" reads the event name and excludes feeder tiers.
  assert.equal(isPremier('BLAST Premier Fall Final 2026'), true);
  assert.equal(isPremier('IEM Fall Open Qualifier'), false);
  assert.equal(isPremier('CCT Season 12'), false);

  assert.equal(normTeam('Team Spirit'), 'spirit', 'VRS matching ignores the Team prefix');
  assert.ok(FALLBACK_PRESETS.groups.length >= 2);
});

test('POST /api/streams/watch validates input', async () => {
  const r = await app.inject({ method: 'POST', url: '/api/streams/watch', payload: {} });
  // no HL_STREAM_TOKEN in tests → the misconfiguration message, never a crash
  assert.equal(r.statusCode, 500);
  assert.match(r.json().error, /HL_STREAM_TOKEN/);
});

test('GET /api/vitals still answers its v2 shape', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/vitals' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.ok(b.hosts && 'rpi' in b.hosts);
  assert.equal(typeof b.interval_s, 'number');
});

// ── Jobs: stepped execution + the audit trail ───────────────────────────────
// The point of these is not that a job "works" — it is that a job which fails
// partway tells you WHERE, and that the record outlives the request.

test('a job declares its whole plan before running any of it', async () => {
  const job = app.jobs.create({
    kind: 'test-plan', title: 'Plan visibility', host: 'rpi', target: 'rpi',
    steps: [{ key: 'a', label: 'First' }, { key: 'b', label: 'Second' }],
  });
  const snap = job.snapshot();
  assert.equal(snap.steps.length, 2);
  assert.deepEqual(snap.steps.map((s) => s.status), ['pending', 'pending'],
    'every step is visible as pending the moment the job exists — that is the whole feature');
  assert.equal(snap.status, 'running');
  job.finish('ok');
});

test('a failing step stops the job and leaves later steps pending, not failed', async () => {
  let ran3 = false;
  await assert.rejects(app.jobs.run({
    kind: 'test-fail', title: 'Fails in the middle', host: 'rpi', target: 'x',
    steps: [{ key: 's1', label: 'ok' }, { key: 's2', label: 'boom' }, { key: 's3', label: 'never' }],
  }, async (job) => {
    await job.step('s1', (note) => { note('fine'); });
    await job.step('s2', () => { throw new Error('the agent refused'); });
    await job.step('s3', () => { ran3 = true; });
  }));

  assert.equal(ran3, false, 'nothing after the failure runs');
  const j = app.jobs.list({ limit: 5 }).find((x) => x.kind === 'test-fail');
  assert.equal(j.status, 'failed');
  assert.equal(j.error, 'the agent refused');
  assert.deepEqual(j.steps.map((s) => s.status), ['ok', 'failed', 'pending'],
    '"we never got there" is different from "it failed" and must render differently');
  assert.match(j.steps[1].output, /refused/, 'the failing step keeps the message it failed with');
});

test('every finished job lands in the durable audit trail', async () => {
  await app.jobs.run({
    kind: 'test-audit', title: 'Audited', host: 'opti', target: 'thing',
    steps: [{ key: 'only', label: 'Do it' }],
  }, async (job) => { await job.step('only', (note) => note('done')); });

  const entries = app.jobs.audit({ days: 2, limit: 100, kind: 'test-audit' });
  assert.ok(entries.length >= 1, 'the record exists independently of the in-memory list');
  const e = entries[0];
  assert.equal(e.host, 'opti');
  assert.equal(e.status, 'ok');
  assert.ok(e.summary.includes('test-audit'), 'the line is greppable without this app');
  assert.ok(e.finished_at, 'finished jobs carry an end time');
});

test('job transitions are emitted on the bus so a browser can watch', async () => {
  const seen = [];
  const onJob = (snap) => seen.push(snap.steps.map((s) => s.status).join(','));
  app.events.on('job', onJob);
  await app.jobs.run({
    kind: 'test-stream', title: 'Streamed', host: 'rpi', target: 't',
    steps: [{ key: 'a', label: 'A' }, { key: 'b', label: 'B' }],
  }, async (job) => {
    await job.step('a', () => {});
    await job.step('b', () => {});
  });
  app.events.off('job', onJob);
  assert.ok(seen.length >= 4, `expected a snapshot per transition, got ${seen.length}`);
  assert.ok(seen.includes('running,pending'), 'the first step reports as it starts, not only when it ends');
});

test('GET /api/jobs and /api/jobs/:id expose the same snapshots', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/jobs' });
  assert.equal(r.statusCode, 200);
  const body = r.json();
  assert.ok(Array.isArray(body.jobs) && body.jobs.length > 0);

  const one = await app.inject({ method: 'GET', url: `/api/jobs/${body.jobs[0].id}` });
  assert.equal(one.statusCode, 200);
  assert.equal(one.json().id, body.jobs[0].id);

  const missing = await app.inject({ method: 'GET', url: '/api/jobs/deadbeefdeadbeef' });
  assert.equal(missing.statusCode, 404);
});

test('GET /api/jobs/audit reads the trail back and filters', async () => {
  const r = await app.inject({ method: 'GET', url: '/api/jobs/audit?days=2&kind=test-audit' });
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.ok(b.entries.length >= 1);
  assert.ok(b.entries.every((e) => e.kind === 'test-audit'), 'the kind filter is honoured');
});
