// PC-part price watch for the opti hypervisor rebuild (2026-08). The pricewatch
// collector on opti writes pricewatch-latest.json into agent-logs (mounted :ro here);
// this just serves it with a short cache so an open board never hammers the mount.
const fs = require('fs');
const path = require('path');
const { AGENT_LOGS_DIR } = require('../lib/controls');

const CACHE_MS = 60_000;
let cache = { at: 0, body: null };

module.exports = async function pricewatchRoutes(app) {
  // GET /api/pricewatch — full latest report: items[], history{}, below_target[]
  app.get('/', async (req, reply) => {
    if (cache.body && Date.now() - cache.at < CACHE_MS) return cache.body;
    const file = path.join(AGENT_LOGS_DIR, 'pricewatch-latest.json');
    try {
      const report = JSON.parse(fs.readFileSync(file, 'utf8'));
      cache = { at: Date.now(), body: report };
      return report;
    } catch (e) {
      return reply.code(502).send({ error: 'pricewatch report unavailable' });
    }
  });
};
