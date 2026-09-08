// The bookmark catalog — port of v1's LINK_GROUPS, now with vendored icon files
// (selfhst/homarr dashboard-icons, Apache-2.0 — LICENSE alongside the SVGs).
// URLs use Pi-hole local DNS names rather than raw IPs, so a host that changes
// address doesn't break this list — the one exception is the router, which has
// no DNS record. `fav` marks the entries the compact home widgets surface.

export interface AppLink {
  label: string;
  url: string;
  icon: string;        // filename under /icons/apps/
  fav?: boolean;
  /** origin the server-side /api/linkcheck probes report under; absent = internal page */
  checkOrigin?: string;
}

export interface LinkGroup {
  group: string;
  links: AppLink[];
}

export const LINK_GROUPS: LinkGroup[] = [
  { group: 'Infrastructure', links: [
    { label: 'Router (Archer BE3600)', url: 'http://192.168.1.1/webpages/index.html', icon: 'tp-link.svg', checkOrigin: 'http://192.168.1.1' },
    { label: 'Pi-hole', url: 'http://rpi.lan/admin', icon: 'pi-hole.svg', fav: true, checkOrigin: 'http://rpi.lan' },
    { label: 'Cockpit console (rpi:9090)', url: 'https://rpi.lan:9090/', icon: 'cockpit.svg', fav: true, checkOrigin: 'https://rpi.lan:9090' },
    { label: 'Uptime Kuma', url: 'http://rpi.lan:3001/', icon: 'uptime-kuma.svg', fav: true },
    { label: 'Dozzle (logs)', url: '/dozzle/', icon: 'dozzle.svg', fav: true },
    { label: 'OpenMediaVault', url: 'http://opti.lan/', icon: 'openmediavault.svg', fav: true, checkOrigin: 'http://opti.lan' },
    { label: 'Portainer', url: 'http://noblenumbat.lan:9000/', icon: 'portainer.svg', fav: true, checkOrigin: 'http://noblenumbat.lan:9000' },
    { label: 'Vaultwarden', url: 'https://bitwarden.rpi.lan/#/vault', icon: 'vaultwarden.svg', fav: true, checkOrigin: 'https://bitwarden.rpi.lan' },
    { label: 'Vaultwarden admin', url: 'https://bitwarden.rpi.lan/admin/users/overview', icon: 'vaultwarden.svg', checkOrigin: 'https://bitwarden.rpi.lan' },
  ]},
  { group: 'Media', links: [
    { label: 'Jellyfin', url: 'http://jellyfin.lan:8096/', icon: 'jellyfin.svg', fav: true, checkOrigin: 'http://jellyfin.lan:8096' },
    { label: 'Kavita (comics)', url: 'http://comics.lan:5000/', icon: 'kavita.svg', fav: true, checkOrigin: 'http://comics.lan:5000' },
  ]},
  { group: 'Library management', links: [
    { label: 'Sonarr (TV)', url: 'http://noblenumbat.lan:8989/', icon: 'sonarr.svg', checkOrigin: 'http://noblenumbat.lan:8989' },
    { label: 'Radarr (movies)', url: 'http://noblenumbat.lan:7878/', icon: 'radarr.svg', checkOrigin: 'http://noblenumbat.lan:7878' },
    { label: 'Lidarr (music)', url: 'http://noblenumbat.lan:8686/', icon: 'lidarr.svg', checkOrigin: 'http://noblenumbat.lan:8686' },
    { label: 'Bazarr (subtitles)', url: 'http://noblenumbat.lan:6767/', icon: 'bazarr.svg', checkOrigin: 'http://noblenumbat.lan:6767' },
    { label: 'Mylar3 (comics)', url: 'http://noblenumbat.lan:8090/', icon: 'generic.svg', checkOrigin: 'http://noblenumbat.lan:8090' },
    { label: 'Prowlarr (indexers)', url: 'http://noblenumbat.lan:9696/', icon: 'prowlarr.svg', checkOrigin: 'http://noblenumbat.lan:9696' },
  ]},
  { group: 'Downloads', links: [
    { label: 'qBittorrent', url: 'http://noblenumbat.lan:8081/', icon: 'qbittorrent.svg', fav: true, checkOrigin: 'http://noblenumbat.lan:8081' },
  ]},
  { group: 'This dashboard', links: [
    { label: 'Architecture map', url: '/architecture/', icon: 'generic.svg' },
    { label: 'Agents', url: '/agents/', icon: 'generic.svg' },
    { label: 'Samba (opti)', url: '/samba/', icon: 'generic.svg' },
    { label: 'Notes', url: '/notes/', icon: 'generic.svg' },
    { label: 'Agentic workspace', url: '/agentic/', icon: 'generic.svg' },
  ]},
];

export const ALL_LINKS = LINK_GROUPS.flatMap((g) => g.links.map((l) => ({ ...l, group: g.group })));

// Internal dashboard pages must not open in a new tab; everything else should.
export const isExternal = (url: string) => !url.startsWith('/');

export const iconUrl = (icon: string) => `/icons/apps/${icon}`;
