// Live per-host vitals for the Home sparklines.
//
// Why this exists: hardware-report runs ONCE A DAY (see .github/workflows/homelab-agents.yml),
// so the Home tiles' CPU/memory numbers could be 24h stale and no sub-daily series existed
// anywhere — the dated report history is one file per day, overwritten intraday.
//
// Shape of the pipeline: each host's hl-arch-agent (v0.2.0+) exposes GET /vitals with RAW
// CUMULATIVE counters. This module polls every 30s, diffs consecutive samples into rates
// and percentages, and keeps a per-host ring buffer. The agent stays stateless, so a
// restarted agent can't emit a bogus spike — a counter that goes backwards yields null
// (a gap), and the sparkline breaks its line there rather than inventing a value.
//
// Persistence: the buffer is snapshotted to /arch-data (the container's only writable
// mount) every 5 min and reloaded at boot, so a webapp restart doesn't blank the charts.
const express = require('express');
const fs = require('fs');
const path = require('path');
const agents = require('./agents');

const router = express.Router();

const HOSTS = agents.AGENT_HOSTS;
const TOKEN = process.env.HL_ARCH_INGEST_TOKEN || '';
const POLL_MS = 30_000;
const MAX_SAMPLES = 720;          // 6h at 30s
const SNAPSHOT_MS = 5 * 60_000;
const MAX_AGE_MS = 6 * 3600_000;

const ARCH_DATA_DIR = fs.existsSync('/arch-data')
  ? '/arch-data'
  : path.join(__dirname, '..', '..', '..', '..', '..', 'arch-data-dev');
const VITALS_DIR = path.join(ARCH_DATA_DIR, 'vitals');

// host -> { samples: [...], prev: <raw counters>, lastError: string|null }
const state = {};
for (const h of Object.keys(HOSTS)) state[h] = { samples: [], prev: null, lastError: null };

function loadSnapshots() {
  for (const host of Object.keys(HOSTS)) {
    try {
      const raw = JSON.parse(fs.readFileSync(path.join(VITALS_DIR, `${host}.json`), 'utf8'));
      const cutoff = Date.now() - MAX_AGE_MS;
      const samples = (raw.samples || []).filter(s => s.t * 1000 > cutoff);
      state[host].samples = samples.slice(-MAX_SAMPLES);
    } catch (_) { /* first boot, or no snapshot yet */ }
  }
}

function writeSnapshots() {
  try { fs.mkdirSync(VITALS_DIR, { recursive: true }); } catch (_) { return; }
  for (const [host, st] of Object.entries(state)) {
    if (!st.samples.length) continue;
    try {
      const tmp = path.join(VITALS_DIR, `${host}.json.tmp`);
      fs.writeFileSync(tmp, JSON.stringify({ host, samples: st.samples }));
      fs.renameSync(tmp, path.join(VITALS_DIR, `${host}.json`));
    } catch (_) { /* best-effort — never break polling over a failed write */ }
  }
}

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

async function pollHost(host) {
  const st = state[host];
  try {
    const headers = {};
    if (TOKEN) headers['Authorization'] = `Bearer ${TOKEN}`;
    const res = await fetch(`${HOSTS[host].base}/vitals`, {
      headers, signal: AbortSignal.timeout(2500),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const cur = await res.json();
    if (typeof cur?.t !== 'number') throw new Error('malformed vitals payload');

    st.agent_version = cur.agent_version || null;
    st.cores = cur.cores || null;
    if (st.prev) {
      st.samples.push(derive(st.prev, cur));
      if (st.samples.length > MAX_SAMPLES) st.samples.splice(0, st.samples.length - MAX_SAMPLES);
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

let started = false;
function start() {
  if (started) return;
  started = true;
  loadSnapshots();
  const pollAll = () => { for (const h of Object.keys(HOSTS)) pollHost(h); };
  pollAll();
  setInterval(pollAll, POLL_MS).unref();
  setInterval(writeSnapshots, SNAPSHOT_MS).unref();
}
start();

// GET /api/vitals — rollup: latest sample + buffer depth per host
router.get('/', (req, res) => {
  const hosts = {};
  for (const [host, st] of Object.entries(state)) {
    hosts[host] = {
      count: st.samples.length,
      latest: st.samples[st.samples.length - 1] || null,
      agent_version: st.agent_version || null,
      error: st.lastError,
    };
  }
  res.json({ hosts, interval_s: POLL_MS / 1000, generated_at: new Date().toISOString() });
});

// GET /api/vitals/:host?points=240
router.get('/:host', (req, res) => {
  const st = state[req.params.host];
  if (!st) return res.status(404).json({ error: `unknown host '${req.params.host}'` });
  const points = Math.min(parseInt(req.query.points, 10) || 240, MAX_SAMPLES);
  res.json({
    host: req.params.host,
    interval_s: POLL_MS / 1000,
    cores: st.cores || null,
    agent_version: st.agent_version || null,
    error: st.lastError,
    samples: st.samples.slice(-points),
    latest: st.samples[st.samples.length - 1] || null,
  });
});

module.exports = router;
