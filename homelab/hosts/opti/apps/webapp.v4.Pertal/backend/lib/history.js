// Metrics history. Two stores, no new database:
//   - the last hour at 15s comes from Pertal's own ring (fed by the vitals snapshots)
//   - 24h and longer come from homelab-db (60s samples for 30 days, hourly before that),
//     read on demand and cached for a minute
'use strict';

const RING_MAX = 240; // 1h at 15s
const METRICS = ['cpu_pct', 'mem_pct', 'load1', 'temp_c', 'rx_bps', 'tx_bps'];
const RANGES = { '1h': null, '24h': 1, '7d': 7, '30d': 30, '90d': 90 };
const CACHE_MS = 60_000;

function createHistory({ hldbUrl = process.env.HOMELAB_DB_URL || '', hldbToken = process.env.HL_DB_TOKEN || '' } = {}) {
  const rings = new Map(); // host -> [{t, ...metrics}]
  const cache = new Map(); // `${host}|${metric}|${days}` -> {at, value}

  // Called for every vitals snapshot refresh.
  function observe(host, derived) {
    if (!derived || typeof derived.t !== 'number') return;
    const ring = rings.get(host) ?? [];
    if (ring.length && ring[ring.length - 1].t === derived.t) return;
    const row = { t: derived.t };
    for (const m of METRICS) row[m] = derived[m] ?? null;
    ring.push(row);
    if (ring.length > RING_MAX) ring.splice(0, ring.length - RING_MAX);
    rings.set(host, ring);
  }

  async function fromHldb(host, metric, days) {
    if (!hldbUrl) throw new Error('HOMELAB_DB_URL not set');
    const key = `${host}|${metric}|${days}`;
    const hit = cache.get(key);
    if (hit && Date.now() - hit.at < CACHE_MS) return hit.value;
    const url = `${hldbUrl}/api/metrics?metric=${encodeURIComponent(metric)}&host=${encodeURIComponent(host)}&days=${days}`;
    const res = await fetch(url, {
      headers: hldbToken ? { Authorization: `Bearer ${hldbToken}` } : {},
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) throw new Error(`homelab-db: HTTP ${res.status}`);
    const d = await res.json();
    const series = (d.series || []).find((s) => s.host === host) || { points: [] };
    const value = {
      source: d.source || 'homelab-db',
      points: series.points.map((p) => [Math.round(Date.parse(p.at) / 1000), p.value ?? p.avg ?? null]),
    };
    cache.set(key, { at: Date.now(), value });
    return value;
  }

  async function series(host, metric, range) {
    if (!METRICS.includes(metric)) throw Object.assign(new Error(`unknown metric '${metric}'`), { statusCode: 400 });
    if (!(range in RANGES)) throw Object.assign(new Error(`range must be one of ${Object.keys(RANGES).join(', ')}`), { statusCode: 400 });
    if (range === '1h') {
      return { source: 'pertal (15s)', points: (rings.get(host) || []).map((r) => [r.t, r[metric]]) };
    }
    return fromHldb(host, metric, RANGES[range]);
  }

  return { observe, series, METRICS, RANGES: Object.keys(RANGES) };
}

module.exports = { createHistory };
