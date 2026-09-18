// HLTV games-of-the-day bot controls — thin proxy to the discord-hltv container's
// control API on the internal docker network. The bot owns its config; this layer
// just forwards and maps failures to JSON.
const { proxyJson } = require('../lib/upstream');

const HLTV_BOT_URL = process.env.HLTV_BOT_URL || 'http://discord-hltv:8080';

// How stale a cached day feed may be before hltv-api re-scrapes for us. This MUST be
// sent: hltv-api's get_day() defaults to max_age=0, and it reads that as "ignore the
// cache", so a bare GET /day drives a full ~60s browser scrape on every single call.
// The dashboard polls this route, so a missing max_age meant every poll started a
// cold scrape, lost the race with the timeout below, and fell back to the on-disk
// last-good copy — which is why the guide sat permanently on a stale feed. The
// Discord bot has always passed one (DAY_MAX_AGE in discord-hltv.py); this didn't.
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
  // query string changes the answer. The timeout has to clear a genuine cold scrape
  // (~60s per the note above) for the times the cache really is empty.
  { method: 'get', path: '/day',     bot: 'GET',  botPath: '/day',     timeout: 75000,
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
