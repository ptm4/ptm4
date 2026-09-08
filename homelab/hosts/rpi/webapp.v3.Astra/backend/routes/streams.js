// Streams page controls — thin proxy to stream-station on noblenumbat.
// stream-station resolves live streams with streamlink and remuxes them to HLS;
// this layer only forwards control calls and maps failures to JSON.
//
// The bearer token lives ONLY here: the browser never sees it, so the token-gated
// start/stop endpoints on nn are effectively "callable by the dashboard" rather than
// by anything on the LAN. The video itself does not come through this route — nginx
// proxies /hls straight to nn (see nginx-wg.conf).
const { proxyJson } = require('../lib/upstream');

const STREAM_URL = process.env.STREAM_URL || 'http://192.168.1.6:8098';
const STREAM_TOKEN = process.env.HL_STREAM_TOKEN || '';

// /start is slow on purpose: streamlink has to resolve the channel and negotiate the
// source before the first segment exists, which is a few seconds on a good day.
const ROUTES = [
  { method: 'get',  path: '/status',  up: 'GET',  upPath: '/status' },
  { method: 'get',  path: '/presets', up: 'GET',  upPath: '/presets' },
  { method: 'post', path: '/start',   up: 'POST', upPath: '/start', timeout: 15000 },
  { method: 'post', path: '/stop',    up: 'POST', upPath: '/stop' },
  // Sent by the open page each poll: "these slots are still wanted". Without it the
  // idle reaper would kill whichever slots aren't in the visible tab.
  { method: 'post', path: '/keepalive', up: 'POST', upPath: '/keepalive' },
];

module.exports = async function streamsRoutes(app) {
  const authHeader = STREAM_TOKEN ? { Authorization: `Bearer ${STREAM_TOKEN}` } : undefined;

  for (const r of ROUTES) {
    app[r.method](r.path, async (req, reply) => {
      // Without a token every POST would come back 401 from nn, which reads in the UI
      // as "the stream station rejected me" rather than "this dashboard is misconfigured".
      if (r.method === 'post' && !STREAM_TOKEN) {
        return reply.code(500).send({ error: 'HL_STREAM_TOKEN is not set on the webapp — cannot control stream-station' });
      }
      try {
        const out = await proxyJson(STREAM_URL, r.up, r.upPath,
          r.method === 'get' ? undefined : req.body, r.timeout || 8000, authHeader);
        reply.code(out.status).send(out.data);
      } catch (e) {
        reply.code(502).send({ error: `stream station unreachable: ${e.message}` });
      }
    });
  }
};
