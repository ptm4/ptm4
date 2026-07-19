#!/usr/bin/env python3
"""
discord-weather — daily Open-Meteo forecast posted to a Discord channel
webhook as an embed, with an HTTP control API for the rpi webapp's
"Weather Channel Bot Settings" tab.

Runs as a container in the rpi compose stack (see ../docker-compose.yml).
Config lives in /data/config.json (named volume, seeded from env +
DEFAULT_LOCATIONS on first boot); the webapp edits it via the API — the
scheduler picks changes up immediately, no restart needed.

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

OM_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OM_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
EMBED_COLOR = 0x58B9FF  # sky blue

DEFAULT_CONFIG = {
    "enabled": True,
    "post_time": "07:00",
    "timezone": "America/New_York",
    "message": "@everyone",  # plain-text content sent above the embed
    "webhook_url": "",  # seeded from DISCORD_WEBHOOK_URL env on first boot
    "locations": [
        {"name": "Bellerose, NY", "lat": 40.7328, "lon": -73.7178},
        {"name": "Kew Gardens, NY", "lat": 40.7143, "lon": -73.8310},
        {"name": "Hicksville, NY", "lat": 40.7684, "lon": -73.5251},
    ],
}

# condition emoji by WMO code group (fallback 🌡️)
WMO_EMOJI = {0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️",
             51: "🌦️", 53: "🌦️", 55: "🌦️", 56: "🌦️", 57: "🌦️",
             61: "🌧️", 63: "🌧️", 65: "🌧️", 66: "🌧️", 67: "🌧️",
             71: "🌨️", 73: "🌨️", 75: "❄️", 77: "🌨️",
             80: "🌧️", 81: "🌧️", 82: "🌧️", 85: "🌨️", 86: "❄️",
             95: "⛈️", 96: "⛈️", 99: "⛈️"}

WMO_TEXT = {
    0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    56: "Freezing Drizzle", 57: "Heavy Freezing Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    66: "Freezing Rain", 67: "Heavy Freezing Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow", 77: "Snow Grains",
    80: "Light Showers", 81: "Showers", 82: "Heavy Showers",
    85: "Snow Showers", 86: "Heavy Snow Showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ Hail", 99: "Severe Thunderstorm",
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
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL", "")
        save_config(cfg)
        log(f"seeded default config at {CONFIG_PATH}")
    # env webhook as fallback if config never got one
    if not cfg.get("webhook_url"):
        cfg["webhook_url"] = os.environ.get("DISCORD_WEBHOOK_URL", "")
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
    locs = cfg.get("locations")
    if not isinstance(locs, list) or not locs:
        return "locations must be a non-empty list"
    for l in locs:
        if not (isinstance(l, dict) and l.get("name")
                and isinstance(l.get("lat"), (int, float))
                and isinstance(l.get("lon"), (int, float))):
            return "each location needs name, lat, lon"
        if not (-90 <= l["lat"] <= 90 and -180 <= l["lon"] <= 180):
            return f"out-of-range coordinates for {l.get('name')}"
    url = cfg.get("webhook_url", "")
    if url and not url.startswith("https://discord.com/api/webhooks/"):
        return "webhook_url must start with https://discord.com/api/webhooks/"
    return None


def mask_webhook(url):
    return f"https://discord.com/api/webhooks/…{url[-6:]}" if url else ""


# ── HTTP + weather ────────────────────────────────────────────────────────────
def http_json(url, body=None, tries=3):
    for attempt in range(tries):
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     "User-Agent": "discord-weather (rpi homelab)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw.strip() else None)
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"{url.split('?')[0]} failed: {e}") from e
            time.sleep(5)


def fetch_forecast(loc, tz):
    qs = urllib.parse.urlencode({
        "latitude": loc["lat"], "longitude": loc["lon"],
        "daily": "temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,weather_code,wind_speed_10m_max,"
                 "apparent_temperature_max,uv_index_max,sunrise,sunset",
        "hourly": "relative_humidity_2m",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "timezone": tz, "forecast_days": 1,
    })
    _, d = http_json(f"{OM_FORECAST_URL}?{qs}")
    daily = d["daily"]
    code = daily["weather_code"][0]
    return {
        "hi": daily["temperature_2m_max"][0],
        "lo": daily["temperature_2m_min"][0],
        "cond": WMO_TEXT.get(code, f"Code {code}"),
        "emoji": WMO_EMOJI.get(code, "🌡️"),
        "feels": daily["apparent_temperature_max"][0],
        "uv": daily["uv_index_max"][0],
        "sunrise": clock_str(daily["sunrise"][0]),
        "sunset": clock_str(daily["sunset"][0]),
        "rain": daily["precipitation_probability_max"][0] or 0,
        "wind": daily["wind_speed_10m_max"][0],
        "humidity": daytime_humidity(d.get("hourly", {})),
    }


def feels_emoji(f):
    """Emoji for the feels-like temperature (°F)."""
    for threshold, emoji in ((100, "🔥"), (90, "🥵"), (75, "😎"), (60, "🙂"),
                             (40, "🧥"), (20, "🥶")):
        if f >= threshold:
            return emoji
    return "🧊"


def clock_str(iso):
    """'2026-07-16T05:38' -> '5:38 AM' (no %-I: not portable to musl)."""
    try:
        dt = datetime.fromisoformat(iso)
        return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    except (ValueError, TypeError):
        return "—"


def daytime_humidity(hourly):
    vals = [v for v in (hourly.get("relative_humidity_2m") or [])[6:19] if v is not None]
    if not vals:
        vals = [v for v in (hourly.get("relative_humidity_2m") or []) if v is not None]
    return round(sum(vals) / len(vals)) if vals else None


SPACER_FIELD = {"name": "​", "value": "​", "inline": True}  # forces 2-per-row grid


def location_field(loc, fc):
    # CAPS title anchored by the town's condition emoji — field names render at
    # a fixed size, so hierarchy comes from contrast, not font size
    if fc is None:
        return {"name": f"📍 {loc['name'].upper()}", "value": "⚠️ data unavailable", "inline": True}
    hum = f"{fc['humidity']}%" if fc["humidity"] is not None else "—"
    return {
        "name": f"{fc['emoji']} {loc['name'].upper()}",
        "value": (f"{fc['cond']}\n"
                  f"**High {round(fc['hi'])}° / Low {round(fc['lo'])}°**\n"
                  f"Feels like {round(fc['feels'])}° {feels_emoji(fc['feels'])} · UV {round(fc['uv'])}\n"
                  f"💧 Humidity {hum}\n"
                  f"🌬️ Wind {round(fc['wind'])} mph · ☔ Rain {round(fc['rain'])}%"),
        "inline": True,
    }


def build_payload(cfg):
    """Fetch all locations and build the webhook payload.
    Returns (payload, failed_names)."""
    tz = cfg["timezone"]
    fields, failed = [], []
    first_fc = None  # sun times shown once in the header, from the first town that resolves
    for loc in cfg["locations"]:
        try:
            fc = fetch_forecast(loc, tz)
            if first_fc is None:
                first_fc = fc
            fields.append(location_field(loc, fc))
        except Exception as e:
            log(f"forecast failed for {loc['name']}: {e}")
            fields.append(location_field(loc, None))
            failed.append(loc["name"])

    # Desktop packs up to 3 inline fields per row and sizes columns by that
    # row's count — pad EVERY row to exactly 3 slots with invisible spacers so
    # all rows align as 2 visible columns. Mobile stacks fields regardless, so
    # spacers there are just hairline gaps.
    spaced = []
    for i in range(0, len(fields), 2):
        pair = fields[i:i + 2]
        spaced.extend(pair)
        spaced.extend(dict(SPACER_FIELD) for _ in range(3 - len(pair)))

    now = datetime.now(ZoneInfo(tz))
    date_str = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    desc = f"**{date_str}**"
    if first_fc:
        desc += f"\nSunrise {first_fc['sunrise']} · Sunset {first_fc['sunset']}"
    payload = {
        "username": "Daily Weather Report",
        # explicit allow-list so @everyone/@here in the message actually ping
        "allowed_mentions": {"parse": ["everyone", "roles", "users"]},
        "embeds": [{
            "title": "🌤️ Daily Weather Report",
            "description": desc,
            "color": EMBED_COLOR,
            "fields": spaced,
            "footer": {"text": "Open-Meteo"},
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
        return False, "DISCORD_WEBHOOK_URL / webhook_url not set"
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
        elif path == "/geocode":
            q = urllib.parse.parse_qs(query).get("q", [""])[0].strip()
            if not q:
                return self._send(400, {"error": "missing ?q="})
            try:
                qs = urllib.parse.urlencode({"name": q, "count": 5, "language": "en", "format": "json"})
                _, d = http_json(f"{OM_GEOCODE_URL}?{qs}")
                results = [{"name": r["name"], "admin1": r.get("admin1", ""),
                            "country": r.get("country_code", ""),
                            "lat": r["latitude"], "lon": r["longitude"]}
                           for r in (d or {}).get("results", [])]
                self._send(200, {"results": results})
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
                                if k in ("enabled", "post_time", "timezone", "locations", "webhook_url", "message")}}
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
            f"locations={[l['name'] for l in merged['locations']]}")
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
            cfg = {**DEFAULT_CONFIG, "webhook_url": os.environ.get("DISCORD_WEBHOOK_URL", "")}
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
