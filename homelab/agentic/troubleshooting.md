# Troubleshooting — known false positives & operational hazards

Two kinds of entry, kept here so nobody re-investigates them from scratch:

- **False positives** — agent findings that look like real problems but aren't.
- **Operational hazards** — traps that cost real time during maintenance. Read the
  relevant ones *before* the work, not after they bite.

If an entry stops matching reality (e.g. after code changes elsewhere), update or remove it.

---

## FALSE POSITIVE — network-report: `[android] No default gateway configured` (critical)

**Status: root cause identified and fixed in code 2026-07-22. Not yet deployed/verified
live — see caveat at the bottom.**

### Symptom
`network-latest.json` flagged android with `severity: critical` — `"gateway": null,
"gateway_reachable": false` — while the same report row showed `"internet": true` and
successful DNS lookups (`github.com`, `webapp.rpi.lan` both resolved). Internet clearly
worked; the finding didn't match reality.

### Root cause
`default_gateway()` in `homelab/tools/collectors/network-report.py` ran `ip route show
default` over SSH and looked for a line starting with `default`. That works on the three
Linux hosts, but **Android routes per-app/per-uid through tables that aren't in the main
routing table an unprivileged process (Termux, unrooted) can see** — so the command
legitimately returns nothing on android even though the OS is routing packets fine
underneath. `routes(host)` (`ip route show`, no `default` filter) confirmed this: android
only showed a local `192.168.1.0/24 dev wlan0` link route, no default line at all — not
because there's no route, but because it's invisible from this vantage point.

### Fix
`default_gateway()` now falls back to `ip route get 1.1.1.1` when `ip route show default`
comes back empty, and parses the `via <gateway>` out of that instead. `ip route get` asks
the kernel what it would actually use to reach a destination — a read-only query, not a
privileged operation — so it works even under Android's per-uid routing and correctly
reports the real gateway (`192.168.1.1`) android's already using.

Verified the parse logic against `ip route get 1.1.1.1` output on a normal Linux host
(`1.1.1.1 via 192.168.1.1 dev <iface> src ... uid 1000`) — same iproute2 output format
Android/Termux's `ip` produces.

### Where
`homelab/tools/collectors/network-report.py`, `default_gateway()`.

### ⚠️ Caveat — not deployed, and android is currently unreachable anyway
This fix lives only in the working tree here (never committed by me — see the
never-commit rule). It takes effect once pushed to `main` and the next scheduled/manual
`network-report` run picks it up on opti's checkout (opti's self-hosted runner re-checks
out `main` on every `homelab-agents.yml` trigger).

I tried to verify it live by dispatching a fresh run (`POST /api/agents/network-report/run`
via the webapp) with the *old*, unfixed code still deployed, as a baseline — and got a
**different, worse result**: all three critical findings fired (gateway, internet, *and*
DNS), not just gateway. Checked directly from the LAN: `ping 192.168.1.54` and
`192.168.1.126` (the other IP it's been seen at, per
`homelab/agentic/runbooks/01-hosts-and-ssh.md`) both got 100% packet loss, TCP 8022 was
closed, and its ARP entry was `STALE`. **android is not answering on the LAN right now** —
screen off / Wi-Fi asleep / Doze, not a routing or detection problem. That's a real,
separate condition this fix does not address.

So: two things are true at once. (1) The original snapshot that motivated this fix (taken
earlier the same day) showed android reachable with `internet: true` + working DNS but
`gateway: null` — a genuine detection gap, now fixed in code. (2) As of this check, android
is fully off the LAN, which will independently produce all-critical findings regardless of
the gateway fix. Don't treat the next `network-report` run as a clean verification unless
android is confirmed awake and reachable first (`ping 192.168.1.54`, or check
`~/xfer_status.txt`-style liveness from the phone side).

---

## HAZARD — Stopping Samba on opti kills the Claude session's shell

**Learned the hard way during the 2026-07-25 ZFS migration.**

### Symptom
Every subsequent Bash tool call fails instantly with
`EHOSTDOWN: host is down, posix_spawn '/bin/bash'`. Not a single command runs — including
the ssh command that would bring the share back. Total deadlock mid-maintenance.

### Root cause
Claude Code on tux spawns shells with cwd inside `/home/ptm/opti/...`, which is the CIFS
mount of the opti share. Stop `smbd` and that cwd becomes a dead mount; the kernel can't
resolve it to spawn a process, so *nothing* executes. Chicken-and-egg: fixing it requires
running a command, and no command can run.

### Avoidance
- Prefix every command with `cd /tmp &&` during any work that might interrupt the share.
  (This is why the migration's later phases all start with `cd /tmp`.)
- Before deliberately taking the share down, get the mount detached first.

### Recovery (needs Peter — see the tux-sudo hazard below)
```bash
sudo systemctl stop home-ptm-opti.automount
sudo umount -l /home/ptm/opti      # lazy: processes still hold cwd on it
```
Then the session works again, offline from the share.

---

## HAZARD — tux has no passwordless sudo (opti/rpi/noblenumbat do)

Any root action **on the workstation itself** — fstab edits, umount, systemctl — cannot be
automated and must be handed to Peter as paste-able commands. Easy to forget mid-flow
because all three servers allow `sudo -n`. Cheap check: `sudo -n true`.

---

## HAZARD — the homelab-guard hook denies Samba/OMV paths by substring, including reads

`homelab/agentic/harness/hooks/homelab-guard.py` → `_samba_or_omv()` matches
`("/etc/samba", "smb.conf", "/etc/openmediavault")` anywhere in a Bash command and denies
it outright. Consequences worth knowing:

- **Even a backup is blocked** (`cat /etc/samba/smb.conf | tee /root/backup`) — it sees a
  write verb near the path. Hand those to Peter.
- **`smb.conf` is a substring**, so `smb.conf.local` would also be denied. This is exactly
  why opti's hand-managed share config lives at **`/etc/homelab/samba-red.conf`** instead —
  outside OMV's territory, which satisfies the guard's intent rather than evading it.
- Sanctioned route for OMV state: the RPC layer (`omv-rpc`, `omv-confdbadm`), not file edits.

---

## HAZARD — ntfs-3g: no remount, and FUSE mounts die with their systemd service

Two distinct traps, both hit while building `homelab-coldcopy.sh`:

1. **`mount -o remount,rw|ro` does not work on ntfs-3g.** It returns
   *"Remounting is not supported at present. You have to umount volume and then mount it
   once again."* A full umount/mount cycle is required to change rw↔ro.
2. **A FUSE mount created inside a `Type=oneshot` service is killed when the service
   exits.** The `ntfs-3g` daemon lands in the service's cgroup, so systemd tears it down
   on exit — the mount silently disappears seconds after a "successful" run. Symptom: the
   script logs `restored ... to ro`, and moments later the filesystem is unmounted.
   **Fix: start the `.mount` unit instead of calling `mount(8)`**, so systemd owns the
   daemon:
   ```bash
   unit=$(systemd-escape -p --suffix=mount /srv/dev-disk-by-uuid-XXXX)
   systemctl start "$unit"
   ```

---

## HAZARD — self-matching process watchers and silently no-op patches

Two ways to get a confidently wrong answer:

- **`pgrep -f 'rsync.*/srv/red'` matches the very command containing that string** — the
  ssh/bash process running your check. A watcher built on it loops forever; a status probe
  reports "still running" for a job that finished hours ago. Use `pgrep -x <name>`, or
  check for the real process another way.
- **`python3` in-place patching with `str.replace` fails silently** when the pattern
  doesn't match (heredoc escaping is the usual culprit) — it rewrites the file unchanged
  and reports success. Always `assert old in text` before replacing, and grep the deployed
  copy afterwards to prove the change landed.

Corollary that caught a real error: a shell redirect `>` runs as the *calling* user even
when the command is `sudo`. `sudo diff a b > /root/out` fails with permission denied, the
output file is never created, and a following `test -s` then reports "no differences" —
a false clean bill of health on a data-verification step. Use `| sudo tee`.

---

## HAZARD — mount shadowing: the path looks right and the data goes nowhere

**The single most dangerous failure class on opti. Caught live 2026-07-26.**

### Mechanism
A mountpoint is just a folder. Mounting *hides* what's underneath; it doesn't remove it. So
`/srv/red/fs` is two different places depending on timing — an empty folder on the boot disk
before `zfs-mount.service` runs, the ZFS dataset after. A **bind mount resolves once**, at
creation. This boot did:

```
[33.05s] Mounted srv-pool.mount   ← bind latched onto the EMPTY FOLDER
[39.08s] Finished zfs-mount.service
```

Six seconds too early, and `/srv/pool` pointed at a dead-end folder on the root disk for the
rest of the boot. Every symptom read as healthy: `ls` worked, `df` showed a filesystem,
writes succeeded. But the bytes were on the 457 GB boot disk — invisible to the share, absent
from snapshots, outside every backup, and silently filling `/`.

### Why it is hard to spot
There is no error. The only tell is the device column:
```bash
findmnt -o TARGET,SOURCE /srv/pool
#  /dev/sda1[/srv/red/fs]   ← WRONG: sourced from the boot disk
#  red/fs                   ← right
```
Definitive check — compare inodes: `[ "$(stat -c %i /srv/pool)" = "$(stat -c %i /srv/red/fs)" ]`

### Defences now in place (all three, deliberately)
1. **Eliminated** — `/srv/pool` was deleted outright (2026-07-26). The two scripts that used
   it (`opti-health-digest.sh`, `opti-backup.sh`) now reference `/srv/red/fs` directly. The
   path no longer exists, so a straggler gets a loud `ENOENT` instead of a silent wrong write.
2. **Sealed** — the empty stubs *underneath* the mounts (`/srv/red`, `/srv/red/fs`,
   `/srv/attic`) are `chattr +i`. If a mount ever fails, writes get `EPERM` immediately
   instead of landing on the boot disk. Verified: mounting over an immutable directory works
   normally (mount does not write to the dir), and mergerfs still mounts over a sealed
   `/srv/attic`.
   To inspect or change them, reach *under* the mounts:
   ```bash
   mount --bind / /mnt/rootview     # the root fs without anything mounted on top
   lsattr -d /mnt/rootview/srv/red  # chattr -i here to unseal
   umount /mnt/rootview
   ```
3. **Detected** — `homelab-doctor` now asks ZFS directly (`zfs list -o name,mountpoint,mounted`)
   and raises a **critical** for any dataset that should be mounted and isn't. Asking ZFS
   rather than inspecting the path matters, because the failure mode *is* that the path looks fine.

### Still open
The boot-ordering fix for the bind was `x-systemd.requires=zfs-mount.service` — now moot since
the bind is gone. But **any future fstab entry whose source is a ZFS path needs that option**,
or it will reproduce this exactly.

---

## HAZARD — `find -xdev` silently excludes ZFS child datasets

`red/media` is a separate dataset mounted *inside* `/srv/red/fs`, so `-xdev` stops at that
boundary. Two things this broke:

- **Migration verification.** The Tier 1 manifest of the copy used `find -xdev` and therefore
  omitted the entire 527 GB media library, then compared that truncated list against a source
  manifest that included it. Combined with a `sudo cmd > /root/file` redirect that failed as
  the calling user (so the diff file was never written and `test -s` found nothing), it
  reported **"IDENTICAL — every file present"** for a comparison that never ran.
- **The coldcopy source floor.** `find -xdev` counted 12,971 files while `du` (which *does*
  cross datasets) reported 608 GiB — the file floor and the byte floor were measuring
  different trees. Fixed 2026-07-26: no `-xdev`, so both cover all 13,278 files / 608 GiB.

Rule of thumb: on a host with nested datasets, `-xdev` is almost never what you want, and any
count you can't reconcile against a second independent measure should be treated as wrong.
