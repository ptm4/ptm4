// Sports bot controls — thin proxy to the discord-sports container's control
// API on the internal docker network (same pattern as weather.js).
// The bot owns its config; this layer just forwards and maps failures to JSON.
const express = require('express');
const router = express.Router();

const SPORTS_BOT_URL = process.env.SPORTS_BOT_URL || 'http://discord-sports:8080';

async function proxy(method, urlPath, body, timeoutMs = 5000) {
  const res = await fetch(`${SPORTS_BOT_URL}${urlPath}`, {
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

// route → bot endpoint. /send and /preview hit ESPN live, so longer timeout.
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
      res.status(502).json({ error: `sports bot unreachable: ${e.message}` });
    }
  });
}

// team search (the weather bot's /geocode pattern)
router.get('/teams', async (req, res) => {
  const league = (req.query.league || '').toString().trim();
  const q = (req.query.q || '').toString().trim();
  if (!league || !q) return res.status(400).json({ error: 'missing ?league= or ?q=' });
  try {
    const out = await proxy('GET', `/teams?league=${encodeURIComponent(league)}&q=${encodeURIComponent(q)}`, undefined, 20000);
    res.status(out.status).json(out.data);
  } catch (e) {
    res.status(502).json({ error: `sports bot unreachable: ${e.message}` });
  }
});

module.exports = router;
