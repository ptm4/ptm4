# discord-sports

Posts a daily scores & schedule report for your teams to a Discord channel
webhook as an embed, and exposes a control API used by the rpi webapp's
**Sports Bot** tab (`https://rpi:8443/#sports`) — teams, post time,
enable/disable, test send and preview are all managed from there, not by
editing files.

Clone of `../discord-weather` (same scaffolding: volume config, catch-up
scheduler, control API on internal :8080); only the domain logic differs.

## Data source

ESPN's public site API (keyless, **unofficial** — shapes can drift, so
everything is parsed defensively and a broken team degrades to
"⚠️ data unavailable" instead of killing the post):

- `…/sports/{sport}/{league}/scoreboard?dates=YYYYMMDD` — yesterday's result
  + today's game per team; one fetch per league per day, shared across teams.
- `…/sports/{sport}/{league}/teams` — powers the tab's team search
  (`GET /teams?league=nba&q=knicks`, the weather bot's `/geocode` pattern).

Leagues: NBA only by design (extend `LEAGUES` in the script + `SPORTS_LEAGUES`
in the webapp's app.js to widen).
Teams render as a 2-per-row grid (same spacer-field trick as discord-weather).

## Config

`/data/config.json` on the `sportsbot_data` volume, seeded on first boot from
`DISCORD_WEBHOOK_URL_SPORTS` in the stack's gitignored `.env` (seed only —
after first boot the volume config is authoritative; rotate from the tab).

```json
{"teams": [{"league": "nba", "sport": "basketball", "id": "20",
            "abbrev": "NY", "name": "New York Knicks"}]}
```

## Control API (internal :8080)

`GET /health` · `GET /config` (webhook masked) · `PUT /config` ·
`POST /send` · `GET /preview` · `GET /teams?league=&q=` (team search)
