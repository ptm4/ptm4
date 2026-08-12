#!/usr/bin/env python3
"""
discord-hltv — "CS2 games of the day" posted to a Discord channel webhook as
an embed, several times a day, with an HTTP control API for the rpi webapp's
"HLTV" bot tab and CS2 board widget. Clone of discord-weather's scaffolding;
only the domain logic differs.

Only notable matches make the cut: a team in the Valve Regional Standings
(VRS) top N (default 32), or a match HLTV rates at min_stars or above.

Data: **hltv.org, and nothing else** — matches, results, map scores, streams
and the VRS ranking all come from the `hltv-api` sidecar, which drives a real
browser because HLTV publishes no API and blocks plain HTTP clients. HLTV's
own team ranking is deliberately never used; VRS is the ranking here.

Posting several times a day is what gives full coverage: the 00:00 post
previews the day, later slots pick up overnight results and matches added
after the earlier post. Each slot is tracked separately in /data/last_post,
so a missed slot doesn't suppress the next one.

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

HLTV_API = os.environ.get("HLTV_API_URL", "http://hltv-api:8080")
VRS_CACHE_SECONDS = 3600     # the sidecar caches for a day; this just avoids chatter
DAY_MAX_AGE = 900            # widget/preview reads may be up to 15 min stale
EMBED_COLOR = 0x2B6EA4       # HLTV blue
MAX_MATCHES = 20
FIELD_CAP = 1024             # Discord's per-field limit
EMBED_CAP = 5800             # Discord's 6000 total, with headroom

DEFAULT_CONFIG = {
    "enabled": True,
    # Several slots a day = full coverage. Midnight previews the day, morning
    # picks up overnight results, evening recaps and previews the NA slate.
    "post_times": ["00:00", "07:00", "18:00"],
    "timezone": "America/New_York",
    "message": "",  # plain-text content sent above the embed
    "webhook_url": "",  # seeded from DISCORD_WEBHOOK_URL_HLTV env on first boot
    "vrs_top_n": 32,  # matches involving a VRS top-N team always make the cut
    "min_stars": 1,  # …as do matches HLTV rates this many stars or more (0 = off)
    "post_when_empty": False,  # False → no notable games = skip; True → post "no games"
    "alert_on_failure": True,  # HLTV is the only source, so say so when it's down
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
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL_HLTV", "")
        save_config(cfg)
        log(f"seeded default config at {CONFIG_PATH}")
    # env webhook as fallback if config never got one
    if not cfg.get("webhook_url"):
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL_HLTV", "")
    # one-time migration off the single daily slot (and the old bo3.gg tier filter)
    if "post_time" in cfg or "tiers" in cfg:
        if "post_times" not in cfg and cfg.get("post_time"):
            cfg["post_times"] = [cfg["post_time"]]
        cfg.pop("post_time", None)
        cfg.pop("tiers", None)
        save_config(cfg)
        log(f"migrated config to post_times={cfg.get('post_times')}")
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


def norm_post_times(v):
    """Canonicalize post_times. Accepts a list or the comma-separated string the
    webapp's text field sends; returns a sorted, deduped list, or None if bad."""
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, list):
        return None
    out = sorted({str(s).strip() for s in v if str(s).strip()})
    if not 1 <= len(out) <= 6:
        return None
    if any(not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s) for s in out):
        return None
    return out


def validate_config(cfg):
    """Returns an error string, or None if cfg is a valid full config."""
    if not isinstance(cfg, dict):
        return "config must be an object"
    if not isinstance(cfg.get("enabled"), bool):
        return "enabled must be true/false"
    if not norm_post_times(cfg.get("post_times")):
        return "post_times must be 1–6 comma-separated HH:MM (24h) values"
    msg = cfg.get("message", "")
    if not isinstance(msg, str) or len(msg) > 2000:
        return "message must be text, max 2000 characters"
    try:
        ZoneInfo(str(cfg.get("timezone")))
    except Exception:
        return f"unknown timezone {cfg.get('timezone')!r}"
    n = cfg.get("vrs_top_n")
    if not isinstance(n, int) or not 1 <= n <= 100:
        return "vrs_top_n must be 1–100"
    stars = cfg.get("min_stars")
    if not isinstance(stars, int) or not 0 <= stars <= 5:
        return "min_stars must be 0–5"
    if not isinstance(cfg.get("post_when_empty"), bool):
        return "post_when_empty must be true/false"
    if not isinstance(cfg.get("alert_on_failure"), bool):
        return "alert_on_failure must be true/false"
    url = cfg.get("webhook_url", "")
    if url and not url.startswith("https://discord.com/api/webhooks/"):
        return "webhook_url must start with https://discord.com/api/webhooks/"
    return None


def mask_webhook(url):
    return f"https://discord.com/api/webhooks/…{url[-6:]}" if url else ""


# ── HTTP helper ───────────────────────────────────────────────────────────────
def http_get(url, tries=3, timeout=30, json_out=True):
    for attempt in range(tries):
        req = urllib.request.Request(
            url, headers={"User-Agent": "discord-hltv (rpi homelab)",
                          "Accept": "application/json" if json_out else "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return json.loads(raw) if json_out else raw.decode()
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"{url.split('?')[0]} failed: {e}") from e
            time.sleep(5)


def post_json(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "discord-hltv (rpi homelab)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


# ── hltv-api sidecar ──────────────────────────────────────────────────────────
def norm_team(name):
    """Normalize for VRS↔match-listing matching: 'Team Spirit' ≈ 'Spirit'."""
    s = str(name or "").lower().strip()
    s = re.sub(r"^team\s+", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


_vrs_cache = {"at": 0, "vrs": None}


def get_vrs():
    """Valve Regional Standings as published on hltv.org. HLTV's own team
    ranking is never used — VRS is the ranking that matters here."""
    if _vrs_cache["vrs"] and time.time() - _vrs_cache["at"] < VRS_CACHE_SECONDS:
        return _vrs_cache["vrs"]
    vrs = http_get(f"{HLTV_API}/vrs", tries=2, timeout=120)
    if not (vrs or {}).get("teams"):
        raise RuntimeError("hltv-api returned no VRS teams")
    _vrs_cache.update(at=time.time(), vrs=vrs)
    return vrs


def get_day(cfg, max_age=0):
    """Every match on hltv.org for today, normalized by the sidecar."""
    tz = cfg["timezone"]
    date_str = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    qs = urllib.parse.urlencode({"date": date_str, "tz": tz, "max_age": max_age})
    day = http_get(f"{HLTV_API}/day?{qs}", tries=2, timeout=240)
    if not isinstance(day, dict) or "matches" not in day:
        raise RuntimeError("hltv-api returned no match data")
    return day


def clock_str(unix, tz):
    try:
        dt = datetime.fromtimestamp(int(unix), ZoneInfo(tz))
        return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    except (ValueError, TypeError, OSError):
        return "?"


def notable(m, top_norm, min_stars):
    """A match makes the digest if either team is VRS top-N, or HLTV rates it
    highly enough. Returns the reason ('vrs'/'stars') or None."""
    if norm_team(m.get("team1")) in top_norm or norm_team(m.get("team2")) in top_norm:
        return "vrs"
    if min_stars and (m.get("stars") or 0) >= min_stars:
        return "stars"
    return None


# ── rendering ─────────────────────────────────────────────────────────────────
def md_escape(s):
    """Team/event names are user-ish text landing inside markdown links."""
    return re.sub(r"([\\`*_~\[\]])", r"\\\1", str(s or ""))


def fmt_maps(m):
    """'Inferno 13–9 · Anubis 6–13', oriented so the series winner reads first."""
    maps = m.get("maps") or []
    if not maps:
        return ""
    flip = (m.get("score2") or 0) > (m.get("score1") or 0)
    parts = []
    for mp in maps:
        s1, s2 = mp.get("s1"), mp.get("s2")
        if s1 is None or s2 is None:
            continue
        a, b = (s2, s1) if flip else (s1, s2)
        parts.append(f"{mp.get('name')} {a}–{b}")
    return " · ".join(parts)


def fmt_match(m, tz):
    """One digest line, shaped by status."""
    t1, t2 = md_escape(m.get("team1")), md_escape(m.get("team2"))
    url = m.get("url")
    bo = f" ({m['bo'].upper()})" if m.get("bo") else ""
    stream = m.get("stream") or {}
    link = f" · [📺 {md_escape(stream.get('name'))}]({stream['url']})" if stream.get("url") else ""
    s1, s2 = m.get("score1"), m.get("score2")

    if m.get("status") == "finished":
        won_first = (s1 or 0) >= (s2 or 0)
        win, lose = (t1, t2) if won_first else (t2, t1)
        ws, ls = (s1, s2) if won_first else (s2, s1)
        head = f"✅ [**{win}** {ws}–{ls} {lose}]({url})" if url else f"✅ **{win}** {ws}–{ls} {lose}"
        maps = fmt_maps(m)
        return head + (f" — {maps}" if maps else "")

    if m.get("status") == "live":
        score = f" {s1}–{s2}" if s1 is not None and s2 is not None else " vs"
        body = f"[{t1}{score} {t2}]({url})" if url else f"{t1}{score} {t2}"
        return f"**🔴 LIVE** — {body}{bo}{link}"

    when = clock_str(m.get("start_unix"), tz)
    body = f"[{t1} vs {t2}]({url})" if url else f"{t1} vs {t2}"
    return f"**{when}** — {body}{bo}{link}"


def pack_lines(lines, cap=FIELD_CAP):
    """Fill a field without ever cutting mid-line — a severed markdown link
    breaks the whole embed, which a blind slice would happily do."""
    out, used = [], 0
    for i, ln in enumerate(lines):
        if used + len(ln) + 1 > cap - 16:
            out.append(f"(+{len(lines) - i} more)")
            break
        out.append(ln)
        used += len(ln) + 1
    return "\n".join(out)


def embed_size(embed):
    n = len(embed.get("title", "")) + len(embed.get("description", ""))
    n += len(embed.get("footer", {}).get("text", ""))
    for f in embed.get("fields", []):
        n += len(f["name"]) + len(f["value"])
    return n


def build_payload(cfg):
    """Fetch VRS + today's matches from hltv.org and build the webhook payload.
    Returns (payload, failed_sections, has_matches)."""
    tz = cfg["timezone"]
    now = datetime.now(ZoneInfo(tz))

    failed = []
    vrs, top_norm = None, set()
    try:
        vrs = get_vrs()
        top_norm = {norm_team(t["name"]) for t in vrs["teams"][:cfg["vrs_top_n"]]}
    except Exception as e:
        log(f"VRS fetch failed (star filter only): {e}")
        failed.append("VRS")

    day, matches = None, []
    try:
        day = get_day(cfg)
        matches = [m for m in day["matches"]
                   if notable(m, top_norm, cfg.get("min_stars", 0))]
    except Exception as e:
        log(f"hltv-api day fetch failed: {e}")
        failed.append("matches")

    # group by event, keeping the sidecar's live → finished → upcoming order
    by_event = {}
    for m in matches[:MAX_MATCHES]:
        by_event.setdefault(m.get("event") or "Unknown event", []).append(m)

    fields = []
    for event, ms in by_event.items():
        lines = [fmt_match(m, tz) for m in ms]
        fields.append({"name": f"🏆 {md_escape(event)}"[:256],
                       "value": pack_lines(lines), "inline": False})

    has_matches = bool(matches)
    date_str = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    desc = [f"**{date_str}**"]
    if has_matches:
        line = f"{len(matches)} notable match{'es' if len(matches) != 1 else ''}"
        if vrs:
            line += f" · VRS top {cfg['vrs_top_n']} as of {vrs.get('as_of', '?')}"
        desc.append(line)
        if len(matches) > MAX_MATCHES:
            desc.append(f"(showing first {MAX_MATCHES})")
        if day and day.get("stale"):
            desc.append(f"⚠️ data as of {clock_str(day.get('fetched_at'), tz)}")
    elif failed:
        desc.append("⚠️ match data unavailable")
    else:
        desc.append("No notable games today.")

    embed = {
        "title": "🎯 CS2 — Games of the Day",
        "description": "\n".join(desc),
        "color": EMBED_COLOR,
        "fields": fields,
        "footer": {"text": "HLTV.org"},
    }
    while embed["fields"] and embed_size(embed) > EMBED_CAP:
        embed["fields"].pop()
        embed["description"] = embed["description"].rstrip() + "\n(truncated)"

    payload = {
        "username": "CS2 Games of the Day",
        "allowed_mentions": {"parse": ["everyone", "roles", "users"]},
        "embeds": [embed],
    }
    if cfg.get("message"):
        payload["content"] = cfg["message"]
    return payload, failed, has_matches


_feed_cache = {"at": 0, "feed": None}
FEED_CACHE_SECONDS = 60


def day_feed(cfg):
    """Structured version of the digest for the dashboard widget: the same
    notable-match filter, but fields instead of Discord markup. Two caches sit
    in front of HLTV — 60s here, 15 min in the sidecar — so a dashboard left
    open all day costs a handful of scrapes."""
    if _feed_cache["feed"] and time.time() - _feed_cache["at"] < FEED_CACHE_SECONDS:
        return _feed_cache["feed"]
    top_norm = set()
    vrs = None
    try:
        vrs = get_vrs()
        top_norm = {norm_team(t["name"]) for t in vrs["teams"][:cfg["vrs_top_n"]]}
    except Exception as e:
        log(f"feed: VRS unavailable ({e})")
    day = get_day(cfg, max_age=DAY_MAX_AGE)
    matches = [m for m in day["matches"] if notable(m, top_norm, cfg.get("min_stars", 0))]
    feed = {
        "date": day.get("date"),
        "fetched_at": day.get("fetched_at"),
        "stale": bool(day.get("stale")),
        "vrs_as_of": (vrs or {}).get("as_of"),
        "matches": matches[:MAX_MATCHES],
    }
    _feed_cache.update(at=time.time(), feed=feed)
    return feed


def post_webhook(url, payload):
    status = post_json(url, payload)
    if not 200 <= status < 300:
        raise RuntimeError(f"webhook returned HTTP {status}")


def post_report(cfg, force=False):
    """Build and post the report. Returns (ok, detail). Scheduled runs
    (force=False) skip no-game days unless post_when_empty; Send-now always posts."""
    payload, failed, has_matches = build_payload(cfg)
    if "matches" in failed:
        return False, "match data unavailable (hltv-api)"
    if not force and not has_matches and not cfg.get("post_when_empty"):
        return True, "skipped — no notable games today"
    url = cfg.get("webhook_url")
    if not url:
        return False, "DISCORD_WEBHOOK_URL_HLTV / webhook_url not set"
    try:
        post_webhook(url, payload)
    except Exception as e:
        return False, str(e)
    detail = "posted" + (" (VRS unavailable, star filter only)" if "VRS" in failed else "")
    return True, detail


# ── scheduler ─────────────────────────────────────────────────────────────────
# /data/last_post holds the latest completed slot as "YYYY-MM-DDTHH:MM" (naive
# local). Slots are totally ordered and the format sorts lexicographically, so
# one marker says "everything up to here is done" — no per-slot bookkeeping.
def read_marker():
    try:
        with open(LAST_POST_PATH) as f:
            s = f.read().strip()
    except OSError:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        # pre-multi-slot stamp: that whole day posted, so treat it as done.
        # Worst case we skip one already-passed slot on upgrade day; the
        # alternative (treating it as T00:00) would double-post.
        return s + "T23:59"
    return s


def write_marker(slot):
    tmp = LAST_POST_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(slot)
    os.replace(tmp, LAST_POST_PATH)


def slots_for(cfg, day):
    return [f"{day.isoformat()}T{t}" for t in norm_post_times(cfg["post_times"])]


def next_post_dt(cfg, now):
    """Next scheduled datetime strictly after `now` (tz-aware)."""
    for day in (now.date(), now.date() + timedelta(days=1)):
        for hhmm in norm_post_times(cfg["post_times"]):
            hh, mm = map(int, hhmm.split(":"))
            cand = now.replace(year=day.year, month=day.month, day=day.day,
                               hour=hh, minute=mm, second=0, microsecond=0)
            if cand > now:
                return cand
    return now + timedelta(days=1)  # unreachable with a valid config


def scheduled_post(cfg, slot):
    tz = ZoneInfo(cfg["timezone"])
    now = datetime.now(tz)
    first_try = _retry["slot"] != slot
    if first_try:  # a new slot gets its own failure clock and its own one alert
        _retry.update(since=now, alerted=False)
    _retry.update(slot=slot, at=now)
    ok, detail = post_report(cfg)
    with _lock:
        _status["last_post_at"] = now.isoformat(timespec="seconds")
        _status["last_status"] = detail if ok else f"failed: {detail}"
    if ok:
        write_marker(slot)
        _retry.update(slot=None, at=None, since=None, alerted=False)
    else:
        stuck = (now - _retry["since"]).total_seconds()
        if cfg.get("alert_on_failure") and not _retry["alerted"] and stuck >= ALERT_AFTER:
            _retry["alerted"] = True
            alert(cfg, f"⚠️ CS2 digest for {slot} has been failing for "
                       f"{round(stuck / 3600, 1)}h — {detail}")
    log(f"post {slot}: {'ok — ' + detail if ok else 'FAILED — ' + detail}")


def alert(cfg, text):
    """HLTV is the only source, so an outage must be visible, not silent."""
    url = cfg.get("webhook_url")
    if not url:
        return
    try:
        post_json(url, {"username": "CS2 Games of the Day", "content": text,
                        "allowed_mentions": {"parse": []}})
        log(f"posted failure alert: {text}")
    except Exception as e:
        log(f"failure alert could not be posted: {e}")


RETRY_INTERVAL = 900       # a failed post is re-attempted every 15 min until it lands
ALERT_AFTER = 2 * 3600     # …and after this long, Discord gets told about it
_retry = {"slot": None, "at": None, "since": None, "alerted": False}


def scheduler_loop():
    while True:
        cfg = load_config()
        tz = ZoneInfo(cfg["timezone"])
        now = datetime.now(tz)

        if not cfg["enabled"]:
            with _lock:
                _status["next_post_at"] = None
            _wake.wait(timeout=3600)
            _wake.clear()
            continue

        # catch-up / retry: a slot from today is due but hasn't landed yet
        marker = read_marker()
        now_str = now.strftime("%Y-%m-%dT%H:%M")
        due = [s for s in slots_for(cfg, now.date()) if s <= now_str and s > marker]
        if due:
            # Only the latest due slot: posting every missed one would just send
            # the same digest twice. Stamping it marks the earlier ones done too.
            slot = due[-1]
            if _retry["slot"] == slot:
                since = (now - _retry["at"]).total_seconds()
                if since < RETRY_INTERVAL:  # pace re-attempts after a failure
                    next_try = _retry["at"] + timedelta(seconds=RETRY_INTERVAL)
                    with _lock:
                        _status["next_post_at"] = next_try.isoformat(timespec="seconds")
                    if _wake.wait(timeout=RETRY_INTERVAL - since):
                        _wake.clear()
                    continue
                log(f"retrying {slot} (last attempt {round(since / 60)} min ago)")
            else:
                log(f"catch-up: {slot} is due, posting now")
            scheduled_post(cfg, slot)
            continue

        nxt = next_post_dt(cfg, now)
        with _lock:
            _status["next_post_at"] = nxt.isoformat(timespec="seconds")
        wait = (nxt - now).total_seconds()
        if _wake.wait(timeout=min(wait, 3600)):
            _wake.clear()
            continue  # config changed — recompute
        if datetime.now(tz) >= nxt:
            scheduled_post(load_config(), nxt.strftime("%Y-%m-%dT%H:%M"))


# ── control API ───────────────────────────────────────────────────────────────
CONFIG_KEYS = ("enabled", "post_times", "timezone", "message", "webhook_url",
               "vrs_top_n", "min_stars", "post_when_empty", "alert_on_failure")


def public_config(cfg):
    pub = dict(cfg)
    pub["webhook_url"] = mask_webhook(cfg.get("webhook_url", ""))
    pub["webhook_configured"] = bool(cfg.get("webhook_url"))
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
                             "post_times": cfg["post_times"], "timezone": cfg["timezone"], **st})
        elif path == "/config":
            self._send(200, public_config(cfg))
        elif path == "/preview":
            try:
                payload, failed, has_matches = build_payload(cfg)
                self._send(200, {"payload": payload, "failed": failed, "has_matches": has_matches})
            except Exception as e:
                self._send(502, {"error": str(e)})
        elif path == "/day":
            # the board widget's feed: same filter as the digest, but structured.
            # Cached upstream so an open dashboard doesn't re-scrape HLTV.
            try:
                self._send(200, day_feed(cfg))
            except Exception as e:
                self._send(502, {"error": str(e)})
        elif path == "/vrs":
            try:
                vrs = get_vrs()
                self._send(200, {"as_of": vrs["as_of"],
                                 "teams": [t["name"] for t in vrs["teams"][:cfg["vrs_top_n"]]]})
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
        merged = {**current, **{k: v for k, v in incoming.items() if k in CONFIG_KEYS}}
        merged["post_times"] = norm_post_times(merged.get("post_times")) or merged.get("post_times")
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
        log(f"config updated: enabled={merged['enabled']} post_times={merged['post_times']} "
            f"vrs_top_n={merged['vrs_top_n']} min_stars={merged['min_stars']}")
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
            cfg = {**DEFAULT_CONFIG, "webhook_url": os.environ.get("DISCORD_WEBHOOK_URL_HLTV", "")}
        if "--dry-run" in argv:
            payload, failed, has_matches = build_payload(cfg)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            print(f"has_matches: {has_matches}", file=sys.stderr)
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
