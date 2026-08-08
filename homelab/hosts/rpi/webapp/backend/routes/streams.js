// Streams page controls — thin proxy to stream-station on noblenumbat (same pattern
// as jellyfin.js). stream-station resolves live streams with streamlink and remuxes
// them to HLS; this layer only forwards control calls and maps failures to JSON.
//
// The bearer token lives ONLY here: the browser never sees it, so the token-gated
// start/stop endpoints on nn are effectively "callable by the dashboard" rather than
// by anything on the LAN. The video itself does not come through this route — nginx
// proxies /hls straight to nn (see nginx-wg.conf).
const express = require('express');
const router = express.Router();

const STREAM_URL = process.env.STREAM_URL || 'http://192.168.1.6:8098';
const STREAM_TOKEN = process.env.HL_STREAM_TOKEN || '';

async function proxy(method, urlPath, body, timeoutMs = 8000) {
  const headers = { 'Content-Type': 'application/json' };
  if (STREAM_TOKEN) headers.Authorization = `Bearer ${STREAM_TOKEN}`;
  const res = await fetch(`${STREAM_URL}${urlPath}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch (_) { data = { raw: text }; }
  return { status: res.status, data };
}

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

for (const r of ROUTES) {
  router[r.method](r.path, async (req, res) => {
    // Without a token every POST would come back 401 from nn, which reads in the UI
    // as "the stream station rejected me" rather than "this dashboard is misconfigured".
    if (r.method === 'post' && !STREAM_TOKEN) {
      return res.status(500).json({ error: 'HL_STREAM_TOKEN is not set on the webapp — cannot control stream-station' });
    }
    try {
      const out = await proxy(r.up, r.upPath, r.method === 'get' ? undefined : req.body, r.timeout);
      res.status(out.status).json(out.data);
    } catch (e) {
      res.status(502).json({ error: `stream station unreachable: ${e.message}` });
    }
  });
}

module.exports = router;
