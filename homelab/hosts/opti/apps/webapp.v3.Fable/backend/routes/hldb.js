// Proxy to homelab-db on opti (:9100) — the queryable index of every collector report,
// host fact, container change and runbook. Same shape as lib/controls.js's dispatcher
// proxy: the token stays server-side, the browser only ever sees this origin.
//
// Everything here is read-only by construction — the upstream opens the database with a
// read-only file descriptor, so there is no write path to expose in the first place.
//
// Degradation still matters here, but the shape of it changed on 2026-09-10. This used
// to be a cross-host dependency — dashboard on rpi, database on opti — so opti could
// vanish while the page stayed up. Both now live on opti, so a whole-host outage takes
// the page with it and no amount of graceful degradation is visible. What remains, and
// is still worth handling honestly, is the narrower set: homelab-db stopped or
// restarting while its host is fine, a missing token, a query that outruns its deadline.
// Those answer 503 with a reason rather than throwing, so callers can say "unavailable"
// instead of showing an error boundary.
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

  // ── Docs ──────────────────────────────────────────────────────────────────
  // homelab-db indexes every runbook, rule, skill and generated report into a `docs`
  // table (~248 rows, split by section, with an FTS index beside it). That makes it the
  // one place where the written architecture and the measured architecture sit together,
  // which is exactly why Peter asked for the documentation to be consolidated there.
  //
  // The upstream has no docs endpoint of its own — only full-text search, which returns
  // ranked snippets rather than readable pages. Rather than add one upstream, these two
  // routes compose read-only SELECTs here and send them through the same guarded /query
  // path everything else uses. The SQL is written server-side and every value is bound as
  // a parameter, so nothing a browser sends is ever concatenated into a statement.
  // /api/query answers columnar — { columns: [...], rows: [[...], ...] } — which is right
  // for the SQL console but wrong for everything else. Zip it once here so the docs routes
  // and their callers deal in ordinary objects.
  const objectify = (data) => {
    const cols = data?.columns || [];
    return (data?.rows || []).map((row) => Object.fromEntries(cols.map((c, i) => [c, row[i]])));
  };

  const runQuery = async (reply, sql, params) => {
    if (!HOMELAB_DB_URL) {
      return reply.code(503).send({
        ok: false, error: 'homelab-db not configured',
        hint: 'Set HOMELAB_DB_URL (and HL_DB_TOKEN) in the webapp service env.',
      });
    }
    const headers = HL_DB_TOKEN ? { Authorization: `Bearer ${HL_DB_TOKEN}` } : undefined;
    try {
      return await proxyJson(HOMELAB_DB_URL, 'POST', '/api/query', { sql, params }, TIMEOUT_MS, headers);
    } catch (err) {
      reply.code(503).send({
        ok: false, error: `homelab-db unreachable: ${err.message}`,
        hint: 'homelab-db.service may be stopped.',
      });
      return null;
    }
  };

  // The shelf: one row per document, sections collapsed, newest source first. Deliberately
  // does NOT carry content — 248 documents of prose is megabytes, and the list view only
  // ever renders titles.
  app.get('/docs', async (req, reply) => {
    const res = await runQuery(reply, `
      SELECT path,
             source_kind,
             MAX(COALESCE(NULLIF(title, ''), path)) AS title,
             COUNT(*)        AS sections,
             SUM(LENGTH(content)) AS bytes,
             MAX(mtime)      AS mtime
      FROM docs
      GROUP BY path, source_kind
      ORDER BY source_kind, path
    `, []);
    if (!res) return undefined;
    const rows = objectify(res.data);
    return reply.code(res.status).send({ ok: true, count: rows.length, docs: rows });
  });

  // One document, whole. Sections come back in stored order and the frontend concatenates
  // them; `path` is bound, never interpolated.
  app.get('/docs/*', async (req, reply) => {
    const path = req.params['*'];
    if (!path) return reply.code(400).send({ ok: false, error: 'path is required' });
    const res = await runQuery(reply, `
      SELECT path, source_kind, title, section, content, mtime
      FROM docs WHERE path = ? ORDER BY id
    `, [path]);
    if (!res) return undefined;
    const rows = objectify(res.data);
    if (!rows.length) return reply.code(404).send({ ok: false, error: `no document at ${path}` });
    return reply.code(res.status).send({
      ok: true,
      path,
      source_kind: rows[0].source_kind,
      title: rows[0].title || path,
      mtime: rows.reduce((m, r) => (r.mtime > m ? r.mtime : m), ''),
      sections: rows.map((r) => ({ section: r.section, content: r.content })),
    });
  });

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
