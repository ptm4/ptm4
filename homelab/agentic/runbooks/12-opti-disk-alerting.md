# 12 — opti disk and pool alerting

opti's ZFS pool `red` is a single WD Red Plus 4 TB disk with no second copy anywhere, and
the boot disk is an aging Seagate (accepted risk, rule `01-homelab-context.md`). Early warning
of disk trouble is the only protection, so this runbook says what watches what.

## What pages, and how

| Watcher | Covers | Path to your phone | Latency |
|---|---|---|---|
| **hl-smartd** (smartd) | SMART on all three disks: health, pending / uncorrectable sectors, self-test failures, temperature; pool disk also ATA error log + usage attributes | `-M exec` → `/usr/local/bin/hl-smartd-alert.sh` → notify.py directly (priority 4, like the `OnFailure=` hook; event-driven, not a finding) | minutes (30-min smartd poll) |
| **homelab-doctor** pool check | `zpool status -j`: pool not ONLINE, vdev read/write/checksum errors, permanent data errors, scrub found errors (critical); no finished scrub in 40 days (warn) | finding → ingest.py routing (`rules/alerting.md`) | pages after ~50 min continuously critical |
| **homelab-doctor** smartd watchdog | `hl-smartd.service` not active (warn) | daily silent digest | next digest |
| **hardware-report** (daily) | SMART snapshot per disk into homelab.db; the boot disk's "+20 reallocated at once" trigger | finding → ingest.py | daily |

ZED (`zfs-zed`) is deliberately **not installed**: on a single-disk pool the useful signal is
error counters going up, and those persist, so the doctor sees them. Revisit when red gets a
mirror. If installed, it must come from `bookworm-backports` (`-t bookworm-backports`) to
match the 2.3.x userland; plain apt picks bookworm's 2.1.11.

## smartd: our unit, not OMV's

- Config: `homelab/hosts/opti/smartd/smartd.conf` → `/etc/homelab/smartd.conf`.
  Hook: `homelab/hosts/opti/smartd/hl-smartd-alert.sh` → `/usr/local/bin/`.
  Unit: `homelab/hosts/opti/systemd/hl-smartd.service`. All installed by `opti-deploy.yml`
  (step "Install smartd config + alert hook"), which validates the config with
  `smartd -q showtests` first.
- **Why not `/etc/smartd.conf`:** OMV's salt state rewrites it from OMV's database, and with
  SMART disabled in OMV it also stops and disables `smartmontools.service` whenever that state
  is applied. The stock unit is disabled; `hl-smartd` `Conflicts=` it.
- **Keep SMART monitoring OFF in the OMV web UI.** Turning it on starts OMV's smartd, which
  stops hl-smartd (Conflicts) and monitors nothing useful; the doctor then warns.
- Disks are listed by `/dev/disk/by-id` because device letters on opti move.
- The boot disk line pages only on rule 01's triggers (health fail, pending, uncorrectable,
  plus failed self-test and critical temperature). Reallocated changes are logged, never paged.
- notify.py runs from a boot-disk copy (`/usr/local/lib/homelab/notify.py`) and keeps its
  dedup state in `/var/lib/hl-smartd`, so a failing pool disk can still page.
- Hook log: `/var/log/hl-smartd-alert.log`. smartd log: `journalctl -u hl-smartd`.

## Testing without a disk failure

Never use `zinject`, `zpool clear/scrub/offline` or similar on red to test alerts.

- Hook end to end (one test push, priority default):
  `sudo env SMARTD_DEVICE=/dev/sdb SMARTD_FAILTYPE=EmailTest SMARTD_MESSAGE="manual test" HL_DATA_DIR=/var/lib/hl-smartd /usr/local/bin/hl-smartd-alert.sh`
- Config and schedule: `sudo smartd -q showtests -c /etc/homelab/smartd.conf`
- Pool check: `pool_health_findings()` in `homelab-doctor.py` is a pure function; feed it a
  copy of `zpool status -j --json-int` edited to DEGRADED / with error counts.

## Rollback

`sudo systemctl disable --now hl-smartd && sudo systemctl enable --now smartmontools` brings
back the stock daemon with whatever `/etc/smartd.conf` holds, then revert the commit so the
next deploy doesn't switch it back.
