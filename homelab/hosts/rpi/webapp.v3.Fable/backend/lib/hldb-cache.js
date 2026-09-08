// A 60-second in-process cache in front of the app's own /api/hldb/* proxy, for
// callers that run on a timer (incidents, the feed poller). The rule for anything
// that polls: cache at the source, so an open dashboard never turns into a
// request per second against homelab-db on opti.
const TTL_MS = 60_000;
const cache = new Map();   // urlPath → { at, data, status }

async function cachedInject(app, urlPath, ttlMs = TTL_MS) {
  const hit = cache.get(urlPath);
  if (hit && Date.now() - hit.at < ttlMs) return hit;
  let entry;
  try {
    const r = await app.inject({ method: 'GET', url: urlPath });
    let data = null;
    try { data = r.json(); } catch (_) { data = null; }
    entry = { at: Date.now(), status: r.statusCode, data };
  } catch (e) {
    entry = { at: Date.now(), status: 0, data: null, error: e.message };
  }
  cache.set(urlPath, entry);
  return entry;
}

module.exports = { cachedInject, TTL_MS };
