# rpi rebuild + app-tier migration to opti

*Drafted 2026-09-08. Status: PLAN — Phase 1 scripts are staged on noblenumbat; nothing else executed.*
*Written for an executing agent. Every step is a command with an expected result. No step
requires a judgment call; where a choice existed it has already been made and is stated.*

## 0. Facts this runbook relies on (verified 2026-09-08)

| Host | Hardware | OS | Role after this runbook |
|---|---|---|---|
| `rpi` 192.168.1.10, MAC `e4:5f:01:89:b6:4d` | Raspberry Pi 4, 4 GB | Ubuntu 24.04 (new) | **DNS + vault only**: Pi-hole, MariaDB, Vaultwarden, nginx-bitwarden |
| `opti` 192.168.1.11 | Dell OptiPlex 7010 MT, i5-3570 4c/4t, 6 GB DDR3 → **32 GB**, ZFS pool `red` (3.6 TB), root on `sda` ST500DM002 (**264 reallocated sectors, 40 078 h — dying**) | Debian 12, ZFS 2.3.2, kernel 6.12, cgroup v2 | **Storage + control plane + app tier**: webapp, 5 Discord bots, hltv-api, notes, Dozzle, second Pi-hole. (Uptime Kuma landed here too, then moved on to noblenumbat 2026-09-10: opti's ufw dropped its bridge→host probes, and a monitor on opti can't report opti down.) |
| `noblenumbat` 192.168.1.6 | Latitude 7400, i7-8665U 4c/8t, 16 GB DDR4 (1 free SODIMM, max 32), NVMe 512 GB, **wired** via ASIX AX88179 USB3 GbE `enx207bd2626533` | Ubuntu 24.04 | unchanged (media). Holds the rescue copy. |

- The network is entirely wired Ethernet. DHCP is served by the TP-Link Archer at 192.168.1.1
  (2 h leases, DNS handed out = 192.168.1.1 + 192.168.1.10). Pi-hole DHCP stays **off**.
- SSH from the Windows workstation: `ssh -i ~/.ssh/rpi ptm@192.168.1.10`,
  `ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11`, `ssh -i ~/.ssh/noblenumbat ptm@192.168.1.6`.
  All three have passwordless sudo for `ptm`.
- **Rescue copy of the dead card** (the only copy): noblenumbat `/home/ptm/rpi-rescue/fs/`
  (5.2 GB). Layout mirrors the Pi. Pi-hole's live config is in
  `var/lib/docker/volumes/compose_pihole_data/_data/`, **not** `srv/docker/pihole/` (stale
  January copy). Vaultwarden DB: `srv/docker/compose/bitwarden-db/data/`.
- Staged on noblenumbat `/home/ptm/rpi-rescue/`: `image/ubuntu-24.04.3-preinstalled-server-arm64+raspi.img.xz`
  (sha256 verified), `preseed/{user-data,network-config,meta-data}` (built, YAML-validated),
  `preseed/flash.sh`, `preseed/restore.sh`, `preseed/build-preseed.sh`.
- Old rpi identities the preseed reproduces: user `ptm` uid 1000 gid 1003, user `bitwarden`
  uid 1001 gid 1004, hostname `rpi`, TZ America/New_York, 5 authorized SSH keys (ptm@ptm,
  claude-homelab-doctor, ptm@opti, workstation-homelab-mgmt, noblenumbat-rpi-restore).
- opti listening ports already taken (do not collide): 22, 80 (OMV nginx), 139/445 (smbd),
  3389 (xrdp), 5357/3702 (wsdd), 8787 (hl-arch-agent), 9090 (cockpit socket), 9100
  (homelab-db). Port 9099 (dispatcher) is currently **not** listening — see §0.1.
- opti's `systemd-resolved` runs with the stub listener on 127.0.0.53:53 and uses
  DNS=192.168.1.10 (drop-in `/etc/systemd/resolved.conf.d/10-homelab-lan-dns.conf`).
- Compose project name on both hosts is `compose` (directory `/srv/docker/compose`), so
  named volumes are `compose_<name>`. Keep that directory name on opti — the volume names
  in the rescue copy depend on it.

### 0.1 Pre-existing breakage found on opti (must be fixed in Phase 2, before Phase 3)

`/srv/red/fs/ptm/repo/ptm4` no longer exists. Peter moved his working copy to the Windows
workstation (`E:\REPO\ptm4`) and parked the pool checkout at
`/srv/red/fs/ptm/old repo location/ptm4` on 2026-09-08 17:39 (main @ f4175b2, **98 uncommitted
modified files, do not delete or reset it — Peter reconciles it**). opti's services were never
re-pointed, so:

- `hl-agent-dispatcher.service` is crash-looping (`Failed at step CHDIR`). Port 9099 is dead.
- `homelab-db.service` is still running from a process started 2026-09-01 and will fail on its
  next restart (unit `WorkingDirectory=/srv/red/fs/ptm/repo/ptm4/homelab/tools/homelab-db`).
- The webapp's `/workspace` mount and the tux CIFS working copy both point at the old path.

**Fix chosen (revised 2026-09-08, Phase 2.3): opti gets no git checkout at all.** Peter wants
`E:\REPO\ptm4` to be the one and only repo working copy — a second clone on opti (even a
read-only one, per the original plan here) is exactly the kind of second copy that caused this
mess. Instead `opti-deploy.yml`'s existing self-hosted-runner checkout is `rsync -a --delete`d
straight into `/srv/red/fs/ptm/repo/ptm4/homelab/` on every push under `homelab/**` (implemented
2026-09-08 — see that workflow's "Sync the homelab/ snapshot" step). That directory is a plain,
`.git`-less snapshot, overwritten wholesale each run; nobody edits it. Because it lands at the
exact path the dispatcher, homelab-db, and the rpi webapp's `/workspace:ro` mount (via
`/mnt/opti-fs/ptm/repo/ptm4` on rpi, the same underlying pool path) already expect, no systemd
unit or compose file needed to change. The moved-aside copy at
`/srv/red/fs/ptm/old repo location/ptm4` is left untouched. This step still needs to actually
run once (push to `main`, or `workflow_dispatch`) before the dispatcher and homelab-db recover.

### 0.2 Decisions already made (do not re-open)

| Topic | Decision |
|---|---|
| rpi OS | Ubuntu Server 24.04.3 arm64, cloud-init preseed, static 192.168.1.10 via netplan |
| rpi boot medium | USB SSD: Crucial BX500 240 GB on StarTech USB3S2SAT3CB, in a **blue** USB 3 port, SD slot empty |
| opti RAM | 4×8 GB DDR3L-1600 UDIMM (Timetec 32 GB kit). Both old sticks come out. |
| opti Docker | docker-ce from Docker's Debian repo, overlay2, **data-root on ZFS dataset `red/docker` mounted at `/var/lib/docker`** (ZFS ≥ 2.2 supports overlayfs). Compose dir on dataset `red/docker-apps` mounted at `/srv/docker`. Nothing Docker-related lives on the dying `sda`. |
| App tier home on opti | `/srv/docker/compose/` (same path as the Pi, so the deploy workflow is a near-copy) |
| Source dirs in the repo | stay under `homelab/hosts/rpi/` (webapp.v2.legacy, discord-*, notes-app, nginx-wg.conf). Only the compose file and the workflow are new. Renaming source dirs is a later cleanup, not part of this runbook. |
| Hostnames | `webapp.rpi.lan` / `webapp.rpi` keep their names and move to 192.168.1.11 (the mkcert cert is for the name, so nothing re-issues). notes/kuma/dozzle direct ports become `opti.lan:3002/3001/9999`. |
| Second Pi-hole on opti | bridge mode (OMV owns :80), DNS only, admin UI on :8053, resolved stub listener disabled |
| Order of work | Phase 1 (rpi back with the FULL old stack) → Phase 2 (opti prep, needs the RAM delivery) → Phase 3 (move app tier) → Phase 4 (trim rpi) → Phase 5 (second Pi-hole + backups). Phases 1 and 2 can overlap in time; 3 needs both done. |

## Phase 0 — parts (Peter buys; prices live from amazon.com 2026-09-08)

| Purpose | Part | Price | Status |
|---|---|---|---|
| rpi boot SSD | Crucial BX500 240 GB CT240BX500SSD1 | $64.88 | ordered, arrives 2026-09-09 |
| rpi USB-SATA | StarTech USB3S2SAT3CB | $9.90 | ordered, arrives 2026-09-09 |
| **opti RAM** | **Timetec 32 GB kit (4×8 GB) DDR3L-1600 PC3L-12800 CL11 UDIMM 1.35/1.5 V** | **$74.99** Prime, "17 left" | to buy. Equivalents: generic 4×8 kits $73.99, A-Tech $83.56, Gigastone $88.99. Must say UDIMM / non-ECC / unbuffered / 240-pin. **Never** RDIMM, ECC, registered, or SODIMM. |
| rpi console | CP2102 USB-to-TTL **cable** (4 female Dupont leads, 3 ft) | $9.99 | recommended |
| rpi video | micro-HDMI → HDMI adapter (UGREEN/JSAUX) | $8.99 | recommended |
| opti OS disk (Phase 6, later) | Crucial BX500 240 GB (OS only) | $64.88 | not yet |
| noblenumbat RAM (optional, not needed) | 16 GB DDR4-2666 SODIMM, e.g. Crucial CT16G4SFRA266 $112.51 / A-Tech $101.54 | — | skip; DDR4 is spiked |

## Phase 1 — rpi rebuild onto the USB SSD

Runs on **noblenumbat** (it holds the image, preseed, and rescue copy). Total ≈ 40 min.

### 1.1 Flash

1. Plug the BX500 into the StarTech adapter and the adapter into a USB port on noblenumbat.
2. Find the device and confirm it is the SSD, not the NVMe:
   ```bash
   ssh -i ~/.ssh/noblenumbat ptm@192.168.1.6 'lsblk -dno NAME,SIZE,TRAN,MODEL,RO | grep -v nvme'
   ```
   Expected: one line like `sda 223.6G usb CT240BX500SSD1 0`. If nothing shows, re-seat the
   cable and re-run. Do not continue until exactly one `usb` disk is listed.
3. Flash (the script refuses the NVMe, anything read-only, anything < 8 GB, and the dead
   card's serial). Replace `sda` with the name from step 2:
   ```bash
   ssh -i ~/.ssh/noblenumbat ptm@192.168.1.6 '/home/ptm/rpi-rescue/preseed/flash.sh /dev/sda'
   ```
   Expected last lines: `--- boot partition now has:` listing `user-data`, `network-config`,
   `meta-data`, then `FLASH DONE — card can be removed and put in the Pi`. Takes ~3 min.
4. If it prints `not an mmc/usb device` or `refusing`, stop and report the printed reason.

### 1.2 First boot

1. Unplug the adapter from noblenumbat. Plug it into one of the Pi's **blue** USB 3 ports.
   The microSD slot must be **empty**. Power on.
2. Wait. First boot expands the root filesystem, then cloud-init sets the static IP, creates
   the users, adds Docker's repo and installs 16 packages. Budget 6 minutes.
3. From the workstation, poll until it answers:
   ```bash
   until ssh -i ~/.ssh/rpi -o ConnectTimeout=3 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ptm@192.168.1.10 'cat /var/lib/cloud/rpi-preseed-done' 2>/dev/null; do sleep 15; done
   ```
   Expected: a UTC timestamp line. (The host key is new at this point; §1.3 restores the old
   one, after which normal `known_hosts` entries work again.)
4. If nothing answers after 10 minutes: the Pi did not boot from USB. The only cause seen in
   practice is a bootloader older than 2020-09-03. Remedy: flash any spare microSD with the
   same image (same `flash.sh`, device `/dev/mmcblk0`), boot from it once, run
   `sudo rpi-eeprom-update -a && sudo reboot`, then remove the card and retry USB. Report
   before doing this — it needs a microSD Peter does not currently own.

### 1.3 Restore the old system onto it

Runs on noblenumbat, pushes over SSH with the `noblenumbat-rpi-restore` key baked into the
preseed:
```bash
ssh -i ~/.ssh/noblenumbat ptm@192.168.1.6 'sudo /home/ptm/rpi-rescue/preseed/restore.sh 2>&1 | tee /home/ptm/rpi-rescue/restore.log'
```
What it does, in order (each step prints `##### <time> N. …`): waits for the preseed marker;
restores `/etc/ssh/ssh_host_*` and restarts sshd; stops Docker; restores `/srv`, all
`compose_*` and `open-webui_*` volumes; **sets Pi-hole `dhcp.active=false`** in the restored
`pihole.toml`; restores `/home/ptm`, `/root`, `/opt/bitwarden`, `/usr/local/bin`,
`/etc/opti-creds`, the homelab timers/units, the Actions-runner unit; appends the two CIFS
lines to `/etc/fstab` and mounts them; starts Docker, enables the timers and services;
`docker compose up -d` in `/srv/docker/compose`; finally switches the Pi's own resolver to
127.0.0.1 if Pi-hole answers on :53.

Expected at the end: the `docker ps` listing shows these 14 containers `Up`: pihole,
bitwarden-db, bitwarden, nginx-bitwarden, notes-api, webapp, discord-weather,
discord-healthdigest, discord-jellyfin, discord-sports, discord-hltv, hltv-api, nginx-webapp,
uptime-kuma, dozzle. Image pulls and the five bot builds make this step 10–15 min on a Pi 4.
Lines beginning `!! rc=` are failures; report them verbatim. `rc=23` from an rsync of
`/home/ptm` is expected (the unreadable Node headers) and harmless.

### 1.4 Verify

Run from the workstation; every line must produce the stated result.
```bash
dig +short rpi.lan @192.168.1.10                      # 192.168.1.10
dig +short google.com @192.168.1.10 | head -1         # any IPv4
curl -sk -o /dev/null -w '%{http_code}\n' https://192.168.1.10/          # 200 (Vaultwarden via nginx)
curl -sk -o /dev/null -w '%{http_code}\n' https://webapp.rpi.lan:8443/   # 200
curl -s  -o /dev/null -w '%{http_code}\n' http://192.168.1.10:3002/notes  # 200
curl -s  -o /dev/null -w '%{http_code}\n' http://192.168.1.10:3001/       # 200 (Kuma)
ssh -i ~/.ssh/rpi ptm@192.168.1.10 'systemctl is-active actions.runner.ptm4-ptm4.rpi-runner hl-arch-agent docker; mount | grep -c cifs; systemctl list-timers --no-pager | grep -c homelab'
#   active / active / active / 2 / 2
```
Then on the Archer's admin page confirm the DHCP client list shows `rpi` at 192.168.1.10 is
**not** present as a lease (it is static) and that DNS handed to clients is still
192.168.1.1 + 192.168.1.10. noblenumbat and opti resolve names again automatically (both
point at .10).

**Peter confirms rpi is online here. Nothing below runs before that confirmation.**

### 1.5 Immediately after: second copy of the rescue data

opti had no backup of the Pi. Put one on the pool before anything else changes:
```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'sudo mkdir -p /srv/red/fs/ptm/backups/rpi-rescue-2026-09-08 && sudo chown ptm:users /srv/red/fs/ptm/backups /srv/red/fs/ptm/backups/rpi-rescue-2026-09-08'
ssh -i ~/.ssh/noblenumbat ptm@192.168.1.6 'sudo tar -C /home/ptm/rpi-rescue -cpf - fs preseed rsync.log rsync-errors.log | ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no ptm@192.168.1.11 "sudo tar -C /srv/red/fs/ptm/backups/rpi-rescue-2026-09-08 -xpf -"'
```
If noblenumbat's key is not authorized on opti, run the tar through the workstation instead
(`ssh nn 'sudo tar …' | ssh opti 'sudo tar …'`). Verify:
`ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'sudo du -sh /srv/red/fs/ptm/backups/rpi-rescue-2026-09-08'` → `5.3G` ± 0.2.

### Rollback for Phase 1
There is nothing to roll back to; the old card is unbootable. If the restore leaves the stack
broken, re-run `restore.sh` (idempotent) or re-flash and start from 1.1. The rescue copy is
never modified by any step.

## Phase 2 — opti preparation (needs the RAM delivery)

### 2.1 Install the RAM (physical, Peter)

1. Shut down cleanly: `ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'sudo systemctl poweroff'`.
   Wait for the power LED to go off, unplug mains, press the power button once to drain.
2. Open the side panel (7010 MT: rear latch). The four DIMM slots sit right of the CPU.
   Slots are labelled **DIMM1..DIMM4** on the board. Currently DIMM1 = 2 GB Hynix, DIMM2 =
   4 GB Samsung, DIMM3/4 empty.
3. Remove **both** old sticks (open the two end latches, lift straight out). Set them aside.
4. Seat the four new 8 GB sticks in all four slots. Notch aligns with the slot key; press
   evenly on both ends until both latches click on their own.
5. Close, plug in, power on. Dell may show "Memory configuration changed" once — press F1.
6. Verify from the workstation:
   ```bash
   ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'free -h | head -2; sudo dmidecode -t 17 | grep -E "Size: [0-9]" | sort | uniq -c'
   ```
   Expected: `Mem: 31Gi` and `4 Size: 8 GB`. Anything else = a stick is not seated; power
   off and re-seat (do not run with 3 sticks).
7. Optional but recommended: one pass of memtest from the GRUB menu is not available on
   this Debian install; instead run `sudo apt-get install -y memtester && sudo memtester 8G 1`
   once (≈ 10 min) and expect `Done.` with no `FAILURE` lines.

### 2.2 Install Docker on opti, data on the pool

```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 bash -s <<'EOF'
set -euo pipefail
# ZFS datasets first, so Docker never writes to sda
sudo zfs create -o mountpoint=/var/lib/docker -o compression=lz4 -o atime=off red/docker
sudo zfs create -o mountpoint=/srv/docker     -o compression=lz4 -o atime=off red/docker-apps
sudo mkdir -p /srv/docker/compose && sudo chown ptm:users /srv/docker /srv/docker/compose
# Docker CE from Docker's repo (Debian 12 = bookworm)
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# make docker wait for the ZFS mount, and rotate logs like the Pi does
sudo mkdir -p /etc/systemd/system/docker.service.d
printf '[Unit]\nAfter=zfs.target zfs-mount.service\nRequiresMountsFor=/var/lib/docker /srv/docker\n' | sudo tee /etc/systemd/system/docker.service.d/10-zfs.conf
printf '{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }\n' | sudo tee /etc/docker/daemon.json
sudo systemctl daemon-reload
sudo systemctl enable --now docker
sudo usermod -aG docker ptm
docker --version; docker compose version
docker info 2>/dev/null | grep -E "Storage Driver|Docker Root Dir|Backing Filesystem"
EOF
```
Expected: `Docker version 2x`, `Storage Driver: overlay2`, `Docker Root Dir: /var/lib/docker`,
`Backing Filesystem: zfs`. Log out/in (or use `sudo docker`) for the group to apply. Then:
`ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'docker run --rm hello-world | head -3'` → `Hello from Docker!`.

If `Backing Filesystem` is not `zfs` or docker fails to start, stop: the dataset did not mount
before Docker. `sudo systemctl restart docker` after `zfs mount -a` fixes a one-off; report if
it recurs.

### 2.3 Restore the repo path opti's services expect

```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 bash -s <<'EOF'
set -euo pipefail
sudo mkdir -p /srv/red/fs/ptm/repo && sudo chown ptm:users /srv/red/fs/ptm/repo
git clone https://github.com/ptm4/ptm4.git /srv/red/fs/ptm/repo/ptm4
cd /srv/red/fs/ptm/repo/ptm4 && git log -1 --format='%h %ad %s' --date=short
sudo systemctl restart hl-agent-dispatcher && sleep 2 && systemctl is-active hl-agent-dispatcher
sudo ss -ltn | grep -c ':9099 '
EOF
```
Expected: a commit line, `active`, `1`. Do **not** touch `/srv/red/fs/ptm/old repo location/`.
Then add this as the first step of the `deploy` job in `.github/workflows/opti-deploy.yml`
(Peter commits it with Phase 3):
```yaml
      - name: Refresh the runtime checkout the services run from
        run: git -C /srv/red/fs/ptm/repo/ptm4 pull --ff-only
```

### 2.4 Confirm the paths the app tier will mount

```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'for p in /srv/red/fs/ptm/security-reports /srv/red/fs/ptm/agent-logs /srv/red/fs/ptm/repo/ptm4 /srv/red/fs/ptm/certs/webapp.rpi.lan.pem /srv/red/fs/ptm/certs/webapp.rpi.lan-key.pem /srv/red/fs/ptm/logging; do printf "%-55s %s\n" $p "$(test -e $p && echo ok || echo MISSING)"; done'
```
All six must print `ok`.

### Rollback for Phase 2
RAM: put the old sticks back in DIMM1/DIMM2. Docker: `sudo apt-get purge -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin && sudo zfs destroy -r red/docker && sudo zfs destroy -r red/docker-apps`. Repo clone: `rm -rf /srv/red/fs/ptm/repo/ptm4` (it is a pristine clone; nothing unique in it).

## Phase 3 — move the app tier from rpi to opti

Preconditions: Phase 1 confirmed by Peter, Phase 2 complete (`docker info` on opti good, port
9099 listening, all six paths `ok`).

### 3.1 Create the opti compose file in the repo

Create `homelab/hosts/opti/docker-compose.apps.yml` with exactly this content. It is the Pi's
compose minus pihole/mariadb/bitwarden/nginx-proxy, with every `/mnt/opti-fs/…` path replaced
by its local pool path and every port bound to `${OPTI_IP}`.

```yaml
#compose — opti app tier (moved from rpi 2026-09). Deploy target: /srv/docker/compose on opti.
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"

services:
  notes-api:
    build: ./notes-app/api
    container_name: notes-api
    restart: unless-stopped
    logging: *default-logging
    environment:
      DATA_DIR: /data
      PORT: 3002
    volumes:
      - ./notes-app/api/index.js:/app/index.js:ro
      - ./notes-app/web:/web:ro
      - notes_data:/data
    ports:
      - "${OPTI_IP}:3002:3002"
    expose:
      - "3002"
    networks:
      - internal

  webapp:
    image: node:lts-alpine
    container_name: webapp
    restart: unless-stopped
    logging: *default-logging
    working_dir: /app/backend
    command: sh -c "npm install --omit=dev --no-audit --no-fund --prefer-offline && node server.js"
    environment:
      DISPATCHER_URL: ${DISPATCHER_URL:-http://192.168.1.11:9099}
      HL_DISPATCH_TOKEN: ${HL_DISPATCH_TOKEN:-}
      LLAMA_URL: ${LLAMA_URL:-http://android.lan:8080}
      LLAMA_CTL_URL: ${LLAMA_CTL_URL:-http://android.lan:8081}
      HL_ARCH_INGEST_TOKEN: ${HL_ARCH_INGEST_TOKEN:-}
      PIHOLE_URL: ${PIHOLE_URL:-http://192.168.1.10}
      PIHOLE_WEB_PASSWORD: ${PIHOLE_WEB_PASSWORD:-}
      KUMA_URL: ${KUMA_URL:-http://uptime-kuma:3001}
      KUMA_API_KEY: ${KUMA_API_KEY:-}
      STREAM_URL: ${STREAM_URL:-http://192.168.1.6:8098}
      HL_STREAM_TOKEN: ${HL_STREAM_TOKEN:-}
      HOMELAB_DB_URL: ${HOMELAB_DB_URL:-http://192.168.1.11:9100}
      HL_DB_TOKEN: ${HL_DB_TOKEN:-}
    volumes:
      - ./webapp:/app
      - /srv/red/fs/ptm/security-reports:/reports:ro
      - /srv/red/fs/ptm/agent-logs:/agent-logs:ro
      - /srv/red/fs/ptm/repo/ptm4:/workspace:ro
      - arch_data:/arch-data
    expose:
      - "3000"
    networks:
      - internal

  discord-weather:
    build: ./discord-weather
    container_name: discord-weather
    restart: unless-stopped
    logging: *default-logging
    environment:
      TZ: "America/New_York"
      DISCORD_WEBHOOK_URL: ${DISCORD_WEBHOOK_URL:-}
    volumes:
      - weather_data:/data
    expose:
      - "8080"
    networks:
      - internal
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8080/health"]
      interval: 60s
      timeout: 5s
      retries: 3

  discord-healthdigest:
    build: ./discord-healthdigest
    container_name: discord-healthdigest
    restart: unless-stopped
    logging: *default-logging
    environment:
      TZ: "America/New_York"
      DISCORD_WEBHOOK_URL_HEALTHDIGEST: ${DISCORD_WEBHOOK_URL_HEALTHDIGEST:-}
      PIHOLE_WEB_PASSWORD: ${PIHOLE_WEB_PASSWORD:-}
      RPI_IP: ${RPI_IP:-192.168.1.10}
      DISPATCHER_URL: ${DISPATCHER_URL:-http://192.168.1.11:9099}
      HL_DISPATCH_TOKEN: ${HL_DISPATCH_TOKEN:-}
    volumes:
      - healthdigest_data:/data
      - /srv/red/fs/ptm/agent-logs:/agent-logs:ro
    expose:
      - "8080"
    networks:
      - internal
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8080/health"]
      interval: 60s
      timeout: 5s
      retries: 3

  discord-jellyfin:
    build: ./discord-jellyfin
    container_name: discord-jellyfin
    restart: unless-stopped
    logging: *default-logging
    environment:
      TZ: "America/New_York"
      DISCORD_WEBHOOK_URL_JELLYFIN: ${DISCORD_WEBHOOK_URL_JELLYFIN:-}
      JELLYFIN_API_KEY: ${JELLYFIN_API_KEY:-}
    volumes:
      - jellyfinbot_data:/data
    expose:
      - "8080"
    networks:
      - internal
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8080/health"]
      interval: 60s
      timeout: 5s
      retries: 3

  discord-sports:
    build: ./discord-sports
    container_name: discord-sports
    restart: unless-stopped
    logging: *default-logging
    environment:
      TZ: "America/New_York"
      DISCORD_WEBHOOK_URL_SPORTS: ${DISCORD_WEBHOOK_URL_SPORTS:-}
    volumes:
      - sportsbot_data:/data
    expose:
      - "8080"
    networks:
      - internal
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8080/health"]
      interval: 60s
      timeout: 5s
      retries: 3

  discord-hltv:
    build: ./discord-hltv
    container_name: discord-hltv
    restart: unless-stopped
    logging: *default-logging
    depends_on:
      - hltv-api
    environment:
      TZ: "America/New_York"
      DISCORD_WEBHOOK_URL_HLTV: ${DISCORD_WEBHOOK_URL_HLTV:-}
      HLTV_API_URL: "http://hltv-api:8080"
    volumes:
      - hltvbot_data:/data
    expose:
      - "8080"
    networks:
      - internal
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8080/health"]
      interval: 60s
      timeout: 5s
      retries: 3

  hltv-api:
    build: ./discord-hltv/hltv-api
    container_name: hltv-api
    restart: unless-stopped
    logging: *default-logging
    environment:
      TZ: "America/New_York"
    volumes:
      - hltvapi_data:/data
    expose:
      - "8080"
    networks:
      - internal
    mem_limit: 1536m
    cpus: 2
    shm_size: 256m
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health')"]
      interval: 60s
      timeout: 10s
      retries: 3

  nginx-webapp:
    image: nginx:stable-alpine
    container_name: nginx-webapp
    restart: unless-stopped
    logging: *default-logging
    ports:
      - "${OPTI_IP}:8443:443"
    volumes:
      - /srv/red/fs/ptm/certs/webapp.rpi.lan.pem:/etc/ssl/certs/webapp.crt:ro
      - /srv/red/fs/ptm/certs/webapp.rpi.lan-key.pem:/etc/ssl/private/webapp.key:ro
      - ./nginx-wg.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - webapp
      - notes-api
      - dozzle
    networks:
      - internal

  uptime-kuma:
    image: louislam/uptime-kuma:1
    container_name: uptime-kuma
    restart: unless-stopped
    logging: *default-logging
    dns:
      - 192.168.1.10
      - 192.168.1.11
    ports:
      - "${OPTI_IP}:3001:3001"
    volumes:
      - kuma_data:/app/data
    networks:
      - internal

  dozzle:
    image: amir20/dozzle:latest
    container_name: dozzle
    restart: unless-stopped
    logging: *default-logging
    environment:
      DOZZLE_REMOTE_AGENT: "192.168.1.6:7007,192.168.1.10:7007"
      DOZZLE_BASE: /dozzle
    ports:
      - "${OPTI_IP}:9999:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - internal

networks:
  internal:
    driver: bridge

volumes:
  kuma_data:
  notes_data:
  weather_data:
  healthdigest_data:
  jellyfinbot_data:
  sportsbot_data:
  hltvbot_data:
  hltvapi_data:
  arch_data:
```
Differences from the Pi file, all deliberate: `hltv-api` memory cap raised 768m → 1536m (opti
has the headroom, Chromium was the tightest thing on the Pi); Kuma gets both Pi-holes as DNS;
Dozzle also attaches the rpi agent added in §4.3.

### 3.2 Create the opti deploy workflow

Create `.github/workflows/opti-apps-deploy.yml`. It is `rpi-deploy.yml` with the runner label,
compose source, and paths changed; the `build-frontend` job is identical.

```yaml
name: Deploy opti App Tier

on:
  push:
    branches: [main]
    paths:
      - "homelab/hosts/opti/docker-compose.apps.yml"
      - "homelab/hosts/rpi/webapp.v2.legacy/**"
      - "homelab/hosts/rpi/nginx-wg.conf"
      - "homelab/hosts/rpi/notes-app/**"
      - "homelab/hosts/rpi/discord-weather/**"
      - "homelab/hosts/rpi/discord-healthdigest/**"
      - "homelab/hosts/rpi/discord-jellyfin/**"
      - "homelab/hosts/rpi/discord-sports/**"
      - "homelab/hosts/rpi/discord-hltv/**"
      - ".github/workflows/opti-apps-deploy.yml"
  workflow_dispatch:

jobs:
  build-frontend:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: npm
          cache-dependency-path: homelab/hosts/rpi/webapp.v2.legacy/frontend/package-lock.json
      - name: Build (tsc + vite)
        working-directory: homelab/hosts/rpi/webapp.v2.legacy/frontend
        run: |
          npm ci --no-audit --no-fund
          npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: webapp-dist
          path: homelab/hosts/rpi/webapp.v2.legacy/frontend/dist
          retention-days: 3

  deploy:
    needs: build-frontend
    runs-on: [self-hosted, opti]
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: webapp-dist
          path: homelab/hosts/rpi/webapp.v2.legacy/frontend/dist
      - name: Copy compose file
        run: cp "$GITHUB_WORKSPACE/homelab/hosts/opti/docker-compose.apps.yml" /srv/docker/compose/docker-compose.yml
      - name: Sync webapp and nginx config
        run: |
          mkdir -p /srv/docker/compose/webapp
          rsync -a --delete --exclude 'node_modules' "$GITHUB_WORKSPACE/homelab/hosts/rpi/webapp.v2.legacy/" /srv/docker/compose/webapp/
          cp "$GITHUB_WORKSPACE/homelab/hosts/rpi/nginx-wg.conf" /srv/docker/compose/nginx-wg.conf
      - name: Copy notes-app
        run: |
          mkdir -p /srv/docker/compose/notes-app/api /srv/docker/compose/notes-app/web
          cp -r "$GITHUB_WORKSPACE/homelab/hosts/rpi/notes-app/api/." /srv/docker/compose/notes-app/api/
          cp -r "$GITHUB_WORKSPACE/homelab/hosts/rpi/notes-app/web/." /srv/docker/compose/notes-app/web/
      - name: Copy discord bots
        run: |
          for bot in discord-weather discord-healthdigest discord-jellyfin discord-sports discord-hltv; do
            mkdir -p "/srv/docker/compose/$bot"
            cp -r "$GITHUB_WORKSPACE/homelab/hosts/rpi/$bot/." "/srv/docker/compose/$bot/"
          done
      - name: Validate compose
        working-directory: /srv/docker/compose
        run: docker compose config --quiet
      - name: Pull latest images
        working-directory: /srv/docker/compose
        run: docker compose pull
      - name: Bring stack up
        working-directory: /srv/docker/compose
        run: docker compose up -d --remove-orphans
      - name: Build and restart notes-api
        working-directory: /srv/docker/compose
        run: |
          docker compose build notes-api
          docker compose up -d notes-api
      - name: Build and restart discord bots
        working-directory: /srv/docker/compose
        run: |
          docker compose build hltv-api discord-weather discord-healthdigest discord-jellyfin discord-sports discord-hltv
          docker compose up -d hltv-api discord-weather discord-healthdigest discord-jellyfin discord-sports discord-hltv
      - name: Restart webapp to pick up code changes
        working-directory: /srv/docker/compose
        run: docker compose restart webapp
      - name: API smoke against the fully deployed stack
        working-directory: /srv/docker/compose
        run: |
          sleep 8
          docker compose exec -T webapp node /app/scripts/smoke-api.mjs --base http://127.0.0.1:3000 --compare /app/scripts/smoke-baseline.json
      - name: Restart nginx to pick up config changes
        working-directory: /srv/docker/compose
        run: docker compose restart nginx-webapp
```
The opti runner user is `ptm`; §2.2 put it in the `docker` group, so no `sudo` in the steps.

### 3.3 Seed opti's compose directory by hand (first time only; the workflow keeps it fresh afterwards)

```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 bash -s <<'EOF'
set -euo pipefail
R=/srv/red/fs/ptm/repo/ptm4; D=/srv/docker/compose
cd $R && git pull --ff-only
cp $R/homelab/hosts/opti/docker-compose.apps.yml $D/docker-compose.yml
mkdir -p $D/webapp $D/notes-app/api $D/notes-app/web
rsync -a --delete --exclude node_modules $R/homelab/hosts/rpi/webapp.v2.legacy/ $D/webapp/
cp $R/homelab/hosts/rpi/nginx-wg.conf $D/nginx-wg.conf
cp -r $R/homelab/hosts/rpi/notes-app/api/. $D/notes-app/api/; cp -r $R/homelab/hosts/rpi/notes-app/web/. $D/notes-app/web/
for bot in discord-weather discord-healthdigest discord-jellyfin discord-sports discord-hltv; do mkdir -p $D/$bot; cp -r $R/homelab/hosts/rpi/$bot/. $D/$bot/; done
ls $D
EOF
```
The frontend `dist/` is produced by CI; for the first manual start copy it from the Pi:
```bash
ssh -i ~/.ssh/rpi ptm@192.168.1.10 'sudo tar -C /srv/docker/compose/webapp/frontend -cf - dist' | ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'tar -C /srv/docker/compose/webapp/frontend -xf -'
```

### 3.4 Copy `.env` and add `OPTI_IP`

```bash
ssh -i ~/.ssh/rpi ptm@192.168.1.10 'sudo cat /srv/docker/compose/.env' | ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'cat > /srv/docker/compose/.env && chmod 600 /srv/docker/compose/.env && grep -q "^OPTI_IP=" /srv/docker/compose/.env || echo "OPTI_IP=192.168.1.11" >> /srv/docker/compose/.env; grep -cE "^(OPTI_IP|RPI_IP|PIHOLE_WEB_PASSWORD|HL_DB_TOKEN)=" /srv/docker/compose/.env'
```
Expected: `4`. The file contains secrets; never copy it through the repo.

### 3.5 Stop the app tier on rpi and copy its volumes to opti

Stopping first guarantees a consistent copy (Kuma's SQLite, the bots' JSON state).
```bash
ssh -i ~/.ssh/rpi ptm@192.168.1.10 'cd /srv/docker/compose && sudo docker compose stop notes-api webapp discord-weather discord-healthdigest discord-jellyfin discord-sports discord-hltv hltv-api nginx-webapp uptime-kuma dozzle && docker ps --format "{{.Names}}" | sort | tr "\n" " "'
```
Expected running set: `bitwarden bitwarden-db nginx-bitwarden pihole`.
```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'cd /srv/docker/compose && docker compose create 2>&1 | tail -3; for v in kuma_data notes_data weather_data healthdigest_data jellyfinbot_data sportsbot_data hltvbot_data hltvapi_data arch_data; do docker volume inspect compose_$v >/dev/null 2>&1 || docker volume create compose_$v >/dev/null; done; docker volume ls | grep -c compose_'
```
Expected: `9`. Now copy each volume's data (run from the workstation; ~2.4 GB):
```bash
for v in kuma_data notes_data weather_data healthdigest_data jellyfinbot_data sportsbot_data hltvbot_data hltvapi_data arch_data; do
  ssh -i ~/.ssh/rpi ptm@192.168.1.10 "sudo tar -C /var/lib/docker/volumes/compose_$v -cpf - _data" | ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 "sudo tar -C /var/lib/docker/volumes/compose_$v -xpf -" && echo "$v ok"
done
```
Nine `ok` lines. Verify sizes match within 1%:
`ssh rpi 'sudo du -sm /var/lib/docker/volumes/compose_*_data | sort'` vs the same on opti.

### 3.6 Start on opti and verify before touching DNS

```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'cd /srv/docker/compose && docker compose up -d --build 2>&1 | tail -5; sleep 45; docker ps --format "{{.Names}}\t{{.Status}}" | sort'
```
Expected: 11 containers `Up` (bots show `(healthy)` after ~1 min). Then, still by IP:
```bash
curl -sk -o /dev/null -w '%{http_code}\n' --resolve webapp.rpi.lan:8443:192.168.1.11 https://webapp.rpi.lan:8443/   # 200
curl -s  -o /dev/null -w '%{http_code}\n' http://192.168.1.11:3002/notes   # 200
curl -s  -o /dev/null -w '%{http_code}\n' http://192.168.1.11:3001/        # 200
curl -s  -o /dev/null -w '%{http_code}\n' http://192.168.1.11:9999/dozzle/ # 200
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 'cd /srv/docker/compose && docker compose exec -T webapp node /app/scripts/smoke-api.mjs --base http://127.0.0.1:3000 --compare /app/scripts/smoke-baseline.json | tail -3'
```
Any non-200 or smoke failure: stop, `docker compose logs --tail 50 <service>` on opti, report.
rpi's app tier is only stopped, not removed, so nothing is lost while this is investigated.

### 3.7 Switch DNS

Pi-hole v6 stores local records in `dns.hosts`. Apply the original 21 records with exactly two
changed: `webapp.rpi.lan` and `webapp.rpi` → `192.168.1.11`. Everything else, including
`bitwarden.rpi.lan`, stays on `192.168.1.10`. Run on rpi:
```bash
ssh -i ~/.ssh/rpi ptm@192.168.1.10 'sudo docker exec pihole pihole-FTL --config dns.hosts "[\"192.168.1.10 bitwarden.rpi.lan\",\"192.168.1.10 bitwarden.rpi\",\"192.168.1.10 vpn.rpi.lan\",\"192.168.1.3 ptm.lan\",\"192.168.1.4 twah.lan\",\"192.168.1.5 ptmshc.lan\",\"192.168.1.6 noblenumbat.lan\",\"192.168.1.6 noblenumbat\",\"192.168.1.10 rpi.lan\",\"192.168.1.10 rpi\",\"192.168.1.11 webapp.rpi.lan\",\"192.168.1.11 webapp.rpi\",\"192.168.1.11 opti.lan\",\"192.168.1.11 opti\",\"192.168.1.3 tux.lan\",\"192.168.1.6 jellyfin.lan\",\"192.168.1.6 jellyfin\",\"192.168.1.6 comics.lan\",\"192.168.1.6 comics\",\"192.168.1.54 android\",\"192.168.1.54 android.lan\"]"'
```
Verify:
```bash
dig +short webapp.rpi.lan @192.168.1.10    # 192.168.1.11
dig +short bitwarden.rpi.lan @192.168.1.10 # 192.168.1.10
curl -sk -o /dev/null -w '%{http_code}\n' https://webapp.rpi.lan:8443/   # 200, now served by opti
```
Clients cache for the record TTL (Pi-hole local records: 300 s by default). Wait 5 minutes
before judging anything by name.

### 3.8 Update the things that pointed at the Pi's app ports

- `HL_ARCH_INGEST_URL` is name-based (`https://webapp.rpi.lan:8443/…`) on all three hosts → no
  change. Confirm ingest still lands: `ssh opti 'sudo systemctl restart hl-arch-agent; sleep 5; journalctl -u hl-arch-agent -n 3 --no-pager'` shows no `HTTP 4xx/5xx`.
- homelab-doctor URL checks list `http://rpi.lan:3002/notes`. Edit the doctor agent's check
  list in `homelab/agentic/agents/` (grep `rpi.lan:3002`) to `http://opti.lan:3002/notes`, and
  any `rpi.lan:3001` / `rpi.lan:9999` likewise. Commit with the rest of this phase.
- Uptime Kuma monitors that targeted `rpi.lan:3002/3001/9999`: edit in Kuma's UI to
  `opti.lan:<port>`. (Monitors for `webapp.rpi.lan:8443` need no change.)

### 3.9 Commit

Peter commits (per house rule the agent never commits): `homelab/hosts/opti/docker-compose.apps.yml`,
`.github/workflows/opti-apps-deploy.yml`, the doctor check-list edit. Pushing triggers
`opti-apps-deploy.yml` once; its run must go green (it re-deploys exactly what §3.3–3.6 already
put in place, so it is a no-op that proves the pipeline).

### Rollback for Phase 3
`ssh rpi 'cd /srv/docker/compose && sudo docker compose start notes-api webapp discord-weather discord-healthdigest discord-jellyfin discord-sports discord-hltv hltv-api nginx-webapp uptime-kuma dozzle'`,
then re-apply the DNS list with `webapp.rpi.lan`/`webapp.rpi` back to `192.168.1.10`, then
`ssh opti 'cd /srv/docker/compose && docker compose down'`. Volumes on opti can be left in
place. Nothing in Phase 3 modifies the Pi's data until Phase 4.

## Phase 4 — trim rpi to DNS + vault

Only after Phase 3 has run for 24 h with the doctor report green.

### 4.1 Lean compose in the repo

Replace `homelab/hosts/rpi/docker-compose.yml` with only the `pihole`, `mariadb`, `bitwarden`,
`nginx-proxy` services from the current file, the `internal` network, and volumes
`pihole_data`, `dnsmasq_data`, `db_data`. Keep every line of those four services byte-for-byte.
Add one service so Dozzle on opti can still show the Pi's logs:
```yaml
  dozzle-agent:
    image: amir20/dozzle:latest
    container_name: dozzle-agent
    restart: unless-stopped
    logging: *default-logging
    command: agent
    ports:
      - "${RPI_IP}:7007:7007"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

### 4.2 Lean deploy workflow

Edit `.github/workflows/rpi-deploy.yml`: delete the `build-frontend` job, the
`download-artifact`, "Sync webapp and nginx config", "Copy notes-app", "Copy discord bots",
"Build and restart notes-api", "Build and restart discord bots", "Restart webapp", "API smoke",
and "Restart nginx" steps, and every `paths:` entry except `homelab/hosts/rpi/docker-compose.yml`
and the workflow itself. What remains: checkout → copy compose → `docker compose pull` →
`docker compose up -d --remove-orphans`. `--remove-orphans` is what removes the eleven moved
containers on the Pi.

### 4.3 Apply

Peter commits and pushes. `rpi-deploy.yml` runs on the ARM64 runner; expected result on the Pi:
```bash
ssh -i ~/.ssh/rpi ptm@192.168.1.10 'docker ps --format "{{.Names}}" | sort | tr "\n" " "; echo; docker system prune -af --volumes=false 2>&1 | tail -1; df -h / | tail -1'
```
`bitwarden bitwarden-db dozzle-agent nginx-bitwarden pihole`, several GB reclaimed. The nine
`compose_*` app volumes stay on the Pi as a cold copy; delete them **only** after Phase 5's
first backup has run: `docker volume rm compose_{kuma,notes,weather,healthdigest,jellyfinbot,sportsbot,hltvbot,hltvapi,arch}_data`.

### 4.4 Optional variant: clean re-image instead of trim-in-place

Not required. If preferred later: re-run Phase 1.1–1.2 on the same SSD, then run
`restore.sh` after editing its `copy` list to `/srv/docker/compose/{vaultwarden-data,bitwarden-db}`,
`/etc`, `/root`, `/home`, `/usr/local/bin`, and only the `compose_pihole_data` /
`compose_dnsmasq_data` volumes, with the lean compose file already in the repo. Same
verification as 1.4 minus the app-port checks.

## Phase 5 — resilience: second Pi-hole on opti, and backups

### 5.1 Pi-hole on opti (DNS only, bridge mode)

```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 bash -s <<'EOF'
set -euo pipefail
# free port 53 on the host: stop resolved's stub, resolve via the container instead
printf '[Resolve]\nDNSStubListener=no\nDNS=127.0.0.1 192.168.1.10\n' | sudo tee /etc/systemd/resolved.conf.d/20-pihole-local.conf
sudo systemctl restart systemd-resolved
sudo ss -lunp | grep ':53 ' || echo "port 53 free"
mkdir -p /srv/docker/pihole && cd /srv/docker/pihole
cat > docker-compose.yml <<'YML'
services:
  pihole:
    image: pihole/pihole:latest
    container_name: pihole-opti
    restart: unless-stopped
    ports:
      - "53:53/tcp"
      - "53:53/udp"
      - "192.168.1.11:8053:80/tcp"
    environment:
      TZ: "America/New_York"
      FTLCONF_webserver_api_password: ${PIHOLE_WEB_PASSWORD}
      FTLCONF_dns_upstreams: "192.168.1.1;1.1.1.1"
      FTLCONF_dns_listeningMode: "all"
    volumes:
      - pihole_data:/etc/pihole
      - dnsmasq_data:/etc/dnsmasq.d
    cap_add:
      - SYS_NICE
volumes:
  pihole_data:
  dnsmasq_data:
YML
grep '^PIHOLE_WEB_PASSWORD=' /srv/docker/compose/.env > .env; chmod 600 .env
docker compose up -d
sleep 20; dig +short google.com @127.0.0.1 | head -1
EOF
```
Expected: `port 53 free`, then an IPv4 address. Then load the same local records (the list
from §3.7, with the `webapp.*` → `.11` change) into it:
`docker exec pihole-opti pihole-FTL --config dns.hosts '[…same JSON list…]'`, and the same
adlists via Teleporter: on rpi's admin (http://rpi.lan/admin → Settings → Teleporter → Export),
then on opti's (http://192.168.1.11:8053/admin → Teleporter → Import, tick only Adlists,
Domains, Clients, Groups — **not** DHCP, not DNS settings). Verify `dig +short webapp.rpi.lan @192.168.1.11` → `192.168.1.11`.

Router: in the Archer's DHCP server settings set primary DNS `192.168.1.10`, secondary
`192.168.1.11` (replacing `192.168.1.1`). Clients pick it up at their next renew (≤ 2 h).

Record changes from now on are made on **both** Pi-holes (same `pihole-FTL --config dns.hosts`
call on each). That is the whole sync procedure; a sync tool is deliberately not introduced.

### 5.2 Nightly backup of the Pi to the pool

MariaDB dump on the Pi (consistent), then opti pulls `/srv` + the Pi-hole volume + the dump.
On rpi:
```bash
ssh -i ~/.ssh/rpi ptm@192.168.1.10 bash -s <<'EOF'
set -euo pipefail
sudo tee /usr/local/bin/homelab-vault-dump.sh >/dev/null <<'SH'
#!/bin/bash
set -euo pipefail
mkdir -p /srv/backups/mariadb
set -a; . /srv/docker/compose/.env; set +a
docker exec bitwarden-db mariadb-dump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines "$MYSQL_DATABASE" | gzip > /srv/backups/mariadb/vaultwarden-$(date +%F).sql.gz
find /srv/backups/mariadb -name '*.sql.gz' -mtime +14 -delete
SH
sudo chmod +x /usr/local/bin/homelab-vault-dump.sh
printf '[Unit]\nDescription=Nightly Vaultwarden DB dump\n[Service]\nType=oneshot\nExecStart=/usr/local/bin/homelab-vault-dump.sh\n' | sudo tee /etc/systemd/system/homelab-vault-dump.service
printf '[Unit]\nDescription=Nightly Vaultwarden DB dump\n[Timer]\nOnCalendar=*-*-* 01:15:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n' | sudo tee /etc/systemd/system/homelab-vault-dump.timer
sudo systemctl daemon-reload && sudo systemctl enable --now homelab-vault-dump.timer
sudo /usr/local/bin/homelab-vault-dump.sh && ls -la /srv/backups/mariadb/
EOF
```
On opti (pull with the collector key `~/.ssh/hl_agents`, already authorized on the Pi):
```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 bash -s <<'EOF'
set -euo pipefail
sudo mkdir -p /srv/red/fs/ptm/backups/rpi
sudo tee /usr/local/bin/homelab-rpi-backup.sh >/dev/null <<'SH'
#!/bin/bash
set -uo pipefail
K=/home/ptm/.ssh/hl_agents; H=ptm@192.168.1.10; D=/srv/red/fs/ptm/backups/rpi
RS="rsync -aHAX --numeric-ids --delete -e 'ssh -i $K -o BatchMode=yes -o StrictHostKeyChecking=accept-new' --rsync-path='sudo rsync'"
eval $RS $H:/srv/ $D/srv/
eval $RS $H:/var/lib/docker/volumes/compose_pihole_data/ $D/pihole_data/
eval $RS $H:/etc/ $D/etc/
zfs snapshot red/fs@rpi-backup-$(date +%F) 2>/dev/null || true
zfs list -t snapshot -o name -H | grep '^red/fs@rpi-backup-' | head -n -14 | xargs -r -n1 zfs destroy
echo "$(date -u +%FT%TZ) rpi backup done" >> $D/backup.log
SH
sudo chmod +x /usr/local/bin/homelab-rpi-backup.sh
printf '[Unit]\nDescription=Nightly rpi backup to pool\n[Service]\nType=oneshot\nUser=root\nExecStart=/usr/local/bin/homelab-rpi-backup.sh\n' | sudo tee /etc/systemd/system/homelab-rpi-backup.service
printf '[Unit]\nDescription=Nightly rpi backup to pool\n[Timer]\nOnCalendar=*-*-* 01:45:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n' | sudo tee /etc/systemd/system/homelab-rpi-backup.timer
sudo systemctl daemon-reload && sudo systemctl enable --now homelab-rpi-backup.timer
sudo /usr/local/bin/homelab-rpi-backup.sh; tail -1 /srv/red/fs/ptm/backups/rpi/backup.log; sudo du -sh /srv/red/fs/ptm/backups/rpi
EOF
```
Expected: a `rpi backup done` line and a size around 0.6–1 GB. The `sudo rsync` on the Pi
side works because `ptm` has passwordless sudo there. Add both new unit files to
`homelab/tools/automation/` (rpi) and `homelab/hosts/opti/systemd/` (opti) so the deploy
workflows own them.

### 5.3 Snapshot the app tier's data on opti

```bash
ssh -i ~/.ssh/optiplex_omv ptm@192.168.1.11 bash -s <<'EOF'
printf '#!/bin/bash\nd=$(date +%%F); zfs snapshot -r red/docker@daily-$d; zfs snapshot -r red/docker-apps@daily-$d\nfor ds in red/docker red/docker-apps; do zfs list -t snapshot -o name -H -r $ds | grep "@daily-" | head -n -14 | xargs -r -n1 zfs destroy; done\n' | sudo tee /usr/local/bin/homelab-docker-snap.sh; sudo chmod +x /usr/local/bin/homelab-docker-snap.sh
printf '[Unit]\nDescription=Daily ZFS snapshot of docker datasets\n[Service]\nType=oneshot\nExecStart=/usr/local/bin/homelab-docker-snap.sh\n' | sudo tee /etc/systemd/system/homelab-docker-snap.service
printf '[Unit]\nDescription=Daily ZFS snapshot of docker datasets\n[Timer]\nOnCalendar=*-*-* 01:30:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n' | sudo tee /etc/systemd/system/homelab-docker-snap.timer
sudo systemctl daemon-reload && sudo systemctl enable --now homelab-docker-snap.timer && sudo /usr/local/bin/homelab-docker-snap.sh && zfs list -t snapshot | grep daily | head -3
EOF
```

## Phase 6 — opti OS disk (out of scope here; blocked on a purchase)

`sda` (ST500DM002, 40 078 h, 264 reallocated sectors) holds Debian and swap only; nothing
Docker- or pool-related is on it after Phase 2. Replacement = fresh Debian 12 on a 240 GB SSD
(BX500, $64.88), `zpool import red`, restore `/etc/homelab/samba-red.conf`, `/etc/hl-agents.env`,
`/etc/hl-arch-agent.env`, `~/.ssh/hl_agents`, re-register the Actions runner, run
`opti-deploy.yml`. That is its own runbook; `homelab/hosts/opti/proxmox-migration.md` Phases 1–4
already describe the same cutover mechanics (minus the hypervisor). **Path C' (the Ryzen build)
in that document is superseded by Peter's 2026-09-08 decision: opti stays the 7010 and gets
upgraded in place.**

## Docs to update when each phase lands

- Phase 1: `homelab/agentic/rules/01-homelab-context.md` host table — rpi is Ubuntu 24.04 on a
  USB SSD; DHCP is the router's; the "Never enable DHCP on the router" bullet becomes "Never
  enable DHCP on Pi-hole". `runbooks/02-network-dhcp-dns.md` intended design flips accordingly.
- Phase 3/4: same host table — opti gains "app tier: webapp :8443, notes :3002, Kuma :3001,
  Dozzle :9999, 5 Discord bots"; rpi loses them. `generated/92-data-flows.md` regenerates itself.
- Phase 5: host table — "DNS: Pi-hole on rpi (.10) **and** opti (.11)"; backup paths.
- Both drawio diagrams in `homelab/docs/`.

## Verification summary (run after every phase; all must hold)

| Check | Command | Expect |
|---|---|---|
| DNS via rpi | `dig +short rpi.lan @192.168.1.10` | 192.168.1.10 |
| DNS via opti (Phase 5+) | `dig +short rpi.lan @192.168.1.11` | 192.168.1.10 |
| Vault | `curl -sk -o /dev/null -w '%{http_code}' https://bitwarden.rpi.lan/` | 200 |
| Webapp | `curl -sk -o /dev/null -w '%{http_code}' https://webapp.rpi.lan:8443/` | 200 |
| Webapp lives on | `dig +short webapp.rpi.lan @192.168.1.10` | .10 (before Phase 3) / .11 (after) |
| Doctor | latest `agent-logs/homelab-doctor-latest.json` `hosts[].status` | no `crit` |
| Dispatcher | `ssh opti 'systemctl is-active hl-agent-dispatcher'` | active |
| Backup (Phase 5+) | `tail -1 /srv/red/fs/ptm/backups/rpi/backup.log` on opti | today's date |

## Post-mortem addendum (2026-09-09, Phase 1 execution)

Phase 1 completed, but two issues cost the evening and are now baked into the preseed/runbook:

1. **systemd-resolved's stub listener breaks Pi-hole on :53 — the big one.** The fresh
   Ubuntu 24.04 image runs systemd-resolved with its stub on 127.0.0.53:53. Linux forbids a
   TCP wildcard LISTEN on a port where any specific-address LISTEN exists, so FTL's embedded
   dnsmasq fails `0.0.0.0:53` TCP with `Address in use`, aborts its whole listener setup, and
   the already-bound UDP socket sits unread (ss showed Recv-Q ~215 KB of queued, unanswered
   queries). Symptoms that mislead: `ss` shows FTL "holding" UDP :53, `pihole status` claims
   IPv4 OK, no third-party process appears to conflict, and the failure is version-independent
   (reproduced on FTL v6.6.2 and v6.7 — do NOT chase image pinning; a downgrade also hits a
   gravity-DB schema wall, v22 vs v21). The old rpi never hit this because it ran
   **systemd-resolved disabled outright** with a hand-managed `/etc/resolv.conf` pointing at
   127.0.0.1 — a fact visible in the rescue copy but not carried by the preseed. Fix applied
   and now in `preseed/user-data.tmpl` runcmd: disable resolved, write the hand-managed
   resolv.conf (127.0.0.1, then 192.168.1.1, search lan).
2. **Pi-hole's webserver held 443 away from Vaultwarden.** pihole.toml ships
   `webserver.port = "80o,443os,..."`; on the old box nginx-bitwarden won the 443 race by
   startup order, on the rebuild FTL won it. Made deterministic by dropping 443 from the
   FTL webserver (`webserver.port = "80o,[::]:80o"` — edit pihole.toml on disk with the
   container stopped; the `pihole-FTL --config` CLI does not reliably persist across
   restarts). Admin UI is HTTP :80 as before.
3. **nginx-bitwarden hardened.** Its config now uses `resolver 127.0.0.11 valid=10s;` plus a
   variable-based `proxy_pass` (lazy runtime resolution) instead of static upstream
   resolution at config parse — immune to start-order and container-recreation races. Live
   at `/srv/docker/compose/nginx.conf` on rpi (not CI-deployed; backup `.bak-preresolver`
   alongside).

## Post-mortem addendum (2026-09-10): the first opti-apps-deploy run

`Deploy opti App Tier` was created during the migration but had **never actually run**
until the v3.Fable go-live push. It failed twice, both times on host state the migration
left behind rather than on anything in the workflow. Recording them because both present
as "the deploy is broken" and neither is.

**1. `open /srv/docker/compose/.env: permission denied`** at the `docker compose config`
step. The file was `root:root 0600`, and the runner executes as `ptm`. Fixed with:

```bash
sudo chmod 640 /srv/docker/compose/.env
```

`getent group root` on opti is exactly `root:x:0:ptm`, so group-read grants access to
`ptm` and nobody else — and `ptm` already has passwordless sudo, so this widens nothing
in practice. Do **not** "fix" this by teaching the workflow to `sudo docker compose`;
that runs the whole stack as root and changes who owns everything it creates.

**2. `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`**
at the next step. This one is the trap: `ssh opti 'docker ps'` works fine, so the
daemon and the group look correct. They are. The **runner process** was started before
`usermod -aG docker ptm` ran during the migration, and supplementary groups are fixed at
process start — a long-running systemd service never picks up a group added afterwards.

Diagnose by comparing the process's groups to a fresh login's, rather than trusting
`id`:

```bash
sudo grep ^Groups /proc/$(pgrep -f Runner.Listener | head -1)/status
getent group docker      # the gid to look for
```

Fixed by restarting the service so it re-reads its groups:

```bash
sudo systemctl restart actions.runner.ptm4-ptm4.opti.service
```

Check no job is in flight first — a restart kills a running one. This is one-time; the
group membership itself is already persistent in `/etc/group`.

**Third-order consequence worth knowing.** The deploy rsyncs the webapp *before* it
validates compose, so both failures left the host in a **mixed state**: v3's files on
disk under `/srv/docker/compose/webapp/`, and the old backend process still running from
before (`/api/health` still answering `webapp.rpi.lan`, every v3 route 404, but the v3
SPA being served). The site looked broken in a way neither version explains. If a deploy
fails after the rsync step, the fix is always to finish the deploy (re-run it), never to
hand-edit the deploy target.

## What belongs on rpi (and what does not)

rpi is a **network virtual appliance** as of 2026-09-09. It runs Pi-hole and a Dozzle
agent. Before adding anything, understand the trade you are making: **every service
added here is a service that can take LAN-wide DNS down with it.** An OOM, a runaway
scraper, a bad image pull, or a reboot for an unrelated app is now a DNS outage for
every device in the house. That is precisely what the app-tier migration bought back.
Nothing goes on rpi because it is "convenient" — only because it belongs there.

**The four-part test.** Add it only if all four are true:

1. **It serves the network itself**, not humans or data. DNS, DHCP, VPN, NTP, routing,
   monitoring probes. If a person opens it in a browser to *use* it, it is an app —
   that goes on opti.
2. **It is effectively stateless.** Config in git or a small flat file; nothing whose
   loss would hurt. Anything with a real database belongs on opti's pool, where ZFS
   snapshots and block checksums protect it.
3. **It fits in ~500 MB RAM and a fraction of a core, at peak.** The Pi has 3.7 GB
   total and Pi-hole needs headroom. `hltv-api` was the cautionary tale: one Chromium
   scraper pinned at its 768 MB cap drove load to 4.5 on 4 cores.
4. **Losing it for an hour matters less than losing DNS.** If the answer is no, it is
   too important to sit behind DNS's blast radius.

**Good candidates** (all pass the test):

| Service | Why it fits |
|---|---|
| **WireGuard** | Network-layer, near-zero load, stateless (keys in config). A `wg.rpi.lan` cert already exists on the pool from an earlier attempt. Strongest candidate on this list. |
| **chrony / NTP server** | Pure network service, negligible resources. Currently every host syncs to the internet independently. |
| **Unbound** | Recursive resolver sitting behind Pi-hole, removing the dependency on upstream resolvers. Classic pairing, small footprint. |
| **Tailscale subnet router / exit node** | Network-layer by definition, tiny daemon. |
| **mosquitto (MQTT)** | If home automation ever appears. Lightweight broker, near-stateless. |
| **rsyslog collector** | Network service; keep retention small and watch disk. |
| **ADS-B / SDR receiver** | Needs the Pi's GPIO/USB proximity anyway. Genuine Pi workload. |
| **smokeping / vnstat** | Network measurement, and measuring *from* the network's edge is the point. |

**Explicitly does not belong here:**

- Anything with a database (Vaultwarden, Kuma, anything SQLite-heavy). Write
  amplification killed the last SD card, and this data wants ZFS.
- Anything CPU-heavy: scrapers driving headless browsers, transcoding, CI builds,
  image builds.
- Anything holding irreplaceable state. That belongs on the pool.
- Web apps with heavy dependency trees — an `npm install` on boot is not appliance
  behaviour.
- "Just one more container" reasoning. That is how this box ended up with 15.

**If it fails the test but you want it anyway:** it goes on opti. opti has 31 GB, 8x
the RAM, a 3.6 TB pool with snapshots, and is currently idling at 0.02 load. There is
room for a great deal more there — which was the whole point of the migration.

## Watching opti's boot disk (ST500DM002, `sdb`)

Peter's call 2026-09-09: **run it until it fails, but see it coming.** That is a
reasonable position, and the numbers support it better than the earlier "dying"
framing in `proxmox-migration.md` suggested.

**Baseline, 2026-09-09:**

| Attribute | Raw | Normalized / threshold | Read |
|---|---|---|---|
| Reallocated_Sector_Ct | 264 | 100 / 36 | Sectors were remapped, but the drive's own health score is untouched and sits far above the failure threshold |
| **Current_Pending_Sector** | **0** | 100 / 0 | **The one that matters. Zero.** |
| **Offline_Uncorrectable** | **0** | 100 / 0 | **Also zero.** |
| Power_On_Hours | 40 106 | 55 | ~4.6 years spinning |
| Temperature | 38 °C | — | Fine |
| Overall self-assessment | PASSED | | |

**The important correction:** 264 reallocated sectors sounds alarming and drove the
earlier "sda is dying" language, but reallocation is the drive *successfully* handling
bad sectors from its spare pool. The leading indicators of imminent failure are
`Current_Pending_Sector` and `Offline_Uncorrectable` — sectors the drive has found bad
and *cannot* fix. Both are zero. Growth has also been slow: 256 → 264 between June and
September, roughly 8 sectors a quarter.

**Escalate on these, in priority order:**

1. **`Current_Pending_Sector` > 0 — order the replacement that day.** This is the real
   warning. Pending sectors mean unreadable data waiting on a rewrite.
2. **`Offline_Uncorrectable` > 0** — same urgency. Data has already been lost.
3. **`Reallocated_Sector_Ct` jumping >25 in a week** — the spare pool is being consumed
   fast; failure is weeks out, not months.
4. **Normalized value on attribute 5 dropping toward 36** — currently 100, so there is
   enormous headroom. If this moves at all, the drive is genuinely late-stage.
5. **`dmesg` I/O errors or ext4 remounting read-only** — past prediction, into failure.

Coverage already exists: `homelab/tools/collectors/hardware-report.py` parses both
`Reallocated_Sector` and `Current_Pending` and the `homelab-hardware` agent runs
weekly. Note that report was 110 h stale on 2026-09-09 because the Pi was down —
worth confirming it resumes.

**What failure actually costs, given Docker now lives on the pool:** `red/docker` and
`red/docker-apps` are ZFS datasets on `sdc`, not on this disk. A boot-disk death means
reinstall Debian, `zpool import red`, restore `/etc/hl-agents.env` + Samba config +
SSH keys, re-register the runner, redeploy. That is a few hours of downtime and **no
data loss** — which is exactly why running it to failure is defensible. It is also why
DNS stays on rpi: when this disk does go, the LAN keeps resolving names.
