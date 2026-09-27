// hl-arch-agent sources — three per agent host:
//   vitals:<host>      15s  CPU/mem/load/temp/net, derived from the agent's raw counters
//   containers:<host>  15s  live `docker ps` via GET /containers (agent v0.7.0+)
//   agent:<host>       5m   agent status + auto-update hold state
'use strict';
const { AGENT_HOSTS } = require('../lib/hosts');

const TOKEN = process.env.HL_ARCH_INGEST_TOKEN || '';

async function agentGet(base, path, signal) {
  const headers = TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
  const res = await fetch(`${base}${path}`, { headers, signal });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

// Turn two raw agent readings into rates. The agent is stateless (cumulative counters),
// so the first reading after a restart has no CPU%/network rate — null, not a fake 0.
function derive(prev, cur) {
  const out = {
    t: cur.t,
    cores: cur.cores ?? null,
    load1: Array.isArray(cur.loadavg) ? cur.loadavg[0] : null,
    cpu_pct: null,
    mem_pct: null,
    mem_total_bytes: cur.mem?.total_bytes ?? null,
    temp_c: cur.temp_c ?? null,
    rx_bps: null,
    tx_bps: null,
    uptime_s: cur.uptime_s ?? null,
    agent_version: cur.agent_version ?? null,
  };
  if (cur.mem?.total_bytes && cur.mem.used_bytes != null) {
    out.mem_pct = Math.round((cur.mem.used_bytes / cur.mem.total_bytes) * 1000) / 10;
  }
  const dt = prev ? cur.t - prev.t : 0;
  if (!prev || dt <= 0) return out;
  if (prev.cpu && cur.cpu) {
    const dTotal = cur.cpu.total - prev.cpu.total;
    const dIdle = cur.cpu.idle - prev.cpu.idle;
    if (dTotal > 0 && dIdle >= 0) {
      out.cpu_pct = Math.max(0, Math.min(100, Math.round((1 - dIdle / dTotal) * 1000) / 10));
    }
  }
  if (prev.net && cur.net) {
    let rx = 0, tx = 0, ok = false;
    for (const [iface, c] of Object.entries(cur.net)) {
      const p = prev.net[iface];
      if (!p) continue;
      const dRx = c.rx_bytes - p.rx_bytes, dTx = c.tx_bytes - p.tx_bytes;
      if (dRx < 0 || dTx < 0) continue; // counter reset on this interface
      rx += dRx; tx += dTx; ok = true;
    }
    if (ok) { out.rx_bps = Math.round(rx / dt); out.tx_bps = Math.round(tx / dt); }
  }
  return out;
}

function registerAgentSources(snapshots) {
  for (const host of Object.values(AGENT_HOSTS)) {
    let prevRaw = null;
    snapshots.register({
      key: `vitals:${host.id}`, group: host.id, label: `${host.label} vitals`,
      intervalMs: 15_000, timeoutMs: 4000,
      fetch: async ({ signal }) => {
        try {
          const cur = await agentGet(host.agent, '/vitals', signal);
          if (typeof cur?.t !== 'number') throw new Error('malformed /vitals payload');
          const derived = derive(prevRaw, cur);
          prevRaw = cur;
          return derived;
        } catch (err) {
          prevRaw = null; // next success starts a fresh baseline instead of a huge delta
          throw err;
        }
      },
    });

    snapshots.register({
      key: `containers:${host.id}`, group: host.id, label: `${host.label} containers`,
      intervalMs: 15_000, timeoutMs: 6000,
      fetch: async ({ signal }) => {
        const d = await agentGet(host.agent, '/containers', signal);
        if (!Array.isArray(d?.containers)) throw new Error('malformed /containers payload');
        return { docker: d.docker !== false, containers: d.containers, error: d.error ?? null };
      },
    });

    snapshots.register({
      key: `agent:${host.id}`, group: host.id, label: `${host.label} agent`,
      intervalMs: 5 * 60_000, timeoutMs: 6000,
      fetch: async ({ signal }) => {
        const [status, autoupdate] = await Promise.all([
          agentGet(host.agent, '/status', signal),
          agentGet(host.agent, '/autoupdate', signal).catch(() => null),
        ]);
        return {
          agent_version: status.agent_version ?? null,
          allowed_units: status.allowed_units ?? [],
          wake_targets: status.wake_targets ?? [],
          last_sync: status.last_run?.ran_at ?? null,
          autoupdate: autoupdate && {
            mode: autoupdate.mode ?? null,
            held_by: autoupdate.flag?.by ?? null,
            held_at: autoupdate.flag?.at ?? null,
            will_run_unattended: autoupdate.will_run_unattended ?? null,
          },
        };
      },
    });
  }
}

module.exports = { registerAgentSources, derive };
