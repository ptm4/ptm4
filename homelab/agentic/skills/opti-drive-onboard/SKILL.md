---
name: opti-drive-onboard
description: Onboard a new physical drive into the opti server (192.168.1.11). Use when the user says they installed a new drive in opti or wants to expand opti storage. Since 2026-07-25 the live storage is ZFS pool `red` — a new drive is either a mirror for it (preferred) or a pool expansion, NOT a mergerfs branch.
---

# Onboard a new drive into opti

Target: `opti` — connect through the [`homelab-ssh`](../homelab-ssh/SKILL.md) skill
(`ssh opti '<cmd>'`; the alias carries user and key on both sides of the workstation).
Passwordless sudo. Tools live in `/usr/sbin` — call as `sudo <tool>`.

**RULES (non-negotiable):**
- Propose every server-side write and get explicit user agreement before running it.
- Wipes destroy data: show the disk's model, serial, size, partitions and have the user
  confirm THAT disk before touching it.
- Never hand-edit `/etc/samba/smb.conf` or anything in `/etc/openmediavault` — OMV
  regenerates them. The `[red]` share config is `/etc/homelab/samba-red.conf` (ours).
- Device letters on opti are **not stable** (they reshuffled 2026-09-10). Identify disks
  by serial and address them by `/dev/disk/by-id/`, never by `/dev/sdX`.

## Known state (verified 2026-11-09 — re-verify live)

- **Live storage: ZFS pool `red`** — a single 4 TB WD Red Plus
  (`ata-WDC_WD40EFZZ-68CPAN0_WD-WX32D163WV1V`), whole-disk, `ashift=12`, **no redundancy
  and no second copy anywhere**. ~76% full (2.77 of 3.62 TB, ~760 GB free, Nov 2026).
  Datasets: `red/fs` (zstd, share root `/srv/red/fs`), `red/media` (recordsize=1M, no
  compression, `/srv/red/fs/ptm/Media`), `red/docker` (`/var/lib/docker`),
  `red/docker-apps` (`/srv/docker`), `red/opsdb` (`/srv/red/opsdb`, homelab.db — not
  under the share).
- zfs-dkms **2.3.2 from bookworm-backports** (base-repo 2.1.11 does not build on the
  6.12 backport kernel). ARC capped 1.5 GiB (`/etc/modprobe.d/zfs.conf`).
- **Scrub:** monthly, by Debian's `/etc/cron.d/zfsutils-linux` (2nd Sunday, ~7.5 h). A
  second, hand-enabled `zfs-scrub-monthly@red.timer` (1st of the month) is being disabled
  through `opti-deploy.yml` (approved 2026-11-10) — until that deploy lands it still fires.
  Check `systemctl list-timers` and the cron file.
- **Snapshots:** `zfs-auto-snapshot` (package cron jobs) on every dataset — 15-min ×4,
  hourly ×24, daily ×31, weekly ×8, monthly. They live on the same disk: they undo
  deletions, they are **not** a backup.
- **SMART:** the daily `hardware-report` collector enumerates every disk via `lsblk`, so a
  new disk is covered automatically. `smartd` (host-only `/etc/smartd.conf`, not in the
  repo) lists `/dev/sda` and `/dev/sdb` by letter only — it does not watch the pool disk.
- **Pool-health alerting:** ZED is not installed, and homelab-doctor reads pool capacity,
  not `zpool status` health. A DEGRADED/FAULTED pool does not page anyone today.
- **No cold copy.** The old mergerfs "attic" job (`homelab-coldcopy`) was **retired
  2026-09-24** (repo copies in `homelab/hosts/opti/retired/`; don't resurrect it). The
  Hitachi it used (now `sda`, NTFS, 596 GB) stays mounted read-only at
  `/srv/dev-disk-by-uuid-C682C2DE82C2D1DB` with a stale partial copy — not a backup, and
  too small to become one.
- Other disks: `ST500DM002` (boot, ext4 root + swap — currently `sdb`), DVD drive.
- Samba `\\opti\red` = `/srv/red/fs`, defined in `/etc/homelab/samba-red.conf`
  (repo: `homelab/hosts/opti/samba/samba-red.conf`), included from OMV's SMB "Extra
  options". Editable at `https://webapp.lan:8443/samba/`.
- Clients: tux `/home/ptm/opti`, rpi `/mnt/opti-fs` (both `//192.168.1.11/red`),
  noblenumbat `/mnt/opti-shows`, `/mnt/opti-library`, `/mnt/opti-media` (subpaths of
  `red/ptm/Media…`).
- SATA: 6 ports — boot disk, Hitachi, DVD drive and the WD Red use four, **2 free**
  (`ata5`, `ata6`). Chassis/PSU realistically fits ~2 more drives.

## Before the drive goes in: the reboot gate

Fitting a drive means powering opti off, and opti boots the **newest** kernel
(`GRUB_DEFAULT=0`). If that kernel has no ZFS module, opti comes back **without pool `red`**
— no share, no dashboard, no vault. Check before the user shuts down:

```bash
export PATH=$PATH:/usr/sbin:/sbin    # modinfo lives in /usr/sbin; without it the check always fails
k=$(ls /boot/vmlinuz-* | sed 's|/boot/vmlinuz-||' | sort -V | tail -1); echo "$k"
modinfo -k "$k" zfs >/dev/null && echo "zfs OK for $k" || echo "NO zfs module for $k — STOP"
```

This is the same rule `homelab-autoreboot.sh`'s guard and homelab-doctor's "next kernel
lacks zfs" check use. If it says STOP, don't proceed: the matching `linux-headers` package
must be installed and zfs-dkms rebuilt for that kernel first — through the repo's deploy
path, with the user's go-ahead. Never reboot opti to "test" a drive.

## Procedure for a NEW drive

### 1. Identify + SMART gate
```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL,SERIAL   # new = serial not listed above
ls -l /dev/disk/by-id/ | grep -v part | grep ata-          # its by-id name
sudo smartctl -i -H /dev/disk/by-id/<ID> && sudo smartctl -t short /dev/disk/by-id/<ID>
# ~2 min, then -a. Gate: PASSED, Reallocated_Sector_Ct=0, Current_Pending_Sector=0
```
If the drive may carry data, STOP and confirm with the user before any wipe.

### 2. Decide the role (ask the user, recommend in this order)
1. **Mirror for `red`** (preferred): converts the pool to self-healing RAID1 — scrub then
   *repairs* corruption instead of reporting it. The new disk must be **at least as large
   as the existing one** (3.62 TiB usable; another "4 TB" model can be a few sectors
   smaller and `attach` will refuse). A mirror adds **no capacity**, and it is still not a
   backup — a deletion or ransomware hits both sides.
   ```bash
   DISK=/dev/disk/by-id/ata-<MODEL>_<SERIAL>     # always by-id, never /dev/sdX
   sudo zpool attach red ata-WDC_WD40EFZZ-68CPAN0_WD-WX32D163WV1V $DISK
   sudo zpool status red    # resilver of ~2.8 TB takes hours; then it's a mirror
   ```
2. **Separate backup pool** (when a disk is meant as the off-pool copy): a second
   single-disk ZFS pool fed by `zfs send | zfs recv` from `red`'s snapshots. **No such job
   exists yet** — this needs its own design (schedule, retention, alerting) and the user's
   sign-off, built as code in the repo. The disk must hold at least `red`'s used data
   (~2.8 TB today). Do not rebuild mergerfs/attic or an rsync cold copy.
3. **Capacity expansion** (`zpool add` = a stripe): AVOID — one drive lost = pool lost.
   Only with the user's eyes-open consent. To grow capacity safely, mirror with larger
   disks and replace the smaller side later (`autoexpand=on`).

### 3. Verify + document
```bash
sudo zpool status red && zfs list
```
- Monitoring gaps to raise with the user, not fix ad hoc: `smartd` won't watch the new
  disk (it lists `/dev/sda`/`/dev/sdb` by letter), and nothing pages on a DEGRADED pool.
  Both belong in the repo as code, not as hand edits on opti.
- Update `homelab/docs/homelab-techdoc.md` (§2 opti table, §10 storage) and this baseline.
- User commits — never commit for them.

## History

The pre-2026-07-25 version of this skill onboarded drives as mergerfs branches under
`/srv/pool` with OMV-managed ext4 mounts. The ZFS migration retired that architecture (and
its `path = /srv/pool/` Samba override in the share's OMV `extraoptions`); the old pair
lived on as a weekly cold copy at `/srv/attic` until that was **removed 2026-09-24** — the
pool's ~1 TB no longer fit, and its writes spilled onto the root disk and filled it on
2026-09-08. Leftovers on opti: an empty immutable `/srv/attic` stub, `/srv/sda-pool` on the
root disk, and (until another cleanup lands) the disabled `homelab-coldcopy` units. The
`/srv/pool` compat bind no longer exists. Migration record: plan
`so-lets-do-both-dazzling-frog` (2026-07-25/26 session).
