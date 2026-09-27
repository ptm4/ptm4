// Snapshot cache — Pertal's one load-bearing rule: no request ever waits on an upstream.
//
// Every data source registers here with its own interval and timeout. A background
// poller refreshes it and stores {data, fetched_at, ok, error}. Routes and the UI only
// ever read the stored copy, so a slow or dead upstream costs one grey card, never a
// hung page (v3's "stale or wrong data" and "page hangs" both came from routes that
// awaited upstreams inline).
//
// A failed refresh KEEPS the last good data and flips ok=false. Staleness is computed at
// read time from fetched_at, so the UI can say "4 min old" instead of pretending.
'use strict';

function createSnapshots({ onChange = () => {} } = {}) {
  const sources = new Map();
  let started = false;

  function register(def) {
    const { key, intervalMs, fetch } = def;
    if (!key || typeof fetch !== 'function' || !(intervalMs > 0)) {
      throw new Error(`snapshot '${key}': key, fetch and intervalMs are required`);
    }
    if (sources.has(key)) throw new Error(`snapshot '${key}' registered twice`);
    sources.set(key, {
      def: {
        key,
        label: def.label ?? key,
        group: def.group ?? null,
        intervalMs,
        timeoutMs: def.timeoutMs ?? 5000,
        staleAfterMs: def.staleAfterMs ?? intervalMs * 3,
        fetch,
      },
      data: null,
      ok: null,
      error: null,
      fetchedAt: null,
      tookMs: null,
      failures: 0,
      inflight: null,
      timer: null,
    });
    if (started) schedule(sources.get(key));
  }

  function meta(key, now = Date.now()) {
    const s = sources.get(key);
    if (!s) return null;
    const age = s.fetchedAt ? now - s.fetchedAt : null;
    return {
      key,
      label: s.def.label,
      group: s.def.group,
      ok: s.ok,
      error: s.error,
      fetched_at: s.fetchedAt ? new Date(s.fetchedAt).toISOString() : null,
      age_ms: age,
      stale: age == null || age > s.def.staleAfterMs,
      interval_ms: s.def.intervalMs,
      stale_after_ms: s.def.staleAfterMs,
      failures: s.failures,
      took_ms: s.tookMs,
    };
  }

  const get = (key) => (sources.has(key) ? { meta: meta(key), data: sources.get(key).data } : null);
  const data = (key) => sources.get(key)?.data ?? null;
  const keys = () => [...sources.keys()];
  const metas = () => Object.fromEntries(keys().map((k) => [k, meta(k)]));

  // Refresh one source. Concurrent callers share the in-flight attempt, and a fetch that
  // ignores its AbortSignal still cannot hold the snapshot past its deadline.
  function refresh(key) {
    const s = sources.get(key);
    if (!s) return Promise.reject(new Error(`unknown snapshot '${key}'`));
    if (s.inflight) return s.inflight;
    s.inflight = (async () => {
      const t0 = Date.now();
      const ac = new AbortController();
      let timer;
      try {
        const deadline = new Promise((_, reject) => {
          timer = setTimeout(() => {
            ac.abort();
            reject(new Error(`timed out after ${s.def.timeoutMs} ms`));
          }, s.def.timeoutMs);
        });
        const result = await Promise.race([s.def.fetch({ signal: ac.signal, previous: s.data }), deadline]);
        s.data = result;
        s.ok = true;
        s.error = null;
        s.fetchedAt = Date.now();
        s.failures = 0;
      } catch (err) {
        s.ok = false;
        s.error = err?.message || String(err);
        s.failures += 1;
      } finally {
        clearTimeout(timer);
        s.tookMs = Date.now() - t0;
        s.inflight = null;
      }
      try { onChange(key, get(key)); } catch (_) { /* a listener must never break polling */ }
      return get(key);
    })();
    return s.inflight;
  }

  const refreshGroup = (group) =>
    Promise.all(keys().filter((k) => sources.get(k).def.group === group).map(refresh));

  function schedule(s) {
    refresh(s.def.key);
    s.timer = setInterval(() => refresh(s.def.key), s.def.intervalMs);
    s.timer.unref?.();
  }

  function start() {
    if (started) return;
    started = true;
    for (const s of sources.values()) schedule(s);
  }

  function stop() {
    started = false;
    for (const s of sources.values()) {
      clearInterval(s.timer);
      s.timer = null;
    }
  }

  return { register, get, data, meta, metas, keys, refresh, refreshGroup, start, stop };
}

module.exports = { createSnapshots };
