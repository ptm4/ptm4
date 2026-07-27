#!/usr/bin/env python3
"""
discord-hltv — daily "CS2 games of the day" posted to a Discord channel
webhook as an embed, with an HTTP control API for the rpi webapp's
"HLTV Bot" tab. Clone of discord-weather's scaffolding; only the domain
logic differs.

Only notable matches make the cut: a team in the Valve Regional Standings
(VRS) top N (default 32), or a top-tier (S/A) tournament.

Data:
  • Valve VRS — official standings from ValveSoftware's GitHub repo
    (counter-strike_regional_standings); latest global standings md, cached
    in /data for a day. HLTV's ranking page is Cloudflare-walled; Valve's
    repo IS the VRS source of truth.
  • bo3.gg public API — today's matches with teams, tournament and tier.

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
VRS_CACHE_PATH = os.path.join(DATA_DIR, "vrs_cache.json")
API_PORT = 8080

VRS_REPO = "ValveSoftware/counter-strike_regional_standings"
VRS_CACHE_HOURS = 24  # Valve updates ~weekly; a daily refresh is plenty
BO3_BASE = "https://api.bo3.gg/api/v1"
EMBED_COLOR = 0x2B6EA4  # HLTV blue
MAX_MATCHES = 20

DEFAULT_CONFIG = {
    "enabled": True,
    "post_time": "09:00",
    "timezone": "America/New_York",
    "message": "",  # plain-text content sent above the embed
    "webhook_url": "",  # seeded from DISCORD_WEBHOOK_URL_HLTV env on first boot
    "vrs_top_n": 32,  # matches involving a team ranked <= this always make the cut
    "tiers": ["s", "a"],  # tournament tiers that make the cut regardless of VRS rank
    "post_when_empty": False,  # False → no notable games = skip; True → post "no games"
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
    n = cfg.get("vrs_top_n")
    if not isinstance(n, int) or not 1 <= n <= 100:
        return "vrs_top_n must be 1–100"
    tiers = cfg.get("tiers")
    if not isinstance(tiers, list) or not all(t in ("s", "a", "b", "c") for t in tiers):
        return "tiers must be a list drawn from s/a/b/c"
    if not isinstance(cfg.get("post_when_empty"), bool):
        return "post_when_empty must be true/false"
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


# ── Valve VRS standings ───────────────────────────────────────────────────────
def norm_team(name):
    """Normalize for VRS↔bo3.gg matching: 'Team Spirit' ≈ 'Spirit', 'FURIA' ≈ 'furia'."""
    s = str(name or "").lower().strip()
    s = re.sub(r"^team\s+", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def fetch_vrs():
    """Latest Valve global standings: {'as_of': 'YYYY_MM_DD', 'teams': [name, …]} in rank order."""
    year = datetime.now(timezone.utc).year
    listing = None
    for y in (year, year - 1):  # early January: the current year's dir may not exist yet
        try:
            listing = http_get(f"https://api.github.com/repos/{VRS_REPO}/contents/live/{y}", tries=1)
            break
        except RuntimeError:
            continue
    if not listing:
        raise RuntimeError("could not list VRS standings dir")
    files = sorted(x["name"] for x in listing
                   if x["name"].startswith("standings_global_") and x["name"].endswith(".md"))
    if not files:
        raise RuntimeError("no global standings files found")
    latest = files[-1]
    md = http_get(f"https://raw.githubusercontent.com/{VRS_REPO}/main/live/{y}/{latest}",
                  tries=2, json_out=False)
    teams = []
    for line in md.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|\s*\d+\s*\|\s*([^|]+?)\s*\|", line)
        if m:
            teams.append(m.group(2))
    if not teams:
        raise RuntimeError(f"could not parse teams out of {latest}")
    as_of = latest.replace("standings_global_", "").replace(".md", "")
    return {"as_of": as_of, "teams": teams}


def get_vrs():
    """fetch_vrs() behind a /data cache so previews don't hammer GitHub."""
    try:
        with open(VRS_CACHE_PATH) as f:
            cache = json.load(f)
        age_h = (time.time() - cache["fetched_at"]) / 3600
        if age_h < VRS_CACHE_HOURS:
            return cache["vrs"]
    except (OSError, ValueError, KeyError):
        cache = None
    try:
        vrs = fetch_vrs()
    except RuntimeError:
        if cache:  # stale cache beats no data
            return cache["vrs"]
        raise
    try:
        tmp = VRS_CACHE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"fetched_at": time.time(), "vrs": vrs}, f)
        os.replace(tmp, VRS_CACHE_PATH)
    except OSError:
        pass  # cache is best-effort (e.g. --dry-run outside the container)
    return vrs


# ── bo3.gg matches ────────────────────────────────────────────────────────────
def fetch_matches(start_utc, end_utc):
    """CS2 matches starting in [start_utc, end_utc), with team/tournament names."""
    qs = urllib.parse.urlencode({
        "page[limit]": 100,
        "sort": "start_date",
        # bo3.gg only honors gt/lt (not gte), and only with full ISO timestamps
        "filter[matches.start_date][gt]": (start_utc - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "filter[matches.start_date][lt]": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "with": "teams,tournament",
    })
    d = http_get(f"{BO3_BASE}/matches?{qs}", tries=2)
    return (d or {}).get("results", [])


def clock_str(iso, tz):
    try:
        dt = datetime.fromisoformat(iso).astimezone(ZoneInfo(tz))
        return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    except (ValueError, TypeError):
        return "?"


def notable(match, top_norm, tiers):
    """A match makes the digest if its tournament tier qualifies, or either team
    is in the VRS top N. Returns the reason ('tier'/'vrs') or None."""
    if (match.get("tier") or "").lower() in tiers:
        return "tier"
    for side in ("team1", "team2"):
        if norm_team((match.get(side) or {}).get("name")) in top_norm:
            return "vrs"
    return None


def build_payload(cfg):
    """Fetch VRS + today's matches and build the webhook payload.
    Returns (payload, failed_sections, has_matches)."""
    tz = ZoneInfo(cfg["timezone"])
    now = datetime.now(tz)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    failed = []
    vrs, top_norm = None, set()
    try:
        vrs = get_vrs()
        top_norm = {norm_team(t) for t in vrs["teams"][:cfg["vrs_top_n"]]}
    except Exception as e:
        log(f"VRS fetch failed (tier filter only): {e}")
        failed.append("VRS")

    matches = []
    try:
        raw = fetch_matches(day_start.astimezone(timezone.utc), day_end.astimezone(timezone.utc))
        tiers = {t.lower() for t in cfg["tiers"]}
        for m in raw:
            if m.get("status") not in ("upcoming", "current"):
                continue
            if notable(m, top_norm, tiers):
                matches.append(m)
    except Exception as e:
        log(f"bo3.gg fetch failed: {e}")
        failed.append("matches")

    # group by tournament, in first-match order
    by_event = {}
    for m in matches[:MAX_MATCHES]:
        event = (m.get("tournament") or {}).get("name") or "Unknown event"
        by_event.setdefault(event, []).append(m)

    fields = []
    for event, ms in by_event.items():
        lines = []
        for m in ms:
            t1 = (m.get("team1") or {}).get("name") or "TBD"
            t2 = (m.get("team2") or {}).get("name") or "TBD"
            when = ("🔴 LIVE" if m.get("status") == "current"
                    else clock_str(m.get("start_date", ""), cfg["timezone"]))
            bo = f" (BO{m['bo_type']})" if m.get("bo_type") else ""
            lines.append(f"**{when}** — {t1} vs {t2}{bo}")
        tier = (ms[0].get("tier") or "").upper()
        name = f"🏆 {event}" + (f" · Tier {tier}" if tier else "")
        fields.append({"name": name[:256], "value": "\n".join(lines)[:1024], "inline": False})

    has_matches = bool(matches)
    date_str = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    desc_lines = [f"**{date_str}**"]
    if has_matches:
        desc_lines.append(f"{len(matches)} notable match{'es' if len(matches) != 1 else ''}"
                          + (f" · VRS top {cfg['vrs_top_n']} as of {vrs['as_of']}" if vrs else ""))
        if len(matches) > MAX_MATCHES:
            desc_lines.append(f"(showing first {MAX_MATCHES})")
    elif failed:
        desc_lines.append("⚠️ match data unavailable")
    else:
        desc_lines.append("No notable games today.")

    payload = {
        "username": "CS2 Games of the Day",
        "allowed_mentions": {"parse": ["everyone", "roles", "users"]},
        "embeds": [{
            "title": "🎯 CS2 — Games of the Day",
            "description": "\n".join(desc_lines),
            "color": EMBED_COLOR,
            "fields": fields,
            "footer": {"text": "Valve VRS · bo3.gg"},
        }],
    }
    if cfg.get("message"):
        payload["content"] = cfg["message"]
    return payload, failed, has_matches


def post_webhook(url, payload):
    status = post_json(url, payload)
    if not 200 <= status < 300:
        raise RuntimeError(f"webhook returned HTTP {status}")


def post_report(cfg, force=False):
    """Build and post the report. Returns (ok, detail). Scheduled runs
    (force=False) skip no-game days unless post_when_empty; Send-now always posts."""
    payload, failed, has_matches = build_payload(cfg)
    if "matches" in failed:
        return False, "match data unavailable (bo3.gg)"
    if not force and not has_matches and not cfg.get("post_when_empty"):
        return True, "skipped — no notable games today"
    url = cfg.get("webhook_url")
    if not url:
        return False, "DISCORD_WEBHOOK_URL_HLTV / webhook_url not set"
    try:
        post_webhook(url, payload)
    except Exception as e:
        return False, str(e)
    detail = "posted" + (" (VRS unavailable, tier filter only)" if "VRS" in failed else "")
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
CONFIG_KEYS = ("enabled", "post_time", "timezone", "message", "webhook_url",
               "vrs_top_n", "tiers", "post_when_empty")


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
                             "post_time": cfg["post_time"], "timezone": cfg["timezone"], **st})
        elif path == "/config":
            self._send(200, public_config(cfg))
        elif path == "/preview":
            try:
                payload, failed, has_matches = build_payload(cfg)
                self._send(200, {"payload": payload, "failed": failed, "has_matches": has_matches})
            except Exception as e:
                self._send(502, {"error": str(e)})
        elif path == "/vrs":
            try:
                vrs = get_vrs()
                self._send(200, {"as_of": vrs["as_of"],
                                 "teams": vrs["teams"][:cfg["vrs_top_n"]]})
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
            f"vrs_top_n={merged['vrs_top_n']} tiers={merged['tiers']}")
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
