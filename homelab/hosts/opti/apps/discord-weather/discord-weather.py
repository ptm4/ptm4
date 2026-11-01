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
    "witty_enabled": True,   # append a generated one-liner after the message
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
    # model-written replies (model_reply.py); off unless a profile turns it on
    "claude": {"enabled": False, "model": "claude-haiku-5-5", "effort": "medium", "daily_cap": 40,
               "max_tokens": 300, "history": 10, "kinds": []},
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


def build_payload(cfg):
    """Fetch all locations and build the webhook payload.
    Returns (payload, failed_names, receipt). The receipt contains the selected
    joke (if any) and weather snapshot; commit only after webhook acceptance."""
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
        desc += (f"\nSunrise {first_fc['sunrise']} · Sunset {first_fc['sunset']}"
                 " — daylight is issued once, use it")
    persona = (witty_messages.EMBED if witty_messages else {}) or {}
    payload = {
        # The whole post is in-character: Mr. Murf files the morning briefing.
        "username": persona.get("username") or "Mr. Murf",
        # explicit allow-list so @everyone/@here in the message actually ping
        "allowed_mentions": {"parse": ["everyone", "roles", "users"]},
        "embeds": [{
            "title": persona.get("title") or "🌤️ Scoutmaster's Morning Briefing",
            "description": desc,
            "color": EMBED_COLOR,
            "fields": spaced,
            "footer": {"text": persona.get("footer") or "Forecast: Open-Meteo. Standards: Mr. Murf."},
        }],
    }
    witty_entry = None
    context = None
    if _witty:
        try:
            context = _witty.weather(observations, now)
            if cfg.get("witty_enabled"):
                witty_entry = _witty.peek(cfg.get("witty_names") or [], first_fc, now,
                                          event=context["event"])
        except Exception as e:
            log(f"witty selection failed: {e}")
    content = cfg.get("message", "")
    if witty_entry:
        composed = f"{content} {witty_messages.apply_pings(witty_entry['rendered'])}".strip()
        if len(composed) <= 2000:
            content = composed
        else:
            witty_entry = None  # too long — drop the joke, keep the report
    if content:
        payload["content"] = content
    # One self-name per post: sender, title and footer reuse the joke's {me}.
    me = witty_messages.self_name(witty_entry) if witty_messages else "Mr. Murf"
    embed = payload["embeds"][0]
    payload["username"] = payload["username"].replace("{me}", me)
    embed["title"] = embed["title"].replace("{me}", me)
    embed["footer"]["text"] = embed["footer"]["text"].replace("{me}", me)
    if context:
        witty_entry = dict(witty_entry or {}, weather_snapshot=context["snapshot"])
    return payload, failed, witty_entry


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
    payload, failed, witty_entry = build_payload(cfg)
    try:
        deliver(cfg, payload)
    except RuntimeError as e:
        return False, str(e)
    if witty_entry and _witty:
        try:
            _witty.commit(witty_entry)
        except Exception as e:
            log(f"witty commit failed (line may repeat): {e}")
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


FULL_RE = r"\b(full|report|briefing|card|everything)\b"


def build_reply(cfg, user_id, text):
    """(content, embed-or-None, kind) answering a ping. Peeks only — never
    consumes the morning joke or advances streaks. The kind is what the message
    asked for (see witty_messages.REPLY_KINDS); only "full" and "weather" answer
    with a forecast, everything else gets an in-character line that still has
    the asker's weather on hand."""
    text = re.sub(r"<[@#][!&]?\d+>", " ", text).lower()
    asker, tz = f"<@{user_id}>", cfg["timezone"]
    reply = witty_messages.reply_line if witty_messages else None
    if witty_messages:
        towns = [w for l in cfg["locations"] for w in (town_of(l), subject_of(l)) if w]
        kind = witty_messages.classify(text, towns)
    else:
        kind = "full" if re.search(FULL_RE, text) else "weather"
    if kind == "full":
        payload, _, receipt = build_payload(cfg)
        me = witty_messages.self_name(receipt) if witty_messages else "Weather Bot"
        line = reply("full", asker, me=me) if reply else f"{asker}, the full briefing:"
        return line, payload["embeds"][0], kind
    if kind == "weather":
        loc = match_location(cfg, text, user_id)
        if loc:
            fc = cached_forecast(loc, tz)
            vals = dict(witty_messages.weather_values(fc), town=town_of(loc)) if witty_messages else {}
            if reply:
                return reply("town", asker, **vals), None, kind
            return f"{asker}: {town_of(loc)} {fc['hi']:.0f}°/{fc['lo']:.0f}°", None, kind
        rows = []
        for l in cfg["locations"]:
            try:
                fc = cached_forecast(l, tz)
                rows.append(f"{fc['emoji']} **{town_of(l)}** {fc['hi']:.0f}°/{fc['lo']:.0f}° · "
                            f"feels {fc['feels']:.0f}° · rain {fc['rain']:.0f}%")
            except Exception as e:
                log(f"reply forecast failed for {l['name']}: {e}")
        summary = "\n".join(rows) or "(no forecast data right now)"
        return (reply("all", asker, summary=summary) if reply else f"{asker}\n{summary}"), None, kind
    vals = reply_facts(cfg, user_id)
    vals["pick"] = witty_messages.pick_name(user_id)
    return reply(kind, asker, **vals), None, kind


# ── model-written replies (model_reply.py), templates as fallback ────────────
def handle_of(user_id, fallback="someone"):
    """The persona's @handle for a Discord id, else the given display name."""
    pings = witty_messages.PINGS if witty_messages else {}
    for name, uid in pings.items():
        if uid == str(user_id) and name.startswith("@"):
            return name
    return fallback


def chat_line(author_id, author_name, text, is_bot=False, me="Weather Bot"):
    """One 'handle: text' line of context for the model: real ids become
    handles, the bot's own posts are labelled with its name, embeds are noted."""
    who = me if is_bot else handle_of(author_id, "@" + str(author_name))
    body = re.sub(r"<@!?(\d+)>", lambda m: handle_of(m.group(1), "@someone"), text or "")
    body = re.sub(r"<@&\d+>", "@" + me, body)
    body = re.sub(r"\s+", " ", body).strip() or "[embed]"
    return f"{who}: {body[:300]}"


def model_line(cfg, user_id, text, kind, recent):
    """Ask the model for this ping's line; None means use the template."""
    if not (model_reply and witty_messages):
        return None
    roster = sorted(n for n in witty_messages.PINGS if n.startswith("@"))
    ping = re.sub(r"<@[!&]?\d+>", " ", text).strip()
    facts = reply_facts(cfg, user_id)
    examples = list(witty_messages.REPLIES.get(kind) or [])[:3]
    system, user = model_reply.build_prompt(witty_messages.BRIEF, roster, recent, handle_of(user_id),
                                            ping, kind, facts, examples)
    raw = model_reply.ask(cfg, system, user, log=log)
    line = model_reply.clean_line(raw, witty_messages.PINGS.values()) if raw else ""
    return witty_messages.apply_pings(line) if line else None


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
    """True if this ping should be ignored: the asker pinged again inside the
    per-person cooldown, or the channel has hit its burst cap. Records the reply
    otherwise."""
    now = time.monotonic() if now is None else now
    if now - _last_reply.get(user_id, -REPLY_COOLDOWN) < REPLY_COOLDOWN:
        return True
    recent = [t for t in _burst.get(channel_id, []) if now - t < BURST_WINDOW]
    if len(recent) >= BURST_LIMIT:
        _burst[channel_id] = recent
        return True
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
        if throttled(msg.author.id, msg.channel.id):
            log(f"gateway: throttled {msg.author} in #{msg.channel}")
            return
        try:
            loop = asyncio.get_running_loop()
            source = "template"
            async with msg.channel.typing():
                content, embed, kind = await loop.run_in_executor(
                    None, build_reply, cfg, msg.author.id, msg.content)
                if model_reply and model_reply.wants(cfg, kind):
                    me = witty_messages.self_name() if witty_messages else "Weather Bot"
                    n = model_reply.settings(cfg)["history"]
                    recent = []
                    if n:
                        async for m in msg.channel.history(limit=n, before=msg):
                            recent.append(chat_line(m.author.id, m.author.display_name, m.content,
                                                    m.author.id == client.user.id, me))
                        recent.reverse()
                    line = await loop.run_in_executor(None, model_line, cfg, msg.author.id,
                                                      msg.content, kind, recent)
                    if line:
                        content, source = line, "claude"
            await msg.reply(content, embed=discord.Embed.from_dict(embed) if embed else None)
            log(f"gateway: answered {msg.author} in #{msg.channel} ({kind}, {source})")
            if kind not in ("weather", "full"):
                inbox_add({"ts": datetime.now().isoformat(timespec="seconds"), "id": str(msg.id),
                           "channel_id": str(msg.channel.id), "channel": str(msg.channel),
                           "guild_id": str(getattr(msg.guild, "id", "")),
                           "author": str(msg.author), "author_id": str(msg.author.id),
                           "text": msg.content, "kind": kind, "answered_with": content,
                           "source": source})
        except Exception as e:
            log(f"gateway: reply failed: {e}")

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
                             "claude": model_reply.status(cfg) if model_reply else None, **st})
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
    scheduler_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
