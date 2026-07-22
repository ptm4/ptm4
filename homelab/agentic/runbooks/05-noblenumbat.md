# noblenumbat (media + code server)

## Roles
- Jellyfin / Radarr / Sonarr media stack.
- Holds the **primary copy of the ptm4 repo**: `noblenumbat:~/code/ptm4`. Edit there — the
  opti mount is stale.

## Known incident: cooling outage (2026-07-16)
- **Symptom:** the whole host went unreachable.
- **Cause:** a **cooling/thermal issue** — NOT a Jellyfin or software fault.
- **Lesson:** if noblenumbat drops off entirely (no SSH, no services), suspect **hardware
  thermal** first, not the media apps. Check physical cooling / ambient temp / fans before
  debugging software.

## Adding media
- Movies: use the `radarr-add` skill (adds to Radarr on noblenumbat, triggers a search).
- TV/docuseries: use the `sonarr-add` skill.
