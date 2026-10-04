// Read endpoints behind specific pages: metrics, logs, launchpad, reports, topology.
//
// Two of these (metrics beyond 1h, logs) read an upstream on demand — history and log
// lines are too big to poll into memory. They are the only exceptions to "no request
// waits on an upstream", and each carries a hard timeout and a plain error body.
'use strict';
const { AGENT_HOSTS, HOSTS } = require('../lib/hosts');
const { agentFetch } = require('../lib/agent-client');
const { LINK_GROUPS } = require('../lib/links');
const { buildTopology } = require('../lib/topology');
const { cs2Summary } = require('../lib/streams-guide');

const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/;
const SINCE_RE = /^\d{1,4}[smh]$/;

module.exports = async function viewRoutes(app) {
  app.get('/console', async () => ({
    enabled: app.cockpitEnabled,
    hosts: HOSTS.filter((host) => host.console).map((host) => {
      const snapshot = app.snapshots.get(`cockpit:${host.id}`);
      return { id: host.id, root: host.console.root,
        ok: snapshot?.meta.ok ?? null, error: snapshot?.meta.error ?? null,
        fetched_at: snapshot?.meta.fetched_at ?? null, stale: snapshot?.meta.stale ?? true,
        pages: snapshot?.data?.pages ?? [] };
    }),
  }));
  // GET /api/metrics/:host?metric=cpu_pct&range=1h|24h|7d|30d|90d
  app.get('/metrics/:host', async (req, reply) => {
    const { host } = req.params;
    if (!AGENT_HOSTS[host]) return reply.code(404).send({ error: `no metrics for '${host}'` });
    try {
      const s = await app.history.series(host, String(req.query.metric || 'cpu_pct'), String(req.query.range || '1h'));
      return { host, metric: req.query.metric || 'cpu_pct', range: req.query.range || '1h', ...s };
    } catch (err) {
      return reply.code(err.statusCode || 502).send({ error: err.message });
    }
  });

  // GET /api/logs/:host/:container?tail=300&since=1h — via the agent (v0.8.0, token-gated).
  app.get('/logs/:host/:container', async (req, reply) => {
    const { host, container } = req.params;
    const cfg = AGENT_HOSTS[host];
    if (!cfg) return reply.code(404).send({ error: `no agent on '${host}'` });
    if (!NAME_RE.test(container)) return reply.code(400).send({ error: 'bad container name' });
    const tail = Math.max(1, Math.min(2000, Number(req.query.tail) || 300));
    const since = req.query.since && SINCE_RE.test(req.query.since) ? `&since=${req.query.since}` : '';
    try {
      const r = await agentFetch(`${cfg.agent}/logs?container=${encodeURIComponent(container)}&tail=${tail}${since}`, { timeoutMs: 12_000 });
      if (r.status === 401 || r.status === 403) {
        return reply.code(502).send({ error: 'the agent refused: Pertal has no agent token here (expected in dev; set HL_ARCH_INGEST_TOKEN in prod)' });
      }
      if (!r.ok) return reply.code(502).send({ error: r.data?.error || `agent answered HTTP ${r.status}` });
      return r.data;
    } catch (err) {
      return reply.code(504).send({ error: `no answer from the agent on ${host}: ${err.message}` });
    }
  });

  app.get('/links', async () => {
    const probe = app.snapshots.get('links');
    // A link is up if ANY of its probe targets answered (see lib/links.js).
    const reach = (check) => {
      const results = [].concat(check || []).map((c) => probe?.data?.[c]).filter(Boolean);
      return results.find((r) => r.up) ?? results[0] ?? null;
    };
    return {
      groups: LINK_GROUPS.map((g) => ({
        group: g.group,
        links: g.links.map((l) => ({ ...l, check: undefined, reach: l.check ? reach(l.check) : null })),
      })),
      checked_at: probe?.meta?.fetched_at ?? null,
    };
  });

  app.get('/reports', async () => {
    const r = app.snapshots.get('hldb:reports');
    const s = app.snapshots.get('hldb:status');
    return {
      hosts: r?.data ?? {},
      doctor: s?.data?.doctor ?? null,
      services: s?.data?.services ?? [],
      fetched_at: r?.meta?.fetched_at ?? null,
      error: r?.meta?.ok === false ? r.meta.error : null,
    };
  });

  app.get('/topology', async () => buildTopology(app.pertal.state.resources));

  // Status-page extras. Each is its own snapshot, so one dead feed greys one card.
  app.get('/extras', async () => {
    const pick = (key) => {
      const s = app.snapshots.get(key);
      return s ? { data: s.data, ok: s.meta.ok, error: s.meta.error, fetched_at: s.meta.fetched_at, stale: s.meta.stale } : null;
    };
    const day = pick('hltv:day');
    return {
      weather: pick('extras:weather'),
      nba: pick('extras:nba'),
      cs2: day && { ...day, data: cs2Summary(day.data) },
      calendar: pick('extras:calendar'), // null = not configured (PERTAL_CALENDAR_ICS)
    };
  });
};
