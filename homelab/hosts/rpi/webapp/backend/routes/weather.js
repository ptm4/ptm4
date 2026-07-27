// Weather bot controls — thin proxy to the discord-weather container's control
// API on the internal docker network (same pattern as controls.js → dispatcher).
// The bot owns its config; this layer just forwards and maps failures to JSON.
const express = require('express');
const router = express.Router();

const WEATHER_BOT_URL = process.env.WEATHER_BOT_URL || 'http://discord-weather:8080';

async function proxy(method, urlPath, body, timeoutMs = 5000) {
  const res = await fetch(`${WEATHER_BOT_URL}${urlPath}`, {
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

// route → bot endpoint. /send and /preview hit Open-Meteo live, so longer timeout.
const ROUTES = [
  { method: 'get', path: '/status',  bot: 'GET',  botPath: '/health' },
  { method: 'get', path: '/config',  bot: 'GET',  botPath: '/config' },
  { method: 'put', path: '/config',  bot: 'PUT',  botPath: '/config' },
  { method: 'post', path: '/send',   bot: 'POST', botPath: '/send',    timeout: 30000 },
  { method: 'get', path: '/preview', bot: 'GET',  botPath: '/preview', timeout: 30000 },
];

for (const r of ROUTES) {
  router[r.method](r.path, async (req, res) => {
    try {
      const out = await proxy(r.bot, r.botPath, r.method === 'get' ? undefined : req.body, r.timeout);
      res.status(out.status).json(out.data);
    } catch (e) {
      res.status(502).json({ error: `weather bot unreachable: ${e.message}` });
    }
  });
}

router.get('/geocode', async (req, res) => {
  const q = (req.query.q || '').toString().trim();
  if (!q) return res.status(400).json({ error: 'missing ?q=' });
  try {
    const out = await proxy('GET', `/geocode?q=${encodeURIComponent(q)}`, undefined, 15000);
    res.status(out.status).json(out.data);
  } catch (e) {
    res.status(502).json({ error: `weather bot unreachable: ${e.message}` });
  }
});

module.exports = router;
