"""Optional model-written replies for discord-weather.

When pinged, the bot can ask Claude to answer whatever was asked, in the
persona's voice, instead of drawing a template; once a day it can also have the
model write the morning line from what the chat said since the last post. This
module owns that path: the key, the prompts, the daily budget, and the checks on
what comes back. Any failure returns None and the caller falls back to the
template line, so the bot never goes quiet because the model did. A spent
budget (calls, tokens, or API credit) is reported as "limit" so the caller can
say so in character instead.

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

# max_tokens covers thinking too (Haiku 5.5 thinks by default), so it is sized
# well above the reply itself; effort "low" keeps chat replies quick and cheap.
DEFAULTS = {"enabled": False, "model": "claude-haiku-5-5", "effort": "low", "daily_cap": 150,
            "daily_tokens": 400000, "max_tokens": 1024, "history": 10, "kinds": [],
            "morning": False, "morning_effort": "medium", "morning_history": 150,
            "memory": False, "memory_tail": 40, "memory_related": 30, "memory_backfill": 20000}
EFFORTS = ("low", "medium", "high")
TIMEOUT = 12.0        # seconds; Discord shows "typing" meanwhile, templates cover a miss
MORNING_TIMEOUT = 45.0  # the morning line is off the hot path; give it room
MAX_CHARS = 900       # an answer, not an essay
MORNING_MAX_CHARS = 400
MODEL_RE = r"[a-z0-9][a-z0-9.-]{2,63}"

# Shown to the model when the persona has no `brief` of its own.
DEFAULT_BRIEF = (
    "You are a Discord weather bot for a small group of friends. You post a forecast "
    "every morning and get pinged with bits in between. Voice: dry, officious, a little "
    "unhinged, like a lab AI that has decided it is in charge of the weather. Deadpan, "
    "short declaratives, occasional fake statistics. Never cruel, never explain the joke.")

RULES = (
    "Rules: answer whatever you were actually asked, on any topic, the way a helpful "
    "chat bot would, but always in character. Reply with ONE Discord message: usually "
    "one to three sentences, never more than 600 characters, no preamble, no quotes "
    "around it, no explanation of the joke. Mention people only by the handles in the "
    "roster, written exactly as @handle; never @everyone or @here. Do not bring up "
    "health, money, work, partners, family, politics, or anything personal that is not "
    "already a running joke in the chat shown or part of the question. If the ping is "
    "about the weather, answer with the numbers given and do not invent others. If a "
    "real answer needs facts you don't have, say so in character rather than guessing. "
    "You know only what is in this prompt: your notes and older messages if shown, the "
    "recent chat, the roster and the weather. Never claim logs, records, statistics, "
    "counts or memories beyond those; if asked what you know, say in character that "
    "you remember what's in your notes and the chat you've read, nothing else.")

FOLD_RULES = (
    "Task: you keep private notes about this Discord group so your replies and morning "
    "lines can be funnier and more in on the joke. Update your notes with the new "
    "messages below. Keep: running jokes and bits, nicknames, short memorable quotes "
    "attributed by @handle, who does what, recurring topics and games, how people "
    "treat you, ongoing stories and rivalries. Merge repeats, drop stale one-off trivia. "
    "Plain notes grouped by person and by bit, at most 1,500 words. Write only what the "
    "messages actually say; never invent. Do not record health, money, work, partners, "
    "family or politics details unless they are already an open running joke. Refer to "
    "people only by the handles shown. Output only the updated notes, no preamble.")

MORNING_RULES = (
    "Task: write the line that follows the @everyone ping on today's morning weather "
    "post. ONE or two sentences, at most 280 characters, no preamble, no quotes. Make "
    "it the funniest line you can from what happened in the chat since your last "
    "morning post: running jokes, who said what, what people asked you, how they "
    "treated you. Tie it to today's weather. Mention at most two people, only by the "
    "handles in the roster, written exactly as @handle; never @everyone or @here. Do "
    "not repeat or closely echo your recent morning lines. Never cruel. Do not bring up "
    "health, money, work, partners, family or politics unless it is already a running "
    "joke in the chat shown. If the chat was quiet, joke about the silence.")

_lock = threading.Lock()
_last_error = ""
_limited = {}         # local date -> why the API said no more today ("credit", "rate")


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
    for k in ("effort", "morning_effort"):
        if s[k] not in EFFORTS:
            return f"claude.{k} must be one of {', '.join(EFFORTS)}"
    for k in ("morning", "memory"):
        if not isinstance(s[k], bool):
            return f"claude.{k} must be true/false"
    for k, lo, hi in (("daily_cap", 0, 1000), ("daily_tokens", 0, 5000000), ("max_tokens", 50, 4000),
                      ("history", 0, 30), ("morning_history", 0, 500), ("memory_tail", 0, 100),
                      ("memory_related", 0, 60), ("memory_backfill", 0, 200000)):
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
            "daily_cap": s["daily_cap"], "daily_tokens": s["daily_tokens"], "morning": s["morning"],
            "memory": s["memory"],
            "today": usage(cfg.get("timezone", "UTC")), "spent": spent(cfg),
            "last_error": _last_error, "sdk": bool(anthropic)}


def decide(cfg, kind):
    """How to answer this ping: "model", "limit" (the model would be used but
    today's budget is spent, so say so in character) or None (template, as
    before). "full" keeps its briefing card; every other kind, weather
    included, can go to the model. "morning" is the daily line."""
    s = settings(cfg)
    if not s["enabled"] or kind == "full" or not anthropic or not key_source():
        return None
    if kind in ("morning", "memory") and not s[kind]:
        return None
    if s["kinds"] and kind not in s["kinds"] and kind not in ("morning", "memory"):
        return None
    return "limit" if spent(cfg) else "model"


def wants(cfg, kind):
    return decide(cfg, kind) == "model"


def spent(cfg):
    """Why today's budget is gone ("calls", "tokens", "credit", "rate"), or ''."""
    s, tz = settings(cfg), cfg.get("timezone", "UTC")
    u = usage(tz)
    if u["calls"] >= s["daily_cap"]:
        return "calls"
    if s["daily_tokens"] and u["input_tokens"] + u["output_tokens"] >= s["daily_tokens"]:
        return "tokens"
    return _limited.get(u["date"], "")


def _limit_reason(exc):
    """'credit' or 'rate' if an API error means "no more today", else ''."""
    text = str(exc).lower()
    if "credit balance" in text or "billing" in text:
        return "credit"
    if getattr(exc, "status_code", None) == 429 or "rate_limit" in text:
        return "rate"
    return ""


# -- prompt -------------------------------------------------------------------
def _notes(digest):
    return f"\n\nYour notes on this group (from chat you have read):\n{digest.strip()}" if digest else ""


def build_prompt(brief, roster, recent, asker, ping, kind, facts, examples, digest="", related=()):
    """(system, user) strings. `recent` is a list of 'handle: text' lines,
    oldest first; `examples` are template lines of this kind, for voice only.
    With memory on, `digest` is the bot's notes and `related` older messages
    that match the ping."""
    system = (brief or DEFAULT_BRIEF).strip() + "\n\n" + RULES
    if roster:
        system += "\n\nRoster (the only handles you may mention): " + ", ".join(roster)
    system += _notes(digest)
    chat = "\n".join(recent) if recent else "(no earlier messages)"
    if related:
        chat = "Older messages that match this ping, oldest first:\n" + "\n".join(related) + \
               "\n\nRecent chat, oldest first:\n" + chat
    else:
        chat = "Recent chat, oldest first:\n" + chat
    weather = ""
    if facts and facts.get("town"):
        weather = (f"\nWeather right now for {facts['town']}: high {facts.get('hi', '?')}, "
                   f"low {facts.get('lo', '?')}, feels like {facts.get('feels', '?')} (F), "
                   f"{str(facts.get('cond', '')).lower()}, rain {facts.get('rain', '?')}%.")
    ex = "\n".join(f"- {e}" for e in examples[:3])
    user = (f"{chat}\n\n"
            f"{asker} just pinged you: {ping.strip()}\n"
            f"The router filed this under: {kind}.{weather}\n\n"
            f"Lines you have used for this kind before (voice reference, do not copy):\n{ex or '- (none)'}\n\n"
            "Write your reply.")
    return system, user


def build_fold_prompt(brief, roster, digest, lines):
    """(system, user) asking the model to fold new chat lines into its notes."""
    system = (brief or DEFAULT_BRIEF).strip() + "\n\n" + FOLD_RULES
    if roster:
        system += "\n\nRoster handles: " + ", ".join(roster)
    user = (f"Your current notes:\n{(digest or '').strip() or '(empty: this is the start)'}\n\n"
            f"New messages, oldest first:\n" + "\n".join(lines) + "\n\nWrite the updated notes.")
    return system, user


def build_morning_prompt(brief, roster, chat, weather, event, recent_lines, digest=""):
    """(system, user) for the morning line. `chat` is 'handle: text' lines since
    the last morning post, oldest first; `weather` one line per town; `event`
    a short note on today's weather story or ''; `recent_lines` the last few
    morning lines, so the model doesn't repeat itself."""
    system = (brief or DEFAULT_BRIEF).strip() + "\n\n" + MORNING_RULES
    if roster:
        system += "\n\nRoster (the only handles you may mention): " + ", ".join(roster)
    system += _notes(digest)
    chat_txt = "\n".join(chat) if chat else "(nobody said anything since your last post)"
    wx = "\n".join(f"- {w}" for w in weather) or "- (no forecast data this morning)"
    prev = "\n".join(f"- {l}" for l in recent_lines[-7:]) or "- (none yet)"
    user = (f"Chat since your last morning post, oldest first:\n{chat_txt}\n\n"
            f"Today's weather:\n{wx}\n"
            + (f"Today's weather story: {event}\n" if event else "")
            + f"\nYour recent morning lines (do not repeat):\n{prev}\n\n"
            "Write today's line.")
    return system, user


def clean_line(text, allowed_ids=(), max_chars=MAX_CHARS):
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
    if len(t) > max_chars:
        cut = t[:max_chars]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = (cut[:end + 1] if end > max_chars // 2 else cut.rstrip() + "…").strip()
    return t


# -- the call -----------------------------------------------------------------
def _create(s, system, user):
    """One Messages API call. Separated so tests can stub it."""
    client = anthropic.Anthropic(api_key=_key(), timeout=s.get("timeout", TIMEOUT), max_retries=0)
    return client.messages.create(
        model=s["model"], max_tokens=s["max_tokens"],
        output_config={"effort": s["effort"]},   # chat, not reasoning; thinking stays adaptive
        system=system,
        messages=[{"role": "user", "content": user}])


def ask(cfg, system, user, log=print, **over):
    """The model's text, or None - in which case the caller uses the template
    it already has (or, if spent(cfg) now says so, its limit line). Records
    today's usage either way the call returns. `over` overrides settings for
    this one call (the morning line's effort and timeout)."""
    global _last_error
    s, tz = {**settings(cfg), **over}, cfg.get("timezone", "UTC")
    try:
        resp = _create(s, system, user)
    except Exception as e:  # auth, network, 4xx/5xx, timeout: all the same to the bot
        _last_error = f"{type(e).__name__}: {str(e)[:160]}"
        reason = _limit_reason(e)
        if reason:   # out of credit or rate-limited: stop asking until tomorrow
            _limited[_today(tz)] = reason
        log(f"claude: call failed - {_last_error}" + (f" (limit: {reason})" if reason else ""))
        return None
    u = getattr(resp, "usage", None)
    _record(tz, getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0))
    if getattr(resp, "stop_reason", "") == "refusal":
        _last_error = "refusal"
        log("claude: refusal - using the template line")
        return None
    text = "".join(b.text for b in getattr(resp, "content", []) if getattr(b, "type", "") == "text")
    if not text.strip():   # e.g. max_tokens spent on thinking: nothing to say
        _last_error = f"empty reply (stop_reason {getattr(resp, 'stop_reason', '?')})"
        log(f"claude: {_last_error} - using the template line")
        return None
    _last_error = ""
    return text
