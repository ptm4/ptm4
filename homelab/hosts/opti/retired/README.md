# Retired opti automation

These files were once installed on opti and are now removed from it. They stay here as a record
and so any of them can be restored. Nothing deploys from this folder.

| Files | What it was | Retired |
|---|---|---|
| `homelab-coldcopy.{sh,service,timer}` | Weekly copy of pool `red` to the attic mergerfs disks. The disks were removed, so it failed every run from 2026-09-24. | 2026-09-24 (repo), 2026-11-10 (host files) |
| `opti-health-digest.{sh,service,timer}` | Hand-made in June 2026 for the "opti DR plan". Ran daily at 06:30, checked SMART on hardcoded `/dev/sda`/`/dev/sdb` plus pool % and failed units, and pushed to a **public ntfy.sh topic**. homelab-doctor, hardware-report and the Discord healthdigest already cover all of it. | 2026-11-10 |
| `opti-backup.{sh,service,timer}` | Planned nightly Borg backup of `/srv/red/fs` and config to NFS on noblenumbat. It never ran: the timer was never enabled, the NFS export was never set up, and the passphrase file never existed. | 2026-11-10 |
| `ip-cutover.sh`, `ip-rollback.sh` | One-time tools that moved opti from .251 to .11 on 2026-06-03. They were in `/usr/local/sbin`. | 2026-11-10 |

The ntfy.sh topic that the digest, the backup and the old `smartd-alert.sh` used should be
treated as leaked. New alerting goes through `homelab/tools/notify.py`.

To restore one: copy the script to `/usr/local/bin/` and the units to `/etc/systemd/system/`,
run `systemctl daemon-reload`, then enable the timer. Better still, move it into
`hosts/opti/systemd/` so CI installs it.
