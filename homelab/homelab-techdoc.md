# Homelab Technical Reference

---

## Table of Contents

1. [Network Topology](#1-network-topology)
2. [Hardware](#2-hardware)
3. [Raspberry Pi — OS & Base Config](#3-raspberry-pi--os--base-config)
4. [Docker Stack Overview](#4-docker-stack-overview)
5. [Pi-hole — DNS & DHCP](#5-pi-hole--dns--dhcp)
6. [WireGuard — VPN](#6-wireguard--vpn)
7. [Vaultwarden + Nginx — Password Manager](#7-vaultwarden--nginx--password-manager)
8. [MariaDB — Vaultwarden Database](#8-mariadb--vaultwarden-database)
9. [Samba — File Server](#9-samba--file-server)
10. [Storage — mergerfs + NFS](#10-storage--mergerfs--nfs)
11. [CI/CD — GitHub Actions Runner](#11-cicd--github-actions-runner)
12. [Log Management](#12-log-management)
13. [Useful Commands & Diagnostics](#13-useful-commands--diagnostics)
14. [WireGuard Peer Manager — Web UI](#14-wireguard-peer-manager--web-ui)
15. [Homelab Agent Platform](#15-homelab-agent-platform)
16. [YAMS Media Stack (noblenumbat)](#16-yams-media-stack-noblenumbat)

---

## 1. Network Topology

```
Internet
    |
Router / Gateway — 192.168.1.1
    |
    LAN: 192.168.1.0/24
    |
    ├── rpi.lan          192.168.1.10   Raspberry Pi 4 (Pi-hole, WireGuard, Vaultwarden, Samba)
    ├── noblenumbat.lan  192.168.1.6    Dell Latitude 7400 (NFS server, YAMS media stack)
    └── opti.lan         192.168.1.11   Custom x86 tower (OpenMediaVault, agent orchestration, Samba \\opti\fs)

VPN tunnel: 10.8.0.0/24   (WireGuard peers, up to 5)
```

**DNS:** Pi-hole at `192.168.1.10:53` handles all LAN DNS. Upstream: `192.168.1.1` (router) + `1.1.1.1` (Cloudflare fallback).

**DHCP:** Pi-hole serves DHCP for `192.168.1.0/24`. Router DHCP should be disabled.

**Local hostnames used in stack:**
- `rpi.lan` → `192.168.1.10`
- `bitwarden.rpi.lan` → `192.168.1.10` (Pi-hole local DNS record)
- `vpn.rpi.lan` → `192.168.1.10` (Pi-hole local DNS record, also needs public DNS if VPN clients are external)
- `noblenumbat.lan` → `192.168.1.6`
- `jellyfin.lan` → `192.168.1.6` (YAMS/Jellyfin media server)
- `opti.lan` → `192.168.1.11`

---

## 2. Hardware

### Raspberry Pi 4 (`rpi.lan`)

| Field | Value |
|---|---|
| CPU | Cortex-A72 · 4c/4t · 1.8 GHz max |
| RAM | 3.7 GB · no swap |
| Disk | 119 GB SD card · 74 GB free · `/dev/mmcblk0p2` |
| Network | `eth0` wired · `wlan0` off |
| OS | Ubuntu Server |
| IP | `192.168.1.10` (static) |

### noblenumbat (`noblenumbat.lan` / `192.168.1.6`)

| Field | Value |
|---|---|
| Model | Dell Latitude 7400 |
| CPU | i7-8665U · 4c/8t · 4.8 GHz boost · VT-x · Intel UHD 620 (QuickSync H.264 VAAPI) |
| RAM | 16 GB DDR4 2667 MT/s |
| Disk | 512 GB NVMe · SK Hynix PC611 · ~389 GB free |
| GPU | `/dev/dri/renderD128` · render gid **992** |
| Network | Intel Wireless-AC · WiFi only (`wlo1`) |
| OS | Ubuntu 24.04.4 |
| IP | `192.168.1.6` (DHCP) |
| Role | NFS server (`/srv/fs-ext`) · YAMS media stack · suspend disabled |

### opti (`opti.lan` / `192.168.1.11`)

| Field | Value |
|---|---|
| CPU | i5-3570 · 4c/4t · 3.4 GHz · Intel HD 2500 (QuickSync H.264) |
| RAM | 5.7 GB |
| Disk | 457 GB root · mergerfs pool `/srv/pool` (~1.1 TB, ~858 GB free) |
| GPU | `/dev/dri/renderD128` · render gid **106** |
| OS | Debian 12 (Bookworm) |
| IP | `192.168.1.11` (DHCP) |
| Role | **OpenMediaVault** NAS · Samba share `\\opti\fs` = `/srv/pool` · homelab agent orchestration · self-hosted GitHub Actions runner (`label: opti`) |

**opti storage map:**
```
/srv/pool/               ← OMV mergerfs pool (~1.1 TB total)
  ptm/
    Media/Movies/        ← Jellyfin MOVIE LIBRARY (primary storage; noblenumbat mounts at /mnt/opti-library)
    Media-Import/        ← file-drop inbox for Jellyfin (\\opti\fs\ptm\Media-Import\)
    security-reports/    ← security agent reports (Pi mounts as /mnt/opti-fs/ptm/security-reports)
    agent-logs/          ← homelab agent logs
    certs/               ← TLS certs for webapp
```

**Note:** OMV manages `/etc/exports` and Samba config on opti — do NOT hand-edit these files.

---

## 3. Raspberry Pi — OS & Base Config

**Docker:** Docker Engine + Compose plugin. Stack file lives at `/srv/docker/compose/docker-compose.yml`. This path is the canonical runtime location — the repo file is pushed here by CI.

**Key paths:**
```
/srv/docker/compose/docker-compose.yml   # live compose file (deployed by CI)
/srv/docker/compose/certs/               # TLS certs for nginx/bitwarden
/srv/docker/compose/nginx.conf           # nginx reverse proxy config
/srv/docker/compose/bitwarden-db/data/   # MariaDB data (bind mount)
/srv/docker/compose/vaultwarden-data/    # Vaultwarden data (bind mount)
/srv/docker/compose/data/wireguard/      # WireGuard config (bind mount)
/srv/fs/                                 # Local storage pool (74 GB SD card)
/srv/fs-merged/                          # mergerfs mount (local + NFS combined)
/mnt/noblenumbat-fs/                     # NFS mount from noblenumbat
/mnt/noblenumbat-fs/ptm/logging/         # Deploy & stack logs (Samba-accessible)
```

**Manage Docker stack:**
```bash
cd /srv/docker/compose
docker compose ps
docker compose up -d --remove-orphans
docker compose down
docker compose pull
docker compose logs -f [service]
docker compose restart [service]
```

---

## 4. Docker Stack Overview

Stack at `/srv/docker/compose/docker-compose.yml`. All services use the shared `json-file` logging driver (max-size: 10m, max-file: 5).

| Container | Image | Network | Ports |
|---|---|---|---|
| `pihole` | `pihole/pihole:latest` | host | :53 (DNS/UDP+TCP), :67 (DHCP), :80/:443 (web UI) |
| `wireguard` | `linuxserver/wireguard` | default | `51820:51820/udp` |
| `nginx-bitwarden` | `nginx:stable-alpine` | internal bridge | `443:443` |
| `bitwarden` | `vaultwarden/server:latest` | internal bridge | :80 (internal only) |
| `bitwarden-db` | `mariadb:11` | internal bridge | :3306 (internal only) |
| `samba` | `dperson/samba` | default | `192.168.1.10:445:445` |
| `wg-manager` | `node:lts-alpine` | internal bridge | :3000 (internal only) |
| `nginx-wgmgr` | `nginx:stable-alpine` | internal bridge | `192.168.1.10:8443:443` |

**Docker network `internal`:** Bridge network isolating Nginx, Vaultwarden, and MariaDB from the host. Only Nginx is reachable from outside (via port 443).

**Restart policy:** All containers: `unless-stopped`.

---

## 5. Pi-hole — DNS & DHCP

**Mode:** `network_mode: host` — required for DHCP broadcast reception and raw DNS port binding.

**Web UI:** `http://192.168.1.10/admin` (or `http://rpi.lan/admin`)

**Key env vars (no password here):**
```yaml
TZ: "America/New_York"
FTLCONF_dns_upstreams: "192.168.1.1;1.1.1.1"
```

**Volumes:**
- `pihole_data` → `/etc/pihole` (block lists, config, local DNS records)
- `dnsmasq_data` → `/etc/dnsmasq.d` (DHCP config, additional DNS options)

**Capabilities:** `NET_ADMIN` (DHCP), `SYS_NICE` (suppresses FTL priority warning)

**Adding a local DNS record** (for custom LAN hostnames like `bitwarden.rpi.lan`):
Pi-hole web UI → Local DNS → DNS Records → add `bitwarden.rpi.lan` → `192.168.1.10`

Or edit via volume: `pihole_data` → `/etc/pihole/custom.list`:
```
192.168.1.10 bitwarden.rpi.lan
192.168.1.10 vpn.rpi.lan
```

**Debug DNS:**
```bash
docker exec pihole pihole -t            # live query log
docker exec pihole pihole status
docker exec pihole pihole restartdns
```

**FTL logs:**
```bash
docker logs pihole --tail=100 -f
```

---

## 6. WireGuard — VPN

**Image:** `linuxserver/wireguard`

**Config volume:** `./data/wireguard:/config` — peer configs are auto-generated here by the container on first start.

**Key settings:**
```yaml
SERVERURL: vpn.rpi.lan      # DNS name (needs to resolve from the internet for external peers)
SERVERPORT: 51820
PEERS: 5                    # number of client configs to auto-generate
PEERDNS: 192.168.1.10       # VPN clients use Pi-hole for DNS
INTERNAL_SUBNET: 10.8.0.0   # VPN address space (10.8.0.0/24)
PUID/PGID: 1000
```

**Port:** `51820/udp` mapped to host (no bind to specific IP — listens on all interfaces).

**Capabilities:** `NET_ADMIN`, `SYS_MODULE` + kernel module volume `/lib/modules:/lib/modules` + sysctl `net.ipv4.conf.all.src_valid_mark=1`

**Peer configs** are generated at:
```
./data/wireguard/peer1/peer1.conf       # client config file
./data/wireguard/peer1/peer1.png        # QR code for mobile
```

**Note:** `vpn.rpi.lan` needs to resolve from the outside internet for external VPN peers to connect. Currently no peers are provisioned. If adding an external peer, either set `SERVERURL` to the Pi's public IP or set up DDNS.

**Debug:**
```bash
docker exec wireguard wg show
docker logs wireguard --tail=50
```

---

## 7. Vaultwarden + Nginx — Password Manager

### Nginx (`nginx-bitwarden`)

Terminates TLS for `bitwarden.rpi.lan`, proxies to Vaultwarden on the internal bridge.

**Port:** `443:443` (host → container)

**Certs (self-signed / mkcert, not public CA):**
```
./certs/bitwarden.rpi.lan.pem       → /etc/ssl/certs/bitwarden.crt
./certs/bitwarden.rpi.lan-key.pem   → /etc/ssl/private/bitwarden.key
```

**Config:** `./nginx.conf` → `/etc/nginx/conf.d/default.conf`

Typical nginx config for Vaultwarden (reference):
```nginx
server {
    listen 443 ssl;
    server_name bitwarden.rpi.lan;
    ssl_certificate     /etc/ssl/certs/bitwarden.crt;
    ssl_certificate_key /etc/ssl/private/bitwarden.key;
    location / {
        proxy_pass http://bitwarden:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /notifications/hub {
        proxy_pass http://bitwarden:3012;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Vaultwarden

**Image:** `vaultwarden/server:latest`

**Access:** `https://bitwarden.rpi.lan` (LAN only — not public facing)

**Data volume:** `./vaultwarden-data:/data` (bind mount — contains the SQLite fallback data directory, though MariaDB is used)

**Key env vars:**
```yaml
DATABASE_URL: "mysql://bitwarden:<pass>@bitwarden-db:3306/bitwarden"
DOMAIN: "https://bitwarden.rpi.lan"
WEBSOCKET_ENABLED: "true"
SIGNUPS_ALLOWED: "true"
```

Admin panel: `https://bitwarden.rpi.lan/admin` (requires `ADMIN_TOKEN`)

**Network:** Internal bridge only — no direct host port exposure. Only reachable through Nginx.

**Debug:**
```bash
docker logs bitwarden --tail=100
docker exec -it bitwarden /bin/sh
```

---

## 8. MariaDB — Vaultwarden Database

**Image:** `mariadb:11`
**Container name:** `bitwarden-db`
**Data:** `./bitwarden-db/data:/var/lib/mysql` (bind mount)
**Network:** `internal` bridge (not exposed to host)
**`stop_grace_period: 60s`** — prevents SIGKILL on deploy, which corrupts `tc.log`.

**Database:** `bitwarden` · user: `bitwarden`

**tc.log note:** If MariaDB fails to start with a `tc.log` corruption error, it was SIGKILL'd mid-transaction. Fix:
```bash
docker run --rm -v /srv/docker/compose/bitwarden-db/data:/var/lib/mysql \
  mariadb:11 mysqld --tc-heuristic-recover=ROLLBACK
```
Or simply delete `tc.log` from the data directory if no in-flight transactions were critical.

**Connect from host (for debugging):**
```bash
docker exec -it bitwarden-db mysql -u bitwarden -p bitwarden
```

**Backup:**
```bash
docker exec bitwarden-db mysqldump -u bitwarden -p bitwarden > ~/bitwarden-backup-$(date +%Y%m%d).sql
```

---

## 9. Samba — File Server

**Image:** `dperson/samba`
**Port:** `192.168.1.10:445:445` (bound to Pi's LAN IP only — not exposed on 0.0.0.0)

**Share config (from compose `command`):**
```
-u "ptm;<password>"         # create user ptm
-s "FS;/share;yes;no;no;ptm"  # share name FS, path /share, browsable, not readonly, not guest, owner ptm
```

**Volume mounts:**
- `/srv/fs-merged:/share` — the mergerfs pool is the share root
- Named volumes for Samba state: `samba_etc`, `samba_run`, `samba_cache`, `samba_lib`, `samba_log`

**Access:**
- Windows: `\\192.168.1.10\FS` or `\\rpi.lan\FS`
- Linux: `smb://192.168.1.10/FS`

**USERID/GROUPID:** `1000` / `1003`

**Healthcheck:** `smbclient -L \\localhost -U % -m SMB3` every 60s

**Logging subdirectory** (separate from the FS share):
- `\\rpi.lan\ptm\logging` → `/mnt/noblenumbat-fs/ptm/logging/` — deploy and stack logs land here, accessible from Windows.

**Debug:**
```bash
docker exec samba smbstatus
docker logs samba --tail=50
```

---

## 10. Storage — mergerfs + NFS

### Architecture

```
/srv/fs-merged/         ← mergerfs mount (unified pool)
    ├── /srv/fs/            ← local SD card storage (~74 GB)
    └── /mnt/noblenumbat-fs/  ← NFS from noblenumbat (/srv/fs-ext, ~397 GB)

Total pool: ~585 GB · Available: ~470 GB
```

Samba shares `/srv/fs-merged` as `\\rpi.lan\FS`.

### NFS

**Server:** noblenumbat (`192.168.1.6`) exports `/srv/fs-ext`

**Client:** Pi mounts it at `/mnt/noblenumbat-fs`

Check Pi's `/etc/fstab` entry:
```fstab
192.168.1.6:/srv/fs-ext  /mnt/noblenumbat-fs  nfs  defaults,_netdev  0  0
```

**Verify NFS mount:**
```bash
mountpoint /mnt/noblenumbat-fs
df -h /mnt/noblenumbat-fs
showmount -e 192.168.1.6           # from Pi
```

**On noblenumbat — check NFS exports:**
```bash
cat /etc/exports
sudo exportfs -v
systemctl status nfs-kernel-server
```

**If NFS drops:** mergerfs degrades gracefully to local-only. Samba stays up. Re-mount:
```bash
sudo mount /mnt/noblenumbat-fs     # or: sudo mount -a
```

### mergerfs

**Check pool status:**
```bash
df -h /srv/fs-merged
ls /srv/fs-merged
```

**Check policy** (mergerfs uses `ff` / `mfs` / `lfs` etc. for placement — check `/etc/fstab` or systemd unit for the mount options):
```bash
cat /proc/mounts | grep mergerfs
```

---

## 11. CI/CD — GitHub Actions Runner

### How it works

The Pi runs a self-hosted GitHub Actions runner process that **polls** GitHub's API over HTTPS (no inbound ports needed). When a push to `main` modifies `Peters Spellbook/RPI/docker-compose.yml`, the workflow triggers and the runner picks it up.

**Workflow file:** `.github/workflows/rpi-deploy.yml`

**Job steps:**
1. `actions/checkout@v4` — clone/update repo on Pi
2. `cp "Peters Spellbook/RPI/docker-compose.yml" /srv/docker/compose/docker-compose.yml` — deploy compose file
3. `docker compose pull` — pull latest images
4. `docker compose up -d --remove-orphans` — bring stack up, remove stale containers
5. `docker compose logs --tail=200` (if: always) — capture startup logs → `/mnt/noblenumbat-fs/ptm/logging/deploy-<timestamp>.log`

**Timeout:** 10 minutes. **Trigger:** also supports `workflow_dispatch` for manual runs from GitHub UI.

### Runner management

**Check runner status:**
```bash
# Find the runner service (usually installed as a systemd service)
systemctl list-units --type=service | grep actions
systemctl status actions.runner.*

# Runner working directory (default install)
ls ~/actions-runner/
```

**Runner logs:**
```bash
ls ~/actions-runner/_diag/
tail -f ~/actions-runner/_diag/Runner_*.log
```

**Re-register runner** (if token expires):
```bash
cd ~/actions-runner
./config.sh remove --token <token>
./config.sh --url https://github.com/<user>/<repo> --token <new-token>
```

---

## 12. Log Management

### Deploy logs (per-deploy snapshot)

**Location:** `/mnt/noblenumbat-fs/ptm/logging/deploy-YYYYMMDD-HHMMSS.log`
**Created by:** Step 5 of the CI workflow (`docker compose logs --tail=200`)
**Windows path:** `\\rpi.lan\ptm\logging\`
**Logrotate:** 10 rotations × 5 MB max = 50 MB total

### Stack log (continuous live stream)

**Location:** `/mnt/noblenumbat-fs/ptm/logging/stack.log`
**Created by:** `docker-stack-logs.service` (systemd) — streams `docker compose logs -f` continuously
**Logrotate:** 5 rotations × 20 MB max = 100 MB total (uses `copytruncate`)

**Live tail:**
```bash
tail -f /mnt/noblenumbat-fs/ptm/logging/stack.log
```

**From Windows:** open `\\rpi.lan\ptm\logging\stack.log` in a text editor that supports live reload.

**Service management:**
```bash
systemctl status docker-stack-logs
systemctl restart docker-stack-logs
journalctl -u docker-stack-logs -f
```

### Timestamps

All Pi and container logs are in **UTC**. Pi is in `America/New_York` (UTC-4 EDT / UTC-5 EST). Convert:
- UTC 05:00 → EDT 01:00 (1 AM local)
- UTC 12:00 → EDT 08:00 (8 AM local)

**Set up once** (already done via `setup-logs.sh`):
```bash
sudo bash "Peters Spellbook/RPI/setup-logs.sh"
```

### Container-level logs

```bash
docker logs <container> --tail=200 -f
docker logs pihole --since 1h
docker logs bitwarden-db --since 30m
```

---

## 13. Useful Commands & Diagnostics

### Stack health

```bash
docker compose ps -a                     # all containers + status
docker stats --no-stream                 # snapshot resource usage
docker system df                         # disk usage by images/volumes
```

### Full redeploy from scratch

```bash
cd /srv/docker/compose
docker compose down
docker compose pull
docker compose up -d
```

### Clear stopped containers / unused images

```bash
docker container prune -f
docker image prune -f
docker volume prune -f                   # careful: only removes volumes not in use
```

### Check what's listening on the host

```bash
ss -tlnp
ss -ulnp                                 # UDP (for DNS :53, WireGuard :51820)
```

### Pi system

```bash
# Temperature
vcgencmd measure_temp

# Memory
free -h

# Disk
df -h

# CPU load
uptime
top

# SD card health (periodic check)
sudo smartctl -a /dev/mmcblk0 2>/dev/null || echo "smartctl not supported on SD"
```

### Network diagnostics

```bash
# Verify DNS is serving from Pi-hole
nslookup google.com 192.168.1.10
dig @192.168.1.10 bitwarden.rpi.lan

# Check Pi-hole is listening
ss -tlnp | grep 53
ss -ulnp | grep 53

# WireGuard
docker exec wireguard wg show

# Samba reachability
smbclient -L \\\\192.168.1.10 -U ptm -m SMB3
```

### NFS troubleshooting

```bash
# On Pi — check if NFS mount is live
mountpoint -q /mnt/noblenumbat-fs && echo "mounted" || echo "NOT mounted"
showmount -e 192.168.1.6

# On noblenumbat — check NFS server
sudo systemctl status nfs-kernel-server
sudo exportfs -v
```

### Vaultwarden / MariaDB

```bash
# DB health
docker exec bitwarden-db mysqladmin -u bitwarden -p ping

# Vaultwarden health
curl -sk https://bitwarden.rpi.lan/alive

# DB size
docker exec bitwarden-db mysql -u bitwarden -p -e \
  "SELECT table_schema, ROUND(SUM(data_length+index_length)/1024/1024,2) AS 'MB' \
   FROM information_schema.tables WHERE table_schema='bitwarden' GROUP BY table_schema;"
```

### Pi-hole

```bash
docker exec pihole pihole status
docker exec pihole pihole -t              # live query log
docker exec pihole pihole updateGravity   # update block lists
docker exec pihole pihole -g              # same as above
```

### Logrotate (manual force)

```bash
sudo logrotate -f /etc/logrotate.d/docker-stack
```

---

## 14. WireGuard Peer Manager — Web UI

### Overview

Self-hosted web UI for managing WireGuard peers. Replaces manual config file editing.
Built with Node.js/Express (backend) + vanilla HTML/JS (frontend), served over HTTPS via a dedicated NGINX container.

**URL:** `https://wg.rpi.lan:8443` (LAN only — NGINX bound to `192.168.1.10:8443`)

### Containers

| Container | Image | Port |
|---|---|---|
| `wg-manager` | `node:lts-alpine` | :3000 (internal only) |
| `nginx-wgmgr` | `nginx:stable-alpine` | `192.168.1.10:8443:443` |

### Volumes

| Mount | Purpose |
|---|---|
| `./data/wireguard:/wg-config` | Read/write WireGuard peer configs (shared with `wireguard` container) |
| `/var/run/docker.sock:/var/run/docker.sock` | Exec `wg syncconf` into the `wireguard` container to apply changes live |
| `./webapp:/app` | Node app source (deployed by CI) |
| `/srv/fs-merged/ptm/certs/wg.rpi.lan.pem` | TLS cert (off-repo, stored at `/srv/fs-merged/ptm/certs/`) |
| `/srv/fs-merged/ptm/certs/wg.rpi.lan-key.pem` | TLS key (off-repo) |

### How peer reload works

After adding or removing a peer, the backend runs:
```bash
docker exec wireguard sh -c "wg syncconf wg0 <(wg-quick strip /config/wg0.conf)"
```
This is **non-disruptive** — existing VPN sessions are not dropped.

### API endpoints

| Method | Route | Action |
|---|---|---|
| GET | `/api/peers` | List all peers from `wg0.conf` |
| GET | `/api/peers/status` | Live handshake/transfer data from `wg show` |
| POST | `/api/peers` | Add peer (body: `{ "name": "..." }`) |
| DELETE | `/api/peers/:dir` | Remove peer by directory name (e.g. `peer_laptop`) |
| GET | `/api/peers/:dir/config` | Download `.conf` file |
| GET | `/api/peers/:dir/qr` | Get QR code PNG |

### TLS cert

Self-signed, 10-year validity. Stored off-repo at `/srv/fs-merged/ptm/certs/`.
To regenerate:
```bash
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /srv/fs-merged/ptm/certs/wg.rpi.lan-key.pem \
  -out /srv/fs-merged/ptm/certs/wg.rpi.lan.pem \
  -subj "/CN=wg.rpi.lan" \
  -addext "subjectAltName=DNS:wg.rpi.lan,IP:192.168.1.10"
```

### Pi-hole DNS record

`wg.rpi.lan → 192.168.1.10` (Local DNS Records in Pi-hole UI)

### Manual fallback (if webapp is down)

Add peer manually:
```bash
# Edit wg0.conf directly
nano /srv/docker/compose/data/wireguard/wg0.conf

# Reload live (no session drop)
docker exec wireguard sh -c "wg syncconf wg0 <(wg-quick strip /config/wg0.conf)"
```

### Debug

```bash
docker logs wg-manager --tail=50
docker logs nginx-wgmgr --tail=50
curl -k https://wg.rpi.lan:8443/api/peers
```

---

## Quick Reference — Service URLs

| Service | URL | Notes |
|---|---|---|
| Pi-hole web UI | `http://192.168.1.10/admin` | or `http://rpi.lan/admin` |
| Vaultwarden | `https://bitwarden.rpi.lan` | LAN only — self-signed cert |
| Vaultwarden admin | `https://bitwarden.rpi.lan/admin` | requires admin token |
| Samba share (Pi) | `\\192.168.1.10\FS` | or `\\rpi.lan\FS` |
| Samba share (opti) | `\\192.168.1.11\fs` | or `\\opti.lan\fs` · OMV-managed |
| Media drop inbox | `\\opti.lan\fs\ptm\Media-Import\` | drop video files here for Jellyfin auto-import |
| Movie library storage | `\\opti.lan\fs\ptm\Media\Movies\` | primary movie library (served by Jellyfin on noblenumbat) |
| Deploy logs | `\\rpi.lan\ptm\logging\` | deploy + stack logs |
| WireGuard Manager | `https://wg.rpi.lan:8443` | LAN only — self-signed cert |
| **Jellyfin** | `http://jellyfin.lan:8096` | runs on noblenumbat · user: admin |
| Radarr | `http://192.168.1.6:7878` | noblenumbat · movie manager |
| Sonarr | `http://192.168.1.6:8989` | noblenumbat · TV manager |
| Prowlarr | `http://192.168.1.6:9696` | noblenumbat · indexer manager |
| qBittorrent | `http://192.168.1.6:8081` | noblenumbat · via gluetun VPN · user: admin |
| Bazarr | `http://192.168.1.6:6767` | noblenumbat · subtitle manager |
| Mylar3 | `http://192.168.1.6:8090` | noblenumbat · comic manager |
| Kavita | `http://192.168.1.6:5000` | noblenumbat · comic/book reader (phone-friendly PWA) |
| Portainer | `http://192.168.1.6:9000` | noblenumbat · Docker UI |
| FlareSolverr | `http://192.168.1.6:8191` | noblenumbat · Cloudflare bypass for Prowlarr |

---

## Quick Reference — Key File Paths

| Path | What |
|---|---|
| `/srv/docker/compose/docker-compose.yml` | Live stack compose file |
| `/srv/docker/compose/nginx.conf` | Nginx reverse proxy config |
| `/srv/docker/compose/certs/` | TLS certs for bitwarden.rpi.lan |
| `/srv/docker/compose/bitwarden-db/data/` | MariaDB data directory |
| `/srv/docker/compose/vaultwarden-data/` | Vaultwarden data directory |
| `/srv/docker/compose/data/wireguard/` | WireGuard config + peer keys |
| `/srv/fs/` | Local SD card storage pool |
| `/srv/fs-merged/` | mergerfs unified mount |
| `/mnt/noblenumbat-fs/` | NFS mount from noblenumbat |
| `/mnt/noblenumbat-fs/ptm/logging/` | All homelab logs |
| `~/actions-runner/` | GitHub Actions runner install |
| `/etc/systemd/system/docker-stack-logs.service` | Live log streaming service |
| `/etc/logrotate.d/docker-stack` | Log rotation config |

---

## noblenumbat — NFS Server Config

**NFS export:** `/srv/fs-ext` → Pi

**Check exports file:**
```
/srv/fs-ext  192.168.1.10(rw,sync,no_subtree_check,no_root_squash)
```

**Suspend disabled:** `sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`

**If noblenumbat goes down:** Pi loses `/mnt/noblenumbat-fs`. mergerfs degrades to local `/srv/fs` only. Samba + all Docker services stay up. NFS re-mounts on Pi reboot or manual `mount /mnt/noblenumbat-fs`.

---

## 15. Homelab Agent Platform

Self-monitoring "agents" are **orchestrated from the opti server** (192.168.1.11) — scheduled by
GitHub Actions on a self-hosted runner, controlled from the webapp via a lightweight dispatcher
service. Nothing depends on the desktop. Setup checklist: `Tools/automation/setup-opti.md`.

The Tier-B homelab agents (`hardware-report`, `software-inventory`, `network-report`, and the
disk/docker half of `homelab-doctor`) gather data **from every box in the homelab** — `opti`,
`rpi` (192.168.1.10) and `noblenumbat` (192.168.1.6) — over SSH. Each host's commands run *on that
host* (including opti, reached via localhost) so reachability/DNS/port checks reflect that box's own
vantage point. The collector reads the host list + key from `HL_HOSTS` / `HL_SSH_KEY` (see
`Tools/homelab/_hosts.py`); it is host-agnostic, so the same command works run from a workstation.
Each report carries a `hosts[]` array the webapp renders per host. If the SSH key is missing the
report fails loudly with a single clear finding rather than silently producing empty data.

### Agents

**Tier A — Security** (→ `security-reports/` → `/api/reports` → webapp `#security`):
| Agent | Report | Purpose |
|---|---|---|
| `journald-hunter` | `journal-hunt-latest.json` | Combs **all** journald logs (every unit/boot) for errors/flags — service failures, OOM, disk/FS/kernel/hardware faults — **plus** security signals (failed/accepted SSH, sudo/su, new users). Combined security + general-health sweep. |
| `persistence-auditor` | `persistence-audit-latest.json` | Baseline+diff of cron, systemd timers/units, autostart, rc/profile files. |

**Tier B — Homelab** (→ `agent-logs/` → `/api/agents` → webapp `#agents`):
| Agent | Report | Purpose |
|---|---|---|
| `hardware-report` | `hardware-latest.json` | Per-host CPU/RAM/disk+SMART/GPU/thermals/uptime/virt across all boxes. |
| `software-inventory` | `software-latest.json` | Per-host package count, pending updates, kernel/service versions, docker. |
| `homelab-doctor` | `homelab-doctor-latest.json` | Network-wide service reachability + TLS cert expiry + report freshness; **per-host** disk + docker. |
| `network-report` | `network-latest.json` | Per-host interfaces, gateway/internet/DNS reachability, listening ports. |

Webapp `#agents` cards are shown in a fixed order — **Homelab Doctor → Hardware → Software →
Network** (set via `order` in the backend `CATALOG`, `routes/agents.js`).

**Leetify** (`leetify-stats` → `leetify-latest.json`) is a non-security CS2-stats agent surfaced on
the webapp **Home** card; dormant unless `LEETIFY_API_KEY` + `STEAM64_ID` are set.

### Control plane

- **Schedule:** `.github/workflows/homelab-agents.yml`, `runs-on: [self-hosted, opti]`. The `opti`
  label keeps it off the Pi deploy runner. `homelab-doctor`+`network` every 30 min; `hardware`,
  `software` + security agents daily. `leetify-stats` and `refresh-cs2-knowledge` make paid Claude
  calls and are **not scheduled** — run them on demand via "Run workflow" (`workflow_dispatch`).
- **Dispatcher:** `hl-agent-dispatcher.service` on opti (`:9099`) owns `agents-state.json` and runs
  agents on demand from an allowlist. The webapp **Enable/Disable** + **Run now** buttons proxy to
  it over the LAN. Both schedule and run-now honor the enabled flag.
- **Config/secrets:** `/etc/hl-agents.env` on opti (paths + `LEETIFY_API_KEY` + `STEAM64_ID` +
  `HL_DISPATCH_TOKEN` + `HL_HOSTS` + `HL_SSH_KEY`), sourced by both the workflow and the dispatcher
  — secrets never leave opti.
- **Multi-host SSH:** `HL_HOSTS="opti=127.0.0.1,rpi=192.168.1.10,noblenumbat=192.168.1.6"` and
  `HL_SSH_KEY=/path/to/hl_agents` (private key authorized on all three boxes *and* on opti itself).
  Non-interactive `BatchMode` SSH; an unreachable host degrades to an "unreachable" entry, not a
  crash. Generate once: `ssh-keygen -t ed25519 -f ~/.ssh/hl_agents -N ''`, then append the `.pub`
  to each host's `~/.ssh/authorized_keys` (opti included).

### Flow

```mermaid
flowchart LR
  subgraph GH[GitHub]
    WF[homelab-agents.yml<br/>schedule + dispatch]
  end
  subgraph OPTI[opti server 192.168.1.11]
    RUN[self-hosted runner<br/>label: opti]
    DISP[agent-dispatcher.service :9099<br/>enable/disable + run-now]
    ENV[/etc/hl-agents.env/]
    AG[agents<br/>journald-hunter · persistence-auditor<br/>hardware · software · homelab-doctor · network · leetify]
    REP[(security-reports/ + agent-logs/<br/>+ agents-state.json)]
  end
  subgraph PI[Raspberry Pi - rpi.lan]
    WEB[webapp backend<br/>/api/reports · /api/agents]
    UI[#security · #agents · Home]
  end
  WF -->|runs on| RUN --> AG
  RUN -. sources .-> ENV
  AG --> REP
  DISP --> AG
  DISP --- REP
  REP -->|CIFS /mnt/opti-fs| WEB --> UI
  UI -->|Enable/Disable · Run now| WEB -->|LAN proxy| DISP
```

**Storage map:** opti `…/fs/ptm/{security-reports,agent-logs}` = Pi `/mnt/opti-fs/ptm/...` = webapp
container `/reports` + `/agent-logs`.

---

## 16. YAMS Media Stack (noblenumbat)

Full YAMS installation on noblenumbat (192.168.1.6) — Jellyfin + arr stack + qBittorrent + ProtonVPN.

### Containers

| Container | Image | Port | Notes |
|---|---|---|---|
| `jellyfin` | `lscr.io/linuxserver/jellyfin` | `8096` | Media server · QuickSync VAAPI |
| `radarr` | `lscr.io/linuxserver/radarr` | `7878` | Movie manager · 43 Batman titles added |
| `sonarr` | `lscr.io/linuxserver/sonarr` | `8989` | TV manager |
| `lidarr` | `lscr.io/linuxserver/lidarr` | `8686` | Music manager |
| `prowlarr` | `lscr.io/linuxserver/prowlarr` | `9696` | Indexer manager (no indexers configured) |
| `qbittorrent` | `lscr.io/linuxserver/qbittorrent:4.6.3` | `8081` | Torrent client · routed through gluetun |
| `sabnzbd` | `lscr.io/linuxserver/sabnzbd` | `8080` | Usenet client · unconfigured |
| `bazarr` | `lscr.io/linuxserver/bazarr` | `6767` | Subtitle manager |
| `gluetun` | `qmcgaw/gluetun:v3.41.0` | — | ProtonVPN free tier · Netherlands · OpenVPN |
| `portainer` | `portainer/portainer-ce` | `9000` | Docker management UI |
| `watchtower` | `nickfedor/watchtower` | — | Auto-updates containers |
| `flaresolverr` | `ghcr.io/flaresolverr/flaresolverr` | `8191` | Cloudflare bypass proxy for Prowlarr indexers |
| `mylar3` | `lscr.io/linuxserver/mylar3` | `8090` | Comic manager (arr for comics) · sends torrents to qBittorrent |
| `kavita` | `lscr.io/linuxserver/kavita` | `5000` | Comic/book library + mobile web reader (CBZ/CBR/epub/PDF, OPDS) |

### Storage layout (on noblenumbat)

```
/srv/media/
  music/           ← Lidarr-managed music
  comics/          ← Mylar3-managed comic library (Kavita library root; Kavita also reads books/)
  downloads/
    torrents/      ← qBittorrent save path (LOCAL — torrents never write to the network)
  staging/         ← media-import drop zone → Radarr DownloadedMoviesScan
  blackhole/       ← torrent blackhole (qBittorrent watch folder, fed by media-import.sh)

/mnt/opti-library/ ← MOVIE LIBRARY — CIFS mount of \\opti\fs\ptm\Media\Movies (opti mergerfs pool).
                     Bind-mounted over /data/movies in jellyfin/radarr/bazarr via
                     docker-compose.custom.yaml, so containers still see /data/movies.
                     Radarr imports are cross-device → copy fallback (no hardlinks).
/mnt/opti-shows/   ← TV LIBRARY — CIFS mount of \\opti\fs\ptm\Media\Shows (opti mergerfs pool).
                     Bind-mounted over /data/tvshows in jellyfin/sonarr/bazarr, same pattern as
                     movies. Migrated 2026-07-08 (85 episode files / ~37 GB, diff-verified against
                     source before the local copy was deleted).
/mnt/opti-media/   ← file-drop inbox — CIFS mount of \\opti\fs\ptm\Media-Import

/opt/yams/         ← YAMS install root
  docker-compose.yaml
  docker-compose.custom.yaml  ← QuickSync patch + opti movie/TV library binds + kavita/mylar3
  .env               ← includes COMPOSE_FILE= so both compose files always load
  config/          ← per-service config volumes
```

Movies and TV both live on **opti** (movies moved 2026-07; TV followed 2026-07-08, freeing an
additional ~37 GB). Only comics/music/downloads/staging remain local. Note: on 2026-07-08 the
opti bind-mounts for `jellyfin`/`radarr`/`sonarr`/`bazarr` were found **missing from the live
`docker-compose.custom.yaml`** despite being documented here and present in git — the deployed
file only had the QuickSync patch, meaning new Radarr/Sonarr imports had been silently landing on
local disk for an unknown period before this was caught and redeployed. If storage docs and live
`docker inspect` output disagree again, trust `docker inspect`, not this file, and re-sync
whichever drifted. The `vpn-stack-heal.timer` also enforces a low-disk guardrail: **< 10 GB free
on `/` pauses all torrents** (log: `/var/log/vpn-stack-heal.log`; resume manually in qBittorrent
after freeing space).

### File-drop pipeline

Drop video files **or `.torrent` files** to **`\\opti.lan\fs\ptm\Media-Import\`** from any Windows machine. (noblenumbat runs no SMB server — the drop share is on opti only. `\\opti\fs\ptm\Media\Movies\` is the movie *library* — don't drop files there.)

On noblenumbat: `/mnt/opti-media` is a CIFS mount of that share (fstab, auto-mount). The `media-import.timer` systemd unit runs `/usr/local/bin/media-import.sh` every 2 min:
- **Video files** (mtime-stable ≥2 min) → moved to `/srv/media/staging/` + `Radarr: DownloadedMoviesScan`. Radarr matches, renames, and imports into the movie library on opti (`/data/movies` in-container = `/mnt/opti-library`). Jellyfin picks it up automatically (realtime monitor enabled).
- **`.torrent` files** → moved to `/srv/media/blackhole/`, which qBittorrent watches (`/data/blackhole` in-container, scan_dirs). qBittorrent downloads via the VPN into `/data/downloads/torrents`; Radarr imports completed downloads.

Logs: `/var/log/media-import.log` on noblenumbat.

### Hardware transcoding (QuickSync)

Jellyfin uses Intel UHD 620 (i7-8665U) for VAAPI H.264 transcoding. The custom compose override passes `/dev/dri` and render gid `992` into the container. Configured in Jellyfin Dashboard → Playback → Hardware acceleration: **VAAPI**, device `/dev/dri/renderD128`.

### VPN (Gluetun / ProtonVPN)

qBittorrent and SABnzbd run inside gluetun's network namespace (`network_mode: service:gluetun`). Free tier: Netherlands servers only, no port forwarding. Credentials in `/opt/yams/.env` (`VPN_USER`/`VPN_PASSWORD` = ProtonVPN OpenVPN credentials, not account login).

### FlareSolverr (Cloudflare bypass)

FlareSolverr runs on port `8191` and solves Cloudflare challenges on behalf of Prowlarr. To wire it in Prowlarr:
1. Prowlarr → Settings → Indexers → Add FlareSolverr proxy → URL: `http://flaresolverr:8191`
2. Tag the proxy (e.g. `flaresolverr`), then assign that tag to any Cloudflare-protected indexer (e.g. 1337x).

### Comics arm (Mylar3 + Kavita)

Defined in `docker-compose.custom.yaml` (not the YAMS base compose, so YAMS updates won't clobber it). Mylar3 monitors series and pushes torrents to qBittorrent (via gluetun, same as everything else); completed downloads land in `/srv/media/comics/`, which Kavita serves as a phone-friendly web reader (also covers `/srv/media/books/`).

One-time wiring (all via UIs):
1. **Mylar3** (`:8090`) → Settings → Web Interface: note the API key. Settings → Download → Torrents: qBittorrent, host `172.60.0.18`, port `8081` (gluetun IP — qBittorrent lives in gluetun's netns), qBittorrent credentials, label/category `comics`. Comic Location: `/data/comics`.
2. **Mylar3 metadata:** requires a free ComicVine API key (comicvine.gamespot.com/api) → Settings → Web Interface → ComicVine API.
3. **Prowlarr** (`:9696`) → Settings → Apps → add **Mylar** → Prowlarr server `http://prowlarr:9696`, Mylar server `http://mylar3:8090`, Mylar3 API key. Indexers with the Comics category sync automatically.
4. **Kavita** (`:5000`) → create admin account on first visit → Add library: type *Comics*, folder `/data/comics` (optionally a second *Books* library at `/data/books`).

Phone reading: open `http://192.168.1.6:5000` in the phone browser → "Add to Home Screen" (PWA, remembers reading position). Native apps connect via OPDS (Kavita → user settings → OPDS URL): Mihon on Android (Kavita extension), Panels/Chunky on iOS. Off-LAN: connect the phone's WireGuard tunnel first (see §WireGuard).

### What is NOT configured (intentional)

- **Prowlarr indexers:** none added — FlareSolverr is ready to support Cloudflare-protected indexers (e.g. 1337x) once you add them via the Prowlarr UI.
- **SABnzbd:** installed but unconfigured (requires paid Usenet provider).

### Manage stack

```bash
# SSH to noblenumbat (via opti jump or direct if key is authorized)
cd /opt/yams
docker compose -f docker-compose.yaml -f docker-compose.custom.yaml ps
docker compose -f docker-compose.yaml -f docker-compose.custom.yaml up -d
docker compose -f docker-compose.yaml -f docker-compose.custom.yaml logs -f jellyfin

# Or use yams CLI (installed at /usr/local/bin/yams)
yams start
yams stop
yams restart

# Check VPN
docker logs gluetun --tail=20
# Check media importer
systemctl status media-import.timer
journalctl -u media-import.service -n 30
tail -f /var/log/media-import.log
```

### Repo files

```
homelab/noblenumbat-srv/yams/
  docker-compose.yml          ← deployed compose (secrets stripped)
  docker-compose.custom.yml   ← QuickSync overlay
  .env.example
  media-import.sh             ← file-drop importer script
  media-import.service        ← systemd unit
  media-import.timer          ← systemd timer (2 min interval)
```
