// Shared agent-control helpers used by both /api/reports and /api/agents.
// - resolves the agent-logs dir (Docker mount /agent-logs, dev fallback)
// - reads agents-state.json (written by the opti dispatcher)
// - attaches enable/disable + run-now endpoints that proxy to the dispatcher over the LAN
const fs = require('fs');
const path = require('path');

const AGENT_LOGS_DIR = fs.existsSync('/agent-logs')
  ? '/agent-logs'
  : path.join(__dirname, '..', '..', '..', '..', '..', 'agent-logs');

const STATE_PATH = path.join(AGENT_LOGS_DIR, 'agents-state.json');

// Dispatcher lives on opti; configured via the webapp container env (.env)
const DISPATCHER_URL = process.env.DISPATCHER_URL || '';
const DISPATCH_TOKEN = process.env.HL_DISPATCH_TOKEN || '';

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_PATH, 'utf8'));
  } catch (_) {
    return {};
  }
}

// Default-enabled unless explicitly disabled
function enabledFor(name) {
  const e = readState()[name];
  return e && typeof e.enabled === 'boolean' ? e.enabled : true;
}

async function dispatch(method, urlPath, body) {
  if (!DISPATCHER_URL) {
    const err = new Error('Dispatcher not configured (set DISPATCHER_URL)');
    err.statusCode = 503;
    throw err;
  }
  const headers = { 'Content-Type': 'application/json' };
  if (DISPATCH_TOKEN) headers['Authorization'] = `Bearer ${DISPATCH_TOKEN}`;
  const res = await fetch(`${DISPATCHER_URL}${urlPath}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(8000),
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch (_) { data = { raw: text }; }
  return { status: res.status, data };
}

// Attaches POST /:name/enabled and POST /:name/run to a router.
// `agentName` maps the route param to the dispatcher's agent key (identity by default).
function attachControls(router) {
  router.post('/:name/enabled', async (req, res) => {
    const enabled = !!req.body.enabled;
    try {
      const r = await dispatch('POST', `/agents/${encodeURIComponent(req.params.name)}/enabled`, { enabled });
      res.status(r.status).json(r.data);
    } catch (e) {
      res.status(e.statusCode || 502).json({ error: e.message });
    }
  });

  router.post('/:name/run', async (req, res) => {
    try {
      const r = await dispatch('POST', `/agents/${encodeURIComponent(req.params.name)}/run`);
      res.status(r.status).json(r.data);
    } catch (e) {
      res.status(e.statusCode || 502).json({ error: e.message });
    }
  });
}

module.exports = { AGENT_LOGS_DIR, readState, enabledFor, attachControls };
