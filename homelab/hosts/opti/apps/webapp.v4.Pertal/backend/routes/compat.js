// v3-compatible read APIs that other parts of the homelab call on the dashboard's
// port, ported from v3.Fable so they keep answering after Pertal takes over :8443:
//
//   GET /api/uptime           Uptime Kuma monitors   (homelab-db ingest: uptime-kuma)
//   GET /api/pihole/summary   Pi-hole v6 stats       (homelab-db ingest: pihole-stats)
//   GET /api/pihole/blocking  blocking state
//   GET /api/pihole/top       most-blocked domains
//
// Same response shapes as v3 (homelab-db parses them). Read-only by construction: no
// route here can change Kuma or Pi-hole. Env: KUMA_URL, KUMA_API_KEY, PIHOLE_URL,
// PIHOLE_WEB_PASSWORD (set for the pertal service in docker-compose.apps.yml).
'use strict';

const KUMA_URL = process.env.KUMA_URL || 'http://192.168.1.6:3001';
const KUMA_API_KEY = process.env.KUMA_API_KEY || '';
const PIHOLE_URL = (process.env.PIHOLE_URL || 'http://192.168.1.10').replace(/\/$/, '');
const PIHOLE_PASSWORD = process.env.PIHOLE_WEB_PASSWORD || '';

// ── Uptime Kuma: its uk1_ API key unlocks exactly GET /metrics (Prometheus text). ──
const LINE_RE = /^(monitor_status|monitor_response_time)\{([^}]*)\}\s+(-?[\d.]+)$/;
const NAME_RE = /monitor_name="((?:[^"\\]|\\.)*)"/;
const TYPE_RE = /monitor_type="((?:[^"\\]|\\.)*)"/;
const KUMA_STATUS = { 0: 'down', 1: 'up', 2: 'pending', 3: 'maintenance' };

function parseKuma(text) {
  const monitors = new Map();
  for (const line of text.split('\n')) {
    const m = LINE_RE.exec(line.trim());
    if (!m) continue;
    const name = NAME_RE.exec(m[2])?.[1];
    if (!name) continue;
    const entry = monitors.get(name) || { name, type: TYPE_RE.exec(m[2])?.[1] || null };
    if (m[1] === 'monitor_status') entry.status = KUMA_STATUS[Number(m[3])] || 'unknown';
    else entry.ms = m[3] === '-1' ? null : Math.round(Number(m[3]));
    monitors.set(name, entry);
  }
  const list = [...monitors.values()].sort((a, b) => a.name.localeCompare(b.name));
  const count = (s) => list.filter((x) => x.status === s).length;
  return {
    ok: true, total: list.length, up: count('up'), down: count('down'),
    pending: count('pending'), maintenance: count('maintenance'),
    monitors: list, checked_at: new Date().toISOString(),
  };
}

// ── Pi-hole v6: POST /api/auth → sid, call with X-FTL-SID, ALWAYS DELETE /api/auth.
// v6 caps concurrent sessions; a leaked one eventually locks every client out. ──
async function fjson(url, opts = {}) {
  const res = await fetch(url, { ...opts, signal: AbortSignal.timeout(8000) });
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch (_) { /* non-JSON error body */ }
  if (!res.ok) {
    const err = new Error(data?.error?.message || `Pi-hole HTTP ${res.status}`);
    err.statusCode = res.status;
    throw err;
  }
  return data;
}

async function withSession(fn) {
  if (!PIHOLE_PASSWORD) {
    const err = new Error('PIHOLE_WEB_PASSWORD not configured for the pertal container');
    err.statusCode = 503;
    throw err;
  }
  const auth = await fjson(`${PIHOLE_URL}/api/auth`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: PIHOLE_PASSWORD }),
  });
  const sid = auth?.session?.sid;
  if (!sid) {
    const err = new Error('Pi-hole auth returned no session (session cap? wrong password?)');
    err.statusCode = 502;
    throw err;
  }
  const H = { 'X-FTL-SID': sid };
  try {
    return await fn(H);
  } finally {
    try { await fetch(`${PIHOLE_URL}/api/auth`, { method: 'DELETE', headers: H, signal: AbortSignal.timeout(4000) }); } catch (_) { /* best effort */ }
  }
}

const blockingOf = (b) => ({ enabled: b.blocking === 'enabled' || b.blocking === true, timer: b.timer ?? null });

const PIHOLE_CACHE_MS = 30_000; // keeps repeated reads from churning auth sessions
let piholeCache = { at: 0, data: null };

module.exports = async function compatRoutes(app) {
  app.get('/api/uptime', async (req, reply) => {
    if (!KUMA_API_KEY) return reply.code(503).send({ ok: false, error: 'KUMA_API_KEY not configured' });
    try {
      const r = await fetch(`${KUMA_URL}/metrics`, {
        headers: { Authorization: `Basic ${Buffer.from(`:${KUMA_API_KEY}`).toString('base64')}` },
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) return reply.code(502).send({ ok: false, error: `Kuma /metrics HTTP ${r.status}` });
      return parseKuma(await r.text());
    } catch (e) {
      return reply.code(502).send({ ok: false, error: `Kuma unreachable: ${e.message}` });
    }
  });

  app.get('/api/pihole/summary', async (req, reply) => {
    if (Date.now() - piholeCache.at < PIHOLE_CACHE_MS && piholeCache.data) return piholeCache.data;
    try {
      const data = await withSession(async (H) => {
        const [summary, blocking] = await Promise.all([
          fjson(`${PIHOLE_URL}/api/stats/summary`, { headers: H }),
          fjson(`${PIHOLE_URL}/api/dns/blocking`, { headers: H }).catch(() => null),
        ]);
        const q = summary?.queries || {};
        return {
          dns_queries_today: q.total ?? null,
          ads_blocked_today: q.blocked ?? null,
          ads_percentage_today: q.percent_blocked ?? null,
          unique_domains: q.unique_domains ?? null,
          queries_forwarded: q.forwarded ?? null,
          queries_cached: q.cached ?? null,
          unique_clients: (typeof summary?.clients === 'object' ? summary.clients?.active : null) ?? null,
          gravity_domains: (typeof summary?.gravity === 'object' ? summary.gravity?.domains_being_blocked : null) ?? null,
          blocking: blocking ? blockingOf(blocking) : null,
          fetched_at: new Date().toISOString(),
        };
      });
      piholeCache = { at: Date.now(), data };
      return data;
    } catch (e) {
      return reply.code(e.statusCode || 502).send({ error: e.message });
    }
  });

  app.get('/api/pihole/blocking', async (req, reply) => {
    try {
      return blockingOf(await withSession((H) => fjson(`${PIHOLE_URL}/api/dns/blocking`, { headers: H })));
    } catch (e) {
      return reply.code(e.statusCode || 502).send({ error: e.message });
    }
  });

  app.get('/api/pihole/top', async (req, reply) => {
    const count = Math.min(Math.max(parseInt(req.query.count, 10) || 10, 1), 25);
    try {
      return await withSession(async (H) => {
        const d = await fjson(`${PIHOLE_URL}/api/stats/top_domains?blocked=true&count=${count}`, { headers: H });
        return { domains: (d?.domains || []).map((x) => ({ domain: x.domain, count: x.count })), fetched_at: new Date().toISOString() };
      });
    } catch (e) {
      return reply.code(e.statusCode || 502).send({ error: e.message });
    }
  });
};

module.exports.parseKuma = parseKuma;
