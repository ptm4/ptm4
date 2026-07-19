#!/usr/bin/env python3
"""
discord-sports — daily scores & schedule for your teams posted to a Discord
channel webhook as an embed, with an HTTP control API for the rpi webapp's
"Sports Bot" tab. Clone of discord-weather's scaffolding; only the domain
logic differs.

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
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LAST_POST_PATH = os.path.join(DATA_DIR, "last_post")
API_PORT = 8080

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
EMBED_COLOR = 0xE67E22  # orange

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
        {"league": "nba", "sport": "basketball", "id": "20",
         "abbrev": "NY", "name": "New York Knicks"},
    ],
}


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


# ── config store ──────────────────────────────────────────────────────────────
_lock = threading.Lock()
_wake = threading.Event()   # poked on config change so the scheduler recomputes
_status = {"last_post_at": None, "last_status": None, "next_post_at": None}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = dict(DEFAULT_CONFIG)
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL_SPORTS", "")
        save_config(cfg)
        log(f"seeded default config at {CONFIG_PATH}")
    # env webhook as fallback if config never got one
    if not cfg.get("webhook_url"):
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL_SPORTS", "")
    # configs written before a key existed pick up its default
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def validate_config(cfg):
    """Returns an error string, or None if cfg is a valid full config."""
    if not isinstance(cfg, dict):
        return "config must be an object"
    if not isinstance(cfg.get("enabled"), bool):
        return "enabled must be true/false"
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(cfg.get("post_time", ""))):
        return "post_time must be HH:MM (24h)"
    msg = cfg.get("message", "")
    if not isinstance(msg, str) or len(msg) > 2000:
        return "message must be text, max 2000 characters"
    try:
        ZoneInfo(str(cfg.get("timezone")))
    except Exception:
        return f"unknown timezone {cfg.get('timezone')!r}"
    teams = cfg.get("teams")
    if not isinstance(teams, list):
        return "teams must be a list"
    for t in teams:
        if not (isinstance(t, dict) and t.get("id") and t.get("name")
                and t.get("league") in LEAGUES):
            return f"each team needs league ({'/'.join(LEAGUES)}), id, name"
    url = cfg.get("webhook_url", "")
    if url and not url.startswith("https://discord.com/api/webhooks/"):
        return "webhook_url must start with https://discord.com/api/webhooks/"
    return None


def mask_webhook(url):
    return f"https://discord.com/api/webhooks/…{url[-6:]}" if url else ""


# ── HTTP + ESPN ───────────────────────────────────────────────────────────────
def http_json(url, body=None, tries=3, timeout=30):
    for attempt in range(tries):
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     "User-Agent": "discord-sports (rpi homelab)"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw.strip() else None)
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"{url.split('?')[0]} failed: {e}") from e
            time.sleep(5)


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


def post_webhook(url, payload):
    status, _ = http_json(url, body=payload)
    if not 200 <= status < 300:
        raise RuntimeError(f"webhook returned HTTP {status}")


def post_report(cfg):
    """Build and post the report. Returns (ok, detail)."""
    payload, failed = build_payload(cfg)
    url = cfg.get("webhook_url")
    if not url:
        return False, "DISCORD_WEBHOOK_URL_SPORTS / webhook_url not set"
    try:
        post_webhook(url, payload)
    except RuntimeError as e:
        return False, str(e)
    detail = "posted" + (f" (no data for: {', '.join(failed)})" if failed else "")
    return True, detail


# ── scheduler ─────────────────────────────────────────────────────────────────
def read_last_post():
    try:
        with open(LAST_POST_PATH) as f:
            return f.read().strip()
    except OSError:
        return ""


def write_last_post(date_str):
    tmp = LAST_POST_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(date_str)
    os.replace(tmp, LAST_POST_PATH)


def next_post_dt(cfg, now):
    """Next scheduled datetime strictly after `now` (tz-aware)."""
    hh, mm = map(int, cfg["post_time"].split(":"))
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def scheduled_post(cfg, today_str):
    _retry.update(date=today_str, at=datetime.now(ZoneInfo(cfg["timezone"])))
    ok, detail = post_report(cfg)
    with _lock:
        _status["last_post_at"] = datetime.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds")
        _status["last_status"] = detail if ok else f"failed: {detail}"
    if ok:
        write_last_post(today_str)
    log(f"daily post: {'ok — ' + detail if ok else 'FAILED — ' + detail}")


RETRY_INTERVAL = 900  # a failed daily post is re-attempted every 15 min until it lands
_retry = {"date": None, "at": None}


def scheduler_loop():
    while True:
        cfg = load_config()
        tz = ZoneInfo(cfg["timezone"])
        now = datetime.now(tz)
        today = now.date().isoformat()

        if not cfg["enabled"]:
            with _lock:
                _status["next_post_at"] = None
            _wake.wait(timeout=3600)
            _wake.clear()
            continue

        # catch-up / retry: today's post is due but hasn't landed yet
        hh, mm = map(int, cfg["post_time"].split(":"))
        todays_slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now >= todays_slot and read_last_post() != today:
            if _retry["date"] == today:
                since = (now - _retry["at"]).total_seconds()
                if since < RETRY_INTERVAL:  # pace re-attempts after a failure
                    next_try = _retry["at"] + timedelta(seconds=RETRY_INTERVAL)
                    with _lock:
                        _status["next_post_at"] = next_try.isoformat(timespec="seconds")
                    if _wake.wait(timeout=RETRY_INTERVAL - since):
                        _wake.clear()
                    continue
                log(f"retrying today's post (last attempt {round(since / 60)} min ago)")
            else:
                log(f"catch-up: {today} {cfg['post_time']} is due, posting now")
            scheduled_post(cfg, today)
            continue

        nxt = next_post_dt(cfg, now)
        with _lock:
            _status["next_post_at"] = nxt.isoformat(timespec="seconds")
        wait = (nxt - now).total_seconds()
        if _wake.wait(timeout=min(wait, 3600)):
            _wake.clear()
            continue  # config changed — recompute
        if datetime.now(tz) >= nxt:
            scheduled_post(load_config(), nxt.date().isoformat())


# ── control API ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # route access logs through our logger
        log(f"api {self.command} {self.path} — {args[0] if args else ''}")

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        path, _, query = self.path.partition("?")
        cfg = load_config()
        if path == "/health":
            with _lock:
                st = dict(_status)
            self._send(200, {"ok": True, "enabled": cfg["enabled"],
                             "post_time": cfg["post_time"], "timezone": cfg["timezone"], **st})
        elif path == "/config":
            pub = dict(cfg)
            pub["webhook_url"] = mask_webhook(cfg.get("webhook_url", ""))
            pub["webhook_configured"] = bool(cfg.get("webhook_url"))
            self._send(200, pub)
        elif path == "/preview":
            try:
                payload, failed = build_payload(cfg)
                self._send(200, {"payload": payload, "failed": failed})
            except Exception as e:
                self._send(502, {"error": str(e)})
        elif path == "/teams":
            qs = urllib.parse.parse_qs(query)
            league = (qs.get("league", [""])[0] or "").strip().lower()
            q = (qs.get("q", [""])[0] or "").strip().lower()
            if league not in LEAGUES:
                return self._send(400, {"error": f"league must be one of {'/'.join(LEAGUES)}"})
            if not q:
                return self._send(400, {"error": "missing ?q="})
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
                self._send(200, {"results": results[:10]})
            except Exception as e:
                self._send(502, {"error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def do_PUT(self):
        if self.path.partition("?")[0] != "/config":
            return self._send(404, {"error": "not found"})
        try:
            incoming = self._body()
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        current = load_config()
        merged = {**current, **{k: v for k, v in incoming.items()
                                if k in ("enabled", "post_time", "timezone", "teams", "webhook_url", "message")}}
        # masked/blank webhook in the payload means "keep the current one"
        wh = incoming.get("webhook_url", "")
        if not wh or "…" in wh:
            merged["webhook_url"] = current.get("webhook_url", "")
        err = validate_config(merged)
        if err:
            return self._send(400, {"error": err})
        with _lock:
            save_config(merged)
        _wake.set()  # reschedule immediately
        log(f"config updated: enabled={merged['enabled']} post_time={merged['post_time']} "
            f"teams={[t['name'] for t in merged['teams']]}")
        pub = dict(merged)
        pub["webhook_url"] = mask_webhook(merged.get("webhook_url", ""))
        pub["webhook_configured"] = bool(merged.get("webhook_url"))
        self._send(200, pub)

    def do_POST(self):
        if self.path.partition("?")[0] != "/send":
            return self._send(404, {"error": "not found"})
        cfg = load_config()
        ok, detail = post_report(cfg)
        with _lock:
            _status["last_post_at"] = datetime.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds")
            _status["last_status"] = f"manual: {detail}" if ok else f"manual failed: {detail}"
        log(f"manual send: {'ok — ' + detail if ok else 'FAILED — ' + detail}")
        self._send(200 if ok else 502, {"ok": ok, "detail": detail})


def main(argv):
    if "--dry-run" in argv or "--once" in argv:
        try:
            cfg = load_config()
        except OSError:  # DATA_DIR not writable (e.g. running outside the container)
            cfg = {**DEFAULT_CONFIG, "webhook_url": os.environ.get("DISCORD_WEBHOOK_URL_SPORTS", "")}
        if "--dry-run" in argv:
            payload, failed = build_payload(cfg)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if failed:
                print(f"WARNING: no data for {failed}", file=sys.stderr)
                return 1
            return 0
        ok, detail = post_report(cfg)
        print(detail)
        return 0 if ok else 1

    # daemon: control API thread + scheduler in main thread
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"control API listening on :{API_PORT}")
    load_config()  # seed on first boot
    scheduler_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
