#!/usr/bin/env python3
"""
discord-sports — daily scores & schedule for your teams posted to a Discord
channel webhook as an embed, with an HTTP control API for the webapp's
"Sports Bot" tab. The scaffolding (config store, daily scheduler, control API,
post-with-retry) comes from ../_botkit; this file is only the domain logic.

Data: ESPN's public site API (keyless, unofficial — parsed defensively):
yesterday's result + today's game per configured team, one scoreboard fetch
per league per day.

Config lives in /data/config.json (named volume, seeded from env on first
boot); the webapp edits it via the API — the scheduler picks changes up
immediately, no restart needed.

Modes:
  (default)   daemon: scheduler loop + control API on :8080
  --once      build + post the report now, then exit
  --dry-run   build + print the payload, no post, then exit
"""
import os
import sys
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# In the image _botkit sits next to this file (/app/_botkit); in the repo it is one up.
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _botkit import Bot, http_json, log, post_webhook  # noqa: E402

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
EMBED_COLOR = 0xE67E22  # orange
# Discord's Cloudflare 403s urllib's default UA; ESPN 403s custom ones (see _botkit/net.py).
DISCORD_UA = "discord-sports (rpi homelab)"

# league slug → sport slug (ESPN URL path is /sports/{sport}/{league}/…).
# NBA only by design; add e.g. "nfl": "football" here (and in the frontend's
# SPORTS_LEAGUES) to widen.
LEAGUES = {"nba": "basketball"}
LEAGUE_EMOJI = {"nba": "🏀"}

DEFAULT_CONFIG = {
    "enabled": True,
    "post_time": "09:30",
    "timezone": "America/New_York",
    "message": "",  # plain-text content sent above the embed
    "webhook_url": "",  # seeded from DISCORD_WEBHOOK_URL_SPORTS env on first boot
    "teams": [
        # ESPN team id 18 = Knicks (20 is the 76ers — the old default had that wrong).
        {"league": "nba", "sport": "basketball", "id": "18",
         "abbrev": "NY", "name": "New York Knicks"},
    ],
}


def validate_teams(cfg):
    teams = cfg.get("teams")
    if not isinstance(teams, list):
        return "teams must be a list"
    for t in teams:
        if not (isinstance(t, dict) and t.get("id") and t.get("name")
                and t.get("league") in LEAGUES):
            return f"each team needs league ({'/'.join(LEAGUES)}), id, name"
    return None


# ── ESPN ──────────────────────────────────────────────────────────────────────
def fetch_scoreboard(league, yyyymmdd):
    sport = LEAGUES[league]
    _, d = http_json(f"{ESPN_BASE}/{sport}/{league}/scoreboard?dates={yyyymmdd}",
                     tries=2, timeout=20)
    return (d or {}).get("events", [])


def clock_str(iso, tz):
    """'2026-07-17T17:35Z' -> '1:35 PM' in tz (no %-I: not portable to musl)."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo(tz))
        return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    except (ValueError, TypeError, AttributeError):
        return "?"


def team_event(events, team_id):
    """The event (game) featuring team_id, with our/their competitor split.
    Returns (event, competition, ours, theirs) or None."""
    for e in events:
        for comp in e.get("competitions", []):
            competitors = comp.get("competitors", [])
            ours = next((c for c in competitors
                         if str((c.get("team") or {}).get("id")) == str(team_id)), None)
            if ours is None:
                continue
            theirs = next((c for c in competitors if c is not ours), {})
            return e, comp, ours, theirs
    return None


def opp_str(ours, theirs):
    opp = (theirs.get("team") or {}).get("abbreviation", "?")
    return f"vs {opp}" if ours.get("homeAway") == "home" else f"@ {opp}"


def result_line(events, team_id):
    """Yesterday: 'W 10–0 vs TB (Final)' / 'no game'."""
    hit = team_event(events, team_id)
    if hit is None:
        return "yesterday: no game"
    _, comp, ours, theirs = hit
    state = ((comp.get("status") or {}).get("type") or {}).get("state")
    detail = ((comp.get("status") or {}).get("type") or {}).get("shortDetail", "")
    if state != "post":
        return f"yesterday: {detail or 'not final'}"
    wl = "W" if ours.get("winner") else ("L" if theirs.get("winner") else "T")
    return f"yesterday: **{wl} {ours.get('score', '?')}–{theirs.get('score', '?')}** {opp_str(ours, theirs)}"


def schedule_line(events, team_id, tz):
    """Today: '7:30 PM vs MIA' / 'LIVE 45–39 @ BOS' / 'no game'."""
    hit = team_event(events, team_id)
    if hit is None:
        return "today: no game"
    e, comp, ours, theirs = hit
    state = ((comp.get("status") or {}).get("type") or {}).get("state")
    if state == "in":
        return f"today: **LIVE {ours.get('score', '?')}–{theirs.get('score', '?')}** {opp_str(ours, theirs)}"
    if state == "post":
        wl = "W" if ours.get("winner") else ("L" if theirs.get("winner") else "T")
        return f"today: **{wl} {ours.get('score', '?')}–{theirs.get('score', '?')}** {opp_str(ours, theirs)} (early game)"
    return f"today: {clock_str(e.get('date', ''), tz)} {opp_str(ours, theirs)}"


SPACER_FIELD = {"name": "​", "value": "​", "inline": True}  # forces 2-per-row grid


def build_payload(cfg):
    """Fetch scoreboards and build the webhook payload.
    Returns (payload, failed_names)."""
    tz = cfg["timezone"]
    now = datetime.now(ZoneInfo(tz))
    today_key = now.strftime("%Y%m%d")
    yday_key = (now - timedelta(days=1)).strftime("%Y%m%d")

    # one scoreboard fetch per league per day, shared across teams
    boards = {}

    def board(league, datekey):
        if (league, datekey) not in boards:
            boards[(league, datekey)] = fetch_scoreboard(league, datekey)
        return boards[(league, datekey)]

    fields, failed = [], []
    for t in cfg["teams"]:
        emoji = LEAGUE_EMOJI.get(t["league"], "🏟️")
        name = f"{emoji} {(t.get('abbrev') or t['name']).upper()}"
        try:
            lines = [result_line(board(t["league"], yday_key), t["id"]),
                     schedule_line(board(t["league"], today_key), t["id"], tz)]
            fields.append({"name": name, "value": "\n".join(lines), "inline": True})
        except Exception as e:
            log(f"scoreboard failed for {t['name']}: {e}")
            fields.append({"name": name, "value": "⚠️ data unavailable", "inline": True})
            failed.append(t["name"])

    # Same 2-per-row spacer trick as discord-weather: pad every row to 3 slots.
    spaced = []
    for i in range(0, len(fields), 2):
        pair = fields[i:i + 2]
        spaced.extend(pair)
        spaced.extend(dict(SPACER_FIELD) for _ in range(3 - len(pair)))

    date_str = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    payload = {
        "username": "Daily Sports Report",
        "allowed_mentions": {"parse": ["everyone", "roles", "users"]},
        "embeds": [{
            "title": "🏟️ Scores & Schedule",
            "description": f"**{date_str}**",
            "color": EMBED_COLOR,
            "fields": spaced or [{"name": "No teams configured",
                                  "value": "Add teams in the webapp's Sports Bot tab.",
                                  "inline": False}],
            "footer": {"text": "ESPN"},
        }],
    }
    if cfg.get("message"):
        payload["content"] = cfg["message"]
    return payload, failed


def preview(cfg):
    payload, failed = build_payload(cfg)
    return {"payload": payload, "failed": failed}


def post_report(cfg, force=False):
    """Build and post the report. Returns (ok, detail). Every run posts, so the
    scheduled and Send-now paths are the same (force is unused)."""
    payload, failed = build_payload(cfg)
    url = cfg.get("webhook_url")
    if not url:
        return False, "DISCORD_WEBHOOK_URL_SPORTS / webhook_url not set"
    try:
        post_webhook(url, payload, ua=DISCORD_UA)
    except RuntimeError as e:
        return False, str(e)
    detail = "posted" + (f" (no data for: {', '.join(failed)})" if failed else "")
    return True, detail


# ── control API extra: team search ────────────────────────────────────────────
def teams_route(cfg, query):
    """GET /teams?league=nba&q=knicks — the tab's team picker."""
    qs = urllib.parse.parse_qs(query)
    league = (qs.get("league", [""])[0] or "").strip().lower()
    q = (qs.get("q", [""])[0] or "").strip().lower()
    if league not in LEAGUES:
        return 400, {"error": f"league must be one of {'/'.join(LEAGUES)}"}
    if not q:
        return 400, {"error": "missing ?q="}
    try:
        _, d = http_json(f"{ESPN_BASE}/{LEAGUES[league]}/{league}/teams", tries=2, timeout=20)
        teams = ((d or {}).get("sports") or [{}])[0].get("leagues", [{}])[0].get("teams", [])
        results = []
        for t in teams:
            tt = t.get("team") or {}
            hay = f"{tt.get('displayName', '')} {tt.get('abbreviation', '')}".lower()
            if q in hay:
                results.append({"league": league, "sport": LEAGUES[league],
                                "id": str(tt.get("id", "")),
                                "abbrev": tt.get("abbreviation", ""),
                                "name": tt.get("displayName", "")})
        return 200, {"results": results[:10]}
    except Exception as e:
        return 502, {"error": str(e)}


bot = Bot(
    name="discord-sports",
    defaults=DEFAULT_CONFIG,
    env={"webhook_url": "DISCORD_WEBHOOK_URL_SPORTS"},
    extra_keys=("teams",),
    validate=validate_teams,
    post_report=post_report,
    preview=preview,
    routes={"/teams": teams_route},
    describe=lambda cfg: f"teams={[t['name'] for t in cfg['teams']]}",
)
Handler = bot.Handler
load_config = bot.load_config

if __name__ == "__main__":
    sys.exit(bot.main(sys.argv[1:]))
