// Live per-host vitals for the sparklines — the poller half of v1's routes/vitals.js,
// now a real lifecycle plugin instead of an import side effect (which a lazy-loading
// rewrite could have silently killed — see the redesign plan's risk table).
//
// Why this exists: hardware-report runs ONCE A DAY, so CPU/memory numbers could be 24h
// stale and no sub-daily series existed anywhere. Each host's hl-arch-agent (v0.2.0+)
// exposes GET /vitals with RAW CUMULATIVE counters. This polls every 30s, diffs
// consecutive samples into rates and percentages, and keeps a per-host ring buffer.
// The agent stays stateless, so a restarted agent can't emit a bogus spike — a counter
// that goes backwards yields null (a gap), and the sparkline breaks its line there.
//
// Persistence: snapshotted to ARCH_DATA_DIR/vitals every 5 min, reloaded at boot, and
// — new in v2 — flushed once more in onClose, so a restart loses zero samples instead
// of up to five minutes' worth.
const fs = require('fs');
const path = require('path');
const fp = require('fastify-plugin');
const { AGENT_HOSTS } = require('../lib/hosts');
const { ARCH_DATA_DIR } = require('../lib/paths');

const TOKEN = process.env.HL_ARCH_INGEST_TOKEN || '';
const POLL_MS = 30_000;
const MAX_SAMPLES = 720;          // 6h at 30s — the high-resolution ring
const SNAPSHOT_MS = 5 * 60_000;
const MAX_AGE_MS = 6 * 3600_000;

// Second tier: 5-minute buckets covering 48h, so the UI can offer 9/24/48h ranges
// without multiplying the 30s ring (which would grind the rpi's SD card with
// megabyte snapshots). Buckets are per-metric AVERAGES of the 30s samples; an
// all-null bucket stays null so gaps still read as gaps.
const LONG_BUCKET_S = 300;
const LONG_MAX = 576;             // 48h at 5min
const LONG_AGE_MS = 48 * 3600_000;
const METRIC_KEYS = ['load1', 'cpu_pct', 'mem_pct', 'temp_c', 'rx_bps', 'tx_bps', 'uptime_s'];
const INT_KEYS = new Set(['rx_bps', 'tx_bps', 'uptime_s']);

const VITALS_DIR = path.join(ARCH_DATA_DIR, 'vitals');

// Diff two raw agent readings into a display sample. Any counter that moved backwards
// (agent restart, host reboot, counter wrap) yields null for that metric.
function derive(prev, cur) {
  const dt = cur.t - prev.t;
  const s = {
    t: cur.t,
    load1: Array.isArray(cur.loadavg) ? cur.loadavg[0] : null,
    cpu_pct: null, mem_pct: null, temp_c: cur.temp_c ?? null,
    rx_bps: null, tx_bps: null,
    // Carried through raw for the cockpit cards — a reset (small again) is the
    // observable proof that a requested reboot actually happened.
    uptime_s: cur.uptime_s ?? null,
  };
  if (dt <= 0) return s;

  if (prev.cpu && cur.cpu) {
    const dTotal = cur.cpu.total - prev.cpu.total;
    const dIdle = cur.cpu.idle - prev.cpu.idle;
    if (dTotal > 0 && dIdle >= 0) {
      s.cpu_pct = Math.max(0, Math.min(100, Math.round((1 - dIdle / dTotal) * 1000) / 10));
    }
  }
  if (cur.mem?.total_bytes && cur.mem.used_bytes != null) {
    s.mem_pct = Math.round((cur.mem.used_bytes / cur.mem.total_bytes) * 1000) / 10;
  }
  if (prev.net && cur.net) {
    let rx = 0, tx = 0, ok = false;
    for (const [iface, c] of Object.entries(cur.net)) {
      const p = prev.net[iface];
      if (!p) continue;
      const dRx = c.rx_bytes - p.rx_bytes, dTx = c.tx_bytes - p.tx_bytes;
      if (dRx < 0 || dTx < 0) continue;   // counter reset — skip this interface
      rx += dRx; tx += dTx; ok = true;
    }
    if (ok) { s.rx_bps = Math.round(rx / dt); s.tx_bps = Math.round(tx / dt); }
  }
  return s;
}

module.exports = fp(async function vitalsPoller(app) {
  // host -> { samples: [30s ring], long: [5min ring], bucket: <accumulator>,
  //           prev: <raw counters>, lastError: string|null }
  const state = {};
  for (const h of Object.keys(AGENT_HOSTS)) {
    state[h] = { samples: [], long: [], bucket: null, prev: null, lastError: null };
  }

  const roundFor = (k, v) => (INT_KEYS.has(k) ? Math.round(v) : Math.round(v * 10) / 10);

  function flushBucket(st) {
    if (!st.bucket) return;
    const out = { t: st.bucket.t };
    for (const k of METRIC_KEYS) {
      out[k] = st.bucket.n[k] ? roundFor(k, st.bucket.acc[k] / st.bucket.n[k]) : null;
    }
    st.long.push(out);
    if (st.long.length > LONG_MAX) st.long.splice(0, st.long.length - LONG_MAX);
    st.bucket = null;
  }

  // Fold one 30s sample into the current 5-minute bucket, flushing on boundary.
  function pushLong(st, s) {
    const t = Math.floor(s.t / LONG_BUCKET_S) * LONG_BUCKET_S;
    if (st.bucket && st.bucket.t !== t) flushBucket(st);
    if (!st.bucket) st.bucket = { t, acc: {}, n: {} };
    for (const k of METRIC_KEYS) {
      const v = s[k];
      if (v != null) {
        st.bucket.acc[k] = (st.bucket.acc[k] ?? 0) + v;
        st.bucket.n[k] = (st.bucket.n[k] ?? 0) + 1;
      }
    }
  }

  function loadSnapshots() {
    for (const host of Object.keys(AGENT_HOSTS)) {
      const st = state[host];
      try {
        const raw = JSON.parse(fs.readFileSync(path.join(VITALS_DIR, `${host}.json`), 'utf8'));
        const cutoff = Date.now() - MAX_AGE_MS;
        st.samples = (raw.samples || []).filter(s => s.t * 1000 > cutoff).slice(-MAX_SAMPLES);
        const longCutoff = Date.now() - LONG_AGE_MS;
        st.long = (raw.long || []).filter(s => s.t * 1000 > longCutoff).slice(-LONG_MAX);
      } catch (_) { /* first boot, or no snapshot yet */ }

      // First run after this feature (or a lost long ring): rebuild what we can
      // from the 30s ring, so the long ranges aren't empty for hours.
      if (st.long.length === 0 && st.samples.length > 0) {
        for (const s of st.samples) pushLong(st, s);
        // the trailing partial bucket stays in the accumulator and flushes live
      }
    }
  }

  function writeSnapshots() {
    try { fs.mkdirSync(VITALS_DIR, { recursive: true }); } catch (_) { return; }
    for (const [host, st] of Object.entries(state)) {
      if (!st.samples.length && !st.long.length) continue;
      try {
        const tmp = path.join(VITALS_DIR, `${host}.json.tmp`);
        fs.writeFileSync(tmp, JSON.stringify({ host, samples: st.samples, long: st.long }));
        fs.renameSync(tmp, path.join(VITALS_DIR, `${host}.json`));
      } catch (_) { /* best-effort — never break polling over a failed write */ }
    }
  }

  async function pollHost(host) {
    const st = state[host];
    try {
      const headers = {};
      if (TOKEN) headers['Authorization'] = `Bearer ${TOKEN}`;
      const res = await fetch(`${AGENT_HOSTS[host].base}/vitals`, {
        headers, signal: AbortSignal.timeout(2500),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const cur = await res.json();
      if (typeof cur?.t !== 'number') throw new Error('malformed vitals payload');

      st.agent_version = cur.agent_version || null;
      st.cores = cur.cores || null;
      if (st.prev) {
        const s = derive(st.prev, cur);
        st.samples.push(s);
        if (st.samples.length > MAX_SAMPLES) st.samples.splice(0, st.samples.length - MAX_SAMPLES);
        pushLong(st, s);
      }
      st.prev = cur;
      st.lastError = null;
    } catch (e) {
      // A failed poll pushes NOTHING — the gap is the honest representation of
      // "we don't know", and the chart draws a break rather than a flat line.
      st.lastError = e.message;
      st.prev = null;   // force a fresh baseline so the next sample isn't a huge delta
    }
  }

  let pollTimer = null, snapTimer = null;

  app.decorate('vitals', { state, POLL_MS, MAX_SAMPLES, LONG_BUCKET_S, LONG_MAX });

  // VITALS_DISABLED short-circuits the network side for inject tests and smoke runs —
  // the routes still serve whatever (empty) state exists.
  app.addHook('onReady', async () => {
    if (process.env.VITALS_DISABLED === '1') return;
    loadSnapshots();
    const pollAll = () => { for (const h of Object.keys(AGENT_HOSTS)) pollHost(h); };
    pollAll();
    pollTimer = setInterval(pollAll, POLL_MS);
    pollTimer.unref();
    snapTimer = setInterval(writeSnapshots, SNAPSHOT_MS);
    snapTimer.unref();
  });

  app.addHook('onClose', async () => {
    if (pollTimer) clearInterval(pollTimer);
    if (snapTimer) clearInterval(snapTimer);
    writeSnapshots();   // final flush — a restart loses zero samples
  });
}, { name: 'vitals-poller' });
