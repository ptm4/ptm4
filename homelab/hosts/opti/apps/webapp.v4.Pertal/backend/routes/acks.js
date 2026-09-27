// /api/acks — acknowledge a known issue so it stops asking for attention (lib/acks.js has
// the matching rules). Both directions are jobs, so the audit trail says who silenced
// what and when.
'use strict';

function runJob(app, spec, body) {
  const job = app.jobs.create(spec);
  (async () => {
    try { await body(job); job.finish('ok'); } catch (err) { job.finish('failed', err); }
  })();
  return job.snapshot();
}

const allIssues = (app) => {
  const s = app.pertal.state.summary;
  return [...(s?.issues ?? []), ...(s?.acknowledged ?? [])];
};

module.exports = async function ackRoutes(app) {
  app.get('/', async () => ({ acks: app.acks.list() }));

  // Apply: rebuild now (not on the next snapshot change) and say what it did to the resource.
  const apply = (job, resourceId) => job.step('apply', async (note) => {
    const before = resourceId ? app.pertal.resource(resourceId)?.status : null;
    app.pertal.rebuild();
    const after = resourceId ? app.pertal.resource(resourceId)?.status : null;
    note(resourceId ? `${resourceId}: ${before} → ${after}` : 'status recomputed');
  });

  app.post('/', async (req, reply) => {
    const key = String(req.body?.key ?? '');
    const issue = allIssues(app).find((i) => i.key === key);
    if (!issue) return reply.code(404).send({ error: 'that issue is not being reported any more' });
    const note = req.body?.note ? String(req.body.note).slice(0, 300) : null;
    const job = runJob(app, {
      kind: 'issue.ack', title: `Acknowledge: ${issue.resource} — ${issue.text}`.slice(0, 160),
      host: issue.host, target: issue.resource, resource: issue.resource_id,
      steps: [
        { key: 'save', label: 'Remember it as known', detail: 'Hidden until it gets more severe or changes kind — numbers changing won\'t bring it back' },
        { key: 'apply', label: 'Recompute status' },
      ],
    }, async (job) => {
      await job.step('save', async (n) => { app.acks.add(issue, { note }); n(`saved to ${app.acks.FILE}`); });
      await apply(job, issue.resource_id);
    });
    return reply.code(202).send({ job });
  });

  app.post('/remove', async (req, reply) => {
    const key = String(req.body?.key ?? '');
    const ack = app.acks.get(key);
    if (!ack) return reply.code(404).send({ error: 'no such acknowledgement' });
    const issue = allIssues(app).find((i) => i.key === key);
    const job = runJob(app, {
      kind: 'issue.unack', title: `Un-acknowledge: ${ack.resource} — ${ack.text}`.slice(0, 160),
      host: ack.host, target: ack.resource, resource: issue?.resource_id ?? null,
      steps: [{ key: 'save', label: 'Forget the acknowledgement' }, { key: 'apply', label: 'Recompute status' }],
    }, async (job) => {
      await job.step('save', async (n) => { app.acks.remove(key); n('removed'); });
      await apply(job, issue?.resource_id ?? null);
    });
    return reply.code(202).send({ job });
  });
};
