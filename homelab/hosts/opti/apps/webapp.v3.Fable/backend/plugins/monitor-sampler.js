// Shared two-second sampler for /monitor.  It is intentionally separate from the
// 30-second vitals poller: this stream only runs while a Monitor client holds a lease.
const fp = require('fastify-plugin');
const { AGENT_HOSTS } = require('../lib/hosts');

const TOKEN = process.env.HL_ARCH_INGEST_TOKEN || '';
const MAX_SAMPLES = 450;
const GRACE_MS = 15_000;
const MIN_INTERVAL_MS = 2_000;
const MAX_INTERVAL_MS = 10_000;
const FETCH_TIMEOUT_MS = 1_500;

const clampInterval = (n) => Math.max(MIN_INTERVAL_MS, Math.min(MAX_INTERVAL_MS, Number(n) || MIN_INTERVAL_MS));
const now = () => new Date().toISOString();

function delta(cur, prev, dt) {
  if (cur == null || prev == null || !dt || cur < prev) return null;
  return (cur - prev) / dt;
}

function cpuUsage(cur, prev) {
  if (!cur || !prev) return null;
  const total = Object.entries(cur).filter(([key]) => key !== 'guest' && key !== 'guest_nice').reduce((sum, [, value]) => sum + value, 0);
  const oldTotal = Object.entries(prev).filter(([key]) => key !== 'guest' && key !== 'guest_nice').reduce((sum, [, value]) => sum + value, 0);
  const dTotal = total - oldTotal;
  const idle = (cur.idle || 0) + (cur.iowait || 0) - (prev.idle || 0) - (prev.iowait || 0);
  if (dTotal <= 0 || idle < 0) return null;
  return Math.max(0, Math.min(100, Math.round((1 - idle / dTotal) * 1000) / 10));
}

function derive(raw, prev, timestamp) {
  const dt = prev ? Math.max(.001, raw.monotonic_s - prev.monotonic_s) : 0;
  const totalCpu = cpuUsage(raw.cpu?.counters, prev?.cpu?.counters);
  const core = Object.fromEntries(Object.entries(raw.cpu?.cores || {}).map(([name, row]) => [name, cpuUsage(row, prev?.cpu?.cores?.[name]) ]));
  const network = Object.fromEntries(Object.entries(raw.network || {}).map(([name, row]) => {
    const old = prev?.network?.[name];
    return [name, { ...row, rx_bps: delta(row.rx_bytes, old?.rx_bytes, dt), tx_bps: delta(row.tx_bytes, old?.tx_bytes, dt) }];
  }));
  const disks = Object.fromEntries(Object.entries(raw.disks || {}).map(([name, row]) => {
    const old = prev?.disks?.[name];
    return [name, { ...row, read_bps: delta(row.read_sectors, old?.read_sectors, dt) == null ? null : delta(row.read_sectors, old?.read_sectors, dt) * 512,
      write_bps: delta(row.write_sectors, old?.write_sectors, dt) == null ? null : delta(row.write_sectors, old?.write_sectors, dt) * 512,
      read_iops: delta(row.reads, old?.reads, dt), write_iops: delta(row.writes, old?.writes, dt),
      busy_pct: delta(row.busy_ms, old?.busy_ms, dt) == null ? null : Math.min(100, delta(row.busy_ms, old?.busy_ms, dt) / 10) }];
  }));
  const totalTicks = Object.values(raw.cpu?.counters || {}).reduce((sum, value) => sum + value, 0) - Object.values(prev?.cpu?.counters || {}).reduce((sum, value) => sum + value, 0);
  const pages = 4096;
  const processes = (raw.processes || []).map((row) => {
    const identity = `${raw.boot_id}:${row.pid}:${row.start_ticks}`;
    const old = prev?.processes?.find((item) => `${prev.boot_id}:${item.pid}:${item.start_ticks}` === identity);
    const ticks = (row.utime || 0) + (row.stime || 0) - ((old?.utime || 0) + (old?.stime || 0));
    return { ...row, identity, memory_bytes: (row.rss_pages || 0) * pages,
      cpu_pct: totalTicks > 0 && ticks >= 0 ? Math.round(ticks / totalTicks * 1000) / 10 : null,
      read_bps: delta(row.read_bytes, old?.read_bytes, dt), write_bps: delta(row.write_bytes, old?.write_bytes, dt) };
  });
  const power = (raw.power || []).map((row) => {
    const old = (prev?.power || []).find((item) => item.name === row.name);
    const rate = delta(row.energy_uj, old?.energy_uj, dt);
    return { ...row, watts: rate == null ? null : rate / 1_000_000 };
  });
  return { schema_version: raw.schema_version, measured_at: new Date(timestamp).toISOString(), measured_epoch_s: raw.measured_at,
    boot_id: raw.boot_id, cpu: { ...raw.cpu, total_pct: totalCpu, core_pct: core }, memory: raw.memory,
    network, disks, mounts: raw.mounts, temperatures: raw.temperatures, power, battery: raw.battery, gpu: raw.gpu, processes };
}

module.exports = fp(async function monitorSampler(app) {
  const state = Object.fromEntries(Object.keys(AGENT_HOSTS).map((host) => [host, { samples: [], raw: null, error: null, inFlight: false, leaseUntil: 0, intervalMs: MIN_INTERVAL_MS, capabilities: null, timer: null, lastAt: null }]));

  async function fetchAgent(host, path, init = {}) {
    const headers = { ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}), ...(init.headers || {}) };
    const res = await fetch(`${AGENT_HOSTS[host].base}${path}`, { ...init, headers, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `agent HTTP ${res.status}`);
    return body;
  }

  function rollup(hosts = Object.keys(state)) {
    const selected = hosts.filter((host) => state[host]);
    return { generated_at: now(), interval_s: MIN_INTERVAL_MS / 1000, hosts: Object.fromEntries(selected.map((host) => {
      const st = state[host];
      return [host, { latest: st.samples.at(-1) || null, count: st.samples.length, error: st.error, measured_at: st.lastAt, capabilities: st.capabilities }];
    })) };
  }

  async function tick(host, force = false) {
    const st = state[host];
    if (!st || st.inFlight || (!force && Date.now() > st.leaseUntil)) return;
    st.inFlight = true;
    try {
      const raw = await fetchAgent(host, '/monitor/snapshot');
      const sample = derive(raw, st.raw, Date.now());
      st.raw = raw;
      st.samples.push(sample);
      if (st.samples.length > MAX_SAMPLES) st.samples.splice(0, st.samples.length - MAX_SAMPLES);
      st.error = null;
      st.lastAt = sample.measured_at;
      app.monitorEvents.emit(host, sample);
    } catch (err) {
      st.error = err.message || String(err);
      app.monitorEvents.emit(host, { error: st.error, measured_at: st.lastAt, host });
    } finally { st.inFlight = false; }
  }

  function ensure(host, intervalMs = MIN_INTERVAL_MS) {
    const st = state[host];
    if (!st) return;
    st.leaseUntil = Math.max(st.leaseUntil, Date.now() + GRACE_MS);
    st.intervalMs = Math.min(st.intervalMs, clampInterval(intervalMs));
    if (!st.timer) {
      tick(host);
      st.timer = setInterval(() => {
        if (Date.now() > st.leaseUntil) { clearInterval(st.timer); st.timer = null; st.intervalMs = MIN_INTERVAL_MS; return; }
        tick(host);
      }, st.intervalMs);
      st.timer.unref();
    }
  }

  async function capabilities(host) {
    const st = state[host];
    if (!st) throw new Error(`unknown monitor host '${host}'`);
    if (!st.capabilities) st.capabilities = await fetchAgent(host, '/monitor/capabilities');
    return st.capabilities;
  }

  const { EventEmitter } = require('events');
  const bus = new EventEmitter();
  bus.setMaxListeners(200);
  app.decorate('monitorEvents', { emit: (host, sample) => bus.emit(host, sample), on: (host, fn) => bus.on(host, fn), off: (host, fn) => bus.off(host, fn) });
  app.decorate('monitor', { state, ensure, tick, rollup, capabilities, request: fetchAgent, hosts: Object.keys(state), maxSamples: MAX_SAMPLES, intervalMs: MIN_INTERVAL_MS });
}, { name: 'monitor-sampler', dependencies: ['event-bus'] });
