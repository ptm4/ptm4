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
    └── noblenumbat      192.168.1.6    Dell Latitude 7400 (NFS server, storage)

VPN tunnel: 10.8.0.0/24   (WireGuard peers, up to 5)
```

**DNS:** Pi-hole at `192.168.1.10:53` handles all LAN DNS. Upstream: `192.168.1.1` (router) + `1.1.1.1` (Cloudflare fallback).

**DHCP:** Pi-hole serves DHCP for `192.168.1.0/24`. Router DHCP should be disabled.

**Local hostnames used in stack:**
- `rpi.lan` → `192.168.1.10`
- `bitwarden.rpi.lan` → `192.168.1.10` (Pi-hole local DNS record)
- `vpn.rpi.lan` → `192.168.1.10` (Pi-hole local DNS record, also needs public DNS if VPN clients are external)

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

### noblenumbat (`192.168.1.6`)

| Field | Value |
|---|---|
| Model | Dell Latitude 7400 |
| CPU | i7-8665U · 4c/8t · 4.8 GHz boost · VT-x |
| RAM | 16 GB DDR4 2667 MT/s |
| Disk | 512 GB NVMe · SK Hynix PC611 |
| Network | Intel Wireless-AC · WiFi only |
| OS | Ubuntu 24.04 |
| IP | `192.168.1.6` (DHCP) |
| Role | NFS server (`/srv/fs-ext`) · suspend disabled |

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
| Samba share | `\\192.168.1.10\FS` | or `\\rpi.lan\FS` |
| Deploy logs | `\\rpi.lan\ptm\logging\` | deploy + stack logs |
| WireGuard Manager | `https://wg.rpi.lan:8443` | LAN only — self-signed cert |

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
