// The (new) meaning of /api/agents: per-host architecture agents (hl-arch-agent.py),
// installed and running on opti/rpi/noblenumbat. Freed up 2026-07-25 when the old
// meaning — the 4 scheduled runners — moved to /api/runners (see routes/runners.js).
//
// This route is a thin proxy: it asks each host's agent directly for /status, and
// POSTs to its /sync for Force Sync, rather than routing through the opti dispatcher
// (that's a different control plane — see agent-dispatcher.py — for a different kind
// of thing, the runners). A stale or unreachable agent is reported as exactly that,
// never silently treated as healthy.
const express = require('express');
const architecture = require('./architecture');

const router = express.Router();

// Matches rules/01-homelab-context.md's host table. Hardcoded rather than
// env-configured because these are the fixed three hosts hl-arch-agent.py is
// installed on — consistent with how build-arch-data.py and the network runner
// already hardcode this homelab's known topology.
const AGENT_HOSTS = {
  opti:        { label: 'opti',        base: 'http://192.168.1.11:8787' },
  rpi:         { label: 'rpi',         base: 'http://192.168.1.10:8787' },
  noblenumbat: { label: 'noblenumbat', base: 'http://192.168.1.6:8787' },
};

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
    const merged = architecture.buildMergedData();
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

// GET /api/agents — one entry per configured host, with a live /status read.
// Never lets one unreachable agent break the list — an unreachable host is a row
// that says so, not a 500 for the whole page.
router.get('/', async (req, res) => {
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
        // how the cockpit tab detects "needs v0.4.0" and disables its buttons.
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
  res.json({ hosts, checked_at: new Date().toISOString() });
});

// POST /api/agents/:host/sync — Force Sync for one host. Blocks until the agent
// actually finishes (its own /sync is synchronous) and returns the real result —
// never a fire-and-forget "queued" the way the dispatcher's run-now does, because a
// single host's sync is fast enough (~seconds) to just wait for.
router.post('/:host/sync', async (req, res) => {
  const cfg = AGENT_HOSTS[req.params.host];
  if (!cfg) return res.status(404).json({ error: `unknown agent host '${req.params.host}'` });

  try {
    const r = await agentFetch(`${cfg.base}/sync`, { method: 'POST', timeoutMs: SYNC_TIMEOUT_MS });
    res.status(r.ok ? 200 : 502).json({ host: req.params.host, ...r.data });
  } catch (e) {
    res.status(502).json({ host: req.params.host, ok: false, error: e.message });
  }
});

// POST /api/agents/sync-all — same, fanned out to every configured host in parallel.
// Partial failure is expected and reported per-host, not surfaced as one opaque error.
router.post('/sync-all', async (req, res) => {
  const results = await Promise.all(Object.keys(AGENT_HOSTS).map(async (host) => {
    try {
      const r = await agentFetch(`${AGENT_HOSTS[host].base}/sync`,
        { method: 'POST', timeoutMs: SYNC_TIMEOUT_MS });
      return { host, ...r.data, ok: r.ok };
    } catch (e) {
      return { host, ok: false, error: e.message };
    }
  }));
  res.json({ results, checked_at: new Date().toISOString() });
});

// POST /api/agents/:host/restart-container — restart one container on that host via
// its agent's /restart (agent v0.2.0+). The agent validates the name against its own
// `docker ps -a` and requires a bearer token, so this proxy stays thin.
// Timeout is generous: a real `docker restart` on a heavy container takes ~10-15s and
// the agent blocks until it finishes, but stays well inside the 240s read timeout the
// /api/agents/ location gets in nginx-wg.conf (raised there for update-container).
//
// AUTH POSTURE (deliberate, reviewed 2026-07-26 — see webapp/BUGS.md B3): this route,
// like every other write on this dashboard (samba config save, runner run-now, bot
// send-now), trusts the LAN. The agent-side bearer token protects the AGENTS from
// arbitrary LAN callers; the webapp is the intended caller. If the dashboard ever
// becomes reachable beyond the LAN, gate the POST routes at nginx first.
router.post('/:host/restart-container', async (req, res) => {
  const cfg = AGENT_HOSTS[req.params.host];
  if (!cfg) return res.status(404).json({ error: `unknown agent host '${req.params.host}'` });
  const container = req.body?.container;
  if (typeof container !== 'string' || !container.trim()) {
    return res.status(400).json({ error: 'body.container is required' });
  }

  try {
    const r = await agentFetch(`${cfg.base}/restart`, {
      method: 'POST', timeoutMs: 55000, body: { container: container.trim() },
    });
    res.status(r.status).json({ host: req.params.host, ...r.data });
  } catch (e) {
    // Distinguish "the agent never answered" from "the agent said no" — the frontend
    // maps these to different toasts.
    res.status(502).json({
      host: req.params.host, ok: false,
      error: /abort|timeout/i.test(e.message)
        ? `agent on ${req.params.host} did not respond in time (restart may still be running)`
        : `agent on ${req.params.host} unreachable: ${e.message}`,
    });
  }
});

// POST /api/agents/:host/update-container — pull the newest image for one container's
// compose service and recreate just that service, via the agent's /update (v0.3.0+).
// The agent does all the validating (name exists, compose labels present, build-only
// service refused, bind mounts reachable), so this proxy stays as thin as the restart
// one. The same LAN-trust posture noted above applies.
//
// The timeout is the big difference: a registry pull on the Pi can genuinely run for
// minutes, so this sits under nginx's 240s /api/agents/ read timeout and above the
// agent's own worst case (140s pull + 45s recreate).
const UPDATE_TIMEOUT_MS = 220000;
router.post('/:host/update-container', async (req, res) => {
  const cfg = AGENT_HOSTS[req.params.host];
  if (!cfg) return res.status(404).json({ error: `unknown agent host '${req.params.host}'` });
  const container = req.body?.container;
  if (typeof container !== 'string' || !container.trim()) {
    return res.status(400).json({ error: 'body.container is required' });
  }

  try {
    const r = await agentFetch(`${cfg.base}/update`, {
      method: 'POST', timeoutMs: UPDATE_TIMEOUT_MS, body: { container: container.trim() },
    });
    res.status(r.status).json({ host: req.params.host, ...r.data });
  } catch (e) {
    res.status(502).json({
      host: req.params.host, ok: false,
      error: /abort|timeout/i.test(e.message)
        ? `agent on ${req.params.host} did not respond in time (the update may still be running — check the containers panel in a minute)`
        : `agent on ${req.params.host} unreachable: ${e.message}`,
    });
  }
});

// ── Cockpit host controls (agent v0.4.0) ─────────────────────────────────────
// Thin proxies like restart/update-container above; the agent does the validating
// (host-mismatch guard, ZFS reboot guard, unit allowlist) and requires the bearer
// token. The same LAN-trust posture applies — see BUGS.md B3.

// POST /api/agents/:host/reboot — reboot the host. The body echoes the host name so
// the agent can refuse a proxy/route mixup (its own HOST must match). The agent
// responds BEFORE rebooting (~2s grace), so even an rpi reboot returns a real 200.
router.post('/:host/reboot', async (req, res) => {
  const cfg = AGENT_HOSTS[req.params.host];
  if (!cfg) return res.status(404).json({ error: `unknown agent host '${req.params.host}'` });
  try {
    const r = await agentFetch(`${cfg.base}/reboot`, {
      method: 'POST', timeoutMs: 15000, body: { host: req.params.host },
    });
    res.status(r.status).json({ host: req.params.host, ...r.data });
  } catch (e) {
    res.status(502).json({
      host: req.params.host, ok: false,
      error: `agent on ${req.params.host} unreachable: ${e.message}`,
    });
  }
});

// POST /api/agents/:host/apt-upgrade — kick the nightly homelab-autoupdate unit now.
// Fast by design: the agent starts the unit and returns; progress is polled via
// GET /:host/apt-status below, so no long request is ever held open.
router.post('/:host/apt-upgrade', async (req, res) => {
  const cfg = AGENT_HOSTS[req.params.host];
  if (!cfg) return res.status(404).json({ error: `unknown agent host '${req.params.host}'` });
  try {
    const r = await agentFetch(`${cfg.base}/apt-upgrade`, { method: 'POST', timeoutMs: 10000 });
    res.status(r.status).json({ host: req.params.host, ...r.data });
  } catch (e) {
    res.status(502).json({
      host: req.params.host, ok: false,
      error: `agent on ${req.params.host} unreachable: ${e.message}`,
    });
  }
});

// GET /api/agents/:host/apt-status — unit state + log tail + reboot-required flag.
router.get('/:host/apt-status', async (req, res) => {
  const cfg = AGENT_HOSTS[req.params.host];
  if (!cfg) return res.status(404).json({ error: `unknown agent host '${req.params.host}'` });
  try {
    const r = await agentFetch(`${cfg.base}/apt-status`, { timeoutMs: 8000 });
    res.status(r.status).json({ host: req.params.host, ...r.data });
  } catch (e) {
    res.status(502).json({
      host: req.params.host, ok: false,
      error: `agent on ${req.params.host} unreachable: ${e.message}`,
    });
  }
});

// POST /api/agents/:host/restart-service — restart one allowlisted systemd unit.
// Timeout ladder must nest: agent restart cap 120s < this 160s < nginx 240s (the
// slow case is docker.service on opti, which restarts every container it runs).
router.post('/:host/restart-service', async (req, res) => {
  const cfg = AGENT_HOSTS[req.params.host];
  if (!cfg) return res.status(404).json({ error: `unknown agent host '${req.params.host}'` });
  const unit = req.body?.unit;
  if (typeof unit !== 'string' || !unit.trim()) {
    return res.status(400).json({ error: 'body.unit is required' });
  }
  try {
    const r = await agentFetch(`${cfg.base}/service-restart`, {
      method: 'POST', timeoutMs: 160000, body: { unit: unit.trim() },
    });
    res.status(r.status).json({ host: req.params.host, ...r.data });
  } catch (e) {
    res.status(502).json({
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
router.post('/:host/wake', async (req, res) => {
  const host = req.params.host;
  if (!WAKE_TARGETS.includes(host)) {
    return res.status(404).json({ error: `'${host}' is not a wake target (no WoL-capable NIC)` });
  }
  const senders = Object.keys(AGENT_HOSTS).filter((h) => h !== host);
  const failures = [];
  for (const sender of senders) {
    try {
      const r = await agentFetch(`${AGENT_HOSTS[sender].base}/wake`, {
        method: 'POST', timeoutMs: 5000, body: { target: host },
      });
      if (r.ok) return res.json({ host, sent_by: sender, ...r.data });
      failures.push(`${sender}: HTTP ${r.status}`);
    } catch (e) {
      failures.push(`${sender}: ${e.message}`);
    }
  }
  res.status(502).json({
    host, ok: false,
    error: `no reachable agent to send the wake packet (${failures.join('; ')})`,
  });
});

// AGENT_HOSTS is the single source of truth for "which hosts run an agent";
// routes/vitals.js polls the same list rather than duplicating the IPs.
router.AGENT_HOSTS = AGENT_HOSTS;

module.exports = router;
