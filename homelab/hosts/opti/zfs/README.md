# opti ZFS dataset properties

`red-properties.tsv` lists the ZFS properties of pool `red` that the repo owns (quotas,
reservations, snapshot opt-outs). `apply-zfs-properties.sh` makes the live pool match it, and
`.github/workflows/opti-deploy.yml` runs it on every deploy, so a change here goes live when
Peter pushes. Don't `zfs set` these by hand: the next deploy puts the listed value back.

```bash
sudo bash homelab/hosts/opti/zfs/apply-zfs-properties.sh homelab/hosts/opti/zfs/red-properties.tsv --dry-run
```

The script only sets or inherits properties. It never creates, destroys or renames datasets
or snapshots. Deleting a line does not undo it on the host: set the value to `inherit` (or
`none` for a size), deploy, then delete the line.

## Not in this file

- **Datasets themselves** (`red/fs`, `red/media`, `red/docker`, `red/docker-apps`,
  `red/opsdb`) were created by hand (runbook 10 and the 2026-07-25 migration).
- **Snapshot schedule** is Debian's `zfs-auto-snapshot` package with its default cron jobs
  (`/etc/cron.d/zfs-auto-snapshot` for frequent, then `/etc/cron.{hourly,daily,weekly,monthly}`).
  It snapshots every dataset whose `com.sun:auto-snapshot` isn't `false` and keeps 4 frequent,
  24 hourly, 31 daily, 8 weekly and 12 monthly.
- **Alerts** are in `homelab/tools/collectors/homelab-doctor.py`: a warning at 80% pool use,
  critical at 90%, and a warning for any dataset at 90% of its quota. They reach the phone
  through ntfy.

## Gotcha: opting a dataset out of snapshots orphans its old ones

Once `com.sun:auto-snapshot=false`, `zfs-auto-snapshot` skips the dataset for pruning as well
as for new snapshots. The snapshots it already has never expire, and they hold anything later
deleted from the dataset. Destroy them by hand after the opt-out deploys. That is a separate,
explicitly approved step, because it can't be undone.

## State on 2026-11-09 (audit finding H-3)

The pool is 3.62T and 76.4% used. It was 25.7% on Sep 30 and grew in bulk copies during
October. `red/fs` has 1.40T live and 173G in snapshots. Those 173G are two game installs
deleted from `ptm/Games/Active` on Oct 23–24:

- CoD MW4 (117G) is only in `daily-2026-10-23` and expires by itself around Nov 23.
- AC Black Flag Resynced (56G) is in snapshots back to `monthly-2026-10-02`. After about
  Dec 16 that monthly snapshot is the only one holding it, and it keeps it until Oct 2027
  unless it's destroyed.
