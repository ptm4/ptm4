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

async function agentFetch(url, { method = 'GET', timeoutMs = STATUS_TIMEOUT_MS } = {}) {
  const headers = {};
  if (TOKEN) headers['Authorization'] = `Bearer ${TOKEN}`;
  const res = await fetch(url, { method, headers, signal: AbortSignal.timeout(timeoutMs) });
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

module.exports = router;
