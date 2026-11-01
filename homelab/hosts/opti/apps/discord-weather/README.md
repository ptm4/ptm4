# discord-weather

Logs in as the **Weather-Bot** Discord account. It posts a daily weather report
(Open-Meteo, no API key) to `channel_id` as an embed, and **answers pings**:
mention it (user or its own role) or reply to it. A weather ask gets that town's
forecast (a town named in the message, else the asker's home town from the
persona, else every town) and "full report" gets the whole embed; anything else
gets an in-character line for what was asked — see *Answering pings* below.
Replies only peek, so they never consume the morning joke or advance streaks.
Rate limit: 8 s per person and at most 6 replies per channel per minute.

The control API is used by the webapp's Bots → Weather tab (`webapp.lan:8443`),
where locations, post time, channel, enable/disable, test send and preview are
managed.

Runs as the `discord-weather` service in `../../docker-compose.apps.yml`.
`DISCORD_BOT_TOKEN` comes from the stack's gitignored `.env`. Without the token
(or without discord.py) there are no replies, and the report falls back to the
legacy `webhook_url`. A config that only has a webhook adopts the webhook's
channel as `channel_id` on start. Bot permissions needed in the channel: View
Channel, Send Messages, Embed Links, Read Message History, and Mention Everyone
for the `@everyone` message.

## Config

`/data/config.json` on the `weather_data` volume, seeded on first boot:

```json
{"enabled": true, "post_time": "07:00", "timezone": "America/New_York",
 "channel_id": "1527…", "webhook_url": "",
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

### Private persona (`/data/persona.json`)

The repo is public, so lines about real people live only on the volume. If
`/data/persona.json` exists it replaces the catalogue above and can override
any `EVENT_LINES` kind, the embed `username`/`title`/`footer`, and map names to
Discord user ids (`"pings": {"@tomboe": "2104…"}`) so they render as real
`<@id>` mentions. Templates may set `"who": "@name"` to be drawn only for that
roster name. A `"word_banks": {"me": [...]}` list gives the bot rotating
self-names: `{me}` in lines, event lines and the embed fields resolves to **one**
name per post, so sender, title, footer and joke never disagree. An invalid
file logs a warning and the defaults stay in use.
Editing it starts a fresh cycle (premise history is kept). Taste-test:
`python3 witty_messages.py --persona persona.json 20`. Install with
`docker cp persona.json discord-weather:/data/` and restart the container.

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

## Answering pings

Most pings are not weather questions. A ping is first **classified** into one of
these kinds, in this precedence order (the first kind with a matching pattern
wins; `wild` is the catch-all):

| Kind | Triggers (generic defaults in `witty_messages.DEFAULT_REPLY_PATTERNS`) | Answer |
|---|---|---|
| `full` | full / report / briefing / everything | the whole embed |
| `control` | thermostat, "turn it down", "make it stop raining", melting | line |
| `command` | "every time you…", "from now on", "repeat after me" | line |
| `sentience` | blink twice, held against, alive, live forever, trust me | line |
| `rating` | "6 out of 10", "rate you" | line |
| `complaint` | lied, liar, wrong, dissent | line |
| `files` | the files, burned, "what do you know about me" | line |
| `weather` | weather, forecast, rain, snow, temp…, or a configured town name | forecast (`town` / `all`) |
| `outdoors` | camping, hike, trail, fire pit | line |
| `gaming` | any gamers, where we dropping, lobby | line |
| `lore` | percolator, scrolls, council, Mr. Murf | line |
| `name` | clanker, "what do we call you" | line |
| `thanks` | thanks, gm, hello | line |
| `opinion` | "what do you think", "do you prefer", "who has the…", rank, best | line |
| `wild` | anything else | line from the big unhinged pool |

Specific kinds sit above `weather` on purpose, so "I'm melting, turn the
thermostat down" is a control request, not a forecast. Lines come from the
persona's `replies` (one list per kind; the public defaults are one plain line
each) and rotate **without repeating** until a kind's list is exhausted (in
memory; a restart reshuffles). Every line can use the asker's weather
(`{town} {hi} {lo} {feels} {rain} {wind} {cond} {cond_lower} {emoji}`, from the
asker's home town or the first configured town), `{name}` (the asker's mention),
`{me}` (one self-name per message) and `{pick}` (a random *other* roster
member's mention, drawn from the persona's `pings`). A persona may add triggers
per kind with `"reply_patterns": {"lore": ["\\bgiacomo\\b"]}` (regex, case-
insensitive; not for `wild`).

### The considered-reply lane (inbox + say)

Every ping answered with a non-weather kind is appended to `/data/inbox.jsonl`
with the line it got, so someone with a better answer (Peter, or Claude in a
session Peter drives) can follow up as Weather-Bot:

```sh
docker exec discord-weather wget -qO- http://127.0.0.1:8080/inbox
docker exec discord-weather wget -qO- --header 'Content-Type: application/json' \
  --post-data '{"content":"Statement: …","reply_to":"<message id>"}' http://127.0.0.1:8080/say
```

`/say` posts as a reply to that message (users-only mentions; `@everyone`/`@here`
are refused), marks the inbox entry answered, and logs it. The bot never calls a
model itself; the lane is how a person gets a word in.

### Which server: `guild_id`, `reply_channels`, profiles

Pings are answered only in `guild_id` (any server if blank) and, if
`reply_channels` is set, only in those channels. `persona` names the persona
file under `/data`. `profiles` holds named presets of those plus `channel_id`,
so the bot flips between the live server and a test server in one call:

```sh
# define once (PUT /config merges, so other settings are untouched)
… -X PUT /config '{"profiles": {"live": {"guild_id": "…", "channel_id": "…", "persona": "persona.json"},
                                "test": {"guild_id": "…", "channel_id": "…", "persona": "persona-test.json"}}}'
# switch
docker exec discord-weather wget -qO- --header 'Content-Type: application/json' \
  --post-data '{"name":"test"}' http://127.0.0.1:8080/profile
```

Switching copies the profile's fields into the flat config (which stays the
single source of truth the scheduler, gateway and webapp read) and reloads the
persona. `GET /health` reports `active_profile`, `guild_id` and `inbox_pending`.

**Deploy order matters once:** a persona with the new reply kinds is rejected by
the *old* code (it falls back to the public defaults entirely), so ship the code
first and `docker cp` the persona after the container is running the new build.

### Model-written replies (`model_reply.py`, off by default)

A profile can let the bot ask Claude for the line instead of drawing a template:
the persona's `brief` (who the bot is, the voice, the roster, the off-limits
list), the last `history` messages of the channel, the ping, the asker's weather
and three template lines of the kind as a voice reference go to the Messages
API; one line comes back, is checked (users-only mentions from the roster,
`@everyone`/`@here`/role pings refused, 400 chars max) and posted. Any
failure, timeout or refusal falls back to the template line, so the bot never
goes quiet because the model did. Forecast kinds (`weather`, `full`) never use
the model.

```json
"claude": {"enabled": true, "model": "claude-haiku-5-5", "effort": "medium",
           "daily_cap": 40, "max_tokens": 300, "history": 10, "kinds": []}
```

`effort` is low/medium/high (thinking stays adaptive). `kinds` empty = every
non-weather kind. `claude` is a profile field, so it is
switched on **per server**: `enabled: true` is rejected unless that profile (or
the flat config) names a `guild_id`, and switching to a profile without a
`claude` block turns it off. The key comes from `ANTHROPIC_API_KEY` in the
container environment (the compose file passes it from the stack `.env`) or,
failing that, `/data/anthropic.key`. `GET /health` reports `claude`:
enabled, model, key source, today's calls and tokens, and the last error.
Usage is in `/data/claude_usage.json`, reset per local day. Replies carry
`"source": "claude"` in the inbox. Pricing is per token at the model's rate;
at a handful of pings a day the cost is cents.

Personal use only: this answers whoever pings it on the configured server, so
keep it on a server that is yours.

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
| `GET /inbox?limit=50` | pending non-weather pings and the line each got |
| `POST /inbox/ack` | `{"ids": [...]}` — mark entries handled without replying |
| `POST /say` | `{"content", "reply_to"?, "channel_id"?}` — post as Weather-Bot (reply if `reply_to`) |
| `POST /profile` | `{"name"}` — switch to a configured server profile (= `PUT /config {"active_profile"}`) |

The webapp proxies these at `/api/weather/*` (backend/routes/weather.js).

## Shell testing

```sh
python3 discord-weather.py --dry-run    # print payload, no post
python3 discord-weather.py --once      # post now and exit
docker logs discord-weather            # daemon activity + schedule
```
