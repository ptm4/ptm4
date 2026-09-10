// Sports bot controls — thin proxy to the discord-sports container's control
// API on the internal docker network. The bot owns its config; this layer just
// forwards and maps failures to JSON.
const { proxyJson } = require('../lib/upstream');

const SPORTS_BOT_URL = process.env.SPORTS_BOT_URL || 'http://discord-sports:8080';

// route → bot endpoint. /send and /preview hit ESPN live, so longer timeout.
const ROUTES = [
  { method: 'get', path: '/status',  bot: 'GET',  botPath: '/health' },
  { method: 'get', path: '/config',  bot: 'GET',  botPath: '/config' },
  { method: 'put', path: '/config',  bot: 'PUT',  botPath: '/config' },
  { method: 'post', path: '/send',   bot: 'POST', botPath: '/send',    timeout: 30000 },
  { method: 'get', path: '/preview', bot: 'GET',  botPath: '/preview', timeout: 30000 },
];

module.exports = async function sportsRoutes(app) {
  for (const r of ROUTES) {
    app[r.method](r.path, async (req, reply) => {
      try {
        const out = await proxyJson(SPORTS_BOT_URL, r.bot, r.botPath,
          r.method === 'get' ? undefined : req.body, r.timeout || 5000);
        reply.code(out.status).send(out.data);
      } catch (e) {
        reply.code(502).send({ error: `sports bot unreachable: ${e.message}` });
      }
    });
  }

  // team search (the weather bot's /geocode pattern)
  app.get('/teams', async (req, reply) => {
    const league = (req.query.league || '').toString().trim();
    const q = (req.query.q || '').toString().trim();
    if (!league || !q) return reply.code(400).send({ error: 'missing ?league= or ?q=' });
    try {
      const out = await proxyJson(SPORTS_BOT_URL, 'GET',
        `/teams?league=${encodeURIComponent(league)}&q=${encodeURIComponent(q)}`, undefined, 20000);
      reply.code(out.status).send(out.data);
    } catch (e) {
      reply.code(502).send({ error: `sports bot unreachable: ${e.message}` });
    }
  });
};
