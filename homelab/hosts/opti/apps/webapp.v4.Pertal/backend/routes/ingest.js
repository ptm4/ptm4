// POST /api/architecture/ingest — v3-compatible target for hl-arch-agent's daily full
// inventory push. Same bearer token (HL_ARCH_INGEST_TOKEN) and the same fragment files,
// so the agents need no reconfiguration at cutover.
'use strict';
const { HOST_ID_RE, writeFragment, buildMergedData } = require('../lib/fragments');

const INGEST_TOKEN = process.env.HL_ARCH_INGEST_TOKEN || '';

module.exports = async function ingestRoutes(app) {
  app.post('/ingest', async (req, reply) => {
    if (INGEST_TOKEN && req.headers.authorization !== `Bearer ${INGEST_TOKEN}`) {
      return reply.code(401).send({ error: 'unauthorized' });
    }
    const host = req.body?.host;
    if (typeof host !== 'string' || !HOST_ID_RE.test(host)) {
      return reply.code(400).send({ error: `body.host must match ${HOST_ID_RE}` });
    }
    try {
      writeFragment(host, req.body);
    } catch (err) {
      return reply.code(500).send({ error: 'could not store fragment', detail: err.message });
    }
    const containers = (req.body?.docker?.containers || []).length;
    app.activity.add({ type: 'inventory', severity: 'ok', host, text: `${host} reported its inventory (${containers} containers)` });
    return { ok: true, host, containers, received_at: new Date().toISOString() };
  });

  // GET /api/architecture/data: curated map + live decoration (v3-compatible contract).
  app.get('/data', async (req, reply) => {
    try {
      return buildMergedData();
    } catch (err) {
      req.log.warn({ err }, 'architecture merge failed');
      return reply.code(500).send({ error: 'merge failed', detail: err.message });
    }
  });
};
