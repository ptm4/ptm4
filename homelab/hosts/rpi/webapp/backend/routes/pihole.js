// Live Pi-hole v6 stats — talks to FTL directly rather than the 30-min network report.
//
// v6 auth contract (same dance as network-report.py's _PIHOLE_SH and the healthdigest
// bot): POST /api/auth {password} → session.sid, call with X-FTL-SID, then ALWAYS
// DELETE /api/auth. v6 caps concurrent sessions — a leaked session eventually locks out
// every other client, so release is in a finally and failures there are swallowed.
//
// The webapp container is on the compose "internal" bridge; Pi-hole is host-network on
// this same rpi, so we reach it via the host's LAN IP (PIHOLE_URL, default below).
// Requires PIHOLE_WEB_PASSWORD in the webapp environment.
//
// A 30s in-process cache keeps tile refreshes from churning auth sessions.
const PIHOLE_URL = (process.env.PIHOLE_URL || 'http://192.168.1.10').replace(/\/$/, '');
const PASSWORD = process.env.PIHOLE_WEB_PASSWORD || '';

const CACHE_MS = 30_000;
let cache = { at: 0, data: null };

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

// Run fn with an authenticated session, releasing it no matter what.
async function withSession(fn) {
  if (!PASSWORD) {
    const err = new Error('PIHOLE_WEB_PASSWORD not configured for the webapp container');
    err.statusCode = 503;
    throw err;
  }
  const auth = await fjson(`${PIHOLE_URL}/api/auth`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: PASSWORD }),
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
    try {
      await fetch(`${PIHOLE_URL}/api/auth`, {
        method: 'DELETE', headers: H, signal: AbortSignal.timeout(4000),
      });
    } catch (_) { /* best-effort release */ }
  }
}

const MAX_PAUSE_S = 3600;

module.exports = async function piholeRoutes(app) {
  // GET /api/pihole/summary — stats/summary + dns/blocking, flattened to the v5-style
  // keys the Home card has always read, plus { blocking: { enabled, timer } }.
  app.get('/summary', async (req, reply) => {
    if (Date.now() - cache.at < CACHE_MS && cache.data) return cache.data;
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
          blocking: blocking ? { enabled: blocking.blocking === 'enabled' || blocking.blocking === true, timer: blocking.timer ?? null } : null,
          fetched_at: new Date().toISOString(),
        };
      });
      cache = { at: Date.now(), data };
      return data;
    } catch (e) {
      return reply.code(e.statusCode || 502).send({ error: e.message });
    }
  });

  // GET /api/pihole/blocking — current blocking state + seconds left on any pause
  app.get('/blocking', async (req, reply) => {
    try {
      const b = await withSession((H) => fjson(`${PIHOLE_URL}/api/dns/blocking`, { headers: H }));
      return { enabled: b.blocking === 'enabled' || b.blocking === true, timer: b.timer ?? null };
    } catch (e) {
      return reply.code(e.statusCode || 502).send({ error: e.message });
    }
  });

  // GET /api/pihole/top?count=10 — most-blocked domains, for the widget's list and
  // as the source for one-click whitelisting below.
  app.get('/top', async (req, reply) => {
    const count = Math.min(Math.max(parseInt(req.query.count, 10) || 10, 1), 25);
    try {
      return await withSession(async (H) => {
        const d = await fjson(`${PIHOLE_URL}/api/stats/top_domains?blocked=true&count=${count}`, { headers: H });
        return {
          domains: (d?.domains || []).map((x) => ({ domain: x.domain, count: x.count })),
          fetched_at: new Date().toISOString(),
        };
      });
    } catch (e) {
      return reply.code(e.statusCode || 502).send({ error: e.message });
    }
  });

  // POST /api/pihole/allow { domain } — whitelist one domain (v6: POST /api/domains).
  // Replaces the "ssh in and run `pihole allow`" chore. Deliberately allow-only:
  // this endpoint can never add a block, so a mis-click cannot break resolution.
  app.post('/allow', {
    schema: {
      body: {
        type: 'object',
        required: ['domain'],
        properties: {
          domain: { type: 'string', minLength: 1, maxLength: 253, pattern: '^[a-zA-Z0-9._-]+$' },
          comment: { type: 'string', maxLength: 200 },
        },
      },
    },
  }, async (req, reply) => {
    const domain = req.body.domain.toLowerCase();
    try {
      const out = await withSession((H) => fjson(`${PIHOLE_URL}/api/domains/allow/exact`, {
        method: 'POST',
        headers: { ...H, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          domain,
          comment: req.body.comment || 'added from the homelab dashboard',
          enabled: true,
        }),
      }));
      cache = { at: 0, data: null };
      return { ok: true, domain, result: out ?? null };
    } catch (e) {
      return reply.code(e.statusCode || 502).send({ error: e.message, domain });
    }
  });

  // POST /api/pihole/blocking { enabled, seconds } — pause or resume ad blocking.
  //
  // Safety: a pause ALWAYS carries a timer, so blocking resumes on its own even if the
  // browser is closed or the resume click never happens. DNS itself is never touched —
  // Pi-hole is this LAN's only DNS *and* DHCP server, so nothing here can stop resolution;
  // pausing only disables blocklist filtering.
  app.post('/blocking', async (req, reply) => {
    const enabled = !!req.body?.enabled;
    const seconds = enabled ? null
      : Math.min(Math.max(parseInt(req.body?.seconds, 10) || 300, 30), MAX_PAUSE_S);
    try {
      const out = await withSession((H) => fjson(`${PIHOLE_URL}/api/dns/blocking`, {
        method: 'POST',
        headers: { ...H, 'Content-Type': 'application/json' },
        body: JSON.stringify({ blocking: enabled, timer: seconds }),
      }));
      cache = { at: 0, data: null };   // summary must not serve a stale blocking state
      return {
        enabled: out?.blocking === 'enabled' || out?.blocking === true,
        timer: out?.timer ?? seconds,
      };
    } catch (e) {
      return reply.code(e.statusCode || 502).send({ error: e.message });
    }
  });
};

// withSession is exported so future routes (quick-whitelist in P5.5) reuse the
// session-release discipline rather than re-implementing the auth dance.
module.exports.withSession = withSession;
module.exports.PIHOLE_URL = PIHOLE_URL;
