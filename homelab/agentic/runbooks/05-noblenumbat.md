# noblenumbat (media server)

## Roles
- Jellyfin / Kavita / *arr media stack, with qBittorrent, SABnzbd, Prowlarr, Mylar3 and
  FlareSolverr behind Gluetun. Compose at `/opt/yams/docker-compose.yaml`.
- Media itself lives on **opti**, mounted at `/mnt/opti-library`, `/mnt/opti-shows` and
  `/mnt/opti-media` — not on the local NVMe.

## It is NOT a code server (corrected 2026-07-25)
The `noblenumbat:~/code/ptm4` clone **was deleted on 2026-07-22** and this host no longer
holds a copy of the repo. Earlier revisions of this runbook called it the primary copy and
said "edit there — the opti mount is stale"; that is wrong, and following it sends you to a
path that does not exist.

The working copy is `/home/ptm/opti/ptm/repo/ptm4` on **tux**, which is a CIFS mount of opti's
pool — see [`01-hosts-and-ssh.md`](01-hosts-and-ssh.md). Deleting that clone is also what
destroyed the only copy of several gitignored skills and rules.

## Known incident: cooling outage (2026-07-16)
- **Symptom:** the whole host went unreachable.
- **Cause:** a **cooling/thermal issue** — NOT a Jellyfin or software fault.
- **Lesson:** if noblenumbat drops off entirely (no SSH, no services), suspect **hardware
  thermal** first, not the media apps. Check physical cooling / ambient temp / fans before
  debugging software.

## Adding media
- Movies: use the `radarr-add` skill (adds to Radarr on noblenumbat, triggers a search).
- TV/docuseries: use the `sonarr-add` skill.
