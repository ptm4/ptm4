# discord-hltv

Posts a daily "CS2 games of the day" digest to a Discord channel webhook as an
embed, and exposes a control API used by the rpi webapp's **HLTV Bot** tab
(`https://rpi:8443/#hltv`) — post time, filters, enable/disable, test send and
preview are all managed from there, not by editing files.

Only notable matches make the cut: **a team in the Valve Regional Standings
(VRS) top N** (default 32), or a **top-tier (S/A) tournament**. Matches group
by tournament, with start times in the bot's timezone and 🔴 LIVE for games
already running.

Clone of `../discord-weather` (same scaffolding: volume config, catch-up
scheduler, control API on internal :8080); only the domain logic differs.

## Data sources

- **Valve VRS** — the official standings, parsed from ValveSoftware's
  `counter-strike_regional_standings` GitHub repo (latest
  `live/<year>/standings_global_*.md`). HLTV's own ranking page is
  Cloudflare-walled; Valve's repo IS the VRS source of truth. Cached in
  `/data/vrs_cache.json` for 24 h (Valve updates ~weekly); a stale cache is
  used if GitHub is unreachable.
- **bo3.gg public API** (unofficial, parsed defensively) — today's matches
  with teams, tournament and tier. Note: their date filter only honors
  `gt`/`lt` with full ISO timestamps.

Team names are normalized on both sides ("Team Spirit" ≈ "Spirit") before
matching against the VRS list. If VRS is unavailable the tier filter still
applies; if bo3.gg is down the post fails and retries (15-min scheduler).

No-game days: `post_when_empty=false` (default) skips the post and stamps the
day done; the webapp's **Send now** button always posts.

## Config

`/data/config.json` on the `hltvbot_data` volume, seeded on first boot from
`DISCORD_WEBHOOK_URL_HLTV` in the stack's gitignored `.env` (seed only — after
first boot the volume config is authoritative; rotate from the webapp tab).

```json
{"vrs_top_n": 32, "tiers": ["s", "a"], "post_when_empty": false}
```

## Control API (internal :8080)

`GET /health` · `GET /config` (webhook masked) · `PUT /config` ·
`POST /send` (always posts) · `GET /preview` (payload + `has_matches`, no
post) · `GET /vrs` (current cached VRS top-N list)
