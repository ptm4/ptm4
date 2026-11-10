# discord-jellyfin

Posts a daily "what landed in Jellyfin yesterday" digest to a Discord channel
webhook as an embed, and exposes a control API used by the rpi webapp's
**Jellyfin Bot** tab (`https://rpi:8443/#jellyfin`) — post time, server URL,
API key, enable/disable, test send and preview are all managed from there,
not by editing files.

Clone of `../discord-weather` (same scaffolding: volume config, catch-up
scheduler, control API on internal :8080); only the domain logic differs.

## Data source

Jellyfin on noblenumbat (`http://192.168.1.6:8096`), API key sent as
`Authorization: MediaBrowser Token="<key>"`. Jellyfin there has
`EnableLegacyAuthorization=false`, so the old `X-Emby-Token` header (and
`?api_key=`) get **401 even with a valid key**; that broke this bot from
2026-09-11 to 2026-11-09. A 401/403 is reported as "Jellyfin rejected the API
key (HTTP 401)" and is not retried within a run; only connection errors and
timeouts say "Jellyfin unreachable".
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

## Tests

Offline, no network: `python3 -m unittest -v test_jellyfin.py` from this folder.
