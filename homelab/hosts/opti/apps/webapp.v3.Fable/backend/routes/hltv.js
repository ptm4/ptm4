// HLTV games-of-the-day bot controls — thin proxy to the discord-hltv container's
// control API on the internal docker network. The bot owns its config; this layer
// just forwards and maps failures to JSON.
const { proxyJson } = require('../lib/upstream');

const HLTV_BOT_URL = process.env.HLTV_BOT_URL || 'http://discord-hltv:8080';

// How stale a day feed may be before the bot rebuilds it. The request path is
// webapp -> discord-hltv -> hltv-api, and BOTH of those hops used to force work: the
// bot threw its query string away (so this was a no-op until 2026-09-18) and
// hltv-api's get_day() reads max_age=0 as "ignore the cache". A read therefore raced
// a cold ~60s scrape and, when it lost, the failure got cached here for a minute —
// which is what made the Streams guide flicker in and out.
const DAY_MAX_AGE = Number(process.env.HLTV_DAY_MAX_AGE || 900);

// route → bot endpoint. /send, /preview, /day and /vrs reach hltv.org through the
// hltv-api sidecar, which drives a real browser — a cold scrape takes ~60s, hence
// the generous timeouts. /day is cached both sides, so the widget's poll is cheap.
const ROUTES = [
  { method: 'get', path: '/status',  bot: 'GET',  botPath: '/health' },
  { method: 'get', path: '/config',  bot: 'GET',  botPath: '/config' },
  { method: 'put', path: '/config',  bot: 'PUT',  botPath: '/config' },
  { method: 'post', path: '/send',   bot: 'POST', botPath: '/send',    timeout: 90000 },
  { method: 'get', path: '/preview', bot: 'GET',  botPath: '/preview', timeout: 90000 },
  // Query is forwarded for /day only, because it is the only bot endpoint whose
  // query string changes the answer. The timeout stays modest on purpose: hltv-api
  // now answers /day from cache or last-good without ever blocking on a scrape, so
  // anything slow here is a real fault, not a cold start. (It was briefly raised to
  // 75s to cover the cold path — that outlasted the deploy smoke gate's own 30s
  // client timeout and failed the deploy. Fix the blocking, not the clock.)
  { method: 'get', path: '/day',     bot: 'GET',  botPath: '/day',     timeout: 25000,
    query: (q) => ({
      max_age: q.max_age ?? DAY_MAX_AGE,
      ...(q.date ? { date: q.date } : {}),
      ...(q.tz ? { tz: q.tz } : {}),
    }) },
  { method: 'get', path: '/vrs',     bot: 'GET',  botPath: '/vrs',     timeout: 20000 },
];

module.exports = async function hltvRoutes(app) {
  for (const r of ROUTES) {
    app[r.method](r.path, async (req, reply) => {
      try {
        const qs = r.query ? new URLSearchParams(r.query(req.query || {})).toString() : '';
        const botPath = qs ? `${r.botPath}?${qs}` : r.botPath;
        const out = await proxyJson(HLTV_BOT_URL, r.bot, botPath,
          r.method === 'get' ? undefined : req.body, r.timeout || 5000);
        reply.code(out.status).send(out.data);
      } catch (e) {
        reply.code(502).send({ error: `hltv bot unreachable: ${e.message}` });
      }
    });
  }
};
