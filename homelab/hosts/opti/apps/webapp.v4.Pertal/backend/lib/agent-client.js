// The one HTTP client for hl-arch-agent (port 8787 on each host in lib/hosts.js).
// Shared by routes/agents.js (Cockpit controls) and routes/maintenance.js (Settings).
// The bearer token is the agents' own gate against arbitrary LAN callers — see the
// AUTH POSTURE note at the top of routes/agents.js.
const TOKEN = process.env.HL_ARCH_INGEST_TOKEN || '';

async function agentFetch(url, { method = 'GET', timeoutMs = 4000, body } = {}) {
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

module.exports = { agentFetch };
