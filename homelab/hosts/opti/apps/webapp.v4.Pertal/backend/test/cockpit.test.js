'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
process.env.ARCH_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'pertal-cockpit-test-'));
process.env.PERTAL_ACTIONS = 'dry';
const buildApp = require('../app');
const { createSnapshots } = require('../lib/snapshots');
const { registerCockpitSources, parseManifests } = require('../sources/cockpit');
const manifests = { shell: {}, system: { menu: { index: { label: 'Overview' },
  services: { label: 'Services' }, '../bad': { label: 'Unsafe' } }, tools: { terminal: { label: 'Terminal' } } }, metrics: {} };
let mode = 'ok', requests = 0, server, upstream;
test.before(async () => {
  server = http.createServer((req, res) => {
    requests++;
    assert.equal(req.url, '/cp-opti/cockpit/@localhost/manifests.json');
    res.setHeader('Content-Type', 'application/json');
    if (mode === 'broken') { res.writeHead(503); return res.end('{}'); }
    if (mode === 'login') return res.end('<html>Sign in</html>');
    if (mode === 'malformed') return res.end('{}');
    if (mode === 'redirect') { res.writeHead(302, { Location: '/' }); return res.end(); }
    if (mode === 'slow') return;
    res.end(JSON.stringify(manifests));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  upstream = `http://127.0.0.1:${server.address().port}`;
});
test.after(async () => { server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); });

test('manifest pages use safe package/entry paths', () => {
  const parsed = parseManifests(manifests);
  assert.deepEqual(parsed.pages.map((p) => p.path), ['system', 'system/services', 'system/terminal', 'metrics']);
  for (const invalid of [null, [], {}, { shell: {}, system: [] }]) assert.throws(() => parseManifests(invalid));
});

test('Console reads memory through loading, failure and recovery, and stays quiet', async () => {
  process.env.PERTAL_COCKPIT = '1';
  const snaps = createSnapshots();
  registerCockpitSources(snaps, [{ id: 'opti', label: 'opti', console: { root: '/cp-opti', upstream } }]);
  const app = await buildApp({ snapshots: snaps, startSources: false, persist: false, logger: false });
  try {
    const get = async () => (await app.inject('/api/console')).json();
    const before = requests;
    const loading = await get();
    assert.equal(loading.enabled, true);
    assert.equal(loading.hosts[0].ok, null);
    assert.equal(loading.hosts[0].stale, true);
    assert.equal(loading.hosts.length, 3);
    assert.equal(requests, before, 'GET must not fetch an upstream');
    mode = 'ok'; await snaps.refresh('cockpit:opti');
    const healthy = (await get()).hosts[0];
    assert.equal(healthy.ok, true); assert.equal(healthy.stale, false);
    assert.ok(healthy.fetched_at); assert.ok(healthy.pages.some((p) => p.path === 'system/terminal'));
    for (const failure of ['broken', 'login', 'malformed', 'redirect']) {
      mode = failure; await snaps.refresh('cockpit:opti');
      const failed = (await get()).hosts[0];
      assert.equal(failed.ok, false); assert.ok(failed.error);
      assert.equal(failed.fetched_at, healthy.fetched_at);
      app.pertal.rebuild();
      assert.ok(!app.pertal.state.summary.issues.some((i) => i.source === 'cockpit:opti'));
    }
    mode = 'ok'; await snaps.refresh('cockpit:opti');
    assert.equal((await get()).hosts[0].ok, true);
    const count = requests; await get(); assert.equal(requests, count);
  } finally { await app.close(); delete process.env.PERTAL_COCKPIT; }
});

test('disabled registration and stale snapshots are explicit', async () => {
  delete process.env.PERTAL_COCKPIT;
  const disabled = await buildApp({ startSources: false, persist: false, logger: false });
  assert.equal((await disabled.inject('/api/console')).json().enabled, false);
  assert.ok(!disabled.snapshots.keys().some((key) => key.startsWith('cockpit:')));
  await disabled.close();
  const fake = createSnapshots();
  fake.register({ key: 'cockpit:opti', intervalMs: 60_000, staleAfterMs: 1, fetch: async () => parseManifests(manifests) });
  await fake.refresh('cockpit:opti');
  await new Promise((resolve) => setTimeout(resolve, 5));
  process.env.PERTAL_COCKPIT = '1';
  const stale = await buildApp({ snapshots: fake, startSources: false, persist: false, logger: false });
  assert.equal((await stale.inject('/api/console')).json().hosts[0].stale, true);
  await stale.close(); delete process.env.PERTAL_COCKPIT;
});

test('source deadlines abort a stalled upstream', async () => {
  mode = 'slow';
  const snaps = createSnapshots();
  const bounded = { register(def) { snaps.register({ ...def, timeoutMs: 30 }); } };
  registerCockpitSources(bounded, [{ id: 'opti', label: 'opti', console: { root: '/cp-opti', upstream } }]);
  const result = await snaps.refresh('cockpit:opti');
  assert.equal(result.meta.ok, false); assert.match(result.meta.error, /timed out/);
  mode = 'ok';
});
