# discord-weather

Posts a daily weather report (Open-Meteo, no API key) to a Discord channel
webhook as an embed, and exposes a control API used by the rpi webapp's
**Weather Channel Bot Settings** tab (`https://rpi:8443/#weather`) — locations,
post time, enable/disable, test send and preview are all managed from there,
not by editing files.

Runs as the `discord-weather` service in `../docker-compose.yml`. The webhook
URL comes from `DISCORD_WEBHOOK_URL` in the stack's gitignored `.env` (seed
only — after first boot the volume-persisted config is authoritative and the
URL can be rotated from the webapp tab).

## Config

`/data/config.json` on the `weather_data` volume, seeded on first boot:

```json
{"enabled": true, "post_time": "07:00", "timezone": "America/New_York",
 "webhook_url": "https://discord.com/api/webhooks/…",
 "locations": [{"name": "Bellerose, NY", "lat": 40.7328, "lon": -73.7178}, …]}
```

Edit via the webapp tab (preferred) or `PUT /config`. `/data/last_post` tracks
the last posted date so a restart spanning post time catches up instead of
double-posting. A failed daily post is re-attempted every 15 minutes until it
lands ("late rather than never"); progress shows in `GET /health` and the
webapp's Home-page Weather Bot card.

## Witty morning messages

When `witty_enabled` is true (the default), the post includes a short Mr. Murf
line after `message`. The refreshed catalogue has **84 ordinary lines** mixing
friendly callouts, little jokes, and easy conversation starters, plus **68
weather-event variants**. These are authored templates, not LLM prompts: stdlib
only, no model/API costs and no reading the Discord chat.

Ordinary days draw from the shuffled catalogue. A premise has a **45-post
cooldown regardless of which friend's name is used**; it also appears at most
once per cycle. Older template/name pair history is a secondary preference.
With too few available templates the oldest premise is used. Empty
`witty_names` still allows nameless lines and weather messages. Upgrading the
catalogue retires pending old recipes automatically while preserving history.

**Weather takes priority across every configured location.** Only one topic
leads the daily message, in this order (longer runs break priority ties):

| Trigger | Message focus |
|---|---|
| Thunderstorms in the forecast | Indoor plans / storm forecast |
| A run of at least 3 🔥 days ends | Final streak count, new badge, distance below the cutoff |
| At least 3 consecutive 🔥 days | Current day count and the ongoing joke |
| Forecast maximum wind at least 30 mph | Wind |
| Snow forecast | Snow; consecutive forecast count from day 3 |
| 🔥 on its first or second recorded day | Heat / start watching the counter |
| 🥶 or 🧊 | Cold; identical-badge count from day 3 |
| At least 3 consecutive 🥵 days | Hot-badge streak |
| At least 3 consecutive rainy forecasts | Rain streak |
| Feels-like forecast changes at least 20°F from yesterday's post | Temperature swing |
| Heavy rain, or rain forecast with at least 80% probability | Wet-weather plans |
| At least 25°F feels-like spread between towns | Different-weather banter |

The fire cutoff shares the embed's exact `feels_emoji` function: **raw feels-like
at least 100°F = 🔥**. A value such as 99.6°F can display rounded as 100° in the
embed but is still 🥵; streak-ending messages retain the precise temperature.
This tracks **posted daily forecasts**, not measured conditions or official
weather alerts. Ordinary sunshine/cloudiness does not manufacture an event.

Greensboro, NC is called **Starks**, using the mapping supplied for this refresh.
Other places use the town name. An optional plain-text `witty_subject` on a
location can override that through `PUT /config` (for example
`{"name": "Greensboro, NC", "lat": 36.07, "lon": -79.79, "witty_subject": "Starks"}`).
The existing settings UI remains usable; it has no dedicated subject editor.

`/data/witty_pool.json` holds recipes, joke history, and up to 400 daily forecast
snapshots. Counts advance **only after Discord accepts a post**. Previews,
dry-runs, failed sends, and rerolls do not advance history. Multiple successful
sends on one local date update that day's snapshot; they never add a day.
Missing days or missing location reports break continuity, and a timezone
change starts a separate count. Coordinates identify a location, so renaming
a town preserves its streak while moving it does not. Counts start with the
updated bot's first successful report; previous screenshots are not backfilled.

Event variants rotate through their own premises before repeating, across all
towns. An event reroll changes the wording while retaining the weather topic.
The `/witty` card's `next_generic` remains the weather-free fallback; use
`/preview` for the actual weather-aware message. Given unchanged forecast facts,
a retry/preview keeps its selection across restarts. Updated facts can change
the message so it stays accurate. A broken witty module still allows the plain
weather report; failed state writes log a warning and fall back to memory.

Examples (illustrative forecasts):

- Ordinary: “What game could this group cooperate in for twenty minutes without appointing a defendant?”
- Streak: “Starks: day 5 of 🔥. At what point do we stop calling this a forecast and start calling it a residency?”
- Streak ends: “Day 0 of Starks being on fire. The 5-day run ends at 99° feels-like. Please respect the fans' privacy.”

Taste-test: `python3 witty_messages.py 30` or `--all` for every ordinary line.
Run offline regression tests (no web requests or Discord sends):

```sh
python3 -m unittest discover -s homelab/hosts/rpi/discord-weather -p 'test_*.py' -v
```

Run from the repo root with Python 3.12+ and timezone data (the Docker image
already installs `tzdata`). The standard rpi deployment workflow copies this
folder, builds the image including `weather_context.py`, and restarts the bot
after the changes are committed and pushed. Persistent volume state is retained.

Layout: locations render as a 2-per-row grid (inline fields + invisible
spacer fields). Sunrise/sunset appear once in the header, taken from the
first location in the list — fine while all locations share a metro area.

## Control API (`:8080`, internal docker network only — never published)

| Endpoint | Purpose |
|---|---|
| `GET /health` | ok flag, enabled, next/last post, last status |
| `GET /config` | config (webhook URL masked) |
| `PUT /config` | update settings; validates, reschedules immediately |
| `POST /send` | build + post the report right now |
| `GET /preview` | today's payload JSON without posting |
| `GET /geocode?q=name` | Open-Meteo geocoding search (top 5) for adding locations |
| `GET /witty` | witty pool status: remaining, cycle, next-up (generic), last posted |
| `POST /witty/reroll` | rotate today's pick to the back of the cycle, return the new one |

The webapp proxies these at `/api/weather/*` (backend/routes/weather.js).

## Shell testing

```sh
python3 discord-weather.py --dry-run    # print payload, no post
python3 discord-weather.py --once      # post now and exit
docker logs discord-weather            # daemon activity + schedule
```
