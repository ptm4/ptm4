// Health digest bot controls — thin proxy to the discord-healthdigest container's
// control API on the internal docker network. The bot owns its config; this layer
// just forwards and maps failures to JSON.
const { proxyJson } = require('../lib/upstream');

const HEALTHDIGEST_BOT_URL = process.env.HEALTHDIGEST_BOT_URL || 'http://discord-healthdigest:8080';

// route → bot endpoint. /send and /preview gather live data (and may kick a
// fresh doctor run, up to ~90s), so generous timeouts.
// NB (pre-existing, found in the 2026-08-10 risk pass): these 120s caps sit behind
// nginx `location /`'s default 60s read timeout, so a >60s digest 504s at nginx
// before this cap fires. Ported verbatim; fixing it is a deliberate nginx change.
const ROUTES = [
  { method: 'get', path: '/status',  bot: 'GET',  botPath: '/health' },
  { method: 'get', path: '/config',  bot: 'GET',  botPath: '/config' },
  { method: 'put', path: '/config',  bot: 'PUT',  botPath: '/config' },
  { method: 'post', path: '/send',   bot: 'POST', botPath: '/send',    timeout: 120000 },
  { method: 'get', path: '/preview', bot: 'GET',  botPath: '/preview', timeout: 120000 },
];

module.exports = async function healthdigestRoutes(app) {
  for (const r of ROUTES) {
    app[r.method](r.path, async (req, reply) => {
      try {
        const out = await proxyJson(HEALTHDIGEST_BOT_URL, r.bot, r.botPath,
          r.method === 'get' ? undefined : req.body, r.timeout || 5000);
        reply.code(out.status).send(out.data);
      } catch (e) {
        reply.code(502).send({ error: `health digest bot unreachable: ${e.message}` });
      }
    });
  }
};
