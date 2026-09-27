// Asset Library: the assets:server source and /api/assets, against a fake asset server on
// an ephemeral local port. No LAN, no disk writes outside a temp dir.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const os = require('os');
const fs = require('fs');
const path = require('path');

process.env.ARCH_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'pertal-assets-test-'));
process.env.PERTAL_ACTIONS = 'dry';

let mode = 'ok';
const seen = [];
const fake = http.createServer((req, res) => {
  seen.push(req.url);
  const send = (code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)); };
  if (mode === 'broken') return send(500, {});
  const u = new URL(req.url, 'http://fake');
  if (u.pathname === '/health') return send(200, { ok: true, service: 'asset-server', version: '1.0.0', roots: ['DND5E'], index: { files: 3 } });
  if (u.pathname === '/api/list') {
    const p = u.searchParams.get('path');
    return p === 'missing' ? send(404, { error: 'no such folder' }) : send(200, { path: p, dirs: [], files: [] });
  }
  if (u.pathname === '/api/search') return send(200, { q: u.searchParams.get('q'), total: 0, results: [] });
  return send(404, { error: 'not found' });
});

let app, snaps;
test.before(async () => {
  await new Promise((r) => fake.listen(0, '127.0.0.1', r));
  process.env.ASSET_SERVER_URL = `http://127.0.0.1:${fake.address().port}`;
  const buildApp = require('../app');
  const { createSnapshots } = require('../lib/snapshots');
  const { registerAssetSources } = require('../sources/assets');
  snaps = createSnapshots();
  registerAssetSources(snaps);
  app = await buildApp({ logger: false, snapshots: snaps, startSources: false, persist: false });
  await app.ready();
});
test.after(async () => {
  await app?.close();
  fake.closeAllConnections();
  await new Promise((r) => fake.close(r));
});

test('cleanPath keeps obviously bad paths on opti', () => {
  const { cleanPath } = require('../routes/assets');
  assert.strictEqual(cleanPath(undefined), '');
  assert.strictEqual(cleanPath('/DND5E//characters/'), 'DND5E/characters');
  for (const bad of ['..', 'a/../b', '.git', 'C:/x', 'a\\b', 'x\u0000y', 'q?', 'x'.repeat(1100)]) {
    assert.strictEqual(cleanPath(bad), null, bad);
  }
});

test('status: online with the server health, from the snapshot', async () => {
  mode = 'ok';
  await snaps.refresh('assets:server');
  const s = (await app.inject('/api/assets/status')).json();
  assert.strictEqual(s.online, true);
  assert.strictEqual(s.server.version, '1.0.0');
  assert.deepStrictEqual(s.server.roots, ['DND5E']);
  assert.ok(s.last_seen_at);
});

test('list and search are relayed; bad input never reaches ptm', async () => {
  mode = 'ok';
  seen.length = 0;
  const list = await app.inject('/api/assets/list?path=DND5E%2Fcharacters%2Fraces');
  assert.strictEqual(list.statusCode, 200);
  assert.strictEqual(list.json().path, 'DND5E/characters/races');
  assert.strictEqual((await app.inject('/api/assets/list?path=missing')).statusCode, 404);
  const search = await app.inject('/api/assets/search?q=goblin%20glb');
  assert.strictEqual(search.json().q, 'goblin glb');
  const before = seen.length;
  assert.strictEqual((await app.inject('/api/assets/list?path=..%2F..%2Fwindows')).statusCode, 400);
  assert.strictEqual((await app.inject('/api/assets/search?q=')).statusCode, 400);
  assert.strictEqual(seen.length, before, 'refused requests must not be forwarded');
});

test('offline is an answer, not a failing source', async () => {
  mode = 'broken';
  const s1 = await snaps.refresh('assets:server');
  assert.strictEqual(s1.meta.ok, true, 'the snapshot itself never fails');
  assert.strictEqual(s1.data.online, false);
  assert.match(s1.data.error, /HTTP 500/);
  assert.ok(s1.data.last_seen_at, 'keeps when it was last seen');
  assert.strictEqual(s1.data.health.version, '1.0.0', 'keeps what it last looked like');

  fake.closeAllConnections();
  await new Promise((r) => fake.close(r));
  const s2 = await snaps.refresh('assets:server');
  assert.strictEqual(s2.meta.ok, true);
  assert.strictEqual(s2.data.online, false);
  assert.match(s2.data.error, /ptm/);
  const list = await app.inject('/api/assets/list?path=DND5E');
  assert.strictEqual(list.statusCode, 503);
  assert.strictEqual(list.json().offline, true);
  const summary = (await app.inject('/api/state')).json().summary;
  assert.ok(!summary.issues.some((i) => i.source === 'assets:server'), 'no Status-page issue for an offline PC');
});
