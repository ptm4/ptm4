# Homelab Inventory (live)

> ⚙️ **AUTO-GENERATED — do not hand-edit.** Rewritten each run by `homelab/Tools/architecture/gen-agentic-docs.py` from `GET /api/architecture/data`. Any manual change here is overwritten on the next run.
> Generated: `2026-07-26T22:42:28+00:00`


## Agent sync status

| Host | Agent | Last synced | Containers | Collection errors |
|---|---|---|---|---|
| noblenumbat | 0.2.0 | 3h ago | 13 | none |
| opti | 0.2.0 | 3h ago | 0 | none |
| rpi | 0.2.0 | 3h ago | 12 | none |


## Nodes

Every node on the architecture map. `Live` columns come from the newest agent sync where available; blank means no agent has reported that host, not that the thing is down — check Agent sync status above.


### Off-LAN

| Node | Plane | Container | State | Image | Summary |
|---|---|---|---|---|---|
| Cloudflare DNS | external | — | n/a | — | 1.1.1.1 — Pi-hole fallback upstream |
| Content APIs | external | — | n/a | — | Weather · HLTV · sports · indexers · usenet |
| Discord API | external | — | n/a | — | Gateway + webhooks for 5 bots |
| GitHub | external | — | n/a | — | ptm4 repo + Actions control plane |
| Internet | external | — | n/a | — | Everything beyond the gateway |
| VPN exit — Netherlands | external | — | n/a | — | Public IP 46.29.25.130 |


### Router / Gateway

| Node | Plane | Container | State | Image | Summary |
|---|---|---|---|---|---|
| Gateway 192.168.1.1 | network | — | n/a | — | Verizon router · DHCP disabled |


### android (S10)

| Node | Plane | Container | State | Image | Summary |
|---|---|---|---|---|---|
| llama-server | apps | — | n/a | — | Qwen2.5-3B :8080 · LAN-only |


### noblenumbat

| Node | Plane | Container | State | Image | Summary |
|---|---|---|---|---|---|
| Bazarr | media | bazarr | running | lscr.io/linuxserver/bazarr:latest | Subtitles :6767 |
| Docker engine | infra | — | n/a | — | 13 containers · YAMS compose |
| FlareSolverr | media | flaresolverr | running | ghcr.io/flaresolverr/flaresolverr:latest | Captcha solver :8191 via VPN |
| Gluetun VPN | network | gluetun | running | qmcgaw/gluetun:v3.41.0 | WireGuard → NL · port-fwd 42328 |
| Jellyfin | media | jellyfin | running | lscr.io/linuxserver/jellyfin:latest | Media server :8096 · HW transcode |
| Kavita | media | kavita | running | lscr.io/linuxserver/kavita:latest | Comics & books :5000 |
| Lidarr | media | lidarr | running | lscr.io/linuxserver/lidarr:latest | Music automation :8686 |
| Mylar3 | media | mylar3 | running | lscr.io/linuxserver/mylar3 | Comics automation :8090 via VPN |
| Portainer | infra | portainer | running | portainer/portainer-ce:latest | Container UI :9000 |
| Prowlarr | media | prowlarr | running | lscr.io/linuxserver/prowlarr | Indexer manager :9696 via VPN |
| Radarr | media | radarr | running | lscr.io/linuxserver/radarr:latest | Movie automation :7878 |
| Remote access | infra | — | n/a | — | sshd :22 · RDP :3389 |
| SABnzbd | media | sabnzbd | running | lscr.io/linuxserver/sabnzbd:latest | Usenet :8081 via VPN |
| Sonarr | media | sonarr | running | lscr.io/linuxserver/sonarr:latest | TV automation :8989 |
| bb-kavita-sync | infra | — | n/a | — | timer · hourly |
| docker net · yams_network | network | — | n/a | — | 172.60.0.0/24 |
| media-import | infra | — | n/a | — | timer · every 2 min |
| netns · service:gluetun | network | — | n/a | — | qbittorrent · sabnzbd · prowlarr · mylar3 · flaresolverr |
| opti CIFS mounts | storage | — | n/a | — | /mnt/opti-library · -shows · -media |
| qBittorrent | media | qbittorrent | running | lscr.io/linuxserver/qbittorrent:4.6.3 | Torrents · pinned 4.6.3 · via VPN |
| vpn-stack-heal | infra | — | n/a | — | timer · every 2 min |


### opti

| Node | Plane | Container | State | Image | Summary |
|---|---|---|---|---|---|
| Actions runner (x86) | infra | — | n/a | — | self-hosted · runs the agent workflow |
| Agent dispatcher | infra | — | n/a | — | Python :9099 · enable/disable + run-now |
| Homelab agents | infra | — | n/a | — | doctor · hardware · software · network · docs |
| OpenMediaVault | infra | — | n/a | — | NAS UI/monitoring · web UI :80 |
| Remote access | infra | — | n/a | — | sshd :22 · xrdp :3389 |
| Samba · share [red] | storage | — | n/a | — | :445 → /srv/red/fs |
| ZFS pool · red | storage | — | n/a | — | /srv/red · 3.6 TB · 16% used |
| agent-logs/ | storage | — | n/a | — | JSON reports on the pool |
| attic · cold copy | storage | — | n/a | — | old sda+sdb pair · noauto · weekly |
| sda · 466 GB HDD | storage | — | n/a | — | ST500DM002 · ext4 root + attic branch |
| sdb · 596 GB HDD | storage | — | n/a | — | Hitachi HTS5475 · NTFS · attic branch (ro) |
| sdc · 4 TB WD Red Plus | storage | — | n/a | — | WD40EFZZ · ZFS vdev |
| systemd timers | infra | — | n/a | — | docs 05:16 · health-digest 06:30 · autoreboot · coldcopy Sun 04:00 · zfs-scrub monthly |


### rpi

| Node | Plane | Container | State | Image | Summary |
|---|---|---|---|---|---|
| /mnt/opti-fs | storage | — | n/a | — | CIFS 3.0 ← //opti/red |
| Actions runner (ARM64) | infra | — | n/a | — | self-hosted · deploys the rpi stack |
| Dashboard webapp | apps | webapp | running | node:lts-alpine | Node/Express :3000 · this page's server |
| Docker engine | infra | — | n/a | — | 12 containers · compose at /srv/docker/compose |
| MariaDB | apps | bitwarden-db | running | mariadb:11 | Vaultwarden datastore :3306 |
| Notes app | apps | notes-api | running | compose-notes-api | Express + JSON store :3002 |
| Pi-hole | network | pihole | running | pihole/pihole:latest | DNS :53 · DHCP · admin :80 |
| Vaultwarden | apps | bitwarden | running | vaultwarden/server:latest | Password manager |
| discord-healthdigest | apps | discord-healthdigest | running | compose-discord-healthdigest | Homelab health summary |
| discord-hltv | apps | discord-hltv | running | compose-discord-hltv | CS2 news & match results |
| discord-jellyfin | apps | discord-jellyfin | running | compose-discord-jellyfin | New-media announcements |
| discord-sports | apps | discord-sports | running | compose-discord-sports | Scores & fixtures |
| discord-weather | apps | discord-weather | running | compose-discord-weather | Daily 7AM ET forecast |
| docker net · internal | network | — | n/a | — | 172.18.0.0/16 — all rpi containers |
| nginx (vault) | network | nginx-bitwarden | running | nginx:stable-alpine | TLS :443 → Vaultwarden |
| nginx (webapp) | network | nginx-webapp | running | nginx:stable-alpine | TLS :8443 → webapp / notes |
| sshd :22 | infra | — | n/a | — | — |
| systemd timers | infra | — | n/a | — | autoreboot 03:00 · autoupdate |


### tux

| Node | Plane | Container | State | Image | Summary |
|---|---|---|---|---|---|
| Browsers & phones | client | — | n/a | — | Dashboard · Jellyfin · vault · notes |
| Other LAN devices | client | — | n/a | — | twah.lan .4 · ptmshc.lan .5 |
| tux workstation | client | — | n/a | — | Editor + Claude Code · CIFS to opti |
