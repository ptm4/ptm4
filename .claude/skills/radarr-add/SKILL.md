---
name: radarr-add
description: Add movies to the homelab Radarr (noblenumbat) by title/year. Use when the user asks to add movies to Radarr, the media server, or their Jellyfin library. Handles lookup, year matching, duplicate detection, and triggers an automatic download search.
---

# Add movies to Radarr

Radarr runs on noblenumbat and is reachable directly on the LAN — no SSH needed.

- **URL:** `http://192.168.1.6:7878` (API base: `/api/v3`)
- **API key:** `f93e83c7f91e46319c73e6d0508e4ecd`
- **Root folder:** `/data/movies`
- **Quality profile:** use the same `qualityProfileId` as existing library entries (currently `4` = HD-1080p); the script auto-detects it.

## Usage

Run the bundled script with one movie per line on stdin, formatted `Title (Year)`:

```bash
python3 .claude/skills/radarr-add/scripts/add_movies.py <<'EOF'
The Godfather (1972)
Heat (1995)
EOF
```

Year is optional but strongly recommended (avoids remake/same-title collisions). The script:

1. Looks each title up via `/movie/lookup`
2. Matches by exact year, falling back to ±1 (TMDB release years sometimes differ from common knowledge, e.g. The Death of Superman is 2019 on TMDB, not 2018)
3. Skips titles already in the library (reports them as `EXISTS`)
4. Adds as **monitored** with `searchForMovie: true` — downloads start immediately via Prowlarr indexers
5. Prints a per-title result line: `ADDED` / `EXISTS` / `NOT FOUND` (with candidates)

## Caveats

- **Docuseries/TV are not movies.** Netflix-style multi-part documentaries (e.g. Fear City, Get Gotti) live on TMDB as TV series — Radarr can't manage them; they belong in Sonarr (`http://192.168.1.6:8989`). The lookup will usually return `NOT FOUND` for these; don't force-match them to similarly named movie entries.
- Radarr tracks **one file per movie** — alternate cuts (theatrical vs. special edition) need manual handling as Jellyfin "versions".
- After adding, downloads appear in qBittorrent (`http://192.168.1.6:8081`) within minutes; imports to Jellyfin are automatic. See homelab/homelab-techdoc.md Section 16.
