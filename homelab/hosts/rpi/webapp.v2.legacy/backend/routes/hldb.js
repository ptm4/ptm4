// Proxy to homelab-db on opti (:9100) — the queryable index of every collector report,
// host fact, container change and runbook. Same shape as lib/controls.js's dispatcher
// proxy: the token stays server-side, the browser only ever sees this origin.
//
// Everything here is read-only by construction — the upstream opens the database with a
// read-only file descriptor, so there is no write path to expose in the first place.
//
// Degradation matters more than usual for these routes: opti is a single point of failure
// for storage, and the dashboard runs on rpi. When opti is down the widgets must render
// an honest "unavailable" state rather than an error boundary, so an unreachable upstream
// answers 503 with a reason rather than throwing.
const { proxyJson } = require('../lib/upstream');

const HOMELAB_DB_URL = process.env.HOMELAB_DB_URL || '';
const HL_DB_TOKEN = process.env.HL_DB_TOKEN || '';

// The upstream caps its own queries at 15s; stay above that so a slow-but-succeeding
// query returns its result instead of being cut off here, and well under nginx's 60s.
const TIMEOUT_MS = 20000;

async function upstream(reply, urlPath) {
  if (!HOMELAB_DB_URL) {
    return reply.code(503).send({
      ok: false,
      error: 'homelab-db not configured',
      hint: 'Set HOMELAB_DB_URL (and HL_DB_TOKEN) in the webapp service env.',
    });
  }
  const headers = HL_DB_TOKEN ? { Authorization: `Bearer ${HL_DB_TOKEN}` } : undefined;
  try {
    const { status, data } = await proxyJson(
      HOMELAB_DB_URL, 'GET', urlPath, undefined, TIMEOUT_MS, headers,
    );
    return reply.code(status).send(data);
  } catch (err) {
    return reply.code(503).send({
      ok: false,
      error: `homelab-db unreachable: ${err.message}`,
      hint: 'opti may be down, or homelab-db.service stopped.',
    });
  }
}

const qs = (params) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const str = search.toString();
  return str ? `?${str}` : '';
};

module.exports = async function hldbRoutes(app) {
  // Liveness for the DB-health widget: distinguishes "configured and reachable" from
  // "not configured" from "opti is down", which are three different fixes.
  app.get('/health', async (req, reply) => {
    if (!HOMELAB_DB_URL) {
      return reply.send({ ok: false, configured: false, error: 'HOMELAB_DB_URL not set' });
    }
    try {
      const { status, data } = await proxyJson(HOMELAB_DB_URL, 'GET', '/healthz', undefined, 5000);
      return reply.send({ ok: status === 200, configured: true, upstream: data });
    } catch (err) {
      return reply.send({ ok: false, configured: true, error: err.message });
    }
  });

  app.get('/status', async (req, reply) => upstream(reply, '/api/status'));
  app.get('/dataplane', async (req, reply) => upstream(reply, '/api/dataplane'));

  app.get('/changes', async (req, reply) =>
    upstream(reply, `/api/changes${qs({ days: req.query.days, host: req.query.host })}`));

  app.get('/metrics', async (req, reply) =>
    upstream(reply, `/api/metrics${qs({
      metric: req.query.metric, host: req.query.host, days: req.query.days,
    })}`));

  app.get('/search', async (req, reply) =>
    upstream(reply, `/api/search${qs({ q: req.query.q || req.query.query, k: req.query.k })}`));

  app.get('/host/:host', async (req, reply) =>
    upstream(reply, `/api/host/${encodeURIComponent(req.params.host)}`));

  app.get('/schema', async (req, reply) => upstream(reply, '/api/schema'));

  // The Query page's console. Read-only is enforced by the upstream engine (a read-only
  // file descriptor plus a default-deny authorizer), not by anything here — this proxy
  // adds no SQL parsing of its own, because a second, weaker validator would only invite
  // drift from the real one. Every query lands in the upstream audit trail.
  app.post('/query', async (req, reply) => {
    if (!HOMELAB_DB_URL) {
      return reply.code(503).send({
        ok: false,
        error: 'homelab-db not configured',
        hint: 'Set HOMELAB_DB_URL (and HL_DB_TOKEN) in the webapp service env.',
      });
    }
    const headers = HL_DB_TOKEN ? { Authorization: `Bearer ${HL_DB_TOKEN}` } : undefined;
    try {
      const { status, data } = await proxyJson(
        HOMELAB_DB_URL, 'POST', '/api/query', req.body || {}, TIMEOUT_MS, headers,
      );
      return reply.code(status).send(data);
    } catch (err) {
      return reply.code(503).send({
        ok: false,
        error: `homelab-db unreachable: ${err.message}`,
        hint: 'opti may be down, or homelab-db.service stopped.',
      });
    }
  });
};
