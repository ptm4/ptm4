// Launchpad catalog (ported from v3's lib/links.ts). Lives in the backend so the
// reachability probe and the page share one list. URLs use Pi-hole local DNS names; the
// router has none. `check` is the origin (or list of alternatives) the probe hits —
// up if ANY answers; the opti-hosted ones list their internal compose name too, because
// opti's firewall drops container→host traffic to their LAN ports. Absent = not probed.
'use strict';

const LINK_GROUPS = [
  { group: 'Infrastructure', links: [
    { label: 'Router (Archer BE3600)', url: 'http://192.168.1.1/webpages/index.html', icon: 'tp-link.svg', check: 'http://192.168.1.1' },
    { label: 'Pi-hole', url: 'http://rpi.lan/admin', icon: 'pi-hole.svg', check: 'http://rpi.lan' },
    { label: 'Uptime Kuma', url: 'http://noblenumbat.lan:3001/', icon: 'uptime-kuma.svg', check: 'http://noblenumbat.lan:3001' },
    { label: 'Dozzle (logs)', url: 'http://opti.lan:9999/', icon: 'dozzle.svg', check: ['http://opti.lan:9999', 'http://dozzle:8080'] },
    { label: 'OpenMediaVault', url: 'http://opti.lan/', icon: 'openmediavault.svg', check: 'http://opti.lan' },
    { label: 'Portainer', url: 'http://noblenumbat.lan:9000/', icon: 'portainer.svg', check: 'http://noblenumbat.lan:9000' },
    // No probe: Pertal runs ON opti, and opti's firewall (rightly) drops container→host
    // traffic to :9090, so a probe would always report a healthy Cockpit as down.
    { label: 'Cockpit · opti', url: 'https://opti.lan:9090/', icon: 'cockpit.svg' },
    { label: 'Cockpit · rpi', url: 'https://rpi.lan:9090/', icon: 'cockpit.svg', check: 'https://rpi.lan:9090' },
    { label: 'Cockpit · noblenumbat', url: 'https://noblenumbat.lan:9090/', icon: 'cockpit.svg', check: 'https://noblenumbat.lan:9090' },
    { label: 'ntfy', url: 'http://noblenumbat.lan:2586/', icon: 'generic.svg', check: 'http://noblenumbat.lan:2586' },
  ]},
  { group: 'Apps', links: [
    { label: 'Vaultwarden', url: 'https://bitwarden.rpi.lan/#/vault', icon: 'vaultwarden.svg', check: ['https://bitwarden.rpi.lan', 'https://nginx-bitwarden'] },
    { label: 'Vaultwarden admin', url: 'https://bitwarden.rpi.lan/admin/users/overview', icon: 'vaultwarden.svg' },
    { label: 'Notes', url: 'https://webapp.lan:8443/notes/', icon: 'generic.svg' },
  ]},
  { group: 'Media', links: [
    { label: 'Jellyfin', url: 'http://jellyfin.lan:8096/', icon: 'jellyfin.svg', check: 'http://jellyfin.lan:8096' },
    { label: 'Kavita (comics)', url: 'http://comics.lan:5000/', icon: 'kavita.svg', check: 'http://comics.lan:5000' },
    { label: 'Seerr (requests)', url: 'http://opti.lan:5055/', icon: 'generic.svg', check: ['http://opti.lan:5055', 'http://seerr:5055'] },
  ]},
  { group: 'Library management', links: [
    { label: 'Sonarr (TV)', url: 'http://noblenumbat.lan:8989/', icon: 'sonarr.svg', check: 'http://noblenumbat.lan:8989' },
    { label: 'Radarr (movies)', url: 'http://noblenumbat.lan:7878/', icon: 'radarr.svg', check: 'http://noblenumbat.lan:7878' },
    { label: 'Lidarr (music)', url: 'http://noblenumbat.lan:8686/', icon: 'lidarr.svg', check: 'http://noblenumbat.lan:8686' },
    { label: 'Bazarr (subtitles)', url: 'http://noblenumbat.lan:6767/', icon: 'bazarr.svg', check: 'http://noblenumbat.lan:6767' },
    { label: 'Mylar3 (comics)', url: 'http://noblenumbat.lan:8090/', icon: 'generic.svg', check: 'http://noblenumbat.lan:8090' },
    { label: 'Prowlarr (indexers)', url: 'http://noblenumbat.lan:9696/', icon: 'prowlarr.svg', check: 'http://noblenumbat.lan:9696' },
  ]},
  { group: 'Downloads', links: [
    { label: 'qBittorrent', url: 'http://noblenumbat.lan:8081/', icon: 'qbittorrent.svg', check: 'http://noblenumbat.lan:8081' },
    { label: 'SABnzbd', url: 'http://noblenumbat.lan:8090/sabnzbd/', icon: 'generic.svg' },
  ]},
];

module.exports = { LINK_GROUPS };
