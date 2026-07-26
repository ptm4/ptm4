---
name: opti-drive-onboard
description: Onboard a new physical drive into the opti server (192.168.1.11). Use when the user says they installed a new drive in opti or wants to expand opti storage. Since 2026-07-25 the live storage is ZFS pool `red` — a new drive is either a mirror for it (preferred) or a pool expansion, NOT a mergerfs branch.
---

# Onboard a new drive into opti

Target: `ptm@192.168.1.11` via `ssh -i ~/.claude/opti_key ptm@192.168.1.11` (passwordless sudo).
Tools live in `/usr/sbin` — call as `sudo <tool>`.

**RULES (non-negotiable):**
- Propose every server-side write and get explicit user agreement before running it.
- Wipes destroy data: show the disk's model, serial, size, partitions and have the user
  confirm THAT disk before touching it.
- Never hand-edit `/etc/samba/smb.conf` or anything in `/etc/openmediavault` — OMV
  regenerates them. The `[red]` share config is `/etc/homelab/samba-red.conf` (ours).

## Known state (baseline 2026-07-25 — the ZFS migration; re-verify live)

- **Live storage: ZFS pool `red`** — single 4 TB WD Red Plus (`WD-WX32D163WV1V`),
  whole-disk, `ashift=12`, datasets `red/fs` (zstd, share root `/srv/red/fs`) and
  `red/media` (recordsize=1M, no compression, mounted at `/srv/red/fs/ptm/Media`).
  zfs-dkms **2.3.2 from bookworm-backports** (base-repo 2.1.11 does not build on the
  6.12 backport kernel). ARC capped 1.5 GiB (`/etc/modprobe.d/zfs.conf`).
- Samba `\\opti\red` = `/srv/red/fs`, defined in `/etc/homelab/samba-red.conf`
  (repo: `homelab/opti-srv/samba/samba-red.conf`), included from OMV's SMB "Extra
  options". Editable at `https://webapp.rpi.lan:8443/samba/`.
- Clients: tux `/home/ptm/opti`, rpi `/mnt/opti-fs`, noblenumbat
  `/mnt/opti-{shows,library,media}` — all on `//192.168.1.11/red`.
- **Cold copy**: the retired mergerfs union (sda dir `/srv/sda-pool` + sdb NTFS Hitachi,
  10.6k hours, 3 reallocated sectors) at `/srv/attic`, `noauto`, sdb fstab'd `ro`.
  Refreshed weekly by `homelab-coldcopy.timer` (Sun 04:00) — see
  `homelab/Tools/automation/homelab-coldcopy.sh` for its interlocks.
- `/srv/pool` is a bind of `/srv/red/fs` (compat; old union path).
- SATA: 6 ports, sda+sdb+sdc used, **3 free**. Chassis/PSU realistically fits ~2 more drives.

## Procedure for a NEW drive

### 1. Identify + SMART gate
```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL,SERIAL   # new = serial not in baseline
sudo smartctl -i -H /dev/sdX && sudo smartctl -t short /dev/sdX   # ~2 min, then -a:
# gate: PASSED, Reallocated_Sector_Ct=0, Current_Pending_Sector=0
```
If the drive may carry data, STOP and confirm with the user before any wipe.

### 2. Decide the role (ask the user, recommend in this order)
1. **Mirror for `red`** (preferred once a second ≥4 TB drive exists): converts the pool
   to self-healing RAID1 — scrub then *repairs* corruption instead of reporting it.
   ```bash
   DISK=/dev/disk/by-id/ata-<MODEL>_<SERIAL>     # always by-id, never /dev/sdX
   sudo zpool attach red ata-WDC_WD40EFZZ-68CPAN0_WD-WX32D163WV1V $DISK
   sudo zpool status red    # wait for the resilver; then it's a mirror
   ```
2. **Replace the cold-copy pair**: retire the aging sdb Hitachi — new drive becomes a
   plain ext4 cold target; update `homelab-coldcopy.sh`'s destination constants.
3. **Capacity expansion** (`zpool add` = a stripe): AVOID — one drive lost = pool lost.
   Only with the user's eyes-open consent.

### 3. Verify + document
```bash
sudo zpool status red && zfs list
```
Update `homelab/homelab-techdoc.md` (§2 opti table, §10 storage) and this baseline.
User commits — never commit for them.

## History

The pre-2026-07-25 version of this skill onboarded drives as mergerfs branches under
`/srv/pool` with OMV-managed ext4 mounts. That architecture (and its
`path = /srv/pool/` Samba override, which lived in the share's OMV `extraoptions`) was
retired by the ZFS migration; the old pool survives intact as the cold copy. Full
migration record: plan `so-lets-do-both-dazzling-frog` (2026-07-25/26 session).
