// homelab-db (:9100 on opti) — collector findings and the doctor's latest verdict.
// One source, one call: GET /api/status is the same payload as the hl_status MCP tool.
'use strict';

const URL_BASE = process.env.HOMELAB_DB_URL || '';
const TOKEN = process.env.HL_DB_TOKEN || '';

// The same finding is re-raised by every ingest cycle; keep the newest per message.
function dedupeFindings(findings) {
  const byKey = new Map();
  for (const f of findings || []) {
    const key = `${f.host ?? ''}|${f.message}`;
    const prev = byKey.get(key);
    if (!prev || String(f.run_at) > String(prev.run_at)) byKey.set(key, f);
  }
  return [...byKey.values()].sort((a, b) => String(b.run_at).localeCompare(String(a.run_at)));
}

function registerHldbSource(snapshots) {
  if (!URL_BASE) return false;
  snapshots.register({
    key: 'hldb:status', group: 'hldb', label: 'homelab-db findings',
    intervalMs: 60_000, timeoutMs: 8000, staleAfterMs: 5 * 60_000,
    fetch: async ({ signal }) => {
      const res = await fetch(`${URL_BASE}/api/status`, {
        headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
        signal,
      });
      if (!res.ok) throw new Error(`homelab-db: HTTP ${res.status}`);
      const d = await res.json();
      return {
        doctor: d.doctor ?? null,
        services: d.services ?? [],
        findings: dedupeFindings(d.open_findings),
        stale_datasets: d.stale_datasets ?? [],
      };
    },
  });
  return true;
}

module.exports = { registerHldbSource, dedupeFindings };
