// /api/assets — the Asset Library page: E:\Assets on the workstation (ptm), read-only.
//
// status reads the snapshot. list and search ask the PC on demand (a 100k-file tree is
// too big to poll into memory), so, like logs, each carries a hard timeout and a plain
// error body. File bytes never pass through Pertal: nginx proxies /asset-files and
// /asset-thumbs straight to the PC, the same shape as /hls.
'use strict';
const { ASSET_SERVER_URL, describe } = require('../sources/assets');

// The asset server applies the full checks; this only keeps obviously bad input on opti.
function cleanPath(p) {
  if (p === undefined || p === null) return '';
  if (typeof p !== 'string' || p.length > 1024 || /[\u0000-\u001f\\:*?"<>|]/.test(p)) return null;
  const segs = p.split('/').filter(Boolean);
  if (segs.some((s) => s === '.' || s === '..' || s.startsWith('.'))) return null;
  return segs.join('/');
}

module.exports = async function assetRoutes(app) {
  app.get('/status', async () => {
    const d = app.snapshots.get('assets:server')?.data;
    return {
      online: d?.online ?? null, // null until the first check
      checked_at: d?.checked_at ?? null,
      last_seen_at: d?.last_seen_at ?? null,
      error: d?.error ?? null,
      server: d?.health ?? null,
    };
  });

  async function relay(reply, path, timeoutMs) {
    try {
      const res = await fetch(`${ASSET_SERVER_URL}${path}`, { signal: AbortSignal.timeout(timeoutMs) });
      const body = await res.json().catch(() => ({}));
      if (!res.ok && !body.error) body.error = `the asset server answered HTTP ${res.status}`;
      return reply.code(res.status).send(body);
    } catch (err) {
      app.snapshots.refresh('assets:server').catch(() => {}); // the page's status catches up now
      if (err?.name === 'TimeoutError') {
        return reply.code(504).send({ error: `ptm took longer than ${timeoutMs / 1000}s to answer`, offline: false });
      }
      return reply.code(503).send({ error: describe(err), offline: true });
    }
  }

  // GET /api/assets/list?path=DND5E/characters  — one folder (the PC reads it live)
  app.get('/list', async (req, reply) => {
    const path = cleanPath(req.query.path);
    if (path === null) return reply.code(400).send({ error: 'bad path' });
    return relay(reply, `/api/list?path=${encodeURIComponent(path)}`, 15_000);
  });

  // GET /api/assets/search?q=goblin glb&limit=200  — the PC's in-memory index
  app.get('/search', async (req, reply) => {
    const q = String(req.query.q ?? '').trim();
    if (q.length < 1 || q.length > 200) return reply.code(400).send({ error: 'q must be 1-200 characters' });
    const limit = Math.max(1, Math.min(500, Number(req.query.limit) || 200));
    return relay(reply, `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`, 10_000);
  });
};

module.exports.cleanPath = cleanPath;
