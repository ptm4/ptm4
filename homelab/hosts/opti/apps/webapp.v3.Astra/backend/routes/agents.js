// /api/agents: per-host architecture agents (hl-arch-agent.py), installed and running
// on opti/rpi/noblenumbat (lib/hosts.js is the host list's single source of truth).
//
// This route is a thin proxy: it asks each host's agent directly for /status, and
// POSTs to its /sync for Force Sync, rather than routing through the opti dispatcher
// (that's a different control plane — see agent-dispatcher.py — for a different kind
// of thing, the runners). A stale or unreachable agent is reported as exactly that,
// never silently treated as healthy.
//
// AUTH POSTURE (deliberate, reviewed 2026-07-26 — see webapp/BUGS.md B3): every write
// on this dashboard trusts the LAN. The agent-side bearer token protects the AGENTS
// from arbitrary LAN callers; the webapp is the intended caller. If the dashboard ever
// becomes reachable beyond the LAN, gate the POST routes at nginx first.
const { AGENT_HOSTS } = require('../lib/hosts');
const { buildMergedData } = require('../lib/arch-data');

const TOKEN = process.env.HL_ARCH_INGEST_TOKEN || '';
const STATUS_TIMEOUT_MS = 4000;
const SYNC_TIMEOUT_MS = 20000;   // a real collection + push, not just a status read

async function agentFetch(url, { method = 'GET', timeoutMs = STATUS_TIMEOUT_MS, body } = {}) {
  const headers = {};
  if (TOKEN) headers['Authorization'] = `Bearer ${TOKEN}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(url, {
    method, headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

function driftCountsByHost() {
  try {
    const merged = buildMergedData();
    const counts = {};
    for (const d of merged.live_merge?.drift?.undescribed || []) {
      counts[d.host] = (counts[d.host] || 0) + 1;
    }
    for (const d of merged.live_merge?.drift?.missing || []) {
      counts[d.host] = (counts[d.host] || 0) + 1;
    }
    return counts;
  } catch (_) {
    return {};
  }
}

module.exports = async function agentsRoutes(app) {
  // GET /api/agents — one entry per configured host, with a live /status read.
  // Never lets one unreachable agent break the list — an unreachable host is a row
  // that says so, not a 500 for the whole page.
  app.get('/', async () => {
    const drift = driftCountsByHost();
    const hosts = await Promise.all(Object.entries(AGENT_HOSTS).map(async ([id, cfg]) => {
      try {
        const r = await agentFetch(`${cfg.base}/status`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return {
          id, label: cfg.label, reachable: true,
          last_run: r.data.last_run || null,
          next_scheduled: r.data.next_scheduled || null,
          agent_version: r.data.agent_version || null,
          drift_count: drift[id] || 0,
          // v0.4.0 control capabilities; null/[] on an older agent, which is exactly
          // how the cockpit detects "needs v0.4.0" and disables its buttons.
          allowed_units: r.data.allowed_units || null,
          wake_targets: r.data.wake_targets || [],
        };
      } catch (e) {
        return {
          id, label: cfg.label, reachable: false, error: e.message,
          last_run: null, next_scheduled: null, agent_version: null,
          drift_count: drift[id] || 0,
        };
      }
    }));
    return { hosts, checked_at: new Date().toISOString() };
  });

  // POST /api/agents/:host/sync — Force Sync for one host. Blocks until the agent
  // actually finishes (its own /sync is synchronous) and returns the real result.
  app.post('/:host/sync', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });

    try {
      const r = await agentFetch(`${cfg.base}/sync`, { method: 'POST', timeoutMs: SYNC_TIMEOUT_MS });
      reply.code(r.ok ? 200 : 502).send({ host: req.params.host, ...r.data });
    } catch (e) {
      reply.code(502).send({ host: req.params.host, ok: false, error: e.message });
    }
  });

  // POST /api/agents/sync-all — same, fanned out to every configured host in parallel.
  // Partial failure is expected and reported per-host, not surfaced as one opaque error.
  app.post('/sync-all', async () => {
    const results = await Promise.all(Object.keys(AGENT_HOSTS).map(async (host) => {
      try {
        const r = await agentFetch(`${AGENT_HOSTS[host].base}/sync`,
          { method: 'POST', timeoutMs: SYNC_TIMEOUT_MS });
        return { host, ...r.data, ok: r.ok };
      } catch (e) {
        return { host, ok: false, error: e.message };
      }
    }));
    return { results, checked_at: new Date().toISOString() };
  });

  // POST /api/agents/:host/restart-container — restart one container on that host via
  // its agent's /restart (agent v0.2.0+). The agent validates the name against its own
  // `docker ps -a` and requires a bearer token, so this proxy stays thin.
  // Timeout is generous: a real `docker restart` on a heavy container takes ~10-15s and
  // the agent blocks until it finishes, but stays well inside the 240s read timeout the
  // /api/agents location gets in nginx-wg.conf.
  app.post('/:host/restart-container', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    const container = req.body?.container;
    if (typeof container !== 'string' || !container.trim()) {
      return reply.code(400).send({ error: 'body.container is required' });
    }

    try {
      const r = await agentFetch(`${cfg.base}/restart`, {
        method: 'POST', timeoutMs: 55000, body: { container: container.trim() },
      });
      reply.code(r.status).send({ host: req.params.host, ...r.data });
    } catch (e) {
      // Distinguish "the agent never answered" from "the agent said no" — the frontend
      // maps these to different toasts.
      reply.code(502).send({
        host: req.params.host, ok: false,
        error: /abort|timeout/i.test(e.message)
          ? `agent on ${req.params.host} did not respond in time (restart may still be running)`
          : `agent on ${req.params.host} unreachable: ${e.message}`,
      });
    }
  });

  // POST /api/agents/:host/update-container — pull the newest image for one container's
  // compose service and recreate just that service, via the agent's /update (v0.3.0+).
  // The timeout is the big difference: a registry pull on the Pi can genuinely run for
  // minutes, so this sits under nginx's 240s /api/agents read timeout and above the
  // agent's own worst case (140s pull + 45s recreate).
  const UPDATE_TIMEOUT_MS = 220000;
  app.post('/:host/update-container', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    const container = req.body?.container;
    if (typeof container !== 'string' || !container.trim()) {
      return reply.code(400).send({ error: 'body.container is required' });
    }

    try {
      const r = await agentFetch(`${cfg.base}/update`, {
        method: 'POST', timeoutMs: UPDATE_TIMEOUT_MS, body: { container: container.trim() },
      });
      reply.code(r.status).send({ host: req.params.host, ...r.data });
    } catch (e) {
      reply.code(502).send({
        host: req.params.host, ok: false,
        error: /abort|timeout/i.test(e.message)
          ? `agent on ${req.params.host} did not respond in time (the update may still be running — check the containers panel in a minute)`
          : `agent on ${req.params.host} unreachable: ${e.message}`,
      });
    }
  });

  // ── Cockpit host controls (agent v0.4.0) ─────────────────────────────────────

  // POST /api/agents/:host/reboot — reboot the host. The body echoes the host name so
  // the agent can refuse a proxy/route mixup (its own HOST must match). The agent
  // responds BEFORE rebooting (~2s grace), so even an rpi reboot returns a real 200.
  app.post('/:host/reboot', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    try {
      const r = await agentFetch(`${cfg.base}/reboot`, {
        method: 'POST', timeoutMs: 15000, body: { host: req.params.host },
      });
      reply.code(r.status).send({ host: req.params.host, ...r.data });
    } catch (e) {
      reply.code(502).send({
        host: req.params.host, ok: false,
        error: `agent on ${req.params.host} unreachable: ${e.message}`,
      });
    }
  });

  // POST /api/agents/:host/apt-upgrade — kick the nightly homelab-autoupdate unit now.
  // Fast by design: the agent starts the unit and returns; progress is polled via
  // GET /:host/apt-status below, so no long request is ever held open.
  app.post('/:host/apt-upgrade', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    try {
      const r = await agentFetch(`${cfg.base}/apt-upgrade`, { method: 'POST', timeoutMs: 10000 });
      reply.code(r.status).send({ host: req.params.host, ...r.data });
    } catch (e) {
      reply.code(502).send({
        host: req.params.host, ok: false,
        error: `agent on ${req.params.host} unreachable: ${e.message}`,
      });
    }
  });

  // GET /api/agents/:host/apt-status — unit state + log tail + reboot-required flag.
  app.get('/:host/apt-status', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    try {
      const r = await agentFetch(`${cfg.base}/apt-status`, { timeoutMs: 8000 });
      reply.code(r.status).send({ host: req.params.host, ...r.data });
    } catch (e) {
      reply.code(502).send({
        host: req.params.host, ok: false,
        error: `agent on ${req.params.host} unreachable: ${e.message}`,
      });
    }
  });

  // POST /api/agents/:host/restart-service — restart one allowlisted systemd unit.
  // Timeout ladder must nest: agent restart cap 120s < this 160s < nginx 240s (the
  // slow case is docker.service on opti, which restarts every container it runs).
  app.post('/:host/restart-service', async (req, reply) => {
    const cfg = AGENT_HOSTS[req.params.host];
    if (!cfg) return reply.code(404).send({ error: `unknown agent host '${req.params.host}'` });
    const unit = req.body?.unit;
    if (typeof unit !== 'string' || !unit.trim()) {
      return reply.code(400).send({ error: 'body.unit is required' });
    }
    try {
      const r = await agentFetch(`${cfg.base}/service-restart`, {
        method: 'POST', timeoutMs: 160000, body: { unit: unit.trim() },
      });
      reply.code(r.status).send({ host: req.params.host, ...r.data });
    } catch (e) {
      reply.code(502).send({
        host: req.params.host, ok: false,
        error: /abort|timeout/i.test(e.message)
          ? `agent on ${req.params.host} did not respond in time (the restart may still be running)`
          : `agent on ${req.params.host} unreachable: ${e.message}`,
      });
    }
  });

  // POST /api/agents/:host/wake — Wake-on-LAN. The one deliberate exception to the
  // thin-proxy rule: the target host is OFF, so a healthy PEER agent broadcasts the
  // magic packet on its behalf. (The webapp container itself sits behind docker
  // bridge NAT, where a UDP broadcast would not reliably reach the LAN.)
  const WAKE_TARGETS = ['opti']; // hosts with WoL-armed NICs; mirrors the agents' WAKE_MACS
  app.post('/:host/wake', async (req, reply) => {
    const host = req.params.host;
    if (!WAKE_TARGETS.includes(host)) {
      return reply.code(404).send({ error: `'${host}' is not a wake target (no WoL-capable NIC)` });
    }
    const senders = Object.keys(AGENT_HOSTS).filter((h) => h !== host);
    const failures = [];
    for (const sender of senders) {
      try {
        const r = await agentFetch(`${AGENT_HOSTS[sender].base}/wake`, {
          method: 'POST', timeoutMs: 5000, body: { target: host },
        });
        // Spread first: the agent's own `host` field is the SENDER — the response's
        // host must stay the wake TARGET.
        if (r.ok) return { ...r.data, host, sent_by: sender };
        failures.push(`${sender}: HTTP ${r.status}`);
      } catch (e) {
        failures.push(`${sender}: ${e.message}`);
      }
    }
    reply.code(502).send({
      host, ok: false,
      error: `no reachable agent to send the wake packet (${failures.join('; ')})`,
    });
  });
};
