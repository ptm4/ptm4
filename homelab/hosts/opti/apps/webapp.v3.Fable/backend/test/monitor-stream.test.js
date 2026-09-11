const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const register = require('../routes/monitor');

test('open Monitor streams renew sampler leases beyond 15 seconds and release on disconnect', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const routes = new Map();
  const bus = new EventEmitter();
  const leases = [];
  const app = {
    get: (path, handler) => routes.set(path, handler), post: () => {},
    monitor: { ensure: (host, interval) => leases.push({ host, interval }), rollup: () => ({ hosts: {} }) },
    monitorEvents: bus,
  };
  await register(app);
  const raw = new EventEmitter();
  raw.writeHead = () => {};
  raw.write = () => true;
  raw.end = () => { raw.writableEnded = true; };
  const req = { query: { hosts: 'opti,rpi,noblenumbat', interval: '2' }, raw: new EventEmitter() };
  routes.get('/events')(req, { hijack() {}, raw });
  assert.equal(leases.length, 3);
  for (let i = 0; i < 4; i++) t.mock.timers.tick(5000);
  assert.equal(leases.length, 15, 'leases still renewed after the idle grace would have expired');
  assert.ok(leases.every((lease) => lease.interval === 2000));
  raw.emit('close');
  t.mock.timers.tick(10000);
  assert.equal(leases.length, 15, 'disconnected clients no longer renew leases');
  for (const host of ['opti', 'rpi', 'noblenumbat']) assert.equal(bus.listenerCount(host), 0);
});
