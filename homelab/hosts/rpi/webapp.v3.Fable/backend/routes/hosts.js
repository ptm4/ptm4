// /api/hosts — the fleet as a list, so the frontend stops hardcoding it. Static
// facts (name, address, role) come from this file and lib/hosts.js; the live bits
// (vitals presence, agent reachability, container counts) are joined from state the
// backend already holds — no new upstream calls.
const { AGENT_HOSTS } = require('../lib/hosts');
const { readFragments } = require('../lib/arch-data');

// Matches rules/01-homelab-context.md's host table, re-verified against the live
// fleet on 2026-09-10: opti answers :8443 and runs 14 containers, rpi answers
// nothing on :8443 and runs two (pihole, dozzle-agent). The app tier moved.
// Roles below describe what each box CONTAINS, which is what the topology map and
// every blast-radius string read — so they are the one place to correct.
const HOSTS = [
  { name: 'opti',        label: 'opti',        ip: '192.168.1.11', role: 'storage · control plane · apps', os: 'Debian 12',   kind: 'server', intermittent: false },
  { name: 'rpi',         label: 'rpi',         ip: '192.168.1.10', role: 'DNS appliance',           os: 'Ubuntu 24.04', kind: 'server', intermittent: false },
  { name: 'noblenumbat', label: 'noblenumbat', ip: '192.168.1.6',  role: 'media',                   os: 'Ubuntu 24.04', kind: 'server', intermittent: false },
  { name: 'android',     label: 'android',     ip: '192.168.1.54', role: 'local LLM',               os: 'Termux',       kind: 'phone',  intermittent: true },
  { name: 'tux',         label: 'tux',         ip: '192.168.1.3',  role: 'workstation',             os: 'CachyOS',      kind: 'workstation', intermittent: true },
];

// The two documented single points of failure — surfaced on the topology map.
// opti's is no longer just the pool: since the app-tier move an opti outage costs
// the dashboard, the vault and the bots at the same time. rpi's stayed narrow on
// purpose — DNS lives on the cheap always-on box precisely so rebooting opti is
// routine, and the LAN keeps resolving names while it is down.
const SPOF = { opti: 'storage+apps', rpi: 'dns' };

// Who depends on whom (edge list), for the topology map's dependency arcs.
const DEPENDS = [
  { from: 'noblenumbat', to: 'opti', why: 'mounts the pool over CIFS' },
  { from: 'rpi',         to: 'opti', why: 'reads reports and agent logs over CIFS' },
  { from: 'opti',        to: 'rpi', why: 'DNS' },
  { from: 'noblenumbat', to: 'rpi', why: 'DNS' },
  { from: 'android',     to: 'rpi', why: 'DNS' },
  { from: 'tux',         to: 'rpi', why: 'DNS' },
];

module.exports = async function hostRoutes(app) {
  app.get('/', async () => {
    let fragments = {};
    try { fragments = readFragments(); } catch (_) { /* no arch data yet */ }
    const vitals = app.vitals?.state || {};

    const hosts = HOSTS.map((h) => {
      const st = vitals[h.name];
      const latest = st?.samples?.length ? st.samples[st.samples.length - 1] : null;
      const frag = fragments[h.name];
      const containers = ((frag?.docker || {}).containers || []);
      return {
        ...h,
        agent: h.name in AGENT_HOSTS,
        agent_base: AGENT_HOSTS[h.name]?.base || null,
        agent_version: st?.agent_version || frag?.agent_version || null,
        spof: SPOF[h.name] || null,
        vitals: latest ? {
          t: latest.t, load1: latest.load1, cpu_pct: latest.cpu_pct, mem_pct: latest.mem_pct,
          temp_c: latest.temp_c, uptime_s: latest.uptime_s,
        } : null,
        vitals_error: st?.lastError || null,
        containers: containers.length,
        containers_up: containers.filter((c) => c.state === 'running').length,
        fragment_at: frag?.collected_at || null,
      };
    });

    return { hosts, depends: DEPENDS, gateway: { ip: '192.168.1.1', label: 'archer', model: 'TP-Link Archer BE3600' }, generated_at: new Date().toISOString() };
  });
};
