// Jellyfin arrivals bot controls — thin proxy to the discord-jellyfin container's
// control API on the internal docker network (same pattern as weather.js).
// The bot owns its config; this layer just forwards and maps failures to JSON.
const express = require('express');
const router = express.Router();

const JELLYFIN_BOT_URL = process.env.JELLYFIN_BOT_URL || 'http://discord-jellyfin:8080';

async function proxy(method, urlPath, body, timeoutMs = 5000) {
  const res = await fetch(`${JELLYFIN_BOT_URL}${urlPath}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch (_) { data = { raw: text }; }
  return { status: res.status, data };
}

// route → bot endpoint. /send, /preview and /check hit the Jellyfin server live.
const ROUTES = [
  { method: 'get', path: '/status',  bot: 'GET',  botPath: '/health' },
  { method: 'get', path: '/config',  bot: 'GET',  botPath: '/config' },
  { method: 'put', path: '/config',  bot: 'PUT',  botPath: '/config' },
  { method: 'post', path: '/send',   bot: 'POST', botPath: '/send',    timeout: 30000 },
  { method: 'get', path: '/preview', bot: 'GET',  botPath: '/preview', timeout: 30000 },
  { method: 'get', path: '/check',   bot: 'GET',  botPath: '/check',   timeout: 15000 },
];

for (const r of ROUTES) {
  router[r.method](r.path, async (req, res) => {
    try {
      const out = await proxy(r.bot, r.botPath, r.method === 'get' ? undefined : req.body, r.timeout);
      res.status(out.status).json(out.data);
    } catch (e) {
      res.status(502).json({ error: `jellyfin bot unreachable: ${e.message}` });
    }
  });
}

module.exports = router;
