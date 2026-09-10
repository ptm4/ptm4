// Jellyfin arrivals bot controls — thin proxy to the discord-jellyfin container's
// control API on the internal docker network. The bot owns its config; this layer
// just forwards and maps failures to JSON.
const { proxyJson } = require('../lib/upstream');

const JELLYFIN_BOT_URL = process.env.JELLYFIN_BOT_URL || 'http://discord-jellyfin:8080';

// route → bot endpoint. /send, /preview and /check hit the Jellyfin server live.
const ROUTES = [
  { method: 'get', path: '/status',  bot: 'GET',  botPath: '/health' },
  { method: 'get', path: '/config',  bot: 'GET',  botPath: '/config' },
  { method: 'put', path: '/config',  bot: 'PUT',  botPath: '/config' },
  { method: 'post', path: '/send',   bot: 'POST', botPath: '/send',    timeout: 30000 },
  { method: 'get', path: '/preview', bot: 'GET',  botPath: '/preview', timeout: 30000 },
  { method: 'get', path: '/check',   bot: 'GET',  botPath: '/check',   timeout: 15000 },
];

module.exports = async function jellyfinRoutes(app) {
  for (const r of ROUTES) {
    app[r.method](r.path, async (req, reply) => {
      try {
        const out = await proxyJson(JELLYFIN_BOT_URL, r.bot, r.botPath,
          r.method === 'get' ? undefined : req.body, r.timeout || 5000);
        reply.code(out.status).send(out.data);
      } catch (e) {
        reply.code(502).send({ error: `jellyfin bot unreachable: ${e.message}` });
      }
    });
  }
};
