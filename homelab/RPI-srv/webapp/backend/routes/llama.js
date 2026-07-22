// Local LLM (android phone) controls — proxies to two services on the phone:
//   - llama-ctl  (LLAMA_CTL_URL, default :8081): status/models/model-switch/runbook CRUD/ask
//   - llama-server (LLAMA_URL, default :8080): raw OpenAI-compatible chat completions
// Same thin-proxy pattern as weather.js/hltv.js, but split across two upstream ports
// since llama-server only does inference — llama-ctl is the management companion.
const express = require('express');
const router = express.Router();

const LLAMA_URL = process.env.LLAMA_URL || 'http://android.lan:8080';
const LLAMA_CTL_URL = process.env.LLAMA_CTL_URL || 'http://android.lan:8081';

async function proxy(base, method, urlPath, body, timeoutMs = 8000) {
  const res = await fetch(`${base}${urlPath}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch (_) { data = { raw: text }; }
  return { status: res.status, data };
}

function fail(res, e, label) {
  res.status(502).json({ error: `${label} unreachable: ${e.message}` });
}

// ── management (llama-ctl, :8081) ──────────────────────────────────────────
router.get('/status', async (req, res) => {
  try {
    const out = await proxy(LLAMA_CTL_URL, 'GET', '/status', undefined, 8000);
    res.status(out.status).json(out.data);
  } catch (e) { fail(res, e, 'llama-ctl'); }
});

router.get('/models', async (req, res) => {
  try {
    const out = await proxy(LLAMA_CTL_URL, 'GET', '/models', undefined, 8000);
    res.status(out.status).json(out.data);
  } catch (e) { fail(res, e, 'llama-ctl'); }
});

// switching models restarts llama-server on the phone (~2min cold reload)
router.post('/model', async (req, res) => {
  try {
    const out = await proxy(LLAMA_CTL_URL, 'POST', '/model', { name: req.body.name }, 15000);
    res.status(out.status).json(out.data);
  } catch (e) { fail(res, e, 'llama-ctl'); }
});

router.get('/runbooks', async (req, res) => {
  try {
    const out = await proxy(LLAMA_CTL_URL, 'GET', '/runbooks', undefined, 8000);
    res.status(out.status).json(out.data);
  } catch (e) { fail(res, e, 'llama-ctl'); }
});

router.put('/runbooks/:name', async (req, res) => {
  try {
    const out = await proxy(LLAMA_CTL_URL, 'PUT', `/runbooks/${encodeURIComponent(req.params.name)}`, { content: req.body.content }, 8000);
    res.status(out.status).json(out.data);
  } catch (e) { fail(res, e, 'llama-ctl'); }
});

router.delete('/runbooks/:name', async (req, res) => {
  try {
    const out = await proxy(LLAMA_CTL_URL, 'DELETE', `/runbooks/${encodeURIComponent(req.params.name)}`, undefined, 8000);
    res.status(out.status).json(out.data);
  } catch (e) { fail(res, e, 'llama-ctl'); }
});

// grounded Q&A — llama-ctl stuffs the runbooks server-side (same logic as the `ask` CLI)
router.post('/ask', async (req, res) => {
  try {
    const out = await proxy(LLAMA_CTL_URL, 'POST', '/ask', { question: req.body.question }, 180000);
    res.status(out.status).json(out.data);
  } catch (e) { fail(res, e, 'llama-ctl'); }
});

// ── raw inference (llama-server, :8080) ────────────────────────────────────
// Unfiltered prompt console — no runbook grounding, straight OpenAI-compatible chat.
// max_tokens default matches askcore.py's: at this phone's context size (~8k tokens
// once the runbooks are in play), CPU generation runs ~1.5-2.5 tok/s even warm, so an
// uncapped/long response can outrun the timeout chain. Caller may still override.
router.post('/chat', async (req, res) => {
  const messages = Array.isArray(req.body.messages) ? req.body.messages : null;
  if (!messages) return res.status(400).json({ error: 'missing messages[]' });
  try {
    const out = await proxy(LLAMA_URL, 'POST', '/v1/chat/completions', {
      messages,
      temperature: req.body.temperature ?? 0.7,
      max_tokens: req.body.max_tokens ?? 200,
    }, 180000);
    res.status(out.status).json(out.data);
  } catch (e) { fail(res, e, 'llama-server'); }
});

module.exports = router;
