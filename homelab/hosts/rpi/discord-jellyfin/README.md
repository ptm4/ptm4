# discord-jellyfin

Posts a daily "what landed in Jellyfin yesterday" digest to a Discord channel
webhook as an embed, and exposes a control API used by the rpi webapp's
**Jellyfin Bot** tab (`https://rpi:8443/#jellyfin`) — post time, server URL,
API key, enable/disable, test send and preview are all managed from there,
not by editing files.

Clone of `../discord-weather` (same scaffolding: volume config, catch-up
scheduler, control API on internal :8080); only the domain logic differs.

## Data source

Jellyfin on noblenumbat (`http://192.168.1.6:8096`), `X-Emby-Token` auth:
`GET /Items?IncludeItemTypes=Movie,Episode&Recursive=true&SortBy=DateCreated…`,
filtered client-side to items whose `DateCreated` falls in yesterday (bot's
timezone). Movies list individually; episodes group by series ("3 episodes of
X", or S/E numbers when ≤3). `max_items` caps the list.

**Mint a dedicated API key** in the Jellyfin dashboard (Admin → API Keys) for
`JELLYFIN_API_KEY` — do not reuse keys embedded in other scripts.

Empty days: `post_when_empty=false` (default) skips the post and stamps the
day done; `true` posts a "Nothing new" embed. The webapp's **Send now** button
always posts either way.

## Config

`/data/config.json` on the `jellyfinbot_data` volume, seeded on first boot
from `DISCORD_WEBHOOK_URL_JELLYFIN` + `JELLYFIN_API_KEY` in the stack's
gitignored `.env` (seed only — after first boot the volume config is
authoritative; rotate secrets from the webapp tab).

## Control API (internal :8080)

`GET /health` · `GET /config` (secrets masked) · `PUT /config` ·
`POST /send` (always posts) · `GET /preview` (payload + `has_items`, no post) ·
`GET /check` (Jellyfin connection test → server name + version)
