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
from weather_context import feels_emoji

try:
    import witty_messages
except Exception as _e:  # a witty bug must never take down the 7 AM report
    print(f"WARNING: witty_messages failed to load, running without it: {_e}", flush=True)
    witty_messages = None

try:
    import model_reply   # optional model-written replies; templates stay the fallback
except Exception as _e:
    print(f"WARNING: model_reply failed to load, replies stay template-only: {_e}", flush=True)
    model_reply = None

try:
    import wbdb          # the bot's memory of the chat; without it, replies use live history
except Exception as _e:
    print(f"WARNING: wbdb failed to load, running without memory: {_e}", flush=True)
    wbdb = None

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LAST_POST_PATH = os.path.join(DATA_DIR, "last_post")
WITTY_STATE_PATH = os.path.join(DATA_DIR, "witty_pool.json")
INBOX_PATH = os.path.join(DATA_DIR, "inbox.jsonl")   # pings worth a considered reply
INBOX_MAX = 500
API_PORT = 8080

DISCORD_API = "https://discord.com/api/v10"
# Weather-Bot's token: posts the report to channel_id and answers pings. Without
# it (or without a channel) the report falls back to webhook_url.
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
OM_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OM_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
EMBED_COLOR = 0x556B2F  # olive drab — scoutmaster khaki, not weather-app blue

DEFAULT_CONFIG = {
    "enabled": True,
    "post_time": "07:00",
    "timezone": "America/New_York",
    "message": "@everyone",  # plain-text content sent above the embed
    "witty_enabled": True,   # legacy: template jokes are no longer posted (model line or none)
    "witty_names": [
        "Joe Stasi", "Matt duBourg", "Andrew Kenny", "Tommy Whisker",
        "Anthony Johnson", "Joey Oddo", "Stanley Mcombe", "Nino",
        "Ryan Ardito", "Matt Kaprowski",
    ],
    "channel_id": "",   # where Weather-Bot posts; learned from the webhook if blank
    "webhook_url": "",  # legacy fallback, seeded from DISCORD_WEBHOOK_URL env
    # Which server the bot talks in. Pings are answered only in guild_id (any
    # guild if blank) and, if reply_channels is set, only in those channels.
    # persona is a file name under /data. profiles are named presets of these
    # four fields, so one call flips the bot between the live server and a
    # test server: PUT /config {"active_profile": "test"} or POST /profile.
    "guild_id": "",
    "reply_channels": [],
    "persona": "persona.json",
    "profiles": {},        # {"live": {"guild_id", "channel_id", "reply_channels", "persona"}, ...}
    "active_profile": "",
    # model-written replies, morning line and learning (model_reply.py, wbdb.py);
    # off unless a profile turns it on
    "claude": {"enabled": False, "model": "claude-haiku-5-5", "effort": "medium", "daily_cap": 150,
               "daily_tokens": 400000, "max_tokens": 4096, "history": 15,
               "morning": False, "morning_effort": "medium", "morning_history": 150,
               "memory": False, "memory_skip_channels": []},
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
_post_lock = threading.Lock()  # serialize manual and scheduled build/post/commit
_wake = threading.Event()   # poked on config change so the scheduler recomputes
_status = {"last_post_at": None, "last_status": None, "next_post_at": None, "gateway": "off"}
_witty = witty_messages.WittyPool(WITTY_STATE_PATH) if witty_messages else None


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
    if not isinstance(cfg.get("witty_enabled"), bool):
        return "witty_enabled must be true/false"
    names = cfg.get("witty_names")
    if not isinstance(names, list) or len(names) > 20:
        return "witty_names must be a list of at most 20 names"
    seen = set()
    for n in names:
        # letters/digits/space/.'-_ plus an optional leading @ so Discord handles
        # work as roast names. @everyone/@here stay blocked: mentions are
        # allow-listed in the payload, so a name rendering as either would ping
        # the whole channel every single morning.
        if not isinstance(n, str) or not re.fullmatch(r"@?[A-Za-z0-9 .'_\-]{1,40}", n.strip()):
            return (f"invalid name {n!r} — letters, digits, spaces, . ' - _ "
                    "and an optional leading @, max 40 chars")
        if n.strip().lstrip("@").strip().lower() in ("everyone", "here"):
            return f"name {n.strip()!r} would ping the whole channel — not allowed"
        if n.strip().lower() in seen:
            return f"duplicate name {n.strip()!r}"
        seen.add(n.strip().lower())
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
        subject = l.get("witty_subject", "")
        if (not isinstance(subject, str)
                or (subject and (not re.fullmatch(r"[A-Za-z0-9 .'_\-]{1,40}", subject)
                                 or subject.strip().lower() in ("everyone", "here")))):
            return "witty_subject must be a plain name, max 40 characters"
    url = cfg.get("webhook_url", "")
    if url and not url.startswith("https://discord.com/api/webhooks/"):
        return "webhook_url must start with https://discord.com/api/webhooks/"
    if not re.fullmatch(r"\d{0,20}", str(cfg.get("channel_id", ""))):
        return "channel_id must be a numeric Discord channel id"
    err = validate_server_fields(cfg)
    if err:
        return err
    profiles = cfg.get("profiles", {})
    if not isinstance(profiles, dict) or len(profiles) > 10:
        return "profiles must be an object of at most 10 named presets"
    for name, prof in profiles.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", str(name)):
            return f"profile name {name!r} — letters, digits, - and _ only, max 24"
        if not isinstance(prof, dict) or set(prof) - PROFILE_FIELDS:
            return f"profile {name!r} may only set {sorted(PROFILE_FIELDS)}"
        merged_prof = {**DEFAULT_CONFIG, **prof}
        err = validate_server_fields(merged_prof) or (model_reply.validate(merged_prof) if model_reply else None)
        if err:
            return f"profile {name!r}: {err}"
    if model_reply:
        err = model_reply.validate(cfg)
        if err:
            return err
    active = cfg.get("active_profile", "")
    if active and active not in profiles:
        return f"active_profile {active!r} is not a configured profile"
    return None


PROFILE_FIELDS = {"guild_id", "channel_id", "reply_channels", "persona", "claude"}


def validate_server_fields(cfg):
    if not re.fullmatch(r"\d{0,20}", str(cfg.get("guild_id", ""))):
        return "guild_id must be a numeric Discord server id"
    if not re.fullmatch(r"\d{0,20}", str(cfg.get("channel_id", ""))):
        return "channel_id must be a numeric Discord channel id"
    chans = cfg.get("reply_channels", [])
    if (not isinstance(chans, list) or len(chans) > 20
            or not all(isinstance(c, str) and re.fullmatch(r"\d{1,20}", c) for c in chans)):
        return "reply_channels must be a list of numeric channel ids"
    persona = cfg.get("persona", "persona.json")
    if not (isinstance(persona, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", persona)
            and persona.endswith(".json") and ".." not in persona):
        return "persona must be a .json file name under /data"
    return None


def apply_profile(cfg):
    """Copy the active profile's server fields into the flat config (which stays
    the single source of truth the scheduler, gateway and webapp read)."""
    prof = (cfg.get("profiles") or {}).get(cfg.get("active_profile") or "")
    if prof:
        for k in PROFILE_FIELDS:
            cfg[k] = prof.get(k, DEFAULT_CONFIG[k])
    return cfg


def reload_persona(cfg):
    """Load the configured persona file; defaults stay on failure, as before."""
    if not witty_messages:
        return
    path = os.path.join(DATA_DIR, cfg.get("persona") or "persona.json")
    err = witty_messages.load_persona(path)
    with _lock:
        _status["persona"] = f"{os.path.basename(path)}: {err}" if err else (
            os.path.basename(path) if os.path.exists(path) else "defaults (no persona file)")
    log(f"persona {path}: {err or 'loaded'}")


def adopt_webhook_channel(cfg):
    """Migration: a webhook knows its channel, so a config that only has a
    webhook_url gets channel_id filled in once and Weather-Bot takes over."""
    if cfg.get("channel_id") or not cfg.get("webhook_url") or not BOT_TOKEN:
        return
    try:
        _, info = http_json(cfg["webhook_url"], tries=1)
        cfg["channel_id"] = str(info["channel_id"])
        with _lock:
            save_config(cfg)
        log(f"adopted webhook channel {cfg['channel_id']} for Weather-Bot posts")
    except Exception as e:
        log(f"could not read the webhook's channel: {e}")


def mask_webhook(url):
    return f"https://discord.com/api/webhooks/…{url[-6:]}" if url else ""


# ── HTTP + weather ────────────────────────────────────────────────────────────
def http_json(url, body=None, tries=3, headers=None):
    for attempt in range(tries):
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     "User-Agent": "DiscordBot (homelab discord-weather, 2)", **(headers or {})})
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
        "code": code,
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
        return {"name": f"📍 {loc['name'].upper()}", "value": "⚠️ no report filed — unacceptable", "inline": True}
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


def build_payload(cfg, morning=False):
    """Fetch all locations and build the webhook payload.
    Returns (payload, failed_names, receipt). The receipt contains the selected
    joke (if any) and weather snapshot; commit only after webhook acceptance.
    morning=True (the real daily post, not a preview) lets the model write the
    line from the chat delta when the profile allows it; the template joke is
    then left unconsumed and the receipt carries the model line instead."""
    tz = cfg["timezone"]
    now = datetime.now(ZoneInfo(tz))
    fields, failed = [], []
    observations = []
    first_fc = None  # sun times shown once in the header, from the first town that resolves
    for loc in cfg["locations"]:
        try:
            fc = fetch_forecast(loc, tz)
            if first_fc is None:
                first_fc = fc
            fields.append(location_field(loc, fc))
            observations.append((loc, fc))
        except Exception as e:
            log(f"forecast failed for {loc['name']}: {e}")
            fields.append(location_field(loc, None))
            failed.append(loc["name"])
            observations.append((loc, None))

    # Desktop packs up to 3 inline fields per row and sizes columns by that
    # row's count — pad EVERY row to exactly 3 slots with invisible spacers so
    # all rows align as 2 visible columns. Mobile stacks fields regardless, so
    # spacers there are just hairline gaps.
    spaced = []
    for i in range(0, len(fields), 2):
        pair = fields[i:i + 2]
        spaced.extend(pair)
        spaced.extend(dict(SPACER_FIELD) for _ in range(3 - len(pair)))

    date_str = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    desc = f"**{date_str}**"
    if first_fc:
        desc += f"\nSunrise {first_fc['sunrise']} · Sunset {first_fc['sunset']}"
    persona = (witty_messages.EMBED if witty_messages else {}) or {}
    me = "WB"
    payload = {
        "username": (persona.get("username") or "WB").replace("{me}", me),
        # explicit allow-list so @everyone/@here in the message actually ping
        "allowed_mentions": {"parse": ["everyone", "roles", "users"]},
        "embeds": [{
            "title": (persona.get("title") or "🌤️ Morning Weather").replace("{me}", me),
            "description": desc,
            "color": EMBED_COLOR,
            "fields": spaced,
            "footer": {"text": (persona.get("footer") or "Forecast: Open-Meteo").replace("{me}", me)},
        }],
    }
    # The weather story (streaks, swings) still comes from the witty pool's
    # history; its template jokes are no longer posted: the only line under
    # @everyone is the one the model writes, or none.
    context = None
    if _witty:
        try:
            context = _witty.weather(observations, now)
        except Exception as e:
            log(f"weather story failed: {e}")
    content = cfg.get("message", "")
    model_entry = None
    if morning:
        try:
            line, cursors = morning_line(cfg, observations, context, now.date().isoformat())
        except Exception as e:  # the model path must never cost the report
            log(f"morning: model line failed: {e}")
            line, cursors = None, None
        if line and len(f"{content} {line}") <= 2000:
            model_entry = {"date": now.date().isoformat(), "line": line, "cursors": cursors or {}}
            content = f"{content} {line}".strip()
    if content:
        payload["content"] = content
    receipt = None
    if context:
        receipt = {"weather_snapshot": context["snapshot"]}
    if model_entry:
        receipt = dict(receipt or {}, model_morning=model_entry)
    return payload, failed, receipt


def post_webhook(url, payload):
    status, _ = http_json(url, body=payload)
    if not 200 <= status < 300:
        raise RuntimeError(f"webhook returned HTTP {status}")


def post_channel(channel_id, payload):
    # a bot can't rename itself per message, so the webhook-only key goes
    body = {k: v for k, v in payload.items() if k != "username"}
    status, _ = http_json(f"{DISCORD_API}/channels/{channel_id}/messages", body=body,
                          headers={"Authorization": f"Bot {BOT_TOKEN}"})
    if not 200 <= status < 300:
        raise RuntimeError(f"Discord returned HTTP {status}")


def deliver(cfg, payload):
    """Post as Weather-Bot when it can; the webhook is the fallback."""
    if BOT_TOKEN and cfg.get("channel_id"):
        post_channel(cfg["channel_id"], payload)
    elif cfg.get("webhook_url"):
        post_webhook(cfg["webhook_url"], payload)
    else:
        raise RuntimeError("set channel_id + DISCORD_BOT_TOKEN (or a webhook_url)")


def post_report(cfg):
    """Build and post the report. Returns (ok, detail)."""
    with _post_lock:
        return _post_report(cfg)


def _post_report(cfg):
    payload, failed, witty_entry = build_payload(cfg, morning=True)
    try:
        deliver(cfg, payload)
    except RuntimeError as e:
        return False, str(e)
    if witty_entry and _witty:
        try:
            _witty.commit(witty_entry)
        except Exception as e:
            log(f"witty commit failed (line may repeat): {e}")
    if witty_entry and witty_entry.get("model_morning"):
        commit_morning(witty_entry["model_morning"])
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


# ── gateway: answer pings ─────────────────────────────────────────────────────
REPLY_COOLDOWN = 8    # seconds per person; the channel burst cap below does the real limiting
FORECAST_TTL = 600
_forecasts = {}       # (lat, lon) -> (fetched monotonic, forecast)


def cached_forecast(loc, tz):
    key = (loc["lat"], loc["lon"])
    hit = _forecasts.get(key)
    if hit and time.monotonic() - hit[0] < FORECAST_TTL:
        return hit[1]
    fc = fetch_forecast(loc, tz)
    _forecasts[key] = (time.monotonic(), fc)
    return fc


def town_of(loc):
    return loc["name"].split(",")[0].strip()


def subject_of(loc):
    return loc.get("witty_subject") or (
        "Starks" if loc["name"].strip().casefold() == "greensboro, nc" else "")


def named_location(cfg, text):
    """The configured town (or its witty subject) named in the message, if any."""
    for loc in cfg["locations"]:
        for word in filter(None, (town_of(loc), subject_of(loc))):
            if re.search(rf"\b{re.escape(word.lower())}\b", text):
                return loc
    return None


def home_location(cfg, user_id):
    home = witty_messages.HOMES.get(str(user_id), "") if witty_messages else ""
    return next((l for l in cfg["locations"] if l["name"].casefold() == home.casefold()), None)


def match_location(cfg, text, user_id):
    """A town named in the message wins, then the asker's home town (persona)."""
    return named_location(cfg, text) or home_location(cfg, user_id)


def reply_facts(cfg, user_id, loc=None):
    """Weather fields for a reply line: the given town, else the asker's home,
    else the first configured town. A failed fetch leaves them blank ('?')."""
    loc = loc or home_location(cfg, user_id) or cfg["locations"][0]
    vals = {}
    try:
        fc = cached_forecast(loc, cfg["timezone"])
        vals = witty_messages.weather_values(fc) if witty_messages else {}
    except Exception as e:
        log(f"reply forecast failed for {loc['name']}: {e}")
    return dict(vals, town=town_of(loc), asker_town=town_of(loc))


FULL_RE = r"\bfull (weather |morning )?(report|briefing|forecast)\b"


def classify_ping(text):
    """What a ping wants: "full" (the briefing card), "weather" (an explicit
    weather ask) or "chat" (everything else). See witty_messages.FORECAST_KINDS
    for the patterns; naming a town or "rain" alone is just chat."""
    t = re.sub(r"<[@#][!&]?\d+>", " ", text or "").lower()
    if witty_messages:
        kind = witty_messages.classify(t)
    else:
        kind = "full" if re.search(FULL_RE, t) else "chat"
    return kind if kind in ("full", "weather") else "chat"


def weather_facts(cfg, user_id, text):
    """Forecast numbers for a weather ask: the town named in it, else the
    asker's home town, else every configured town (a list)."""
    t = re.sub(r"<[@#][!&]?\d+>", " ", text or "").lower()
    loc = match_location(cfg, t, user_id)
    if loc:
        return reply_facts(cfg, user_id, loc)
    return [reply_facts(cfg, user_id, l) for l in cfg["locations"]]


def plain_weather(asker, facts):
    """Numbers only, for a weather ask when the model can't be reached. Data,
    not a joke: no line here pretends to be WB talking."""
    rows = [f"{f['town']} {f.get('hi', '?')}°/{f.get('lo', '?')}°, feels {f.get('feels', '?')}°, "
            f"rain {f.get('rain', '?')}%" for f in (facts if isinstance(facts, list) else [facts]) if f]
    return f"{asker} " + " · ".join(rows) if rows else ""


# ── model-written replies (model_reply.py) ───────────────────────────────────
def handle_of(user_id, fallback="someone"):
    """The persona's @handle for a Discord id, else the given display name."""
    pings = witty_messages.PINGS if witty_messages else {}
    for name, uid in pings.items():
        if uid == str(user_id) and name.startswith("@"):
            return name
    return fallback


FORECAST_TEXT_RE = (r"\d+\s*°|\b\d+\s*%\s*(chance|rain|precip|humid)|\bfeels like\b|\b(high|low)s? (of )?\d+"
                    r"|\b\d+\s*mph\b|\buv (index )?\d")


def chat_line(author_id, author_name, text, is_bot=False, me="WB", bot_author=False):
    """One 'handle: text' line of context for the model: real ids become
    handles, the bot's own posts are labelled with its name, embeds are noted.
    A bot's post carrying forecast numbers (WB's own, the old webhook reports)
    is reduced to a note, so stale numbers from earlier in the chat can't be
    repeated as if they were today's."""
    who = me if is_bot else handle_of(author_id, "@" + str(author_name))
    body = re.sub(r"<@!?(\d+)>", lambda m: handle_of(m.group(1), "@someone"), text or "")
    body = re.sub(r"<@&\d+>", "@" + me, body)
    body = re.sub(r"\s+", " ", body).strip() or "[embed]"
    if (is_bot or bot_author) and (body == "[embed]" or re.search(FORECAST_TEXT_RE, body, re.I)):
        body = "[posted a forecast]"
    return f"{who}: {body[:300]}"


def model_answer(cfg, user_id, author_name, text, kind, recent, replied_to="", mentioned=(), own_id=""):
    """WB's reply to a ping, written by the model, or None. The prompt carries
    WB's notes on itself, the group, the asker and anyone mentioned (WBdb), the
    recent chat, the message being replied to, WB's last few replies, weather
    numbers only for a weather ask, and the message itself last."""
    if not (model_reply and witty_messages):
        return None
    roster = sorted(n for n in witty_messages.PINGS if n.startswith("@"))
    body = text or ""
    if own_id:
        body = re.sub(rf"<@!?{own_id}>", " ", body)
    body = re.sub(r"<@&\d+>", " ", body)
    body = re.sub(r"<@!?(\d+)>", lambda m: handle_of(m.group(1), "@someone"), body)
    message = witty_messages.redact(re.sub(r"\s+", " ", body).strip())
    asker = handle_of(user_id, "@" + str(author_name))
    self_notes = group_notes = ""
    people, own_recent = [], []
    db = memory_db() if memory_on(cfg) else None
    if db:
        try:
            self_notes, group_notes = db.profile("self")["notes"], db.profile("group")["notes"]
            for uid in dict.fromkeys([str(user_id)] + [str(m) for m in mentioned]):
                p = db.profile(uid)
                if p["notes"]:
                    people.append((handle_of(uid, p["handle"] or "@someone"), p["notes"]))
            own_recent = db.recent_replies(5)
        except Exception as e:
            log(f"wbdb: profiles unavailable ({e})")
    facts = None
    if kind == "weather":
        facts = weather_facts(cfg, user_id, text)
    elif kind == "full":
        facts = [reply_facts(cfg, user_id, l) for l in cfg["locations"]]
    system, user = model_reply.build_chat_prompt(
        witty_messages.BRIEF, roster, recent, asker, message, self_notes, group_notes, people,
        replied_to, own_recent, facts)
    raw = model_reply.ask(cfg, system, user, log=log)
    line = model_reply.clean_line(raw, witty_messages.PINGS.values()) if raw else ""
    if line and witty_messages.forgotten(line):
        log("claude: reply named a forgotten term; not sending it")
        return None
    return witty_messages.apply_pings(line) if line else None


NAG_INTERVAL = 600   # one "slow down" line per person per 10 min; the rest are ignored
_last_nag = {}       # user id -> monotonic time of their last pester line


def limit_line(cfg, user_id, kind="limit"):
    """One of the lines WB wrote ahead of time for when it can't call the model:
    "limit" (out of words for today) or "pester" (pinged again too fast). None
    if it hasn't written any yet; the caller reacts instead."""
    db = memory_db() if memory_on(cfg) else None
    try:
        line = db.line(kind) if db else None
    except Exception as e:
        log(f"wbdb: line unavailable ({e})")
        line = None
    if not line:
        return None
    line = line.replace("{name}", f"<@{user_id}>")
    return witty_messages.apply_pings(line) if witty_messages else line


def nag_ok(user_id, now=None):
    """True at most once per NAG_INTERVAL per person (and records it)."""
    now = time.monotonic() if now is None else now
    if now - _last_nag.get(user_id, -NAG_INTERVAL) < NAG_INTERVAL:
        return False
    _last_nag[user_id] = now
    return True


# ── morning line from the chat delta (model_reply.py) ────────────────────────
# Each morning the model reads what the group said since the previous morning
# post and writes the line that rides under @everyone. A per-channel cursor (the
# newest message id that the last *posted* line had read) lives in
# chat_cursor.json and moves only once a post lands, so a failed or retried
# morning re-reads the same delta. It reads over REST, not the gateway, so the
# delta is the same whether or not the bot was online overnight. The day's line
# is kept as a draft, so the 15-minute retries re-post the same text.
CHAT_CURSOR_PATH = os.path.join(DATA_DIR, "chat_cursor.json")
MORNING_DRAFT_PATH = os.path.join(DATA_DIR, "morning_draft.json")
MORNING_LOG_PATH = os.path.join(DATA_DIR, "morning_lines.jsonl")
MORNING_LOG_MAX = 60
FIRST_LOOKBACK = 86400   # no cursor yet: read the last day
DISCORD_EPOCH_MS = 1420070400000
_self_id = {}


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def snowflake_at(epoch_seconds):
    """The smallest Discord id at a moment, for 'after' queries by time."""
    return str(max(0, int(epoch_seconds * 1000) - DISCORD_EPOCH_MS) << 22)


def morning_channels(cfg):
    """The post channel and any reply channels, deduplicated."""
    out = []
    for c in [cfg.get("channel_id")] + list(cfg.get("reply_channels") or []):
        c = str(c or "")
        if re.fullmatch(r"\d{1,20}", c) and c not in out:
            out.append(c)
    return out


def _discord_get(path):
    _, data = http_json(f"{DISCORD_API}{path}", headers={"Authorization": f"Bot {BOT_TOKEN}"}, tries=2)
    return data


def bot_user_id():
    """Weather-Bot's own user id, to label its messages; '' (and asked again
    next time) if Discord can't be reached."""
    if not _self_id.get("id") and BOT_TOKEN:
        try:
            _self_id["id"] = str((_discord_get("/users/@me") or {}).get("id", ""))
        except Exception as e:
            log(f"could not read the bot's own id: {e}")
    return _self_id.get("id", "")


def fetch_since(channel_id, after, limit):
    """Up to `limit` of the newest messages in a channel with ids above
    `after`, oldest first. Pages backwards from now so a busy night keeps its
    latest messages, and stops at the cursor."""
    got, before = [], None
    while len(got) < limit:
        n = min(100, limit - len(got))
        qs = urllib.parse.urlencode({"limit": n, **({"before": before} if before else {})})
        page = sorted(_discord_get(f"/channels/{channel_id}/messages?{qs}") or [],
                      key=lambda m: int(m["id"]), reverse=True)
        fresh = [m for m in page if int(m["id"]) > int(after)]
        got.extend(fresh)
        if len(fresh) < len(page) or len(page) < n:
            break
        before = page[-1]["id"]
    return sorted(got, key=lambda m: int(m["id"]))


def chat_delta(cfg, limit, now=None):
    """('handle: text' lines since the last posted morning line, oldest first;
    {channel: newest id read}) across the post and reply channels, or every
    channel WBdb reads when memory is on. Forgotten messages never make it in."""
    cursors = read_json(CHAT_CURSOR_PATH, {})
    first = snowflake_at((now or time.time()) - FIRST_LOOKBACK)
    me = "WB"
    own = bot_user_id() if BOT_TOKEN else ""
    msgs, newest = [], {}
    for ch in (memory_channels(cfg) if memory_on(cfg) else morning_channels(cfg)):
        try:
            got = fetch_since(ch, cursors.get(ch) or first, limit)
        except Exception as e:
            log(f"morning: skipping channel {ch} ({e})")
            continue
        if got:
            newest[ch] = got[-1]["id"]
        msgs.extend(dict(m, _channel=ch) for m in got)
    tagged = len(newest) > 1
    msgs = sorted(msgs, key=lambda m: int(m["id"]))[-limit:] if limit else []
    lines = []
    for m in msgs:
        a = m.get("author") or {}
        text = m.get("content") or ""
        if not text.strip() and not m.get("embeds"):
            continue   # joins, pins, stickers
        if witty_messages and witty_messages.forgotten(text, a.get("global_name"), a.get("username"),
                                                       user_id=a.get("id")):
            continue
        line = chat_line(a.get("id", ""), a.get("global_name") or a.get("username") or "someone",
                         text, str(a.get("id")) == own, me, bool(a.get("bot")))
        lines.append((channel_tag(m["_channel"]) if tagged else "") + line)
    return lines, newest


def describe_event(context):
    ev = (context or {}).get("event") or {}
    if not ev.get("kind"):
        return ""
    facts = ", ".join(f"{k} {v}" for k, v in (ev.get("facts") or {}).items())
    return ev["kind"].replace("_", " ") + (f" ({facts})" if facts else "")


def morning_line(cfg, observations, context, today):
    """(line, cursors) written by the model from the chat delta, or (None, None)
    for the template. Reuses today's draft so retries post the same line."""
    if not (model_reply and witty_messages) or model_reply.decide(cfg, "morning") != "model":
        return None, None
    draft = read_json(MORNING_DRAFT_PATH, {})
    if draft.get("date") == today and draft.get("line"):
        return draft["line"], draft.get("cursors") or {}
    s = model_reply.settings(cfg)
    try:
        chat, cursors = chat_delta(cfg, s["morning_history"]) if BOT_TOKEN else ([], {})
    except Exception as e:
        log(f"morning: chat read failed ({e}); writing from the weather alone")
        chat, cursors = [], {}
    weather = [f"{town_of(loc)}: high {fc['hi']:.0f}°F, low {fc['lo']:.0f}°F, feels like {fc['feels']:.0f}°F, "
               f"{str(fc['cond']).lower()}, rain {fc['rain']:.0f}%" for loc, fc in observations if fc]
    recent = [e.get("line", "") for e in read_jsonl(MORNING_LOG_PATH)]
    roster = sorted(n for n in witty_messages.PINGS if n.startswith("@"))
    self_notes, group_notes = memory_notes(cfg)
    system, user = model_reply.build_morning_prompt(witty_messages.BRIEF, roster, chat, weather,
                                                    describe_event(context), recent, self_notes, group_notes)
    raw = model_reply.ask(cfg, system, user, log=log, effort=s["morning_effort"],
                          timeout=model_reply.SLOW_TIMEOUT, retries=model_reply.SLOW_RETRIES,
                          max_tokens=max(s["max_tokens"], 2048))
    line = model_reply.clean_line(raw, witty_messages.PINGS.values(), model_reply.MORNING_MAX_CHARS) if raw else ""
    if not line or witty_messages.forgotten(line):
        return None, None
    line = witty_messages.apply_pings(line)
    try:
        write_json(MORNING_DRAFT_PATH, {"date": today, "line": line, "cursors": cursors})
    except OSError as e:
        log(f"morning: draft not saved ({e}); a retry will ask again")
    log(f"morning: model line from {len(chat)} chat message(s)")
    return line, cursors


# ── WBdb: what WB learns about the group (wbdb.py) ───────────────────────────
# With memory on, WB reads every text channel in the server (minus
# memory_skip_channels and any that answer 403) forward from the moment it first
# sees each one: there is no history import, it gets to know the group day by
# day. Every LEARN_HOUR it has the model update its notes on each person who
# posted that day, on the group, and on itself (what landed: the reactions on its
# replies), then writes a fresh set of limit/pester lines in its current voice.
# Profiles start from a private seed file (SEED_PATH, loaded once). Anything
# naming the persona's "forget" list is never stored and is purged if it was.
# A nightly copy goes to WBDB_BACKUP_DIR.
WBDB_PATH = os.path.join(DATA_DIR, "wb.sqlite")
SEED_PATH = os.path.join(DATA_DIR, "wb_seed.json")
WBDB_BACKUP_DIR = os.environ.get("WBDB_BACKUP_DIR", "/backup")
INGEST_EVERY = 900
LEARN_HOUR, BACKUP_KEEP = 3, 7
LEARN_RESERVE = 50           # calls left for pings when learning runs
LEARN_MIN_MESSAGES = 3       # fewer than this in a day (and no pings): profile unchanged
CHANNELS_TTL = 3600          # re-list the server's channels hourly
_wb = {"db": None, "error": ""}
_wb_lock = threading.Lock()      # opening the db
_ingest_lock = threading.Lock()  # one reader of Discord at a time
_channels = {"at": None, "ids": [], "names": {}}   # the server's text channels, cached
_unreadable = set()                   # channels that answered 403 (until restart)


def memory_on(cfg):
    return bool(model_reply and wbdb and model_reply.settings(cfg)["memory"])


def memory_db():
    """The open WBdb, or None (memory off for this call; replies go without notes)."""
    with _wb_lock:
        if _wb["db"] is None and wbdb:
            try:
                _wb["db"] = wbdb.WBDB(WBDB_PATH)
                _wb["error"] = ""
                if _wb["db"].note:
                    log(f"wbdb: {_wb['db'].note}")
            except Exception as e:
                _wb["error"] = f"{type(e).__name__}: {e}"
                log(f"wbdb: open failed - {_wb['error']}")
        return _wb["db"]


def memory_notes(cfg):
    """(self notes, group notes) for the morning line, or ('', '')."""
    db = memory_db() if memory_on(cfg) else None
    try:
        return (db.profile("self")["notes"], db.profile("group")["notes"]) if db else ("", "")
    except Exception as e:
        log(f"wbdb: notes read failed: {e}")
        return "", ""


def memory_channels(cfg):
    """Every text channel in the server WB should read: the post and reply
    channels, plus the guild's listing (cached), minus memory_skip_channels and
    any the bot was refused. If Discord can't list them, the last list stands."""
    now = time.monotonic()
    if cfg.get("guild_id") and (_channels["at"] is None or now - _channels["at"] > CHANNELS_TTL):
        try:
            listed = _discord_get(f"/guilds/{cfg['guild_id']}/channels") or []
            listed = [c for c in sorted(listed, key=lambda c: c.get("position", 0)) if c.get("type") in (0, 5)]
            _channels["ids"] = [str(c["id"]) for c in listed]   # text, announcement
            _channels["names"] = {str(c["id"]): str(c.get("name") or "") for c in listed}
            _channels["at"] = now
        except Exception as e:
            log(f"wbdb: could not list channels ({e})")
    skip = set(model_reply.settings(cfg)["memory_skip_channels"]) | _unreadable
    return [c for c in dict.fromkeys(morning_channels(cfg) + _channels["ids"]) if c not in skip]


def channel_tag(channel_id):
    """'[#name] ' for a context line, so the model can tell conversations apart."""
    name = _channels.get("names", {}).get(str(channel_id), "")
    return f"[#{name}] " if name else f"[#channel-{str(channel_id)[-4:]}] "


def refused(channel_id, error):
    """Note a channel the bot may not read, once, and stop trying it."""
    if "403" in str(error):
        if channel_id not in _unreadable:
            log(f"wbdb: channel {channel_id} is not readable; skipping it")
        _unreadable.add(channel_id)
        return True
    return False


def is_forgotten(text="", *names, user_id=None):
    return bool(witty_messages and witty_messages.forgotten(text, *names, user_id=user_id))


def to_row(m, channel_id, own_id=""):
    """A Discord API message -> a WBdb row (mentions as handles, embeds noted),
    or None if it names anything on the persona's forget list."""
    a = m.get("author") or {}
    text = m.get("content") or ""
    if is_forgotten(text, a.get("global_name"), a.get("username"), user_id=a.get("id")):
        return None
    if not text.strip() and m.get("embeds"):
        text = "[embed]"
    body = re.sub(r"<@!?(\d+)>", lambda x: handle_of(x.group(1), "@someone"), text)
    return {"id": int(m["id"]), "channel_id": str(channel_id), "author_id": str(a.get("id", "")),
            "author": handle_of(a.get("id", ""), "@" + str(a.get("global_name") or a.get("username") or "someone")),
            "is_bot": str(a.get("id")) == own_id or bool(a.get("bot")), "ts": m.get("timestamp") or "",
            "content": re.sub(r"<@&\d+>", "@role", body).strip()}


def row_line(r, own_id="", me="WB"):
    who = me if own_id and r["author_id"] == own_id else r["author"]
    body = re.sub(r"\s+", " ", r["content"]).strip() or "[blank]"
    return f"{who}: {body[:300]}"


def ingest(db, cfg, channels=None):
    """Read channels (all of them by default) forward from their stored
    position. A channel seen for the first time starts at its newest message:
    nothing older is imported. Returns new rows."""
    own = bot_user_id()
    new = 0
    for ch in (memory_channels(cfg) if channels is None else channels):
        start = db.newest(ch)
        try:
            if start is None:
                latest = _discord_get(f"/channels/{ch}/messages?limit=1") or []
                db.mark(ch, int(latest[0]["id"]) if latest else 0)
                continue
            got = fetch_since(ch, str(start), 1000)
        except Exception as e:
            if not refused(ch, e):
                log(f"wbdb: read failed for channel {ch}: {e}")
            continue
        if got:
            new += db.add([r for r in (to_row(m, ch, own) for m in got) if r])
            db.mark(ch, max(int(m["id"]) for m in got))
    db.set_meta("last_ingest_at", datetime.now().isoformat(timespec="seconds"))
    return new


def learn_ok(cfg):
    """Learning may spend a call: memory is on, the model is usable, and today's
    usage leaves LEARN_RESERVE calls and a third of the token cap for pings."""
    if not model_reply or model_reply.decide(cfg, "learn") != "model":
        return False
    s = model_reply.settings(cfg)
    u = model_reply.usage(cfg.get("timezone", "UTC"))
    if u["calls"] >= s["daily_cap"] - min(LEARN_RESERVE, s["daily_cap"] // 3):
        return False
    tokens = u["input_tokens"] + u["output_tokens"]
    return not s["daily_tokens"] or tokens < s["daily_tokens"] - s["daily_tokens"] // 3


def _ask_notes(cfg, system, user):
    raw = model_reply.ask(cfg, system, user, log=log, effort="low", max_tokens=3000,
                          timeout=model_reply.SLOW_TIMEOUT, retries=model_reply.SLOW_RETRIES)
    if not raw:
        return None
    return "\n".join(l for l in raw.strip().splitlines() if not is_forgotten(l))


def _reactions(p):
    counts = json.loads(p.get("reactions") or "{}")
    return (" [reactions: " + " ".join(f"{e}x{n}" for e, n in counts.items()) + "]") if counts else ""


def learn(db, cfg):
    """The nightly pass: update each active person's notes, the group's, WB's
    own, and its ready-made lines. Messages and pings it used are marked so the
    next night starts where this one stopped; only what it got through is
    marked, so a pass cut short by the budget picks up the rest tomorrow.
    Returns calls made."""
    msgs = db.unlearned(5000)
    pings = db.unlearned_pings()
    brief = witty_messages.BRIEF if witty_messages else ""
    roster = sorted(n for n in (witty_messages.PINGS if witty_messages else {}) if n.startswith("@"))
    own = bot_user_id()
    by_person = {}
    for r in msgs:
        if not r["is_bot"]:
            by_person.setdefault(r["author_id"], []).append(r)
    asks = {}
    for p in pings:
        asks.setdefault(p["author_id"], []).append(f"{p['text']} -> {p['reply'] or '(no reply)'}{_reactions(p)}")
    calls, done_msgs, done_pings = 0, [], []
    people = sorted(set(by_person) | set(asks), key=lambda u: -len(by_person.get(u, [])))
    for uid in people:
        rows = by_person.get(uid, [])
        if len(rows) < LEARN_MIN_MESSAGES and uid not in asks:
            done_msgs += [r["id"] for r in rows]
            continue
        if not learn_ok(cfg):
            break
        prof = db.profile(uid)
        handle = handle_of(uid, rows[-1]["author"] if rows else prof["handle"] or "@someone")
        notes = _ask_notes(cfg, *model_reply.build_person_prompt(
            brief, handle, prof["notes"], [row_line(r, own) for r in rows][-300:], asks.get(uid, [])[-20:]))
        calls += 1
        if notes is None:
            break
        db.set_profile(uid, notes, handle)
        done_msgs += [r["id"] for r in rows]
        done_pings += [p["message_id"] for p in pings if p["author_id"] == uid]
    if msgs and learn_ok(cfg):
        notes = _ask_notes(cfg, *model_reply.build_group_prompt(
            brief, roster, db.profile("group")["notes"],
            [channel_tag(r["channel_id"]) + row_line(r, own) for r in msgs][-400:]))
        calls += 1
        if notes is not None:
            db.set_profile("group", notes)
    if pings and learn_ok(cfg):
        exchanges = [f"{p['author']}: {p['text']} -> you: {p['reply'] or '(no reply)'}{_reactions(p)}"
                     for p in pings][-60:]
        notes = _ask_notes(cfg, *model_reply.build_self_prompt(brief, db.profile("self")["notes"], exchanges))
        calls += 1
        if notes is not None:
            db.set_profile("self", notes)
    if learn_ok(cfg):
        raw = model_reply.ask(cfg, *model_reply.build_lines_prompt(
            brief, db.profile("self")["notes"], db.profile("group")["notes"]),
            log=log, effort="low", max_tokens=2000, timeout=model_reply.SLOW_TIMEOUT,
            retries=model_reply.SLOW_RETRIES)
        calls += 1
        for kind, texts in model_reply.parse_lines(raw).items():
            texts = [t for t in texts if "{name}" in t and not is_forgotten(t)]
            if texts:
                db.set_lines(kind, texts)
    db.mark_learned(done_msgs + [r["id"] for r in msgs if r["is_bot"]], done_pings)
    db.prune()
    log(f"wbdb: learned from {len(done_msgs)} message(s) and {len(done_pings)} ping(s) in {calls} call(s)")
    return calls


def learn_due(db, now):
    return now.hour >= LEARN_HOUR and not str(db.get_meta("last_learn") or "").startswith(now.date().isoformat())


def load_seed(db):
    """Load the private seed profiles once (a profile already there is kept)."""
    try:
        with open(SEED_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return 0
    except (OSError, ValueError) as e:
        log(f"wbdb: seed unreadable ({e})")
        return 0
    n = db.seed(data)
    if n:
        log(f"wbdb: seeded {n} profile(s) from {os.path.basename(SEED_PATH)}")
    return n


def memory_pass(cfg):
    """One round of the memory loop: seed, forget, read new, learn, back up."""
    db = memory_db()
    if not db or not BOT_TOKEN:
        return
    load_seed(db)
    if witty_messages and (witty_messages.FORGET["terms"] or witty_messages.FORGET["user_ids"]):
        gone = db.purge(lambda t: is_forgotten(t), witty_messages.FORGET["user_ids"])
        if gone:
            log(f"wbdb: purged {gone} row(s) on the forget list")
    with _ingest_lock:
        n = ingest(db, cfg)
    now = datetime.now(ZoneInfo(cfg["timezone"]))
    if learn_due(db, now):
        try:
            learn(db, cfg)
        finally:
            db.set_meta("last_learn", now.isoformat(timespec="seconds"))
        try:
            log(f"wbdb: backup {db.backup(WBDB_BACKUP_DIR, now.date().isoformat(), BACKUP_KEEP)}")
        except Exception as e:
            log(f"wbdb: backup failed: {e}")
    if n:
        log(f"wbdb: +{n} message(s)")


def memory_loop():
    while True:
        cfg = load_config()
        if memory_on(cfg):
            try:
                memory_pass(cfg)
            except Exception as e:
                log(f"wbdb: pass failed: {e}")
        time.sleep(INGEST_EVERY)


def memory_health(cfg):
    """A small summary for /health: off, error, or counts and freshness."""
    if not memory_on(cfg):
        return {"enabled": False}
    db = memory_db()
    if not db:
        return {"enabled": True, "error": _wb["error"]}
    try:
        return {"enabled": True, **db.stats(), "unreadable": sorted(_unreadable)}
    except Exception as e:
        return {"enabled": True, "error": str(e)}


def log_exchange(cfg, msg, reply_msg, content):
    """Record a ping and WB's answer, so reactions to it can be counted."""
    db = memory_db() if memory_on(cfg) else None
    if not db or is_forgotten(msg.content or ""):
        return
    try:
        db.log_ping(msg.id, msg.channel.id, msg.author.id,
                    handle_of(msg.author.id, "@" + str(msg.author.display_name)),
                    chat_line(msg.author.id, msg.author.display_name, msg.content).split(": ", 1)[-1],
                    getattr(reply_msg, "id", ""), content or "")
    except Exception as e:
        log(f"wbdb: ping log failed: {e}")


def read_jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except (OSError, ValueError):
        return []


def commit_morning(entry):
    """After the post lands: advance the cursors, log the line, drop the draft."""
    try:
        cursors = read_json(CHAT_CURSOR_PATH, {})
        cursors.update(entry.get("cursors") or {})
        write_json(CHAT_CURSOR_PATH, cursors)
        lines = read_jsonl(MORNING_LOG_PATH) + [{"date": entry.get("date"), "line": entry.get("line")}]
        tmp = MORNING_LOG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for e in lines[-MORNING_LOG_MAX:]:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, MORNING_LOG_PATH)
        if os.path.exists(MORNING_DRAFT_PATH):
            os.remove(MORNING_DRAFT_PATH)
    except OSError as e:
        log(f"morning: commit failed (tomorrow may re-read some chat): {e}")


# ── gateway helpers (pure, so they can be tested without discord.py) ─────────
BURST_LIMIT, BURST_WINDOW = 6, 60   # replies per channel per minute, all askers together
_last_reply = {}   # user id -> monotonic time of their last answered ping
_burst = {}        # channel id -> recent reply times


def addressed(msg, me):
    """Mentioned directly, through the bot's own managed role (@Weather-Bot the
    role, which is what the mention picker often inserts), or replied to."""
    if any(getattr(u, "id", None) == me.id for u in getattr(msg, "mentions", []) or []):
        return True
    for role in getattr(msg, "role_mentions", []) or []:
        if getattr(getattr(role, "tags", None), "bot_id", None) == me.id:
            return True
    ref = getattr(getattr(msg, "reference", None), "resolved", None)
    return getattr(getattr(ref, "author", None), "id", None) == me.id


def in_scope(cfg, msg):
    """Only the configured server (and channels, if listed) get answers, so a
    test-server profile can't leak replies into the live one or vice versa."""
    guild = str(cfg.get("guild_id") or "")
    if guild and str(getattr(getattr(msg, "guild", None), "id", "")) != guild:
        return False
    chans = cfg.get("reply_channels") or []
    return not chans or str(msg.channel.id) in chans


def throttled(user_id, channel_id, now=None):
    """Why this ping should be ignored, or False: "cooldown" if the asker pinged
    again inside the per-person cooldown, "burst" if the channel has hit its
    cap. Records the reply otherwise."""
    now = time.monotonic() if now is None else now
    if now - _last_reply.get(user_id, -REPLY_COOLDOWN) < REPLY_COOLDOWN:
        return "cooldown"
    recent = [t for t in _burst.get(channel_id, []) if now - t < BURST_WINDOW]
    if len(recent) >= BURST_LIMIT:
        _burst[channel_id] = recent
        return "burst"
    recent.append(now)
    _burst[channel_id] = recent
    _last_reply[user_id] = now
    return False


# ── inbox + say: the lane for a considered reply ─────────────────────────────
# Every ping that didn't ask for weather is appended here with the line the bot
# answered on the spot, so a person (or Claude in a session Peter drives) can
# follow up with a real answer through POST /say. Read with GET /inbox.
_inbox_lock = threading.Lock()


def inbox_read():
    try:
        with open(INBOX_PATH, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except OSError:
        return []


def _inbox_write(entries):
    tmp = INBOX_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in entries[-INBOX_MAX:]:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, INBOX_PATH)


def inbox_add(entry):
    with _inbox_lock:
        try:
            _inbox_write(inbox_read() + [entry])
        except OSError as e:
            log(f"inbox write failed: {e}")


def inbox_pending(limit=50):
    return [e for e in inbox_read() if not e.get("answered")][-limit:]


def inbox_mark(message_ids, how="acked"):
    ids = {str(i) for i in message_ids}
    with _inbox_lock:
        entries = inbox_read()
        n = 0
        for e in entries:
            if str(e.get("id")) in ids and not e.get("answered"):
                e["answered"] = how
                n += 1
        if n:
            _inbox_write(entries)
    return n


def say(cfg, content, channel_id=None, reply_to=None):
    """Post `content` as Weather-Bot, as a reply to `reply_to` if given. Persona
    names become mentions; @everyone/@here are refused outright and could not
    ping anyway (allowed_mentions is users-only). Returns the new message id."""
    if not BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN not set — cannot speak")
    content = str(content or "").strip()
    if not content or len(content) > 2000:
        raise ValueError("content must be 1–2000 characters")
    if re.search(r"@(everyone|here)\b", content):
        raise ValueError("@everyone/@here are not allowed in replies")
    channel = str(channel_id or cfg.get("channel_id") or "")
    if not re.fullmatch(r"\d{1,20}", channel):
        raise ValueError("channel_id required (none configured)")
    if reply_to is not None and not re.fullmatch(r"\d{1,20}", str(reply_to)):
        raise ValueError("reply_to must be a message id")
    body = {"content": witty_messages.apply_pings(content) if witty_messages else content,
            "allowed_mentions": {"parse": ["users"], "replied_user": True}}
    if reply_to:
        body["message_reference"] = {"message_id": str(reply_to), "fail_if_not_exists": False}
    status, posted = http_json(f"{DISCORD_API}/channels/{channel}/messages", body=body,
                               headers={"Authorization": f"Bot {BOT_TOKEN}"}, tries=1)
    if not 200 <= status < 300:
        raise RuntimeError(f"Discord returned HTTP {status}")
    if reply_to:
        inbox_mark([reply_to], "said")
    log(f"say: posted {len(content)} chars to channel {channel}" + (f" replying to {reply_to}" if reply_to else ""))
    return str((posted or {}).get("id", ""))


def run_gateway():
    """Keep Weather-Bot logged in and answer mentions/replies. Optional: no token
    or no discord.py just means no replies; the daily report is unaffected."""
    if not BOT_TOKEN:
        log("DISCORD_BOT_TOKEN not set — not answering pings")
        return
    try:
        import asyncio
        import discord
    except ImportError as e:
        log(f"discord.py unavailable ({e}) — not answering pings")
        return

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions(
        everyone=False, roles=False, users=True, replied_user=True))

    @client.event
    async def on_ready():
        with _lock:
            _status["gateway"] = f"connected as {client.user}"
        log(f"gateway: connected as {client.user}")

    @client.event
    async def on_message(msg):
        if msg.author.bot or client.user is None or not addressed(msg, client.user):
            return
        cfg = load_config()
        if not in_scope(cfg, msg):
            return
        why = throttled(msg.author.id, msg.channel.id)
        if why:
            log(f"gateway: throttled ({why}) {msg.author} in #{msg.channel}")
            if why == "cooldown" and nag_ok(msg.author.id):   # one "slow down", then silence
                line = limit_line(cfg, msg.author.id, "pester")
                try:
                    if line:
                        await msg.reply(line)
                except Exception as e:
                    log(f"gateway: pester reply failed: {e}")
            return
        try:
            loop = asyncio.get_running_loop()
            kind = classify_ping(msg.content)
            content, embed, source = None, None, "none"
            async with msg.channel.typing():
                if kind == "full":
                    payload, _, _ = await loop.run_in_executor(None, build_payload, cfg)
                    embed = payload["embeds"][0]
                how = model_reply.decide(cfg, kind) if model_reply else None
                if how == "model":
                    me = "WB"
                    recent = []
                    n = model_reply.settings(cfg)["history"]
                    if n:
                        async for m in msg.channel.history(limit=n, before=msg):
                            if is_forgotten(m.content, m.author.display_name, m.author.name, user_id=m.author.id):
                                continue
                            recent.append(chat_line(m.author.id, m.author.display_name, m.content,
                                                    m.author.id == client.user.id, me, m.author.bot))
                        recent.reverse()
                    replied_to = ""
                    ref = getattr(getattr(msg, "reference", None), "resolved", None)
                    if ref is not None and getattr(ref, "author", None) is not None and not is_forgotten(
                            ref.content, user_id=ref.author.id):
                        replied_to = chat_line(ref.author.id, ref.author.display_name, ref.content,
                                               ref.author.id == client.user.id, me, ref.author.bot)
                    mentioned = [u.id for u in msg.mentions if not u.bot]
                    content = await loop.run_in_executor(
                        None, model_answer, cfg, msg.author.id, msg.author.display_name, msg.content, kind,
                        recent, replied_to, mentioned, str(client.user.id))
                    source = "claude" if content else source
                    if not content and model_reply.spent(cfg):   # this very call ran out of budget or credit
                        how = "limit"
                if how == "limit":
                    content = await loop.run_in_executor(None, limit_line, cfg, msg.author.id)
                    source = "limit" if content else source
                if not content and kind == "weather":   # numbers, never a canned joke
                    content = await loop.run_in_executor(None, lambda: plain_weather(
                        f"<@{msg.author.id}>", weather_facts(cfg, msg.author.id, msg.content)))
                    source = "numbers" if content else source
            if not content and not embed:
                await msg.add_reaction("💤")   # WB can't think right now; says nothing it didn't write
                log(f"gateway: no reply for {msg.author} in #{msg.channel} ({kind}); reacted")
                return
            sent = await msg.reply(content, embed=discord.Embed.from_dict(embed) if embed else None)
            log(f"gateway: answered {msg.author} in #{msg.channel} ({kind}, {source})")
            if source == "claude":
                await loop.run_in_executor(None, log_exchange, cfg, msg, sent, content)
            if kind == "chat":
                inbox_add({"ts": datetime.now().isoformat(timespec="seconds"), "id": str(msg.id),
                           "channel_id": str(msg.channel.id), "channel": str(msg.channel),
                           "guild_id": str(getattr(msg.guild, "id", "")),
                           "author": str(msg.author), "author_id": str(msg.author.id),
                           "text": msg.content, "kind": kind, "answered_with": content or "",
                           "source": source})
        except Exception as e:
            log(f"gateway: reply failed: {e}")

    async def on_reaction(payload, delta):
        """Count reactions on WB's replies: the nightly learning reads them."""
        if client.user is None or payload.user_id == client.user.id:
            return
        cfg = load_config()
        db = memory_db() if memory_on(cfg) else None
        if db:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, db.react, payload.message_id, str(payload.emoji), delta)
            except Exception as e:
                log(f"wbdb: reaction not recorded: {e}")

    @client.event
    async def on_raw_reaction_add(payload):
        await on_reaction(payload, 1)

    @client.event
    async def on_raw_reaction_remove(payload):
        await on_reaction(payload, -1)

    while True:
        try:
            client.run(BOT_TOKEN, log_handler=None)
            return
        except discord.LoginFailure as e:
            log(f"gateway: login rejected ({e}) — check DISCORD_BOT_TOKEN")
            with _lock:
                _status["gateway"] = "login rejected"
            return
        except Exception as e:
            with _lock:
                _status["gateway"] = f"disconnected: {e}"
            log(f"gateway: crashed ({e}); reconnecting in 60s")
            time.sleep(60)


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
                             "post_time": cfg["post_time"], "timezone": cfg["timezone"],
                             "guild_id": cfg.get("guild_id", ""), "channel_id": cfg.get("channel_id", ""),
                             "active_profile": cfg.get("active_profile", ""),
                             "inbox_pending": len(inbox_pending(INBOX_MAX)),
                             "claude": model_reply.status(cfg) if model_reply else None,
                             "wbdb": memory_health(cfg), **st})
        elif path in ("/memory", "/profiles"):
            db = memory_db() if memory_on(cfg) else None
            if not db:
                return self._send(200, {"enabled": memory_on(cfg), "error": _wb["error"]})
            self._send(200, {"enabled": True, **db.stats(), "profiles": db.profiles()})
        elif path == "/inbox":
            limit = urllib.parse.parse_qs(query).get("limit", ["50"])[0]
            limit = int(limit) if limit.isdigit() else 50
            self._send(200, {"pending": inbox_pending(limit),
                             "kinds": list(witty_messages.REPLY_KINDS) if witty_messages else []})
        elif path == "/config":
            pub = dict(cfg)
            pub["webhook_url"] = mask_webhook(cfg.get("webhook_url", ""))
            pub["webhook_configured"] = bool(cfg.get("webhook_url"))
            self._send(200, pub)
        elif path == "/preview":
            try:
                payload, failed, _entry = build_payload(cfg)  # peek only — never consumes
                self._send(200, {"payload": payload, "failed": failed})
            except Exception as e:
                self._send(502, {"error": str(e)})
        elif path == "/witty":
            if _witty is None:
                return self._send(200, {"available": False,
                                        "reason": "witty module failed to load"})
            try:
                self._send(200, {"available": True,
                                 "enabled": bool(cfg.get("witty_enabled")),
                                 "names": cfg.get("witty_names") or [],
                                 **_witty.status(cfg.get("witty_names") or [])})
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
        self._update_config(incoming)

    def _update_config(self, incoming):
        current = load_config()
        merged = {**current, **{k: v for k, v in incoming.items()
                                if k in ("enabled", "post_time", "timezone", "locations", "channel_id",
                                         "webhook_url", "message", "witty_enabled", "witty_names",
                                         "guild_id", "reply_channels", "persona", "profiles",
                                         "active_profile", "claude")}}
        # masked/blank webhook in the payload means "keep the current one"
        wh = incoming.get("webhook_url", "")
        if not wh or "…" in wh:
            merged["webhook_url"] = current.get("webhook_url", "")
        err = validate_config(merged)
        if err:
            return self._send(400, {"error": err})
        # choosing (or editing) a profile copies its server fields into the config
        if merged.get("active_profile") and (merged["active_profile"] != current.get("active_profile")
                                             or "profiles" in incoming):
            apply_profile(merged)
        with _lock:
            save_config(merged)
        _wake.set()  # reschedule immediately
        if merged.get("persona") != current.get("persona"):
            reload_persona(merged)
        log(f"config updated: enabled={merged['enabled']} post_time={merged['post_time']} "
            f"locations={[l['name'] for l in merged['locations']]} "
            f"profile={merged.get('active_profile') or '-'} guild={merged.get('guild_id') or 'any'}")
        pub = dict(merged)
        pub["webhook_url"] = mask_webhook(merged.get("webhook_url", ""))
        pub["webhook_configured"] = bool(merged.get("webhook_url"))
        self._send(200, pub)

    def do_POST(self):
        path = self.path.partition("?")[0]
        if path == "/send":
            cfg = load_config()
            ok, detail = post_report(cfg)  # note: a posted witty line is consumed
            with _lock:
                _status["last_post_at"] = datetime.now(ZoneInfo(cfg["timezone"])).isoformat(timespec="seconds")
                _status["last_status"] = f"manual: {detail}" if ok else f"manual failed: {detail}"
            log(f"manual send: {'ok — ' + detail if ok else 'FAILED — ' + detail}")
            self._send(200 if ok else 502, {"ok": ok, "detail": detail})
        elif path == "/witty/reroll":
            cfg = load_config()
            if _witty is None:
                return self._send(400, {"error": "witty messages not configured"})
            try:
                # Use exactly the same all-location context as preview/send.
                _, _, receipt = build_payload(cfg)
                event = None
                if receipt and receipt.get("event"):
                    event = json.loads(receipt["signature"])
                out = _witty.reroll(cfg.get("witty_names") or [],
                                   now=datetime.now(ZoneInfo(cfg["timezone"])), event=event)
            except Exception as e:
                return self._send(502, {"error": str(e)})
            self._send(200 if out.get("ok") else 400, out)
        elif path == "/say":
            try:
                body = self._body()
                mid = say(load_config(), body.get("content"), body.get("channel_id"), body.get("reply_to"))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(502, {"error": str(e)})
            self._send(200, {"ok": True, "message_id": mid})
        elif path == "/memory/reset":
            # forget everything WB learned; the seed profiles load again on the next pass
            db = memory_db()
            if not db:
                return self._send(503, {"error": _wb["error"] or "wbdb unavailable"})
            with _ingest_lock:
                db.reset()
                n = load_seed(db)
            log(f"wbdb: reset; {n} seed profile(s) loaded")
            self._send(200, {"reset": True, "seeded": n})
        elif path == "/profiles":
            # {"subject": "<user id>|group|self", "notes": "..."}: hand-edit one profile
            try:
                body = self._body()
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            subject, notes = str(body.get("subject") or ""), body.get("notes")
            db = memory_db()
            if not db:
                return self._send(503, {"error": _wb["error"] or "wbdb unavailable"})
            if not (subject in ("group", "self") or subject.isdigit()) or not isinstance(notes, str):
                return self._send(400, {"error": "need subject (user id, group or self) and notes"})
            db.set_profile(subject, notes, body.get("handle"), source="edited", limit=6000)
            self._send(200, {"ok": True, "profile": db.profile(subject)})
        elif path == "/inbox/ack":
            try:
                ids = self._body().get("ids") or []
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            self._send(200, {"acked": inbox_mark(ids)})
        elif path == "/profile":
            # shortcut for PUT /config {"active_profile": name}: switch servers in one call
            try:
                name = str(self._body().get("name") or "")
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            self._update_config({"active_profile": name})
        else:
            self._send(404, {"error": "not found"})


def main(argv):
    if "--dry-run" in argv or "--once" in argv:
        try:
            cfg = load_config()
        except OSError:  # DATA_DIR not writable (e.g. running outside the container)
            cfg = {**DEFAULT_CONFIG, "webhook_url": os.environ.get("DISCORD_WEBHOOK_URL", "")}
        if "--dry-run" in argv:
            payload, failed, _entry = build_payload(cfg)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if failed:
                print(f"WARNING: no data for {failed}", file=sys.stderr)
                return 1
            return 0
        ok, detail = post_report(cfg)
        print(detail)
        return 0 if ok else 1

    # daemon: control API + gateway threads, scheduler in main thread
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"control API listening on :{API_PORT}")
    adopt_webhook_channel(load_config())  # seeds on first boot, then migrates
    reload_persona(load_config())         # the configured persona file, not just the default path
    threading.Thread(target=run_gateway, daemon=True).start()
    threading.Thread(target=memory_loop, daemon=True).start()
    scheduler_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
