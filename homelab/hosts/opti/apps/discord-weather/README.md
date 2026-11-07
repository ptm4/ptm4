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

**No longer posted.** Every line WB says is written by the model (see
*Answering pings*); the morning post carries the model's line under `message`,
or no line at all. The template pool below is kept only for its weather
history (`weather_days`), which feeds the morning line's "weather story"
(streaks, swings), and for `GET /witty`. The rest of this section describes the
pool as it was.

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

A ping (mention, the bot's role, or a reply to it) is one of three things:

| Kind | When | Answer |
|---|---|---|
| `full` | "full report", "full briefing", "morning briefing" | the briefing card, with a model-written line |
| `weather` | an explicit ask: "weather report", "tell me my weather", "what's the weather", "weather in Hicksville", a bare "weather?" | a model reply with that town's numbers (the town named, else the asker's home, else every town) |
| `chat` | everything else, including a town name or "rain" on its own | a model reply with no forecast data |

There are no template answers. If the model can't be reached, a weather ask
gets the plain numbers and anything else gets a 💤 reaction. Patterns live in
`witty_messages.DEFAULT_REPLY_PATTERNS`; a persona can't widen the two forecast
kinds.

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

### WB: model-written replies and memory (`model_reply.py`, `wbdb.py`)

Every reply is one Messages API call to Claude Haiku 5.5. WB has no
hand-written personality: it starts from a short seed (`model_reply.SEED_BRIEF`,
or the persona's `brief` if one is set) and grows its own notes. The prompt
holds, in order:

- system: the seed, the rules, the roster, WB's notes on itself, on the group,
  and on the asker and anyone mentioned
- user: the last `history` messages of the channel, WB's last 5 replies (so it
  doesn't repeat itself), the weather numbers for a weather ask, the message
  being replied to, and **the message itself, last**

The rules say: answer what was said first, with the humor inside the answer;
most replies need no callback; mention people only by roster handle; no weather
without numbers; jokes are fine but made-up records presented as real are not;
the off-limits list. The reply is checked (users-only mentions from the roster,
`@everyone`/`@here`/role pings refused, 900 chars max) and posted.

```json
"claude": {"enabled": true, "model": "claude-haiku-5-5", "effort": "medium",
           "daily_cap": 150, "daily_tokens": 1500000, "max_tokens": 4096, "history": 15,
           "morning": true, "morning_effort": "medium", "morning_history": 150,
           "memory": true, "memory_skip_channels": []}
```

`effort` is low/medium/high (thinking stays adaptive; `max_tokens` covers the
thinking too, so keep it well above the reply).

**Limits.** When today's budget is spent (`daily_cap` calls or `daily_tokens`
tokens, local day; `daily_tokens: 0` = no token cap) or the API says the credit
is gone or rate-limits it, WB stops calling the model until tomorrow and posts
one of the "out of words" lines it wrote the night before. Someone pinging again
inside the 8 s cooldown gets one "slow down" line, then silence for 10 minutes.
Before the first night's learning there are no such lines, and WB reacts 💤
instead.

**Morning line.** With `morning: true` the line under `@everyone` is written by
the model from every message since the last posted morning line (REST, per
channel cursor in `/data/chat_cursor.json`, moved only once a post lands),
today's weather, the weather story and WB's notes. The day's line is kept as a
draft so retries re-post it. No line if the model is off or fails.

**Memory: WBdb (`memory: true`).** `/data/wb.sqlite` on opti's ZFS pool. WB reads
every text channel in the server (minus `memory_skip_channels` and any that
answer 403) forward from the moment it first sees each one; there is no history
import. Every night after 3 AM it has the model update:

- each person's notes from what they said that day, what they asked WB, and the
  reactions to WB's answers (people with fewer than 3 messages and no pings are
  skipped that night)
- the group's notes (lore, running bits, plans, what they ask)
- its own notes (the voice the group seems to like, what landed, what flopped)
- its "out of words" and "slow down" lines, in its current voice

The notes start from a private seed, `/data/wb_seed.json`
(`{"group", "self", "people": {"<user id>": {"handle", "notes"}}}`, loaded once;
built from `private/PROFILES.md`). Learning leaves 50 calls and a third of
`daily_tokens` for pings, and only marks what it got through, so a cut-short
night resumes the next. Learned messages are dropped after 30 days; the notes
stay. Reactions on WB's replies are counted live.

**Forgetting.** The private persona's `"forget": {"terms": [...], "user_ids":
[...]}` lists what the bot must act as if it never saw. A message naming a term,
written by that user or @mentioning them is never stored, and is purged if it
was; note lines and ready-made lines naming a term are dropped; a ping naming
one reaches the model as `[removed]`; a reply that names one isn't sent. Terms
match whole words in any case. The list stays in the persona because the repo
is public.

**Reliability.** One connection behind a lock, batches in one transaction,
`PRAGMA quick_check` at open (a bad file is set aside and replaced by an empty
one), and a nightly `VACUUM INTO` copy to `/backup`, which compose binds to
`/srv/red/fs/ptm/wbdb/backup` (7 kept, `wb-<date>.sqlite`) so the weekly cold
copy takes it. If WBdb can't serve a reply, the reply goes without notes.

`claude` is a profile field, so it is switched on **per server**: `enabled:
true` is rejected unless that profile (or the flat config) names a `guild_id`,
and switching to a profile without a `claude` block turns it off. The key comes
from `ANTHROPIC_API_KEY` (the compose file passes it from the stack `.env`) or
`/data/anthropic.key`. Usage is in `/data/claude_usage.json`, reset per local
day. Cost on Haiku 5.5 ($0.10 in / $0.50 out per million tokens): a replay of 15
real pings averaged about 3,300 input and 450 output tokens a reply, about
$0.0005 each; the nightly learning is about 10 calls. The Max plan's monthly API
credit covers that many times over; see
https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers.

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
| `GET /inbox?limit=50` | pending chat pings and the reply each got |
| `GET /profiles` | WBdb counts and every profile (people, `group`, `self`) |
| `PUT /profiles` | `{"subject", "notes", "handle"?}`: hand-edit one profile |
| `POST /memory/reset` | forget everything WB learned; the seed loads again |
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
