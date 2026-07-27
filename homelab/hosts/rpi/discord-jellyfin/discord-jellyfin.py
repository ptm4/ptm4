#!/usr/bin/env python3
"""
discord-jellyfin — daily "what landed in Jellyfin yesterday" digest posted to a
Discord channel webhook as an embed, with an HTTP control API for the rpi
webapp's "Jellyfin Bot" tab. Clone of discord-weather's scaffolding; only the
domain logic differs.

Queries the Jellyfin server on noblenumbat (X-Emby-Token auth) for items whose
DateCreated falls in yesterday (bot's timezone): movies listed individually,
episodes grouped by series.

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
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LAST_POST_PATH = os.path.join(DATA_DIR, "last_post")
API_PORT = 8080

EMBED_COLOR = 0x9B59B6  # jellyfin purple
FETCH_LIMIT = 200  # newest items pulled per run; filtered to yesterday client-side

DEFAULT_CONFIG = {
    "enabled": True,
    "post_time": "09:00",
    "timezone": "America/New_York",
    "message": "",  # plain-text content sent above the embed
    "webhook_url": "",  # seeded from DISCORD_WEBHOOK_URL_JELLYFIN env on first boot
    "jellyfin_url": "http://192.168.1.6:8096",
    "api_key": "",  # seeded from JELLYFIN_API_KEY env on first boot
    "max_items": 12,
    "post_when_empty": False,  # False → quiet day is skipped; True → "Nothing new" embed
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
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL_JELLYFIN", "")
        cfg["api_key"] = os.environ.get("JELLYFIN_API_KEY", "")
        save_config(cfg)
        log(f"seeded default config at {CONFIG_PATH}")
    # env secrets as fallback if config never got them
    if not cfg.get("webhook_url"):
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL_JELLYFIN", "")
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("JELLYFIN_API_KEY", "")
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
    if not str(cfg.get("jellyfin_url", "")).startswith(("http://", "https://")):
        return "jellyfin_url must be an http(s) URL"
    n = cfg.get("max_items")
    if not isinstance(n, int) or not 1 <= n <= 25:
        return "max_items must be 1–25"
    if not isinstance(cfg.get("post_when_empty"), bool):
        return "post_when_empty must be true/false"
    url = cfg.get("webhook_url", "")
    if url and not url.startswith("https://discord.com/api/webhooks/"):
        return "webhook_url must start with https://discord.com/api/webhooks/"
    return None


def mask_webhook(url):
    return f"https://discord.com/api/webhooks/…{url[-6:]}" if url else ""


# ── HTTP helper ───────────────────────────────────────────────────────────────
def http_json(url, body=None, tries=3, headers=None, timeout=30):
    for attempt in range(tries):
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     "User-Agent": "discord-jellyfin (rpi homelab)",
                     **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw.strip() else None)
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"{url.split('?')[0]} failed: {e}") from e
            time.sleep(5)


# ── jellyfin ──────────────────────────────────────────────────────────────────
def jf_get(cfg, path_qs, timeout=20):
    if not cfg.get("api_key"):
        raise RuntimeError("api_key not set — mint one in the Jellyfin dashboard")
    _, d = http_json(f"{cfg['jellyfin_url'].rstrip('/')}{path_qs}",
                     headers={"X-Emby-Token": cfg["api_key"]}, tries=2, timeout=timeout)
    return d


def parse_created(iso):
    """Jellyfin DateCreated is UTC with 7-digit fractional seconds, which
    fromisoformat rejects — parse just the seconds-resolution prefix."""
    return datetime.fromisoformat(iso[:19]).replace(tzinfo=timezone.utc)


def fetch_arrivals(cfg):
    """Items whose DateCreated falls within yesterday in the bot's timezone.
    Returns (movies, episodes): movies as [{name, year}], episodes as
    [{series, season, episode, name}]."""
    tz = ZoneInfo(cfg["timezone"])
    today_local = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_local - timedelta(days=1)
    qs = urllib.parse.urlencode({
        "IncludeItemTypes": "Movie,Episode", "Recursive": "true",
        "SortBy": "DateCreated", "SortOrder": "Descending", "Limit": FETCH_LIMIT,
        "Fields": "DateCreated,SeriesName,ProductionYear,ParentIndexNumber,IndexNumber",
    })
    d = jf_get(cfg, f"/Items?{qs}") or {}
    movies, episodes = [], []
    for it in d.get("Items", []):
        try:
            created = parse_created(it["DateCreated"]).astimezone(tz)
        except (KeyError, ValueError, TypeError):
            continue
        if not start <= created < today_local:
            continue
        if it.get("Type") == "Movie":
            movies.append({"name": it.get("Name", "?"), "year": it.get("ProductionYear")})
        elif it.get("Type") == "Episode":
            episodes.append({"series": it.get("SeriesName") or "Unknown series",
                             "season": it.get("ParentIndexNumber"),
                             "episode": it.get("IndexNumber"),
                             "name": it.get("Name", "?")})
    return movies, episodes


def sxxeyy(ep):
    if ep["season"] is None or ep["episode"] is None:
        return ep["name"]
    return f"S{ep['season']:02d}E{ep['episode']:02d}"


def build_payload(cfg):
    """Fetch yesterday's arrivals and build the webhook payload.
    Returns (payload, failed_sections, has_items)."""
    tz = ZoneInfo(cfg["timezone"])
    yesterday = datetime.now(tz) - timedelta(days=1)
    date_str = yesterday.strftime("%A, %B %d").replace(" 0", " ")

    failed = []
    movies, episodes = [], []
    try:
        movies, episodes = fetch_arrivals(cfg)
    except Exception as e:
        log(f"arrivals fetch failed: {e}")
        failed.append("Jellyfin")

    budget = cfg["max_items"]
    fields = []

    if movies:
        shown = movies[:budget]
        lines = [f"• **{m['name']}**{f' ({m['year']})' if m['year'] else ''}" for m in shown]
        if len(movies) > len(shown):
            lines.append(f"…and {len(movies) - len(shown)} more")
        budget -= len(shown)
        fields.append({"name": "🎥 Movies", "value": "\n".join(lines)[:1024], "inline": False})

    if episodes:
        by_series = {}
        for ep in episodes:
            by_series.setdefault(ep["series"], []).append(ep)
        lines, shown_series = [], 0
        for series, eps in by_series.items():
            if shown_series >= max(budget, 0):
                break
            shown_series += 1
            if len(eps) == 1:
                lines.append(f"• **{series}** — {sxxeyy(eps[0])}")
            elif len(eps) <= 3:
                lines.append(f"• **{series}** — {', '.join(sxxeyy(e) for e in eps)}")
            else:
                lines.append(f"• {len(eps)} episodes of **{series}**")
        if len(by_series) > shown_series:
            lines.append(f"…and {len(by_series) - shown_series} more series")
        fields.append({"name": "📺 TV", "value": "\n".join(lines)[:1024], "inline": False})

    has_items = bool(movies or episodes)
    if failed:
        desc = "⚠️ Jellyfin unreachable — no arrivals data"
    elif not has_items:
        desc = "Nothing new landed yesterday."
    else:
        n_ep = len(episodes)
        bits = []
        if movies:
            bits.append(f"{len(movies)} movie{'s' if len(movies) != 1 else ''}")
        if n_ep:
            bits.append(f"{n_ep} episode{'s' if n_ep != 1 else ''}")
        desc = " · ".join(bits)

    payload = {
        "username": "Jellyfin Arrivals",
        "allowed_mentions": {"parse": ["everyone", "roles", "users"]},
        "embeds": [{
            "title": f"🎬 New in Jellyfin — {date_str}",
            "description": desc,
            "color": EMBED_COLOR,
            "fields": fields,
            "footer": {"text": "Jellyfin · noblenumbat"},
        }],
    }
    if cfg.get("message"):
        payload["content"] = cfg["message"]
    return payload, failed, has_items


def post_webhook(url, payload):
    status, _ = http_json(url, body=payload)
    if not 200 <= status < 300:
        raise RuntimeError(f"webhook returned HTTP {status}")


def post_report(cfg, force=False):
    """Build and post the report. Returns (ok, detail). Scheduled runs
    (force=False) skip empty days unless post_when_empty; Send-now always posts."""
    payload, failed, has_items = build_payload(cfg)
    if failed:
        return False, "Jellyfin unreachable"
    if not force and not has_items and not cfg.get("post_when_empty"):
        return True, "skipped — nothing new yesterday"
    url = cfg.get("webhook_url")
    if not url:
        return False, "DISCORD_WEBHOOK_URL_JELLYFIN / webhook_url not set"
    try:
        post_webhook(url, payload)
    except RuntimeError as e:
        return False, str(e)
    return True, "posted"


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
CONFIG_KEYS = ("enabled", "post_time", "timezone", "message", "webhook_url",
               "jellyfin_url", "api_key", "max_items", "post_when_empty")


def public_config(cfg):
    pub = dict(cfg)
    pub["webhook_url"] = mask_webhook(cfg.get("webhook_url", ""))
    pub["webhook_configured"] = bool(cfg.get("webhook_url"))
    pub["api_key"] = ""
    pub["api_key_configured"] = bool(cfg.get("api_key"))
    return pub


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
        path, _, _query = self.path.partition("?")
        cfg = load_config()
        if path == "/health":
            with _lock:
                st = dict(_status)
            self._send(200, {"ok": True, "enabled": cfg["enabled"],
                             "post_time": cfg["post_time"], "timezone": cfg["timezone"], **st})
        elif path == "/config":
            self._send(200, public_config(cfg))
        elif path == "/preview":
            try:
                payload, failed, has_items = build_payload(cfg)
                self._send(200, {"payload": payload, "failed": failed, "has_items": has_items})
            except Exception as e:
                self._send(502, {"error": str(e)})
        elif path == "/check":
            try:
                d = jf_get(cfg, "/System/Info", timeout=10) or {}
                self._send(200, {"ok": True, "server_name": d.get("ServerName"),
                                 "version": d.get("Version")})
            except Exception as e:
                self._send(502, {"ok": False, "error": str(e)})
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
        merged = {**current, **{k: v for k, v in incoming.items() if k in CONFIG_KEYS}}
        # masked/blank secrets in the payload mean "keep the current one"
        wh = incoming.get("webhook_url", "")
        if not wh or "…" in wh:
            merged["webhook_url"] = current.get("webhook_url", "")
        if not incoming.get("api_key"):
            merged["api_key"] = current.get("api_key", "")
        err = validate_config(merged)
        if err:
            return self._send(400, {"error": err})
        with _lock:
            save_config(merged)
        _wake.set()  # reschedule immediately
        log(f"config updated: enabled={merged['enabled']} post_time={merged['post_time']} "
            f"max_items={merged['max_items']} post_when_empty={merged['post_when_empty']}")
        self._send(200, public_config(merged))

    def do_POST(self):
        if self.path.partition("?")[0] != "/send":
            return self._send(404, {"error": "not found"})
        cfg = load_config()
        ok, detail = post_report(cfg, force=True)
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
            cfg = {**DEFAULT_CONFIG,
                   "webhook_url": os.environ.get("DISCORD_WEBHOOK_URL_JELLYFIN", ""),
                   "api_key": os.environ.get("JELLYFIN_API_KEY", "")}
        if "--dry-run" in argv:
            payload, failed, has_items = build_payload(cfg)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            print(f"has_items: {has_items}", file=sys.stderr)
            if failed:
                print(f"WARNING: no data for {failed}", file=sys.stderr)
                return 1
            return 0
        ok, detail = post_report(cfg, force=True)
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
