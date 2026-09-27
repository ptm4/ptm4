// JSON API. Every GET answers from memory; the only POST that does work is
// /actions/:kind, which starts a job and returns immediately.
'use strict';
const { ACTIONS, describe, startAction, ActionError } = require('../lib/actions');

const ACTOR_RE = /^[a-z0-9][a-z0-9 ._@-]{0,39}$/i;

module.exports = async function apiRoutes(app) {
  const { state, resource } = app.pertal;

  // Health: no upstream I/O at all, so the container healthcheck measures Pertal itself.
  app.get('/health', async () => ({
    status: 'ok', app: 'pertal', version: app.pertal.version, uptime_s: Math.round(process.uptime()),
  }));

  // Everything the UI needs for first paint, in one request.
  app.get('/state', async () => ({
    version: app.pertal.version,
    resources: state.resources,
    summary: state.summary,
    snapshots: app.snapshots.metas(),
    jobs: app.jobs.list({ limit: 20 }),
    activity: app.activity.list({ limit: 30 }),
    built_at: state.built_at,
    now: new Date().toISOString(),
  }));

  app.get('/resources', async () => ({ resources: state.resources, summary: state.summary, built_at: state.built_at }));

  app.get('/resources/:id', async (req, reply) => {
    const r = resource(req.params.id);
    if (!r) return reply.code(404).send({ error: `no resource '${req.params.id}'` });
    const children = r.type === 'host' ? state.resources.filter((x) => x.type === 'container' && x.host === r.id) : [];
    const jobs = app.jobs.list({ limit: 200 }).filter((j) => j.resource === r.id).slice(0, 20);
    const audit = app.jobs.audit({ days: 60, limit: 500 })
      .filter((j) => j.resource === r.id || (r.type === 'host' ? j.host === r.id && !j.resource : j.host === r.host && j.target === r.name))
      .slice(0, 30);
    return {
      resource: r,
      children,
      jobs,
      audit,
      activity: app.activity.list({ limit: 50, ...(r.type === 'host' ? { host: r.id } : { resource: r.id }) }),
    };
  });

  app.get('/snapshots', async () => ({ snapshots: app.snapshots.metas() }));
  app.get('/snapshots/:key', async (req, reply) => {
    const s = app.snapshots.get(req.params.key);
    if (!s) return reply.code(404).send({ error: `no snapshot '${req.params.key}'` });
    return s;
  });

  app.get('/actions', async () => ({ actions: Object.keys(ACTIONS).map(describe) }));

  // Start an action. Body: { resource: "<id>", confirm?: bool, params?: {}, actor?: "name" }
  app.post('/actions/:kind', async (req, reply) => {
    const body = req.body || {};
    const actor = typeof body.actor === 'string' && ACTOR_RE.test(body.actor) ? body.actor : 'pertal';
    try {
      const job = startAction(app, req.params.kind, resource(body.resource), {
        confirm: body.confirm === true, params: body.params ?? null, actor,
      });
      return reply.code(202).send({ job });
    } catch (err) {
      if (err instanceof ActionError) return reply.code(err.statusCode).send({ error: err.message });
      throw err;
    }
  });

  app.get('/jobs', async (req) => ({ jobs: app.jobs.list({ limit: Math.min(Number(req.query.limit) || 50, 200) }) }));
  app.get('/jobs/:id', async (req, reply) => {
    const j = app.jobs.get(req.params.id);
    if (!j) return reply.code(404).send({ error: 'job not found (finished jobs age out of memory; see /api/activity)' });
    return { job: j };
  });

  // The one feed: activity entries + finished jobs from the audit trail + live jobs.
  app.get('/activity', async (req) => {
    const limit = Math.min(Number(req.query.limit) || 100, 500);
    const live = app.jobs.list({ limit: 200 });
    const liveIds = new Set(live.map((j) => j.id));
    const jobs = [...live, ...app.jobs.audit({ days: 60, limit: 500 }).filter((j) => !liveIds.has(j.id))]
      .map((j) => ({ type: 'job', id: j.id, at: j.started_at, severity: j.status === 'failed' ? 'crit' : 'ok', host: j.host, resource_id: j.resource ?? null, job: j }));
    const items = [...app.activity.list({ limit: 500 }), ...jobs]
      .sort((a, b) => String(b.at).localeCompare(String(a.at)))
      .slice(0, limit);
    return { items };
  });
};
