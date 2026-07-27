// HLTV games-of-the-day bot controls — thin proxy to the discord-hltv
// container's control API on the internal docker network (same pattern as
// weather.js). The bot owns its config; this layer just forwards and maps
// failures to JSON.
const express = require('express');
const router = express.Router();

const HLTV_BOT_URL = process.env.HLTV_BOT_URL || 'http://discord-hltv:8080';

async function proxy(method, urlPath, body, timeoutMs = 5000) {
  const res = await fetch(`${HLTV_BOT_URL}${urlPath}`, {
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

// route → bot endpoint. /send, /preview and /vrs hit GitHub/bo3.gg live.
const ROUTES = [
  { method: 'get', path: '/status',  bot: 'GET',  botPath: '/health' },
  { method: 'get', path: '/config',  bot: 'GET',  botPath: '/config' },
  { method: 'put', path: '/config',  bot: 'PUT',  botPath: '/config' },
  { method: 'post', path: '/send',   bot: 'POST', botPath: '/send',    timeout: 30000 },
  { method: 'get', path: '/preview', bot: 'GET',  botPath: '/preview', timeout: 30000 },
  { method: 'get', path: '/vrs',     bot: 'GET',  botPath: '/vrs',     timeout: 20000 },
];

for (const r of ROUTES) {
  router[r.method](r.path, async (req, res) => {
    try {
      const out = await proxy(r.bot, r.botPath, r.method === 'get' ? undefined : req.body, r.timeout);
      res.status(out.status).json(out.data);
    } catch (e) {
      res.status(502).json({ error: `hltv bot unreachable: ${e.message}` });
    }
  });
}

module.exports = router;
