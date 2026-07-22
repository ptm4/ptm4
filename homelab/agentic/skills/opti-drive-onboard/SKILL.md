---
name: opti-drive-onboard
description: Onboard a new physical drive into the opti server (192.168.1.11) mergerfs pool /srv/pool. Use when the user says they installed a new drive in opti, wants to add a disk to the pool/share, or expand opti storage. Walks through identify → SMART → wipe → ext4 → OMV mount → mergerfs branch add → verify.
---

# Onboard a new drive into the opti mergerfs pool

Target: `ptm@192.168.1.11` via `ssh -i ~/.claude/opti_key ptm@192.168.1.11` (passwordless sudo).
Tools live in `/usr/sbin` (not in the non-login PATH) — call them as `sudo /usr/sbin/<tool>` or `sudo <tool>`.

**RULES (non-negotiable):**
- Propose every server-side write and get explicit user agreement before running it (see memory: discuss-before-deploy).
- The wipe step destroys data. Show the disk's model, serial, size, and current partitions and get the user to confirm THAT disk before wiping.
- Never hand-edit anything between `# >>> [openmediavault]` / `# <<< [openmediavault]` markers in `/etc/fstab`, nor `/etc/samba/smb.conf` or `/etc/exports` — OMV regenerates them. The mergerfs line lives OUTSIDE the OMV markers and is ours to edit.

## Known state (baseline as of 2026-07-07 — re-verify live, don't trust blindly)

- OMV 7.7.x, mergerfs 2.33.5. No OMV mergerfs plugin: the pool is a hand-maintained fstab entry.
- Existing disks (serials — anything NOT in this list is a candidate new drive):
  - `sda` ST500DM002-1BD142, serial `Z6E9H7VE`, 465 GB — root ext4; branch is the **directory** `/srv/sda-pool` on the root fs.
  - `sdb` Hitachi HTS547564A9E384, serial `110926J2380053CXKRHC`, 596 GB — NTFS partition mounted by OMV at `/srv/dev-disk-by-uuid-C682C2DE82C2D1DB`; branch is its `fs/` subdir.
- Current fstab mergerfs line (one line):
  ```
  /srv/sda-pool:/srv/dev-disk-by-uuid-C682C2DE82C2D1DB/fs /srv/pool fuse.mergerfs defaults,allow_other,use_ino,category.create=mfs,minfreespace=30G,fsname=mergerfs-pool,nofail,x-systemd.requires=/srv/dev-disk-by-uuid-C682C2DE82C2D1DB 0 0
  ```
- Pool root perms: `ptm:users`, mode `2775` (rwxrwsr-x). New branches must match.
- Samba: `[fs]` share currently points at the sdb branch dir (`/srv/dev-disk-by-uuid-C682C2DE82C2D1DB/fs/`), a second share points at `/srv/pool/`. Pool growth needs no Samba change. 6 SATA ports (ata1–6); chassis/PSU realistically maxes at 2 more drives.

## Procedure

### 1. Identify the new disk
```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL,SERIAL
```
The new drive is the one whose serial is not in the baseline list above. Confirm device node (e.g. `/dev/sdc`), model, serial, and size with the user. Device letters can shuffle across reboots — from here on prefer by-id/by-uuid paths for anything persistent.

### 2. SMART baseline
```bash
sudo smartctl -i -H /dev/sdX
sudo smartctl -t short /dev/sdX   # ~2 min, then:
sudo smartctl -a /dev/sdX         # check: SMART overall-health PASSED, Reallocated_Sector_Ct=0, Current_Pending_Sector=0
```
For a brand-new large drive, offer (don't force) a long test (`-t long`, hours) or a full `badblocks`-style burn-in; short test is the minimum gate.

### 3. Partition + filesystem (DESTRUCTIVE — confirm first)
```bash
sudo wipefs -a /dev/sdX
sudo parted -s /dev/sdX mklabel gpt mkpart primary ext4 0% 100%
sudo mkfs.ext4 -m 0 -L pool-4tb-N /dev/sdX1   # N = 1, 2, ... ; -m 0: no root reserve on a data disk
sudo blkid /dev/sdX1                          # record the UUID
```

### 4. Mount it the OMV way (so the UI/DB tracks it)
Preferred — OMV RPC (creates the DB entry, fstab entry inside OMV markers, and mounts):
```bash
sudo omv-rpc -u admin "FileSystemMgmt" "mount" '{"id":"/dev/disk/by-uuid/<UUID>","fstab":true}'
sudo omv-salt deploy run fstab
```
If the RPC signature errors (verify with `sudo omv-rpc -u admin "FileSystemMgmt" "enumerateMountedFilesystems" '{"includeroot":false}'` and adjust), fall back to: user mounts it in the OMV web UI (Storage → File Systems → ▸ Mount existing). Either way the result must be a mount at `/srv/dev-disk-by-uuid-<UUID>` and an entry inside the OMV fstab markers. Verify:
```bash
findmnt /srv/dev-disk-by-uuid-<UUID>
sudo omv-confdbadm read conf.system.filesystem.mountpoint
```

### 5. Create the branch directory
Branch is a subdir, not the fs root (keeps `lost+found` out of the pool):
```bash
sudo mkdir -p /srv/dev-disk-by-uuid-<UUID>/fs
sudo chown ptm:users /srv/dev-disk-by-uuid-<UUID>/fs
sudo chmod 2775 /srv/dev-disk-by-uuid-<UUID>/fs
```

### 6. Persist the branch in fstab (propose diff first)
Edit ONLY the mergerfs line (outside OMV markers): append `:/srv/dev-disk-by-uuid-<UUID>/fs` to the branch list, and append `,x-systemd.requires=/srv/dev-disk-by-uuid-<UUID>` to the options. Show the user the exact before/after line, get agreement, apply with a targeted `sudo sed -i.bak` or a heredoc rewrite of that line, then:
```bash
sudo systemctl daemon-reload
```

### 7. Add the branch to the live pool (no unmount)
mergerfs ≥2.33 runtime API via the control file:
```bash
sudo setfattr -n user.mergerfs.branches -v '+>/srv/dev-disk-by-uuid-<UUID>/fs' /srv/pool/.mergerfs   # +> appends
sudo getfattr -n user.mergerfs.branches /srv/pool/.mergerfs                                          # confirm
```
If setfattr/xattr is unavailable, fall back to a brief remount (warn user: closes open Samba handles):
```bash
sudo umount /srv/pool && sudo mount /srv/pool
```

### 8. Verify
```bash
df -h /srv/pool                      # size grew by ~the new drive
touch /srv/pool/.onboard-test && ls /srv/dev-disk-by-uuid-<UUID>/fs/   # with category.create=mfs the new (emptiest) branch should receive it
rm /srv/pool/.onboard-test
```
Then have the user (or check from a client) confirm the `\\opti` Samba share still lists content. Optionally reboot opti once during a quiet window to prove the fstab entry survives boot ordering (`nofail` + `x-systemd.requires` should handle it).

### 9. Documentation
Update `homelab/homelab-techdoc.md` (opti hardware table, section 10 storage: new disk model/serial/UUID, new pool size) and the "Known state" baseline in this skill file. Remind the user to commit (never commit yourself).

## Notes / future work
- `category.create=mfs` = new files go to the branch with most free space, so new 4 TB drives naturally absorb writes. `minfreespace=30G` stays sane.
- Once both 4 TB drives are in, consider evacuating the two legacy branches: the NTFS Hitachi laptop drive (ntfs-3g FUSE = slow, no POSIX perms, weakest disk in the pool) and `/srv/sda-pool` (shares the OS root disk). Evacuate with rsync branch→branch, then remove the branch from fstab + runtime (`-<` xattr value removes), then retire/repurpose the disk.
- The Samba `[fs]` share points at the sdb *branch*, not `/srv/pool` — clients on that share can't see files placed on other branches. Worth repointing to `/srv/pool` via the OMV UI (shared folder → filesystem) at some point; discuss with user first.
