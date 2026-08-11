// HLTV games-of-the-day bot controls — thin proxy to the discord-hltv container's
// control API on the internal docker network. The bot owns its config; this layer
// just forwards and maps failures to JSON.
const { proxyJson } = require('../lib/upstream');

const HLTV_BOT_URL = process.env.HLTV_BOT_URL || 'http://discord-hltv:8080';

// route → bot endpoint. /send, /preview and /vrs hit GitHub/bo3.gg live.
const ROUTES = [
  { method: 'get', path: '/status',  bot: 'GET',  botPath: '/health' },
  { method: 'get', path: '/config',  bot: 'GET',  botPath: '/config' },
  { method: 'put', path: '/config',  bot: 'PUT',  botPath: '/config' },
  { method: 'post', path: '/send',   bot: 'POST', botPath: '/send',    timeout: 30000 },
  { method: 'get', path: '/preview', bot: 'GET',  botPath: '/preview', timeout: 30000 },
  { method: 'get', path: '/vrs',     bot: 'GET',  botPath: '/vrs',     timeout: 20000 },
];

module.exports = async function hltvRoutes(app) {
  for (const r of ROUTES) {
    app[r.method](r.path, async (req, reply) => {
      try {
        const out = await proxyJson(HLTV_BOT_URL, r.bot, r.botPath,
          r.method === 'get' ? undefined : req.body, r.timeout || 5000);
        reply.code(out.status).send(out.data);
      } catch (e) {
        reply.code(502).send({ error: `hltv bot unreachable: ${e.message}` });
      }
    });
  }
};
