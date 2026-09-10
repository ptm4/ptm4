// /api/jobs — what the webapp has done, is doing, and said about it.
//
// Three reads, no writes: jobs are created by the routes that take the actions
// (agents.js), never by a POST here. That asymmetry is deliberate — this endpoint can
// be handed to anything that wants to watch or audit without widening what can act.
module.exports = async function jobRoutes(app) {
  // In-flight and recently finished, from memory. This is what the drawer polls if the
  // SSE stream is unavailable; when SSE is up, `job` events carry the same snapshots.
  app.get('/', async (req) => {
    const limit = Math.min(Number(req.query?.limit) || 50, 200);
    const jobs = app.jobs.list({ limit });
    return {
      jobs,
      running: jobs.filter((j) => j.status === 'running').length,
      generated_at: new Date().toISOString(),
    };
  });

  // The durable trail. Survives restarts, unlike the list above — so a job present here
  // and absent there is simply old, not lost.
  app.get('/audit', async (req) => {
    const days = Math.min(Number(req.query?.days) || 30, 400);
    const limit = Math.min(Number(req.query?.limit) || 200, 1000);
    const entries = app.jobs.audit({
      days, limit,
      kind: req.query?.kind || null,
      host: req.query?.host || null,
    });
    return { entries, count: entries.length, days, generated_at: new Date().toISOString() };
  });

  app.get('/:id', async (req, reply) => {
    const job = app.jobs.get(req.params.id);
    if (job) return job;
    // Fall through to the audit trail so a link to a job stays good after a restart.
    const hit = app.jobs.audit({ days: 400, limit: 1000 }).find((j) => j.id === req.params.id);
    if (hit) return { ...hit, from_audit: true };
    return reply.code(404).send({ error: `no job ${req.params.id}` });
  });
};
