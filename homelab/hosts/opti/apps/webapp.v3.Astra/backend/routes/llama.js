// Local LLM (android phone) controls — proxies to two services on the phone:
//   - llama-ctl  (LLAMA_CTL_URL, default :8081): status/models/model-switch/runbook CRUD/ask
//   - llama-server (LLAMA_URL, default :8080): raw OpenAI-compatible chat completions
// Same thin-proxy pattern as the bots, but split across two upstream ports since
// llama-server only does inference — llama-ctl is the management companion.
const { proxyJson } = require('../lib/upstream');

const LLAMA_URL = process.env.LLAMA_URL || 'http://android.lan:8080';
const LLAMA_CTL_URL = process.env.LLAMA_CTL_URL || 'http://android.lan:8081';

module.exports = async function llamaRoutes(app) {
  const fail = (reply, e, label) =>
    reply.code(502).send({ error: `${label} unreachable: ${e.message}` });

  // ── management (llama-ctl, :8081) ──────────────────────────────────────────
  app.get('/status', async (req, reply) => {
    try {
      const out = await proxyJson(LLAMA_CTL_URL, 'GET', '/status', undefined, 8000);
      reply.code(out.status).send(out.data);
    } catch (e) { fail(reply, e, 'llama-ctl'); }
  });

  app.get('/models', async (req, reply) => {
    try {
      const out = await proxyJson(LLAMA_CTL_URL, 'GET', '/models', undefined, 8000);
      reply.code(out.status).send(out.data);
    } catch (e) { fail(reply, e, 'llama-ctl'); }
  });

  // switching models restarts llama-server on the phone (~2min cold reload)
  app.post('/model', async (req, reply) => {
    try {
      const out = await proxyJson(LLAMA_CTL_URL, 'POST', '/model', { name: req.body?.name }, 15000);
      reply.code(out.status).send(out.data);
    } catch (e) { fail(reply, e, 'llama-ctl'); }
  });

  app.get('/runbooks', async (req, reply) => {
    try {
      const out = await proxyJson(LLAMA_CTL_URL, 'GET', '/runbooks', undefined, 8000);
      reply.code(out.status).send(out.data);
    } catch (e) { fail(reply, e, 'llama-ctl'); }
  });

  app.put('/runbooks/:name', async (req, reply) => {
    try {
      const out = await proxyJson(LLAMA_CTL_URL, 'PUT',
        `/runbooks/${encodeURIComponent(req.params.name)}`, { content: req.body?.content }, 8000);
      reply.code(out.status).send(out.data);
    } catch (e) { fail(reply, e, 'llama-ctl'); }
  });

  app.delete('/runbooks/:name', async (req, reply) => {
    try {
      const out = await proxyJson(LLAMA_CTL_URL, 'DELETE',
        `/runbooks/${encodeURIComponent(req.params.name)}`, undefined, 8000);
      reply.code(out.status).send(out.data);
    } catch (e) { fail(reply, e, 'llama-ctl'); }
  });

  // grounded Q&A — llama-ctl stuffs the runbooks server-side (same logic as the `ask` CLI)
  app.post('/ask', async (req, reply) => {
    try {
      const out = await proxyJson(LLAMA_CTL_URL, 'POST', '/ask', { question: req.body?.question }, 180000);
      reply.code(out.status).send(out.data);
    } catch (e) { fail(reply, e, 'llama-ctl'); }
  });

  // ── raw inference (llama-server, :8080) ────────────────────────────────────
  // Unfiltered prompt console — no runbook grounding, straight OpenAI-compatible chat.
  // max_tokens default matches askcore.py's: at this phone's context size (~8k tokens
  // once the runbooks are in play), CPU generation runs ~1.5-2.5 tok/s even warm, so an
  // uncapped/long response can outrun the timeout chain. Caller may still override.
  app.post('/chat', async (req, reply) => {
    const messages = Array.isArray(req.body?.messages) ? req.body.messages : null;
    if (!messages) return reply.code(400).send({ error: 'missing messages[]' });
    try {
      const out = await proxyJson(LLAMA_URL, 'POST', '/v1/chat/completions', {
        messages,
        temperature: req.body.temperature ?? 0.7,
        max_tokens: req.body.max_tokens ?? 200,
      }, 180000);
      reply.code(out.status).send(out.data);
    } catch (e) { fail(reply, e, 'llama-server'); }
  });
};
