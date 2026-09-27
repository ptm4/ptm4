// Offline tests: fake sources, no network, no disk writes outside a temp dir.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const os = require('os');
const fs = require('fs');
const path = require('path');

process.env.ARCH_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'pertal-test-'));
process.env.PERTAL_ACTIONS = 'dry';

const buildApp = require('../app');
const { createSnapshots } = require('../lib/snapshots');

const containers = (list) => ({ docker: true, containers: list, error: null });
const running = (name, health = null) => ({ name, image: `img/${name}`, state: 'running', status: 'Up 2 days', health });

function fakeSnapshots(overrides = {}) {
  const snaps = createSnapshots();
  const data = {
    'vitals:opti': { t: 1, cpu_pct: 4, mem_pct: 38, uptime_s: 90000, cores: 4 },
    'containers:opti': containers([running('webapp', 'healthy'), running('discord-jellyfin', 'healthy'), { ...running('notes-api'), state: 'exited', status: 'Exited (1)' }]),
    'agent:opti': { agent_version: '0.7.0', autoupdate: { mode: 'disabled', held_at: '2026-09-17' } },
    'vitals:rpi': { t: 1, cpu_pct: 1, mem_pct: 17, uptime_s: 3600 },
    'containers:rpi': containers([running('pihole', 'healthy')]),
    'agent:rpi': { agent_version: '0.7.0', autoupdate: { mode: 'enabled' } },
    'vitals:noblenumbat': null, // set below to fail
    'containers:noblenumbat': containers([]),
    'agent:noblenumbat': { agent_version: '0.7.0' },
    'probe:android': { reachable: false, rtt_ms: null },
    'hldb:status': {
      findings: [
        { tool: 'homelab-db', severity: 'critical', host: 'opti', message: '[opti] sdb SMART reallocated sectors: 272', run_at: '2026-09-27T10:00:00Z' },
        { tool: 'homelab-db', severity: 'warn', host: 'opti', message: '[bots] discord-jellyfin last attempt: failed: 401', run_at: '2026-09-27T10:00:00Z' },
        { tool: 'persistence-auditor', severity: 'warn', host: null, message: 'NEW persistence entry: a', run_at: '2026-09-27T09:00:00Z' },
        { tool: 'persistence-auditor', severity: 'warn', host: null, message: 'NEW persistence entry: b', run_at: '2026-09-27T09:00:00Z' },
      ],
    },
    ...overrides,
  };
  for (const [key, value] of Object.entries(data)) {
    const [kind, host] = key.split(':');
    snaps.register({
      key, group: host, label: key, intervalMs: 60_000,
      fetch: async () => {
        if (key === 'vitals:noblenumbat') throw new Error('connect ECONNREFUSED');
        return value;
      },
    });
    void kind;
  }
  return snaps;
}

async function appWith(snaps) {
  const app = await buildApp({ logger: false, snapshots: snaps, startSources: false, persist: false });
  await app.ready();
  await Promise.all(snaps.keys().map((k) => snaps.refresh(k)));
  await Promise.all(snaps.keys().filter((k) => k === 'vitals:noblenumbat').map((k) => snaps.refresh(k)));
  app.pertal.rebuild();
  return app;
}

test('snapshot cache keeps last good data when a refresh fails', async () => {
  let fail = false;
  const snaps = createSnapshots();
  snaps.register({ key: 'x', intervalMs: 1000, fetch: async () => { if (fail) throw new Error('boom'); return { v: 1 }; } });
  await snaps.refresh('x');
  fail = true;
  const after = await snaps.refresh('x');
  assert.deepStrictEqual(after.data, { v: 1 });
  assert.strictEqual(after.meta.ok, false);
  assert.strictEqual(after.meta.error, 'boom');
});

test('snapshot cache enforces its deadline even if fetch ignores the signal', async () => {
  const snaps = createSnapshots();
  snaps.register({ key: 'slow', intervalMs: 1000, timeoutMs: 50, fetch: () => new Promise(() => {}) });
  const s = await snaps.refresh('slow');
  assert.strictEqual(s.meta.ok, false);
  assert.match(s.meta.error, /timed out/);
});

test('resource model: reachability, findings and grouping', async () => {
  const app = await appWith(fakeSnapshots());
  const { resources, summary } = (await app.inject('/api/resources')).json();
  const byId = Object.fromEntries(resources.map((r) => [r.id, r]));

  assert.strictEqual(byId.opti.online, true, 'a critical finding does not make a host offline');
  assert.strictEqual(byId.opti.status, 'crit');
  assert.strictEqual(byId.noblenumbat.online, false);
  assert.strictEqual(byId.android.status, 'offline', 'intermittent host is offline, not critical');
  assert.strictEqual(byId['opti:notes-api'].status, 'crit');
  assert.strictEqual(byId['opti:discord-jellyfin'].status, 'warn', 'finding naming a container attaches to it');
  assert.match(byId['opti:discord-jellyfin'].status_text, /401/);
  assert.strictEqual(byId['opti:webapp'].status, 'ok');
  assert.strictEqual(summary.hosts.up, 2);

  const persistence = summary.issues.filter((i) => i.resource === 'persistence-auditor');
  assert.strictEqual(persistence.length, 1, 'unattached findings are grouped per tool');
  assert.strictEqual(persistence[0].details.length, 2);
  await app.close();
});

test('actions: applicability, confirmation and job lifecycle', async () => {
  const app = await appWith(fakeSnapshots());
  const opti = app.pertal.resource('opti');
  const kinds = opti.actions.map((a) => a.kind);
  assert.ok(kinds.includes('host.updates-resume'), 'held host offers resume');
  assert.ok(!kinds.includes('host.updates-hold'));

  const risky = await app.inject({ method: 'POST', url: '/api/actions/host.reboot', payload: { resource: 'opti' } });
  assert.strictEqual(risky.statusCode, 428);

  const bad = await app.inject({ method: 'POST', url: '/api/actions/container.restart', payload: { resource: 'opti' } });
  assert.strictEqual(bad.statusCode, 400);

  const missing = await app.inject({ method: 'POST', url: '/api/actions/nope', payload: { resource: 'opti' } });
  assert.strictEqual(missing.statusCode, 404);

  const ok = await app.inject({ method: 'POST', url: '/api/actions/resource.refresh', payload: { resource: 'opti:webapp' } });
  assert.strictEqual(ok.statusCode, 202);
  const { job } = ok.json();
  assert.strictEqual(job.steps[0].status === 'pending' || job.steps[0].status === 'running', true);

  // Let the detached job finish, then read it back.
  await new Promise((r) => setTimeout(r, 100));
  const done = (await app.inject(`/api/jobs/${job.id}`)).json().job;
  assert.strictEqual(done.status, 'ok');
  assert.strictEqual(done.resource, 'opti:webapp');
  await app.close();
});

test('a failing action is a failed job with a reason, never a silent no-op', async () => {
  const app = await appWith(fakeSnapshots());
  // noblenumbat's vitals source always throws, so refreshing it must fail the job.
  const res = await app.inject({ method: 'POST', url: '/api/actions/resource.refresh', payload: { resource: 'noblenumbat' } });
  const { job } = res.json();
  await new Promise((r) => setTimeout(r, 100));
  const done = (await app.inject(`/api/jobs/${job.id}`)).json().job;
  assert.strictEqual(done.status, 'failed');
  assert.match(done.error, /source\(s\) failed/);
  await app.close();
});

test('health answers without touching any upstream', async () => {
  const app = await buildApp({ logger: false, snapshots: createSnapshots(), startSources: false, persist: false });
  const res = await app.inject('/api/health');
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(res.json().app, 'pertal');
  await app.close();
});

test('topology: a finding does not break an edge, a dead host does', async () => {
  const app = await appWith(fakeSnapshots());
  const topo = (await app.inject('/api/topology')).json();
  const edge = (from, to) => topo.edges.find((e) => e.from === from && e.to === to);
  assert.strictEqual(edge('rpi', 'opti').status, 'ok', 'opti has a critical finding but is up');
  assert.strictEqual(edge('opti', 'noblenumbat').status, 'crit', 'noblenumbat is not answering');
  await app.close();
});

test('metrics: last hour comes from the in-memory ring; bad input is a 4xx', async () => {
  const app = await appWith(fakeSnapshots());
  app.history.observe('opti', { t: 100, cpu_pct: 5, mem_pct: 40 });
  app.history.observe('opti', { t: 115, cpu_pct: 7, mem_pct: 41 });
  const ok = (await app.inject('/api/metrics/opti?metric=cpu_pct&range=1h')).json();
  assert.deepStrictEqual(ok.points, [[100, 5], [115, 7]]);
  assert.strictEqual((await app.inject('/api/metrics/opti?metric=nope&range=1h')).statusCode, 400);
  assert.strictEqual((await app.inject('/api/metrics/opti?metric=cpu_pct&range=5y')).statusCode, 400);
  assert.strictEqual((await app.inject('/api/metrics/android?metric=cpu_pct')).statusCode, 404);
  await app.close();
});

test('logs: names are validated before anything is sent to an agent', async () => {
  const app = await appWith(fakeSnapshots());
  assert.strictEqual((await app.inject('/api/logs/opti/..%2Fetc')).statusCode, 400);
  assert.strictEqual((await app.inject('/api/logs/android/x')).statusCode, 404);
  await app.close();
});

test('ics: time zones, all-day events, weekly recurrence and EXDATE', () => {
  const { eventsBetween } = require('../lib/ics');
  const ics = [
    'BEGIN:VCALENDAR',
    'BEGIN:VEVENT', 'DTSTART;TZID=America/New_York:20260928T090000', 'DTEND;TZID=America/New_York:20260928T093000',
    'SUMMARY:Standup', 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE', 'EXDATE;TZID=America/New_York:20260930T090000', 'END:VEVENT',
    'BEGIN:VEVENT', 'DTSTART;VALUE=DATE:20260929', 'DTEND;VALUE=DATE:20260930', 'SUMMARY:Trash day', 'END:VEVENT',
    'BEGIN:VEVENT', 'DTSTART:20260929T230000Z', 'SUMMARY:Cancelled thing', 'STATUS:CANCELLED', 'END:VEVENT',
    'END:VCALENDAR',
  ].join('\r\n');
  const from = Date.parse('2026-09-28T00:00:00-04:00');
  const to = Date.parse('2026-10-06T00:00:00-04:00');
  const got = eventsBetween(ics, from, to).map((e) => `${e.title}@${e.start}`);
  assert.deepStrictEqual(got, [
    'Standup@2026-09-28T13:00:00.000Z',   // 09:00 EDT
    'Trash day@2026-09-29T00:00:00.000Z', // all-day
    'Standup@2026-10-05T13:00:00.000Z',   // Wed 30th excluded; next Monday
  ]);
});

test('streams guide: stale feed never claims live; only HLTV-listed streams are watchable', () => {
  const { buildGuide, cs2Summary } = require('../lib/streams-guide');
  const now = Math.floor(Date.now() / 1000);
  const day = {
    date: '2026-09-27', fetched_at: now, stale: false,
    matches: [
      { id: '1', event: 'IEM Chengdu', team1: 'Vitality', team2: 'MOUZ', status: 'live', stars: 3, stream: { url: 'https://www.twitch.tv/eslcs', name: 'ESL CS' } },
      { id: '2', event: 'BLAST Premier Fall', team1: 'NAVI', team2: 'G2', status: 'live', stars: 2 }, // no stream listed
      { id: '3', event: 'Some Cup Qualifier', team1: 'A', team2: 'B', status: 'upcoming', stars: 0 },
    ],
  };
  const status = { version: '0.1.0', slots: [{ slot: 1, state: 'running', platform: 'twitch', channel: 'eslcs' }, { slot: 2, state: 'idle' }] };
  const vrs = { teams: ['Vitality', 'MOUZ', 'NAVI'] };

  const fresh = buildGuide({ status, presets: null, day, dayMeta: { ok: true }, vrs });
  const m1 = fresh.matches.find((m) => m.id === '1');
  const m2 = fresh.matches.find((m) => m.id === '2');
  assert.strictEqual(m1.status, 'live');
  assert.deepStrictEqual([m1.rank1, m1.rank2], [1, 2]);
  assert.strictEqual(m1.watching_slot, 1, 'already playing in slot 1');
  assert.strictEqual(m2.channel, null, 'no organizer fallback: BLAST event without a listed stream is not watchable');
  assert.ok(m1.premier && !fresh.matches.find((m) => m.id === '3').premier);

  const stale = buildGuide({ status, presets: null, day: { ...day, fetched_at: now - 3600 }, dayMeta: { ok: true }, vrs });
  assert.ok(stale.matches.every((m) => m.status !== 'live'), 'a stale feed degrades live to unknown');

  const card = cs2Summary(day);
  assert.deepStrictEqual(card.matches.map((m) => m.id), ['1', '2'], 'unstarred upcoming match is left off the card');
});
