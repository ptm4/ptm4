// A 60-second in-process cache in front of the app's own /api/hldb/* proxy, for
// callers that run on a timer (incidents, the feed poller). The rule for anything
// that polls: cache at the source, so an open dashboard never turns into a
// request per second against homelab-db on opti.
const TTL_MS = 60_000;
const cache = new Map();      // urlPath → { at, data, status } — the freshness window
const lastGood = new Map();   // urlPath → the last entry that actually carried data

// True for a response we would be willing to show a user. A 2xx with an unparseable
// (null) body is not one: /guide reads fields straight off `data`.
const usable = (e) => e.status >= 200 && e.status < 300 && e.data != null;

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
  if (usable(entry)) {
    lastGood.set(urlPath, entry);
    cache.set(urlPath, entry);
    return entry;
  }
  // A failed refresh must not erase an answer we already have. This used to cache
  // the failure, so a single upstream blip blanked every caller for the whole TTL —
  // the dashboard's Streams guide visibly "coming and going" was exactly that.
  // Serve the last good payload instead, flagged `stale` so callers can say so, and
  // deliberately do NOT write the failure into `cache`: the next call retries at once
  // rather than sitting on the error for a minute.
  const prev = lastGood.get(urlPath);
  if (prev) return { ...prev, stale: true, error: entry.error || `HTTP ${entry.status}` };
  cache.set(urlPath, entry);
  return entry;
}

module.exports = { cachedInject, TTL_MS };
