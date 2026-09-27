// Topology: the homelab as a diagram — hosts, the services that matter on each (a
// service groups one or more containers), the outside world, and the dependencies that
// explain an outage. Status is live: a service is as healthy as its worst container, a
// host-level service (Samba, llama.cpp) follows its host. The frontend only does layout.
//
// An edge is "broken" only if one end is actually DOWN (unreachable / not running) —
// never merely because it has findings. opti with a disk warning still serves DNS.
'use strict';

const EXTERNAL = [
  { id: 'internet', label: 'Internet', sub: 'WAN · hltv.org · Twitch', kind: 'external' },
  { id: 'discord', label: 'Discord', sub: 'bot channels', kind: 'external' },
  { id: 'proton', label: 'ProtonVPN', sub: 'WireGuard · Netherlands', kind: 'external' },
];
const ROUTER = { id: 'router', label: 'TP-Link Archer', sub: '192.168.1.1 · DHCP · WireGuard', kind: 'network' };

// Order within a host is the order drawn. `members` are resource ids; a regex `match`
// picks containers by name on that host. `host: true` = a host-level service (no container).
const SERVICES = [
  { id: 'pihole', host: 'rpi', label: 'Pi-hole', sub: 'DNS for the whole LAN', kind: 'network', members: ['rpi:pihole'] },
  { id: 'dozzle-agent-rpi', host: 'rpi', label: 'Dozzle agent', sub: 'ships logs to opti', kind: 'infra', members: ['rpi:dozzle-agent'] },

  { id: 'samba', host: 'opti', label: 'Samba · red', sub: '4 TB ZFS share', kind: 'storage', hostLevel: true },
  { id: 'pertal', host: 'opti', label: 'Pertal', sub: 'this dashboard', kind: 'apps', members: ['opti:pertal'] },
  { id: 'webapp', host: 'opti', label: 'Dashboard v3', sub: 'webapp.lan:8443', kind: 'apps', members: ['opti:webapp', 'opti:nginx-webapp'] },
  { id: 'vault', host: 'opti', label: 'Vaultwarden', sub: 'passwords', kind: 'apps', members: ['opti:bitwarden', 'opti:bitwarden-db', 'opti:nginx-bitwarden'] },
  { id: 'seerr', host: 'opti', label: 'Seerr', sub: 'media requests', kind: 'media', members: ['opti:seerr'] },
  { id: 'bots', host: 'opti', label: 'Discord bots', sub: '', kind: 'apps', match: /^discord-/ },
  { id: 'hltv', host: 'opti', label: 'hltv-api', sub: 'CS2 scraper', kind: 'apps', members: ['opti:hltv-api'] },
  { id: 'notes', host: 'opti', label: 'Notes', sub: 'notes-api', kind: 'apps', members: ['opti:notes-api'] },
  { id: 'dozzle', host: 'opti', label: 'Dozzle', sub: 'every container log', kind: 'infra', members: ['opti:dozzle'] },

  { id: 'jellyfin', host: 'noblenumbat', label: 'Jellyfin', sub: 'streaming · HW transcode', kind: 'media', members: ['noblenumbat:jellyfin'] },
  { id: 'arr', host: 'noblenumbat', label: '*arr stack', sub: '', kind: 'media',
    members: ['noblenumbat:sonarr', 'noblenumbat:radarr', 'noblenumbat:lidarr', 'noblenumbat:bazarr', 'noblenumbat:prowlarr', 'noblenumbat:mylar3'] },
  { id: 'downloaders', host: 'noblenumbat', label: 'Downloaders', sub: 'qBittorrent · SABnzbd', kind: 'media',
    members: ['noblenumbat:qbittorrent', 'noblenumbat:sabnzbd', 'noblenumbat:flaresolverr'] },
  { id: 'gluetun', host: 'noblenumbat', label: 'Gluetun', sub: 'VPN gateway', kind: 'network', members: ['noblenumbat:gluetun'] },
  { id: 'kavita', host: 'noblenumbat', label: 'Kavita', sub: 'comics & books', kind: 'media', members: ['noblenumbat:kavita'] },
  { id: 'streams', host: 'noblenumbat', label: 'stream-station', sub: 'live streams → HLS', kind: 'media', members: ['noblenumbat:stream-station'] },
  { id: 'kuma', host: 'noblenumbat', label: 'Uptime Kuma', sub: 'watches from outside', kind: 'infra', members: ['noblenumbat:uptime-kuma'] },
  { id: 'ntfy', host: 'noblenumbat', label: 'ntfy', sub: 'phone push', kind: 'infra', members: ['noblenumbat:ntfy'] },
  { id: 'portainer', host: 'noblenumbat', label: 'Portainer', sub: 'container UI', kind: 'infra', members: ['noblenumbat:portainer', 'noblenumbat:dozzle-agent'] },

  { id: 'llama', host: 'android', label: 'llama.cpp', sub: 'local LLM', kind: 'apps', hostLevel: true },
];

// from → to. Ids are external/router/service ids, or `host:<id>` for a host itself.
const EDGES = [
  { from: 'internet', to: 'router', label: 'WAN', kind: 'network' },
  { from: 'router', to: 'host:rpi', label: 'DHCP hands out rpi as DNS', kind: 'network' },
  { from: 'host:rpi', to: 'host:opti', label: 'DNS', kind: 'dns' },
  { from: 'host:rpi', to: 'host:noblenumbat', label: 'DNS', kind: 'dns' },
  { from: 'samba', to: 'jellyfin', label: 'media library (CIFS)', kind: 'storage' },
  { from: 'samba', to: 'arr', label: 'imports into the library', kind: 'storage' },
  { from: 'seerr', to: 'arr', label: 'approved requests', kind: 'media' },
  { from: 'arr', to: 'downloaders', label: 'grabs releases', kind: 'media' },
  { from: 'downloaders', to: 'gluetun', label: 'shares its network', kind: 'vpn' },
  { from: 'gluetun', to: 'proton', label: 'encrypted tunnel', kind: 'vpn' },
  { from: 'hltv', to: 'bots', label: 'match data', kind: 'apps' },
  { from: 'bots', to: 'discord', label: 'daily posts', kind: 'apps' },
  { from: 'bots', to: 'jellyfin', label: 'new arrivals', kind: 'apps' },
  { from: 'kuma', to: 'host:opti', label: 'monitors', kind: 'monitor' },
  { from: 'ntfy', to: 'internet', label: 'push to your phone', kind: 'monitor' },
];

const RANK = { ok: 0, offline: 0, unknown: 1, warn: 2, crit: 3 };
const worse = (a, b) => (RANK[b] > RANK[a] ? b : a);

function buildTopology(resources) {
  const byId = new Map(resources.map((r) => [r.id, r]));
  const hostsOut = resources.filter((r) => r.type === 'host').map((h) => ({
    id: h.id, label: h.name, status: h.status, online: h.online, state_text: h.state_text,
    role: h.facts.find((f) => f.label === 'Role')?.value ?? null,
    metrics: h.metrics ? { cpu_pct: h.metrics.cpu_pct, mem_pct: h.metrics.mem_pct, temp_c: h.metrics.temp_c } : null,
    counts: h.counts,
    // Kept for the host cards above the diagram.
    children: resources.filter((c) => c.type === 'container' && c.host === h.id)
      .map((c) => ({ id: c.id, name: c.name, kind: c.kind, status: c.status })),
  }));
  const hostById = new Map(hostsOut.map((h) => [h.id, h]));

  const services = [];
  for (const s of SERVICES) {
    const host = hostById.get(s.host);
    if (!host) continue;
    const members = s.match
      ? resources.filter((r) => r.type === 'container' && r.host === s.host && s.match.test(r.name))
      : (s.members || []).map((id) => byId.get(id)).filter(Boolean);
    if (!s.hostLevel && !members.length) continue; // not deployed (e.g. Seerr before it exists)
    let status = 'ok';
    let down = false;
    if (s.hostLevel) {
      status = host.online === false ? (host.status === 'offline' ? 'offline' : 'crit') : 'ok';
      down = host.online === false;
    } else {
      for (const m of members) status = worse(status, m.status);
      down = members.every((m) => m.state !== 'running');
    }
    const bad = members.filter((m) => m.status === 'warn' || m.status === 'crit');
    services.push({
      id: s.id, host: s.host, label: s.label, kind: s.kind, status, down,
      sub: s.sub || (members.length > 1 ? `${members.length} containers` : ''),
      detail: bad.length ? bad.map((m) => `${m.name}: ${m.status_text}`).join(' · ') : null,
      count: members.length,
      resource: members.length === 1 ? members[0].id : s.hostLevel ? s.host : null,
      members: members.map((m) => ({ id: m.id, name: m.name, status: m.status })),
    });
  }

  const present = new Set([...EXTERNAL.map((e) => e.id), ROUTER.id, ...services.map((s) => s.id), ...hostsOut.map((h) => `host:${h.id}`)]);
  const isDown = (id) => {
    if (id.startsWith('host:')) return hostById.get(id.slice(5))?.online === false;
    return services.find((s) => s.id === id)?.down ?? false;
  };
  const edges = EDGES.filter((e) => present.has(e.from) && present.has(e.to))
    .map((e) => ({ ...e, status: isDown(e.from) || isDown(e.to) ? 'crit' : 'ok' }));

  return { external: EXTERNAL, router: ROUTER, hosts: hostsOut, services, edges, nodes: [...EXTERNAL, ROUTER] };
}

module.exports = { buildTopology, SERVICES, EDGES };
