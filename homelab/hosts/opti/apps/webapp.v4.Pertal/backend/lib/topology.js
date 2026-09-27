// Topology: the handful of dependencies that explain an outage, overlaid with live
// status from the resource model. Deliberately small — the full architecture map
// (build-arch-data.py, 70+ nodes) answers "what exists"; this answers "what breaks what".
'use strict';

const NODES = [
  { id: 'internet', label: 'Internet', kind: 'external' },
  { id: 'router', label: 'TP-Link Archer', sub: '192.168.1.1 · DHCP · WireGuard', kind: 'network' },
  { id: 'proton', label: 'ProtonVPN', sub: 'gluetun tunnel · NL', kind: 'external' },
];

// from → to, and what flows. Resource ids refer to hosts/containers in the model.
const EDGES = [
  { from: 'internet', to: 'router', label: 'WAN' },
  { from: 'router', to: 'rpi', label: 'DHCP hands out rpi as DNS' },
  { from: 'rpi', to: 'opti', label: 'DNS for every host', critical: true },
  { from: 'rpi', to: 'noblenumbat', label: 'DNS for every host', critical: true },
  { from: 'opti', to: 'noblenumbat', label: 'Samba share (media library)', critical: true },
  { from: 'noblenumbat:uptime-kuma', to: 'opti', label: 'watches from outside' },
  { from: 'noblenumbat:gluetun', to: 'proton', label: 'downloads leave via VPN' },
  { from: 'opti:discord-jellyfin', to: 'noblenumbat:jellyfin', label: 'new-media posts' },
  { from: 'opti:hltv-api', to: 'opti:discord-hltv', label: 'match data' },
  { from: 'noblenumbat:ntfy', to: 'internet', label: 'phone push' },
];

function buildTopology(resources) {
  const byId = new Map(resources.map((r) => [r.id, r]));
  // "Down" means unreachable or not running — NOT "has findings". A host with a disk
  // warning still serves DNS; only a dead end breaks an edge.
  const down = (id) => {
    const r = byId.get(id);
    if (!r) return !NODES.some((n) => n.id === id);
    return r.type === 'host' ? r.online === false : r.state !== 'running';
  };
  const hosts = resources.filter((r) => r.type === 'host').map((h) => ({
    id: h.id, label: h.name, status: h.status, online: h.online, state_text: h.state_text,
    role: h.facts.find((f) => f.label === 'Role')?.value ?? null,
    children: resources.filter((c) => c.type === 'container' && c.host === h.id)
      .map((c) => ({ id: c.id, name: c.name, kind: c.kind, status: c.status })),
  }));
  const edges = EDGES.map((e) => ({ ...e, status: down(e.from) || down(e.to) ? 'crit' : 'ok' }));
  return { nodes: NODES, hosts, edges };
}

module.exports = { buildTopology };
