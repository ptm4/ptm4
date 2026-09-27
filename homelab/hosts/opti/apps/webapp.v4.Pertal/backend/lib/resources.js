// The resource model — the Azure-portal idea Pertal borrows. Every host and container
// is a resource with the same shape, so one page template, one search index and one
// command bar serve all of them. Built purely from snapshots (never from a live call),
// and rebuilt whenever a snapshot changes.
//
// Status vocabulary, and the rule behind it ("healthy is quiet"):
//   ok       fine — renders without colour
//   warn     wants attention eventually
//   crit     wants attention now
//   unknown  we don't have fresh enough data to say — never shown as ok
//   offline  expected to be off sometimes (android) — not an issue
'use strict';
const { HOSTS } = require('./hosts');

const RANK = { ok: 0, offline: 0, unknown: 1, warn: 2, crit: 3 };
const worse = (a, b) => (RANK[b] > RANK[a] ? b : a);

const BOT_RE = /^discord-/;
const INFRA = new Set(['dozzle', 'dozzle-agent', 'nginx-webapp', 'nginx-bitwarden', 'portainer',
  'gluetun', 'pihole', 'uptime-kuma', 'ntfy', 'flaresolverr', 'webapp']);
const kindOf = (name) => (BOT_RE.test(name) ? 'bot' : INFRA.has(name) ? 'infra' : 'app');

const findingSeverity = (f) => (f.severity === 'critical' ? 'crit' : f.severity === 'warn' ? 'warn' : null);
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function fmtUptime(s) {
  if (s == null) return null;
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} m` : `${m} m`;
}

function containerStatus(c) {
  const st = c.state;
  if (st === 'running') {
    if (c.health === 'unhealthy') return ['warn', 'unhealthy'];
    if (c.health === 'starting') return ['ok', 'starting'];
    return ['ok', c.health === 'healthy' ? 'healthy' : 'running'];
  }
  if (st === 'restarting') return ['warn', 'restarting'];
  if (st === 'paused') return ['warn', 'paused'];
  if (st === 'created') return ['warn', 'created, not started'];
  return ['crit', st || 'unknown state'];
}

function buildResources(snapshots) {
  const resources = [];
  const hldb = snapshots.get('hldb:status');
  const findings = hldb?.data?.findings || [];
  const claimed = new Set();

  for (const host of HOSTS) {
    const r = {
      id: host.id, type: 'host', kind: 'host', name: host.label, host: host.id,
      // `online` is reachability; `status` also folds in findings. A host with a
      // critical disk warning is still up — the two must never be conflated.
      status: 'ok', state_text: 'up', online: null, reasons: [],
      facts: [
        { label: 'IP', value: host.ip },
        { label: 'Role', value: host.role },
        { label: 'OS', value: host.os },
      ],
      metrics: null, counts: null, links: host.links, sources: [], updated_at: null,
    };
    const touch = (meta) => {
      if (!meta) return;
      r.sources.push(meta.key);
      if (meta.fetched_at && (!r.updated_at || meta.fetched_at > r.updated_at)) r.updated_at = meta.fetched_at;
    };

    if (host.agent) {
      const vitals = snapshots.get(`vitals:${host.id}`);
      const cont = snapshots.get(`containers:${host.id}`);
      const agent = snapshots.get(`agent:${host.id}`);
      touch(vitals?.meta); touch(cont?.meta); touch(agent?.meta);

      if (!vitals || vitals.meta.ok === null) {
        r.status = 'unknown'; r.state_text = 'waiting for first reading';
      } else if (!vitals.meta.ok && (vitals.meta.failures >= 2 || !vitals.data)) {
        r.status = 'crit'; r.state_text = 'not answering'; r.online = false;
        r.reasons.push({ severity: 'crit', text: `agent not answering: ${vitals.meta.error}`, source: vitals.meta.key });
      } else if (vitals.meta.stale) {
        r.status = 'unknown'; r.state_text = 'data is stale';
      } else {
        r.online = true;
      }
      if (vitals?.data) {
        const v = vitals.data;
        r.metrics = {
          cpu_pct: v.cpu_pct, mem_pct: v.mem_pct, load1: v.load1, cores: v.cores, temp_c: v.temp_c,
          uptime_s: v.uptime_s, rx_bps: v.rx_bps, tx_bps: v.tx_bps, mem_total_bytes: v.mem_total_bytes,
        };
        r.facts.push({ label: 'Uptime', value: fmtUptime(v.uptime_s) });
        if (r.online) r.state_text = `up ${fmtUptime(v.uptime_s)}`;
      }
      if (cont?.data?.containers) {
        const list = cont.data.containers;
        r.counts = { containers: list.length, running: list.filter((c) => c.state === 'running').length };
      }
      if (agent?.data) {
        const a = agent.data;
        r.facts.push({ label: 'Agent', value: a.agent_version ? `v${a.agent_version}` : 'unknown' });
        if (a.autoupdate?.mode === 'disabled') {
          r.facts.push({ label: 'Updates', value: `held since ${String(a.autoupdate.held_at || '').slice(0, 10)}`, tone: 'warn' });
        } else if (a.autoupdate?.mode) {
          r.facts.push({ label: 'Updates', value: 'nightly' });
        }
      }
    } else if (host.probe) {
      const probe = snapshots.get(`probe:${host.id}`);
      touch(probe?.meta);
      if (!probe?.data) { r.status = 'unknown'; r.state_text = 'not probed yet'; }
      else if (probe.data.reachable) { r.online = true; r.state_text = `reachable, ${probe.data.rtt_ms} ms`; }
      else {
        r.online = false;
        r.status = host.intermittent ? 'offline' : 'crit';
        r.state_text = host.intermittent ? 'offline (normal)' : 'unreachable';
      }
    }
    resources.push(r);

    // Containers on this host.
    const cont = host.agent ? snapshots.get(`containers:${host.id}`) : null;
    for (const c of cont?.data?.containers || []) {
      const [status, text] = containerStatus(c);
      const cr = {
        id: `${host.id}:${c.name}`, type: 'container', kind: kindOf(c.name), name: c.name, host: host.id,
        status: cont.meta.stale ? 'unknown' : status,
        state_text: cont.meta.stale ? `last seen ${text}` : text,
        reasons: status === 'ok' ? [] : [{ severity: status, text: `${c.name} is ${text}`, source: cont.meta.key }],
        facts: [
          { label: 'Image', value: c.image?.startsWith('sha256:') ? `${c.image.slice(0, 19)}…` : c.image },
          { label: 'Status', value: c.status },
          { label: 'Service', value: c.compose_service || '—' },
          { label: 'Ports', value: c.ports || '—' },
        ],
        state: c.state, health: c.health,
        metrics: null, counts: null, links: {}, sources: [cont.meta.key], updated_at: cont.meta.fetched_at,
      };
      resources.push(cr);
    }
  }

  // Attach homelab-db findings: to the container a message names, else to its host.
  const byName = resources.filter((r) => r.type === 'container');
  for (const f of findings) {
    const sev = findingSeverity(f);
    if (!sev) continue;
    const target =
      byName.find((c) => (!f.host || f.host === c.host) && new RegExp(`\\b${escapeRe(c.name)}\\b`).test(f.message)) ||
      resources.find((r) => r.type === 'host' && r.id === f.host);
    if (!target) continue;
    claimed.add(f);
    target.reasons.push({ severity: sev, text: f.message.replace(/^\[[^\]]+\]\s*/, ''), source: `hldb:${f.tool}`, at: f.run_at });
    target.status = worse(target.status, sev);
  }

  // status_text: what the list shows. The top reason when something is wrong, else the
  // plain state ("up 17 d", "healthy").
  for (const r of resources) {
    r.reasons.sort((a, b) => RANK[b.severity] - RANK[a.severity]);
    r.status_text = (r.status === 'warn' || r.status === 'crit') && r.reasons.length ? r.reasons[0].text : r.state_text;
  }

  return { resources, summary: summarize(resources, findings.filter((f) => !claimed.has(f)), snapshots) };
}

function summarize(resources, unclaimed, snapshots) {
  const hosts = resources.filter((r) => r.type === 'host');
  const containers = resources.filter((r) => r.type === 'container');
  const issues = [];
  for (const r of resources) {
    for (const why of r.reasons) {
      issues.push({ severity: why.severity, resource_id: r.id, resource: r.name, host: r.host, text: why.text, source: why.source, at: why.at ?? null });
    }
  }
  // Findings that name no resource, grouped per tool: 13 "NEW persistence entry" lines
  // are one issue with 13 details, not 13 issues.
  const groups = new Map();
  for (const f of unclaimed) {
    const sev = findingSeverity(f);
    if (!sev) continue;
    const key = `${f.tool}|${sev}`;
    if (!groups.has(key)) groups.set(key, { severity: sev, tool: f.tool, host: f.host ?? null, at: f.run_at, details: [] });
    const g = groups.get(key);
    g.details.push(f.message);
    if (String(f.run_at) > String(g.at)) g.at = f.run_at;
  }
  for (const g of groups.values()) {
    issues.push({
      severity: g.severity, resource_id: null, resource: g.tool, host: g.host,
      text: g.details.length === 1 ? g.details[0] : `${g.details.length} findings`,
      details: g.details.length > 1 ? g.details : undefined,
      source: `hldb:${g.tool}`, at: g.at,
    });
  }
  // A failing data source is itself an issue — otherwise its cards just quietly age.
  // Not for the Status extras (weather, NBA…) or link probes: their cards say so
  // themselves, and a public API hiccup is not a homelab problem.
  // hltv:/streams: too — hltv-api and stream-station are containers, so if they die
  // their own resource says so; a feed warming up is not an incident.
  const quiet = /^(vitals:|probe:|extras:|hltv:|streams:|qbt:|vpn:|seerr:|links$)/;
  for (const [key, m] of Object.entries(snapshots.metas())) {
    if (m.ok === false && !quiet.test(key)) {
      issues.push({ severity: 'warn', resource_id: null, resource: m.label, host: m.group, text: `data source failing: ${m.error}`, source: key, at: null });
    }
  }
  issues.sort((a, b) => RANK[b.severity] - RANK[a.severity] || String(b.at).localeCompare(String(a.at)));
  const overall = issues.reduce((acc, i) => worse(acc, i.severity), 'ok');
  return {
    overall,
    hosts: {
      total: hosts.length,
      up: hosts.filter((h) => h.online === true).length,
      down: hosts.filter((h) => h.online === false && h.status !== 'offline').length,
      offline: hosts.filter((h) => h.status === 'offline').length,
    },
    containers: { total: containers.length, running: containers.filter((c) => c.state === 'running').length },
    issues,
    counts: { crit: issues.filter((i) => i.severity === 'crit').length, warn: issues.filter((i) => i.severity === 'warn').length },
  };
}

module.exports = { buildResources, containerStatus, kindOf };
