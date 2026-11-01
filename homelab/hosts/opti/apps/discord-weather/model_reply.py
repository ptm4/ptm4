"""Optional model-written replies for discord-weather.

When a ping is not a weather question, the bot can ask Claude for one line in
the persona's voice instead of drawing a template. This module owns that path:
the key, the prompt, the daily cap, and the checks on what comes back. Any
failure returns None and the caller falls back to the template line, so the
bot never goes quiet because the model did.

Gating lives in the config (`claude.enabled`, per server profile) and is
validated here: it cannot be switched on for "any server".
"""
import json
import os
import re
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import anthropic
except ImportError:  # the image installs it; tests and the report don't need it
    anthropic = None

DATA_DIR = os.environ.get("DATA_DIR", "/data")
KEY_PATH = os.path.join(DATA_DIR, "anthropic.key")
USAGE_PATH = os.path.join(DATA_DIR, "claude_usage.json")

DEFAULTS = {"enabled": False, "model": "claude-haiku-5-5", "effort": "medium", "daily_cap": 40,
            "max_tokens": 300, "history": 10, "kinds": []}
EFFORTS = ("low", "medium", "high")
TIMEOUT = 12.0        # seconds; Discord shows "typing" meanwhile, templates cover a miss
MAX_CHARS = 400       # a line, not an essay
MODEL_RE = r"[a-z0-9][a-z0-9.-]{2,63}"

# Shown to the model when the persona has no `brief` of its own.
DEFAULT_BRIEF = (
    "You are a Discord weather bot for a small group of friends. You post a forecast "
    "every morning and get pinged with bits in between. Voice: dry, officious, a little "
    "unhinged, like a lab AI that has decided it is in charge of the weather. Deadpan, "
    "short declaratives, occasional fake statistics. Never cruel, never explain the joke.")

RULES = (
    "Rules: reply with ONE message of at most 300 characters, no preamble, no quotes "
    "around it, no explanation. Stay in character. Mention people only by the handles "
    "in the roster, written exactly as @handle; never @everyone or @here. Do not bring "
    "up health, money, work, partners, family, politics, or anything personal that is "
    "not already a running joke in the chat shown. If the ping is really about the "
    "weather, answer with the numbers given. If you have nothing good, be briefly "
    "dismissive rather than long.")

_lock = threading.Lock()
_last_error = ""


def settings(cfg):
    return {**DEFAULTS, **(cfg.get("claude") or {})}


def validate(cfg):
    """Error string or None. Enabling requires a specific guild so the model
    can never answer in 'any server'."""
    c = cfg.get("claude", DEFAULTS)
    if not isinstance(c, dict):
        return "claude must be an object"
    if set(c) - set(DEFAULTS):
        return f"claude may only set {sorted(DEFAULTS)}"
    s = {**DEFAULTS, **c}
    if not isinstance(s["enabled"], bool):
        return "claude.enabled must be true/false"
    if not (isinstance(s["model"], str) and re.fullmatch(MODEL_RE, s["model"])):
        return "claude.model must be a model id"
    if s["effort"] not in EFFORTS:
        return f"claude.effort must be one of {', '.join(EFFORTS)}"
    for k, lo, hi in (("daily_cap", 0, 1000), ("max_tokens", 50, 2000), ("history", 0, 30)):
        if not (isinstance(s[k], int) and not isinstance(s[k], bool) and lo <= s[k] <= hi):
            return f"claude.{k} must be an integer {lo}-{hi}"
    if not isinstance(s["kinds"], list) or not all(isinstance(k, str) for k in s["kinds"]):
        return "claude.kinds must be a list of reply kinds"
    if s["enabled"] and not str(cfg.get("guild_id") or "").strip():
        return "claude.enabled needs guild_id set (the model never answers in 'any server')"
    return None


def key_source():
    """'env', 'file' or '' - where a key would come from. Never the key itself."""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "env"
    return "file" if os.path.isfile(KEY_PATH) else ""


def _key():
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if k:
        return k
    try:
        with open(KEY_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


# -- daily cap ----------------------------------------------------------------
def _today(tz):
    try:
        return datetime.now(ZoneInfo(tz)).date().isoformat()
    except Exception:
        return datetime.now().date().isoformat()


def usage(tz="UTC"):
    """{"date", "calls", "input_tokens", "output_tokens"} for the local day."""
    blank = {"date": _today(tz), "calls": 0, "input_tokens": 0, "output_tokens": 0}
    try:
        with open(USAGE_PATH, encoding="utf-8") as f:
            u = json.load(f)
        return u if u.get("date") == blank["date"] else blank
    except (OSError, ValueError):
        return blank


def _record(tz, input_tokens, output_tokens):
    with _lock:
        u = usage(tz)
        u["calls"] += 1
        u["input_tokens"] += int(input_tokens or 0)
        u["output_tokens"] += int(output_tokens or 0)
        tmp = USAGE_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(u, f)
            os.replace(tmp, USAGE_PATH)
        except OSError:
            pass
        return u


def status(cfg):
    s = settings(cfg)
    return {"enabled": s["enabled"], "model": s["model"], "key": key_source() or "none",
            "daily_cap": s["daily_cap"], "today": usage(cfg.get("timezone", "UTC")),
            "last_error": _last_error, "sdk": bool(anthropic)}


def wants(cfg, kind):
    """Should this ping go to the model? Config says so, the kind is eligible,
    there is a key, and today's cap has room."""
    s = settings(cfg)
    if not s["enabled"] or kind in ("weather", "full") or not anthropic or not key_source():
        return False
    if s["kinds"] and kind not in s["kinds"]:
        return False
    return usage(cfg.get("timezone", "UTC"))["calls"] < s["daily_cap"]


# -- prompt -------------------------------------------------------------------
def build_prompt(brief, roster, recent, asker, ping, kind, facts, examples):
    """(system, user) strings. `recent` is a list of 'handle: text' lines,
    oldest first; `examples` are template lines of this kind, for voice only."""
    system = (brief or DEFAULT_BRIEF).strip() + "\n\n" + RULES
    if roster:
        system += "\n\nRoster (the only handles you may mention): " + ", ".join(roster)
    chat = "\n".join(recent) if recent else "(no earlier messages)"
    weather = ""
    if facts and facts.get("town"):
        weather = (f"\nWeather right now for {facts['town']}: high {facts.get('hi', '?')}, "
                   f"low {facts.get('lo', '?')}, feels like {facts.get('feels', '?')} (F), "
                   f"{str(facts.get('cond', '')).lower()}, rain {facts.get('rain', '?')}%.")
    ex = "\n".join(f"- {e}" for e in examples[:3])
    user = (f"Recent chat, oldest first:\n{chat}\n\n"
            f"{asker} just pinged you: {ping.strip()}\n"
            f"The router filed this under: {kind}.{weather}\n\n"
            f"Lines you have used for this kind before (voice reference, do not copy):\n{ex or '- (none)'}\n\n"
            "Write your reply.")
    return system, user


def clean_line(text, allowed_ids=()):
    """Trim the model's text down to one safe Discord message, or '' if it is
    unusable. Raw <@id> mentions outside the roster are replaced, role and
    mass mentions are refused outright."""
    t = (text or "").strip()
    for _ in range(2):   # quotes around a labelled line, or a label on a quoted one
        if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'“”":
            t = t[1:-1].strip()
        t = re.sub(r"^(reply|response|bot|wb)\s*:\s*", "", t, flags=re.I)
    if re.search(r"@(everyone|here)\b", t) or "<@&" in t:
        return ""
    allowed = {str(i) for i in allowed_ids}
    t = re.sub(r"<@!?(\d+)>", lambda m: m.group(0) if m.group(1) in allowed else "someone", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    if len(t) > MAX_CHARS:
        cut = t[:MAX_CHARS]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = (cut[:end + 1] if end > MAX_CHARS // 2 else cut.rstrip() + "…").strip()
    return t


# -- the call -----------------------------------------------------------------
def _create(s, system, user):
    """One Messages API call. Separated so tests can stub it."""
    client = anthropic.Anthropic(api_key=_key(), timeout=TIMEOUT, max_retries=0)
    return client.messages.create(
        model=s["model"], max_tokens=s["max_tokens"],
        output_config={"effort": s["effort"]},   # chat, not reasoning; thinking stays adaptive
        system=system,
        messages=[{"role": "user", "content": user}])


def ask(cfg, system, user, log=print):
    """The model's text, or None - in which case the caller uses the template
    it already has. Records today's usage either way the call returns."""
    global _last_error
    s, tz = settings(cfg), cfg.get("timezone", "UTC")
    try:
        resp = _create(s, system, user)
    except Exception as e:  # auth, network, 4xx/5xx, timeout: all the same to the bot
        _last_error = f"{type(e).__name__}: {str(e)[:160]}"
        log(f"claude: call failed - {_last_error}")
        return None
    u = getattr(resp, "usage", None)
    _record(tz, getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0))
    if getattr(resp, "stop_reason", "") == "refusal":
        _last_error = "refusal"
        log("claude: refusal - using the template line")
        return None
    text = "".join(b.text for b in getattr(resp, "content", []) if getattr(b, "type", "") == "text")
    _last_error = ""
    return text
