// /api/requests — Seerr's request queue (from its snapshot) and approve / decline as
// jobs. New requests are made in Seerr itself (it owns search, seasons and quotas).
'use strict';
const { seerr } = require('../sources/seerr');

const DRY = process.env.PERTAL_ACTIONS === 'dry';

module.exports = async function requestRoutes(app) {
  app.get('/', async () => {
    const s = app.snapshots.get('seerr:requests');
    const b = app.snapshots.get('readarr:books');
    return {
      data: s?.data ?? null, meta: s?.meta ?? null,
      configured: !!process.env.SEERR_API_KEY,
      seerr_url: 'http://opti.lan:5055',
      books: b?.data ?? null, books_meta: b?.meta ?? null,
      books_configured: !!process.env.READARR_API_KEY,
      readarr_url: 'http://noblenumbat.lan:8788',
    };
  });

  app.post('/:id/:op', async (req, reply) => {
    const id = Number(req.params.id);
    const op = req.params.op;
    if (!Number.isInteger(id) || id <= 0) return reply.code(400).send({ error: 'bad request id' });
    if (!['approve', 'decline'].includes(op)) return reply.code(404).send({ error: `unknown operation '${op}'` });
    const r = (app.snapshots.data('seerr:requests')?.requests ?? []).find((x) => x.id === id);
    if (!r) return reply.code(404).send({ error: 'no such request' });

    const verb = op === 'approve' ? 'Approve' : 'Decline';
    const job = app.jobs.create({
      kind: `request.${op}`, title: `${verb} ${r.title ?? `request ${id}`}`, host: 'opti', target: r.title ?? String(id),
      resource: 'opti:seerr',
      steps: [
        { key: 'send', label: `${verb} in Seerr`, detail: op === 'approve' ? 'Seerr then hands it to Sonarr/Radarr.' : null },
        { key: 'verify', label: 'Re-read the request queue' },
      ],
    });
    (async () => {
      try {
        await job.step('send', async (note) => {
          if (DRY) return note(`dry run: would ${op} request ${id}`);
          await seerr(`/request/${id}/${op}`, { method: 'POST' });
          note('Seerr accepted');
        });
        await job.step('verify', async (note) => {
          const s = await app.snapshots.refresh('seerr:requests');
          const now = s?.data?.requests?.find((x) => x.id === id);
          note(now ? `request is now ${now.status}` : 'request no longer listed');
        });
        job.finish('ok');
      } catch (err) {
        job.finish('failed', err);
      }
    })();
    return reply.code(202).send({ job: job.snapshot() });
  });
};
