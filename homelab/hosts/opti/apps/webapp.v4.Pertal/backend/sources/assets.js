// Asset Library: E:\Assets on the workstation (ptm), served read-only by
// homelab/hosts/ptm/asset-server. ptm is a dual-boot desktop, so "not answering" is its
// normal state whenever it is off, asleep or in Linux. This source records that as data
// (online: false) instead of failing: it stays off the Status page's issues and out of
// the Activity feed, and the Asset Library page is the one place that says so.
//   assets:server  30s  the asset server's /health (top folders, index size, thumbnails)
'use strict';

const ASSET_SERVER_URL = (process.env.ASSET_SERVER_URL || 'http://192.168.1.3:8767').replace(/\/+$/, '');

// Plain words for a failed call to ptm. A stopped server behind the Windows firewall
// looks the same as a sleeping PC (the SYN is dropped), so timeouts don't guess.
function describe(err) {
  const code = err?.cause?.code || err?.code;
  if (err?.name === 'TimeoutError' || code === 'ETIMEDOUT' || code === 'UND_ERR_CONNECT_TIMEOUT' || code === 'EHOSTUNREACH') {
    return 'ptm is not answering: it is off, asleep or in Linux, or the asset server is not running';
  }
  if (code === 'ECONNREFUSED') return 'ptm refused the connection: it is in Linux, or the asset server is not running';
  return `asset server on ptm: ${err?.message || err}`;
}

function registerAssetSources(snapshots) {
  snapshots.register({
    key: 'assets:server', group: 'assets', label: 'Asset Library (ptm)',
    intervalMs: 30_000, timeoutMs: 5000, staleAfterMs: 2 * 60_000,
    // Never throws: offline is an answer. Its own 3.5 s timeout beats the snapshot's 5 s.
    fetch: async ({ signal, previous }) => {
      const checked_at = new Date().toISOString();
      try {
        const res = await fetch(`${ASSET_SERVER_URL}/health`, { signal: AbortSignal.any([signal, AbortSignal.timeout(3500)]) });
        if (!res.ok) throw new Error(`/health answered HTTP ${res.status}`);
        const health = await res.json();
        return { online: true, checked_at, last_seen_at: checked_at, error: null, health };
      } catch (err) {
        return {
          online: false, checked_at, error: describe(err),
          last_seen_at: previous?.last_seen_at ?? null,
          health: previous?.health ?? null, // what it looked like when last seen
        };
      }
    },
  });
}

module.exports = { registerAssetSources, ASSET_SERVER_URL, describe };
