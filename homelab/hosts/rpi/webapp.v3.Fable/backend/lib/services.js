// Every web UI in the homelab, as data. The Launchpad renders this joined with the
// server-side link probes (/api/linkcheck) and the container states (/api/containers)
// so each tile carries live health. Sources: rules/01-homelab-context.md host table,
// the opti and noblenumbat compose files, nginx-wg.conf. URLs use Pi-hole DNS names
// NOTE (2026-09-10): `host` is where the container actually RUNS, which is what the
// fleet table and blast-radius copy read. It is NOT parsed from the URL — several
// services kept their `*.rpi.lan` hostname after moving to opti, because renaming a
// vault's URL breaks every saved client. Host and hostname disagree on purpose.
// except the router (no record).
//
// `container` ties a service to the container that serves it (for state + actions),
// `probe` is the origin /api/linkcheck reports under (absent = internal page or not
// probed), `internal` marks dashboard-served pages.
const SERVICES = [
  // ── infrastructure ──────────────────────────────────────────────────────────
  { id: 'router', label: 'Router (Archer BE3600)', url: 'http://192.168.1.1/webpages/index.html', icon: 'tp-link.svg', category: 'Infrastructure', host: null, probe: 'http://192.168.1.1', description: 'Gateway · WireGuard · DHCP off (Pi-hole owns it)' },
  { id: 'pihole', label: 'Pi-hole', url: 'http://rpi.lan/admin', icon: 'pi-hole.svg', category: 'Infrastructure', host: 'rpi', container: 'pihole', probe: 'http://rpi.lan', fav: true, description: 'LAN DNS (DHCP is the router’s)', internalPage: '/pihole' },
  { id: 'cockpit', label: 'Cockpit console', url: 'https://rpi.lan:9090/', icon: 'cockpit.svg', category: 'Infrastructure', host: 'rpi', probe: 'https://rpi.lan:9090', fav: true, description: 'Host console for rpi (+ opti / nn via @host)' },
  { id: 'uptime-kuma', label: 'Uptime Kuma', url: 'http://opti.lan:3001/', icon: 'uptime-kuma.svg', category: 'Infrastructure', host: 'opti', container: 'uptime-kuma', probe: 'http://opti.lan:3001', fav: true, description: 'Synthetic monitors' },
  { id: 'dozzle', label: 'Dozzle (logs)', url: '/dozzle/', icon: 'dozzle.svg', category: 'Infrastructure', host: 'opti', container: 'dozzle', fav: true, description: 'Live container logs, all hosts', internalPage: '/logs' },
  { id: 'omv', label: 'OpenMediaVault', url: 'http://opti.lan/', icon: 'openmediavault.svg', category: 'Infrastructure', host: 'opti', probe: 'http://opti.lan', fav: true, description: 'NAS UI (monitoring only — the share is samba-red.conf)' },
  { id: 'portainer', label: 'Portainer', url: 'http://noblenumbat.lan:9000/', icon: 'portainer.svg', category: 'Infrastructure', host: 'noblenumbat', container: 'portainer', probe: 'http://noblenumbat.lan:9000', fav: true, description: 'Container UI for the media host' },
  { id: 'vaultwarden', label: 'Vaultwarden', url: 'https://bitwarden.rpi.lan/#/vault', icon: 'vaultwarden.svg', category: 'Infrastructure', host: 'opti', container: 'bitwarden', probe: 'https://bitwarden.rpi.lan', fav: true, description: 'Password manager' },
  { id: 'vaultwarden-admin', label: 'Vaultwarden admin', url: 'https://bitwarden.rpi.lan/admin/users/overview', icon: 'vaultwarden.svg', category: 'Infrastructure', host: 'opti', container: 'bitwarden', probe: 'https://bitwarden.rpi.lan', description: 'Users & server settings' },
  { id: 'homelab-db', label: 'homelab-db', url: 'http://192.168.1.11:9100/healthz', icon: 'generic.svg', category: 'Infrastructure', host: 'opti', probe: 'http://192.168.1.11:9100', description: 'Queryable index + MCP server on opti', internalPage: '/query' },
  { id: 'gluetun', label: 'Gluetun (VPN)', url: 'http://noblenumbat.lan:8003/', icon: 'generic.svg', category: 'Infrastructure', host: 'noblenumbat', container: 'gluetun', probe: 'http://noblenumbat.lan:8003', description: 'VPN tunnel control API · HTTP proxy :8888' },
  // ── media ───────────────────────────────────────────────────────────────────
  { id: 'jellyfin', label: 'Jellyfin', url: 'http://jellyfin.lan:8096/', icon: 'jellyfin.svg', category: 'Media', host: 'noblenumbat', container: 'jellyfin', probe: 'http://jellyfin.lan:8096', fav: true, description: 'Media server, HW transcode' },
  { id: 'kavita', label: 'Kavita (comics)', url: 'http://comics.lan:5000/', icon: 'kavita.svg', category: 'Media', host: 'noblenumbat', container: 'kavita', probe: 'http://comics.lan:5000', fav: true, description: 'Comics & books reader' },
  { id: 'streams', label: 'Streams', url: '/streams', icon: 'generic.svg', category: 'Media', host: 'noblenumbat', container: 'stream-station', probe: 'http://192.168.1.6:8098', fav: true, description: 'Live Twitch/YouTube → HLS player, 4 slots', internalPage: '/streams' },
  // ── library management ──────────────────────────────────────────────────────
  { id: 'sonarr', label: 'Sonarr (TV)', url: 'http://noblenumbat.lan:8989/', icon: 'sonarr.svg', category: 'Library', host: 'noblenumbat', container: 'sonarr', probe: 'http://noblenumbat.lan:8989', description: 'TV automation' },
  { id: 'radarr', label: 'Radarr (movies)', url: 'http://noblenumbat.lan:7878/', icon: 'radarr.svg', category: 'Library', host: 'noblenumbat', container: 'radarr', probe: 'http://noblenumbat.lan:7878', description: 'Movie automation' },
  { id: 'lidarr', label: 'Lidarr (music)', url: 'http://noblenumbat.lan:8686/', icon: 'lidarr.svg', category: 'Library', host: 'noblenumbat', container: 'lidarr', probe: 'http://noblenumbat.lan:8686', description: 'Music automation' },
  { id: 'bazarr', label: 'Bazarr (subtitles)', url: 'http://noblenumbat.lan:6767/', icon: 'bazarr.svg', category: 'Library', host: 'noblenumbat', container: 'bazarr', probe: 'http://noblenumbat.lan:6767', description: 'Subtitles' },
  { id: 'mylar', label: 'Mylar3 (comics)', url: 'http://noblenumbat.lan:8090/', icon: 'generic.svg', category: 'Library', host: 'noblenumbat', container: 'mylar', probe: 'http://noblenumbat.lan:8090', description: 'Comic automation · inside the VPN namespace' },
  { id: 'prowlarr', label: 'Prowlarr (indexers)', url: 'http://noblenumbat.lan:9696/', icon: 'prowlarr.svg', category: 'Library', host: 'noblenumbat', container: 'prowlarr', probe: 'http://noblenumbat.lan:9696', description: 'Indexer manager · inside the VPN namespace' },
  { id: 'flaresolverr', label: 'FlareSolverr', url: 'http://noblenumbat.lan:8191/', icon: 'generic.svg', category: 'Library', host: 'noblenumbat', container: 'flaresolverr', probe: 'http://noblenumbat.lan:8191', description: 'Captcha solver for indexers' },
  // ── downloads ───────────────────────────────────────────────────────────────
  { id: 'qbittorrent', label: 'qBittorrent', url: 'http://noblenumbat.lan:8081/', icon: 'qbittorrent.svg', category: 'Downloads', host: 'noblenumbat', container: 'qbittorrent', probe: 'http://noblenumbat.lan:8081', fav: true, description: 'Torrents · via gluetun' },
  { id: 'sabnzbd', label: 'SABnzbd', url: 'http://noblenumbat.lan:8080/', icon: 'generic.svg', category: 'Downloads', host: 'noblenumbat', container: 'sabnzbd', description: 'Usenet · not LAN-published (port mapping commented out)' },
  // ── ai ──────────────────────────────────────────────────────────────────────
  { id: 'llama', label: 'llama.cpp (android)', url: 'http://android.lan:8080/', icon: 'generic.svg', category: 'AI', host: 'android', probe: 'http://192.168.1.54:8080', description: 'Qwen2.5-3B on the phone · intermittent', internalPage: '/llm' },
  { id: 'llama-ctl', label: 'llama-ctl', url: 'http://android.lan:8081/', icon: 'generic.svg', category: 'AI', host: 'android', probe: 'http://192.168.1.54:8081', description: 'Model switch / management API' },
  // ── this dashboard ──────────────────────────────────────────────────────────
  { id: 'architecture', label: 'Architecture map', url: '/architecture/', icon: 'generic.svg', category: 'Dashboard', host: 'opti', internal: true, description: 'Curated + live architecture graph' },
  { id: 'agents', label: 'Agents', url: '/agents/', icon: 'generic.svg', category: 'Dashboard', host: 'opti', internal: true, description: 'Per-host arch agents' },
  { id: 'samba', label: 'Samba (opti)', url: '/samba/', icon: 'generic.svg', category: 'Dashboard', host: 'opti', internal: true, description: 'Share config editor' },
  { id: 'notes', label: 'Notes', url: '/notes/', icon: 'generic.svg', category: 'Dashboard', host: 'opti', container: 'notes-api', internal: true, description: 'Notes app' },
  { id: 'agentic', label: 'Agentic workspace', url: '/agentic/', icon: 'generic.svg', category: 'Dashboard', host: 'opti', internal: true, description: 'Skills, rules, runbooks' },
  { id: 'legacy', label: 'Legacy UI (v1)', url: '/legacy/', icon: 'generic.svg', category: 'Dashboard', host: 'opti', internal: true, description: 'The pre-redesign dashboard' },
];

module.exports = { SERVICES };
