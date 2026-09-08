// Weather bot controls — thin proxy to the discord-weather container's control
// API on the internal docker network. The bot owns its config; this layer just
// forwards and maps failures to JSON.
const { proxyJson } = require('../lib/upstream');

const WEATHER_BOT_URL = process.env.WEATHER_BOT_URL || 'http://discord-weather:8080';

// route → bot endpoint. /send and /preview hit Open-Meteo live, so longer timeout.
const ROUTES = [
  { method: 'get', path: '/status',  bot: 'GET',  botPath: '/health' },
  { method: 'get', path: '/config',  bot: 'GET',  botPath: '/config' },
  { method: 'put', path: '/config',  bot: 'PUT',  botPath: '/config' },
  { method: 'post', path: '/send',   bot: 'POST', botPath: '/send',    timeout: 30000 },
  { method: 'get', path: '/preview', bot: 'GET',  botPath: '/preview', timeout: 30000 },
  { method: 'get', path: '/witty',   bot: 'GET',  botPath: '/witty' },
  { method: 'post', path: '/witty/reroll', bot: 'POST', botPath: '/witty/reroll', timeout: 30000 },
];

module.exports = async function weatherRoutes(app) {
  for (const r of ROUTES) {
    app[r.method](r.path, async (req, reply) => {
      try {
        const out = await proxyJson(WEATHER_BOT_URL, r.bot, r.botPath,
          r.method === 'get' ? undefined : req.body, r.timeout || 5000);
        reply.code(out.status).send(out.data);
      } catch (e) {
        reply.code(502).send({ error: `weather bot unreachable: ${e.message}` });
      }
    });
  }

  app.get('/geocode', async (req, reply) => {
    const q = (req.query.q || '').toString().trim();
    if (!q) return reply.code(400).send({ error: 'missing ?q=' });
    try {
      const out = await proxyJson(WEATHER_BOT_URL, 'GET', `/geocode?q=${encodeURIComponent(q)}`, undefined, 15000);
      reply.code(out.status).send(out.data);
    } catch (e) {
      reply.code(502).send({ error: `weather bot unreachable: ${e.message}` });
    }
  });
};
