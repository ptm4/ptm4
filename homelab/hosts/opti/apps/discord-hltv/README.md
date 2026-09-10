# discord-hltv — CS2 games of the day

Posts a "CS2 — Games of the Day" embed to a Discord webhook **several times a day**, and feeds
the dashboard's `cs2-matches` board widget. Managed from the webapp's Discord bots page
(`#hltv` tab) — don't edit files on the Pi to change behaviour.

Two containers:

| | |
|---|---|
| `discord-hltv` | scheduler, filtering, embed rendering, control API on `:8080` |
| `hltv-api` | **our own read-only HLTV.org API** (`hltv-api/`), driving a real browser |

## Source of truth: hltv.org, and only hltv.org

Matches, results, per-map scores, streams **and the ranking** all come from hltv.org.

The ranking is the **Valve Regional Standings** as HLTV publishes them at
`/valve-ranking/teams`. HLTV's *own* team ranking is deliberately never read — VRS is the
ranking this bot cares about.

### Why a browser

HLTV has no public API and Cloudflare 403s plain HTTP clients (curl, urllib). A real browser
passes without any interactive challenge, so `hltv-api` drives one with Playwright. Two facts
cost real time to discover, so don't undo them:

- **It must be the full Chromium build.** Playwright's `chromium-headless-shell` is stripped
  enough that Cloudflare serves it "Just a moment…" forever. The image installs Debian's
  `chromium` package (`CHROME_PATH=/usr/bin/chromium`), which is also the only option on arm64,
  where Playwright ships no browser at all. Headless itself is fine.
- **Wait for elements `state="attached"`, not visible.** `.match` rows sit in collapsed day
  sections and never become "visible".

A **persistent browser profile** lives on the `hltvapi_data` volume, so the Cloudflare clearance
cookie survives restarts and the service looks like one returning visitor. Pacing is
deliberately gentle: 3 scheduled scrapes a day, a 10-minute response cache, 2s between page
loads, at most `DETAIL_CAP` match-detail pages per scrape.

**The browser only runs during a scrape.** It is launched on demand and shut down as soon as
the job queue drains, because a resident Chromium is not free at idle: HLTV's ad and analytics
scripts keep executing after the DOM is parsed, and a browser left up held ~1.4 cores and
550 MB indefinitely on the Pi (measured 2026-08-12). Shutting it down leaves a ~6 MB Python
process between scrapes and costs ~3s of cold start on the next one — a trivial price at three
scrapes a day. Images are also disabled via `--blink-settings=imagesEnabled=false`; we only
read the DOM. Do **not** switch that to Playwright request interception: routing deadlocks the
sync API, and blocking third-party requests breaks the Cloudflare challenge.

**Interactive challenges are never solved automatically.** If one ever appears, the scrape
aborts, `/health` reports `challenge_detected`, and the digest fails loudly (see below). To
clear it by hand, run the container with `CHALLENGE_ASSIST=1` to get a headed browser, solve it
once, and unset the variable — the profile keeps the clearance.

## Schedule

`post_times` is a list, default `["00:00", "07:00", "18:00"]` (America/New_York). Midnight
previews the day, 07:00 picks up overnight results and the EU slate, 18:00 recaps and previews
the NA evening. The webapp field takes a comma-separated string; the bot canonicalizes it.

`/data/last_post` holds the latest completed slot as `YYYY-MM-DDTHH:MM`. Slots are totally
ordered and the format sorts lexicographically, so one marker means "everything up to here is
done". A pre-existing date-only stamp is read as `<date>T23:59` — that day counts as finished,
so upgrading never double-posts.

Only the **latest** due slot is caught up: posting every missed slot would just send the same
digest twice. A failed post retries every 15 minutes, and after 2 hours the webhook gets one
`⚠️` notice (`alert_on_failure`) — with a single source, an outage must not be silent.

## What a match line looks like

```
**7:30 PM** — [Spirit vs MOUZ](hltv) (BO3) · [📺 ESL TV](twitch)
**🔴 LIVE** — [BIG 1–0 Aurora](hltv) (BO1) · [📺 zur1s](kick)
✅ [**Mindfreak** 2–1 Rooster](hltv) — Inferno 13–9 · Anubis 6–13 · Mirage 13–10
```

Finished matches lead with the winner, and map scores are oriented winner-first. A match makes
the digest if either team is in the **VRS top N** (`vrs_top_n`, default 32) or HLTV rates it
`min_stars`+ (default 1; set 0 to disable).

The whole day goes in the embed description as one block — Discord puts vertical space around
every field, so a list split across fields reads as unrelated groups with gaps in it. Past the
description's 4096 characters it falls back to fields, chunked at 1024 each. Either way every
match is listed rather than trailing off in a "+N more", and lines are never cut mid-way: a
severed markdown link breaks the whole embed.

`DETAIL_CAP` (default 24) bounds how many match pages a scrape opens, and **only those matches
get a stream link and map scores** — set it below a day's notable-match count and the tail of
the digest quietly loses its streams.

### Which stream gets linked

**Only the tournament organizer's official broadcast, preferring its English feed.** A big
match carries 40+ stream boxes — watch parties, casters, personal channels — in no useful
order, and HLTV marks none of them "official" on the match page. Two signals identify the real
one:

1. **The channel name matches the event name** — "Esports World Cup" on
   `twitch.tv/EWC_plus_en` for *Esports World Cup 2026*. Digits are ignored so "CCT 3" still
   matches "CCT 2026 Europe Series 7", and generic words ("Open Qualifier") never match alone.
2. **HLTV's own classification.** The `/matches` sidebar tags each live channel
   `ORGANIZER` / `CASTER` / `STREAMER`; every scrape harvests the organizers into
   `/data/organizers.json`. That registry only grows, because an event's stream has to be
   recognisable hours before it goes on air, when it isn't live yet and so isn't in the sidebar.

English is preferred via the box's flag or an `_en` channel suffix, which also picks the right
one when an event runs two simultaneous English feeds (`EWC_plus_en` vs `EWC_Plus_EN2`).
**If no organizer stream is found, the line carries no link** rather than pointing at some
stranger's stream.

## Config (`/data/config.json`, in the `hltvbot_data` volume)

```json
{
  "enabled": true,
  "post_times": ["00:00", "07:00", "18:00"],
  "timezone": "America/New_York",
  "message": "",
  "webhook_url": "",
  "vrs_top_n": 32,
  "min_stars": 1,
  "post_when_empty": false,
  "alert_on_failure": true
}
```

Seeded from `DISCORD_WEBHOOK_URL_HLTV` on first boot. A blank or masked `webhook_url` in a PUT
means "keep the current one". Config changes take effect without a restart.

## APIs

`discord-hltv` `:8080` — proxied by the webapp at `/api/hltv/*`:

| | |
|---|---|
| `GET /health` | enabled, post_times, last/next post, last status |
| `GET /config` · `PUT /config` | webhook masked on read |
| `GET /preview` | the embed it would post now |
| `GET /day` | structured feed for the board widget (60s cache) |
| `GET /vrs` | VRS top N team names |
| `POST /send` | post now; never consumes a slot |

`hltv-api` `:8080` — internal only:

| | |
|---|---|
| `GET /day?date&tz&max_age` | normalized matches for a local day |
| `GET /vrs` | `{as_of, teams[{rank,name,points}]}`, cached 24h |
| `GET /selftest` | per-selector element counts — the DOM-drift alarm |
| `GET /health` | `last_success_at`, `last_error`, `challenge_detected` |

Both support CLI use: `python3 hltv_api.py --once|--vrs|--selftest`, and
`python3 discord-hltv.py --dry-run|--once`.

## When it breaks

1. `GET /api/hltv/status` → `last_status` says what failed.
2. `docker exec hltv-api python3 hltv_api.py --selftest` — if a selector count is 0, HLTV
   changed its markup and the extractors in `hltv_api.py` need updating.
3. `docker logs hltv-api` — `challenge_detected` means Cloudflare escalated; see CHALLENGE_ASSIST
   above.

A failed day scrape falls back to the last good snapshot for that date (`stale: true`), which
the digest and widget both label rather than hide.
