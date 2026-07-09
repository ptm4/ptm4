---
name: sonarr-add
description: Add TV series (including docuseries) to the homelab Sonarr (noblenumbat) by title/year. Use when the user asks to add shows, series, seasons, or multi-part documentaries to Sonarr, the media server, or their Jellyfin library.
---

# Add series to Sonarr

Sonarr runs on noblenumbat and is reachable directly on the LAN — no SSH needed.

- **URL:** `http://192.168.1.6:8989` (API base: `/api/v3`)
- **API key:** `e4260f7ab67d482aa2b3cbd2ebc7aef0`
- **Root folder:** `/data/tvshows`
- **Quality profiles:** 1=Any, 2=SD, 3=HD-720p, 4=HD-1080p, 5=Ultra-HD, 6=HD-720p/1080p. Default to `4` (HD-1080p) to match the movie library.

## Usage

Run the bundled script with one series per line on stdin, formatted `Title (Year)` (year optional but recommended — it disambiguates reboots, e.g. Batman 1966 vs 2004):

```bash
python3 .claude/skills/sonarr-add/scripts/add_series.py <<'EOF'
Batman: The Animated Series (1992)
Fear City: New York vs The Mafia (2020)
EOF
```

The script:

1. Looks each title up via `/series/lookup` (TVDB-backed)
2. Matches by exact year, falling back to ±1
3. Skips series already in the library (reports `EXISTS`)
4. Adds as **monitored** (all seasons) with season folders and `searchForMissingEpisodes: true` — downloads start immediately via Prowlarr indexers
5. Prints per-title results: `ADDED` / `EXISTS` / `NOT FOUND` (with candidates)

## Caveats

- **Movies are not series** — feature-length documentaries belong in Radarr (see the `radarr-add` skill). One-off TV specials sometimes appear on TVDB as single-episode series; check the candidates line before assuming a miss.
- Sonarr monitors **future episodes too** — for an ongoing docuseries it will keep grabbing new seasons. That's usually wanted; unmonitor in the UI if not.
- Episode files import to `/data/tvshows/<Series>/Season NN/`; Jellyfin's TV Shows library picks them up automatically.
- If content was downloaded outside Sonarr (e.g. blackhole torrent), use Sonarr → Wanted → Manual Import pointing at `/data/downloads/torrents/`.
