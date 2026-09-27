# Homelab audit & cleanup plan — 2026-09-27

Full audit of opti, rpi, noblenumbat, the Discord bot fleet and the repo. Every finding here
was observed live or in the repo on 2026-09-27; the high-severity ones were re-verified by hand.
Work top to bottom. Tick items as they land; delete this file once it's all done or superseded.

Legend — effort **S** <30 min · **M** an afternoon · **L** a project. 👤 = needs Peter's hands
(credentials, physical access, or a decision).

## Already done today

- ntfy "down/up" flapping: collector race in `agent-dispatcher.py` fixed (pushed in `5777eb4`,
  verified live); VPN watchdog pages only after 60 min dead (pushed, verified).
- Cold copy retired for real: `opti-deploy.yml` no longer re-enables it; units in `hosts/opti/retired/`.
- Pruned ~38 GB: opti 5.9 GB, rpi 4.4 GB (52 orphan volumes + old compose tree incl. a stale
  Vaultwarden copy, archived to `opti:/srv/docker/_archive/rpi-leftovers-2026-09-27.tgz`),
  noblenumbat 30 GB images.
- Disabled dead/failing units: rpi docker-stack-logs, smartd, fwupd-refresh, workstation CIFS
  mount (fstab backed up); noblenumbat xrdp.
- Stale docs/facts corrected: architecture data, runbook 01, homelab-ssh skill, incidents.json,
  doctor now reports "autoupdate held" instead of "timer dead?".
- Webapp: Health-bot `post_mode` choices fixed in `bots.ts` (was offering values the bot rejects).
- Webapp v4 plan: `homelab/hosts/opti/apps/WEBAPP-V4-PLAN.md`.

## P0 — security, this week

- [ ] 👤 **Rotate the leaked WireGuard key** (S) — in progress. Order matters: new Proton config
      (NAT-PMP on) → key into `/opt/yams/.env` + `chmod 600` → *then* compose line →
      `${WIREGUARD_PRIVATE_KEY}` and push → verify forwarded port → delete the old Proton config.
      Pushing the compose change before `.env` has the key takes the VPN stack down.
- [ ] 👤 **Change the qBittorrent admin password** (S) — `yams_qbt` is public in
      `vpn-stack-heal.sh:59`. Script should read it from a root-only file on the host.
- [ ] **opti sshd** (S): `PermitRootLogin yes` + `PasswordAuthentication yes`, reachable from the
      LAN and every Archer WireGuard client (ufw allows `10.213.87.0/24` to the whole host). Set
      `PermitRootLogin prohibit-password`, `PasswordAuthentication no`; keep a session open while
      reloading. Same `PasswordAuthentication no` on noblenumbat. rpi is already correct.
- [ ] **Narrow the ufw VPN rule** (S) on opti + noblenumbat from "anything" to the ports a remote
      client actually needs (22, 443, 8443, 8096…).
- [ ] **Gluetun exposure** (S): control server :8003 answers unauthenticated; HTTP proxy :8888 and
      shadowsocks :8388 bound 0.0.0.0. Add a control-server API key, confirm `PROXY_USER/PASSWORD`
      are actually enforced, drop shadowsocks if unused.
- [ ] **ntfy auth** (S): no auth — anyone on LAN/VPN can read or publish to `homelab`. Enable
      `auth-default-access: deny-all`, a publish token for `notify.py`, read user for the phone.
- [ ] 👤 **rpi `/srv/docker/compose/.env`** (S): mode 777, still holds the migrated apps' secrets.
      Trim to `PIHOLE_WEB_PASSWORD` + `RPI_IP`, `chmod 600`.

## P1 — backups (the biggest real risk)

opti's single WD Red holds the only copy of everything (Samba, media, Vaultwarden, bots, notes,
homelab.db). ZFS auto-snapshots exist for all datasets but live on the same disk.
`opti-backup.timer` (Borg) was scaffolded but never finished: its NFS target on noblenumbat was
never exported, and it only covered `red/fs`.

- [ ] **Small-but-precious off-box backup first** (M): nightly Borg (or `zfs send` of snapshots)
      of `red/docker-apps` (Vaultwarden + MariaDB dump, bots, notes, webapp data) and `red/opsdb`
      (homelab.db via its `VACUUM INTO` snapshot) → noblenumbat (188 GB free). A few GB total.
- [ ] **noblenumbat `/opt/yams/config`** (S): nightly tar/Borg → opti. *arr API keys, indexers,
      Jellyfin library DB; Kavita's own zips too.
- [ ] 👤 **Second disk for `red`** (L): `zpool attach` a mirror per the `opti-drive-onboard`
      skill. Until then the media library (617 GB) has no second copy anywhere.
- [ ] Alert on backup staleness through the existing collector → `notify.py` path.

## P2 — reliability

- [ ] 👤 **Auto-updates** (S): held on all three since 2026-09-17. Proposal: `apt-mark hold`
      docker-ce/containerd.io/docker-*-plugin everywhere, then lift the hold. Security updates
      pending (5 on noblenumbat).
- [ ] 👤 **noblenumbat auto-reboot** (M): 2 of the last 5 unattended reboots stayed down (5.7 d,
      22 h) — hangs at firmware/POST after a clean shutdown. Disable `homelab-autoreboot.timer` there
      until someone watches one reboot; consider BIOS update (on 1.6.1) and "continue on warnings".
      opti never auto-reboots (Debian doesn't produce `reboot-required`) — make that explicit.
- [ ] **Pinned-but-ancient images** (S–M): `qbittorrent:4.6.3` (2 yrs), `gluetun:v3.41.0` —
      both face the VPN tunnel. Everything else floats on `:latest` with manual pulls only.
- [ ] **Persistence-auditor noise** (S): re-baseline so the Sep 24 collector timers stop being
      reported as NEW daily.
- [ ] **Dedupe SMART critical** (S): opti sdb 272 reallocated is re-raised every ingest; page on
      *change* only. Real watch items: pending/uncorrectable sectors (still 0).

## P3 — Discord bot fleet

Source: `homelab/hosts/opti/apps/discord-*/`, one copy, in sync with opti. All stdlib Python.

- [ ] 👤 **Jellyfin API key** (S) — bot gets 401; new key in Jellyfin, set via the webapp.
- [ ] **discord-jellyfin error handling** (S): report "auth failed (401)" instead of
      "Jellyfin unreachable"; don't retry every 15 min on 401 (204 wasted attempts / 72 h).
- [ ] **Shared `bot_common.py`** (M): ~240 lines × 5 bots are the same config store, HTTP retry,
      scheduler and control API. Keep one container per bot; share the code. Test with `--dry-run`.
- [ ] **Meaningful health** (S): `/health` is always 200. Either report last-post failure there or
      document that homelab-db `ingest_bot_health` is the real signal.
- [ ] **hltv-api cache** (S): Chromium profile volume is 636 MB and growing; `lastgood-*.json`
      never pruned. Add a size cap / weekly trim.
- [ ] **Stale "rpi" text** (S): bot docstrings, User-Agents, READMEs, runbook 04 title.

## P4 — hosts & repo tidy

- [ ] noblenumbat: `disable --now rpcbind cups cups-browsed ModemManager bluetooth` (rpcbind is
      listening on 0.0.0.0:111). Old kernel 6.8 is held by the GA metapackage — pick GA or HWE.
- [ ] opti: podman-auto-update timer + dead filebrowser pod units (no podman containers);
      `/srv/sda-pool` (only `.Trash`); Hitachi NTFS disk mounted ro and unused — unmount or wipe
      and reuse it as a backup target for the P1 small-data backup.
- [ ] Pi-hole: confirm/prune `vpn.rpi.lan`, `twah.lan` (.4), `ptmshc.lan` (.5).
- [ ] Repo: remove committed native build output under `homelab/PTMonitor.v2.GPT/taskbar-native/build/`
      (~6 MB) + gitignore; delete `README.md.bak`; move `homelab/docs/homelab-techdoc.md`
      (self-marked superseded) to an archive.
- [ ] Architecture data: resolve the WireGuard contradiction (notes say decommissioned, router
      node + flows say active — the ufw rules prove it's active); model the workstation as
      `E:\REPO\ptm4`, not a tux CIFS edit path.
- [ ] Add a minimal `ruff` config for `homelab/tools` + host scripts.

## P5 — webapp

See `homelab/hosts/opti/apps/WEBAPP-V4-PLAN.md`. Phase 0 (baked image, healthcheck, global
request timeout, prettier/eslint) is independent of the redesign and worth doing first.
- [ ] 👤 Decide: retire `webapp.v3.Astra/` now or after harvesting `snapshot.js` / fixtures /
      `guide.js`; keep `webapp.v2.legacy/` as rollback until v4 ships?

## Verified healthy — leave alone

TLS certs (webapp.lan to 2028-12, vault to 2028-11) · Pi-hole DHCP off, all post-move DNS records
point at the right hosts · Uptime Kuma's 22 monitors all current · dispatcher :9099 and
homelab-db :9100 require tokens · hl-arch-agent mutating routes require a token · CI workflows
correctly scoped, one runner per host · notify.py is the only alert channel · opti app-tier
`.env` is 640 · rpi sshd hardened.
