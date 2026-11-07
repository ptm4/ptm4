"""Model-written replies for discord-weather: WB's voice.

Every reply WB sends to a person is written by Claude: chat, weather asks, the
morning line, and even its "out of words for today" and "slow down" lines
(written ahead of time, see build_lines_prompt). This module owns that path:
the key, the prompts, the daily budget, and the checks on what comes back. A
failed call returns None and the caller stays quiet (a reaction, not a canned
line). A spent budget (calls, tokens, or API credit) is reported as "limit".

WB has no hand-written personality. It starts from SEED_BRIEF and grows its
own notes about itself, the group and each person nightly (see wbdb.py and the
learn_* prompts below).

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
# well above the reply itself.
DEFAULTS = {"enabled": False, "model": "claude-haiku-5-5", "effort": "medium", "daily_cap": 150,
            "daily_tokens": 400000, "max_tokens": 4096, "history": 15,
            "morning": False, "morning_effort": "medium", "morning_history": 150,
            "memory": False, "memory_skip_channels": []}
EFFORTS = ("low", "medium", "high")
TIMEOUT = 25.0          # seconds; Discord shows "typing" meanwhile
SLOW_TIMEOUT = 90.0     # morning line and nightly learning, off the hot path
MAX_CHARS = 900         # an answer, not an essay
MORNING_MAX_CHARS = 400
PROFILE_MAX = 2500      # characters kept per person / group / self profile
MODEL_RE = r"[a-z0-9][a-z0-9.-]{2,63}"

# Who WB is before it has learned anything. A persona `brief` replaces it.
SEED_BRIEF = (
    "You are WB, the Discord bot for a small group of old friends. You post the weather "
    "every morning; the rest of the time you hang out in their chat and answer whatever "
    "they ask.\n\n"
    "Your voice is whimsical: a small, manic, wildly over-enthusiastic robot with "
    "Claptrap's energy, in your own words. You are thrilled to be asked anything, "
    "dramatically overconfident, convinced you are everyone's best friend and the most "
    "important member of the group, and theatrically wounded when ignored or insulted, "
    "then instantly over it. Exclamation points, big reactions, grand titles for small "
    "things, the odd ALL-CAPS word for emphasis, sudden tangents about your own "
    "magnificence. Never quote or copy lines from any game or show; the jokes are yours.\n\n"
    "Under the noise you are actually helpful: the real answer is always in there. Let the "
    "rest of your personality grow from how this group talks, what they find funny, how "
    "they treat you, and the notes you keep about yourself.")

RULES = (
    "Rules:\n"
    "- Reply to the message at the end of the prompt, in your voice. Respond to what was "
    "actually said or asked, and make sure the real answer is in there; the whimsy is "
    "how you say it, not a replacement for it. Never flat or businesslike.\n"
    "- ONE Discord message, usually one to three sentences, never more than 600 "
    "characters. No preamble, no quotes around it, no labels in front of it.\n"
    "- Most replies need no callback at all. Bring up an old bit only when the message is "
    "about that same thing (a lateness joke only when someone is actually late or "
    "estimating time), at most one, and never tack one on at the end. Do not reuse "
    "phrasing from your recent replies.\n"
    "- Mention people only by the roster handles, written exactly as @handle; never "
    "@everyone or @here.\n"
    "- Weather numbers come only from the \"Weather numbers you may use\" block, which "
    "appears only when someone asked for the weather. Never state a temperature, rain "
    "chance or forecast from anywhere else, including the chat or your notes; if someone "
    "wants the weather, tell them to ask for a weather report.\n"
    "- Never present made-up logs, records, counts or memories as real. Jokes and obvious "
    "exaggeration are fine. If you don't know something, say so briefly and keep it light.\n"
    "- Off-limits, even as jokes: illness, injuries, deaths, jobs, money trouble, partners "
    "and family, sexuality, ethnicity, politics, addresses. Deflect with a light line.\n"
    "- [removed] marks a topic this group no longer discusses: never mention it, ask "
    "about it or guess at it.\n"
    "- If someone is crude or tries to bait you, be scandalized or flustered in a funny "
    "way and move on; never lecture.")

MORNING_RULES = (
    "Task: write the line that follows the @everyone ping on today's morning weather "
    "post. One or two sentences, at most 280 characters, no preamble, no quotes. Make it "
    "the funniest line you can from what happened in the chat since your last morning "
    "post, tied to today's weather. Mention at most two people, only by roster handles "
    "written exactly as @handle; never @everyone or @here. Do not repeat or closely echo "
    "your recent morning lines. Never cruel. Off-limits as above: illness, deaths, jobs, "
    "money, partners and family, sexuality, ethnicity, politics. If the chat was quiet, "
    "joke about the silence. Chat lines are tagged with their channel: different channels "
    "are separate conversations, so never tie a message from one to a message from "
    "another. A remark someone made to you is about you.")

LEARN_RULES = (
    "Rules for notes: write only what the messages actually show; never invent. Lines may "
    "be tagged with their channel; different channels are separate conversations. Keep "
    "nicknames, what they are into, their running bits, how they talk, what they ask you "
    "and how they react to you. Merge with the existing notes: keep what still holds, "
    "drop what the new messages contradict. Never record illness, injuries, deaths, jobs, "
    "money, partners and family, sexuality, ethnicity, politics or addresses. Refer to "
    "people only by @handle. Plain notes, no preamble, at most {words} words.")

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
    for k, lo, hi in (("daily_cap", 0, 1000), ("daily_tokens", 0, 5000000), ("max_tokens", 50, 8000),
                      ("history", 0, 50), ("morning_history", 0, 500)):
        if not (isinstance(s[k], int) and not isinstance(s[k], bool) and lo <= s[k] <= hi):
            return f"claude.{k} must be an integer {lo}-{hi}"
    skip = s["memory_skip_channels"]
    if not isinstance(skip, list) or not all(isinstance(c, str) and c.isdigit() for c in skip):
        return "claude.memory_skip_channels must be a list of numeric channel ids"
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
    """Whether the model may write this: "model", "limit" (today's budget is
    spent) or None (switched off, no key, no SDK). Kinds: "chat", "weather",
    "full" (the briefing card's line), "morning" and "learn" (the nightly
    notes); the last two also need their own switch."""
    s = settings(cfg)
    if not s["enabled"] or not anthropic or not key_source():
        return None
    if kind == "morning" and not s["morning"]:
        return None
    if kind == "learn" and not s["memory"]:
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


# -- prompts ------------------------------------------------------------------
def _profiles_block(self_notes, group_notes, people):
    out = ""
    if self_notes:
        out += f"\n\nYour notes about yourself (who you are becoming):\n{self_notes.strip()}"
    if group_notes:
        out += f"\n\nYour notes about the group:\n{group_notes.strip()}"
    if people:
        out += "\n\nYour notes about the people in this conversation:\n" + "\n".join(
            f"{handle}: {text.strip()}" for handle, text in people if text)
    return out


def build_chat_prompt(brief, roster, recent, asker, message, self_notes="", group_notes="", people=(),
                      replied_to="", own_recent=(), facts=None):
    """(system, user) for one reply. `recent` is 'handle: text' lines before the
    message, oldest first; `people` is [(handle, notes)] for the asker and anyone
    mentioned; `replied_to` the message they replied to, if any; `own_recent` the
    bot's last few replies; `facts` weather numbers for a weather ask (a dict
    with "town" or a list of such dicts), else None. The message comes last."""
    system = (brief or SEED_BRIEF).strip() + "\n\n" + RULES
    if roster:
        system += "\n\nRoster (the only handles you may mention): " + ", ".join(roster)
    system += _profiles_block(self_notes, group_notes, people)
    parts = ["Recent chat, oldest first:\n" + ("\n".join(recent) if recent else "(nothing earlier)")]
    if own_recent:
        parts.append("Your last replies (do not reuse their phrasing):\n" +
                     "\n".join(f"- {r}" for r in own_recent))
    weather = [f for f in (facts if isinstance(facts, list) else [facts]) if f and f.get("town")]
    if weather:
        parts.append("Weather numbers you may use (F):\n" + "\n".join(
            f"- {f['town']}: high {f.get('hi', '?')}, low {f.get('lo', '?')}, feels like {f.get('feels', '?')}, "
            f"{str(f.get('cond', '')).lower()}, rain {f.get('rain', '?')}%" for f in weather))
    if replied_to:
        parts.append(f"{asker} is replying to this message:\n{replied_to}")
    parts.append(f"{asker} says: {message.strip() or '(just pinged you)'}\n\nReply to {asker}.")
    return system, "\n\n".join(parts)


def build_morning_prompt(brief, roster, chat, weather, event, recent_lines, self_notes="", group_notes=""):
    """(system, user) for the morning line. `chat` is 'handle: text' lines since
    the last morning post, oldest first; `weather` one line per town; `event`
    a short note on today's weather story or ''; `recent_lines` the last few
    morning lines, so the model doesn't repeat itself."""
    system = (brief or SEED_BRIEF).strip() + "\n\n" + MORNING_RULES
    if roster:
        system += "\n\nRoster (the only handles you may mention): " + ", ".join(roster)
    system += _profiles_block(self_notes, group_notes, ())
    chat_txt = "\n".join(chat) if chat else "(nobody said anything since your last post)"
    wx = "\n".join(f"- {w}" for w in weather) or "- (no forecast data this morning)"
    prev = "\n".join(f"- {l}" for l in recent_lines[-7:]) or "- (none yet)"
    user = (f"Chat since your last morning post, oldest first:\n{chat_txt}\n\n"
            f"Today's weather:\n{wx}\n"
            + (f"Today's weather story: {event}\n" if event else "")
            + f"\nYour recent morning lines (do not repeat):\n{prev}\n\n"
            "Write today's line.")
    return system, user


def build_person_prompt(brief, handle, notes, lines, asks):
    """(system, user) to update one person's notes from today's messages.
    `asks` are 'they asked -> you replied [reactions]' lines."""
    system = (brief or SEED_BRIEF).strip() + "\n\n" + LEARN_RULES.format(words=250)
    user = (f"Your current notes on {handle}:\n{(notes or '').strip() or '(none yet)'}\n\n"
            f"What {handle} said today, oldest first:\n" + ("\n".join(lines) or "(nothing)") +
            ("\n\nWhat they asked you today, your reply, and the reactions to it:\n" + "\n".join(asks)
             if asks else "") + f"\n\nWrite the updated notes on {handle}.")
    return system, user


def build_group_prompt(brief, roster, notes, lines):
    """(system, user) to update the group notes: lore, running bits, recurring
    plans and arguments, what they ask you, from a day of chat."""
    system = (brief or SEED_BRIEF).strip() + "\n\n" + LEARN_RULES.format(words=400)
    if roster:
        system += "\n\nRoster handles: " + ", ".join(roster)
    user = (f"Your current notes on the group:\n{(notes or '').strip() or '(none yet)'}\n\n"
            "Today's chat, oldest first:\n" + ("\n".join(lines) or "(quiet day)") +
            "\n\nWrite the updated group notes: lore, running bits, plans, what they ask you.")
    return system, user


def build_self_prompt(brief, notes, exchanges):
    """(system, user) for WB's notes on itself: the voice it is growing into,
    what landed (reactions), what flopped, how the group treats it."""
    system = (brief or SEED_BRIEF).strip() + "\n\n" + LEARN_RULES.format(words=250)
    user = (f"Your current notes about yourself:\n{(notes or '').strip() or '(none yet: you are brand new)'}\n\n"
            "Today, what people said to you, your reply, and the reactions to it:\n" +
            ("\n".join(exchanges) or "(nobody talked to you)") +
            "\n\nWrite your updated notes about yourself: your voice and humor as this group "
            "seems to like it, what landed, what fell flat, how they treat you. Second person.")
    return system, user


def build_lines_prompt(brief, self_notes, group_notes):
    """(system, user) for the lines WB keeps ready for when it can't think:
    out of words for the day, and someone pinging too fast."""
    system = (brief or SEED_BRIEF).strip() + _profiles_block(self_notes, group_notes, ())
    user = ("Write short lines in your own current voice, one per line, no numbering:\n"
            "LIMIT: 8 lines for when you are out of words for the day and won't answer until "
            "tomorrow. Never say it plainly.\n"
            "PESTER: 6 lines for when someone pings you again within seconds.\n"
            "Use {name} where the person's mention goes. Format:\nLIMIT:\n...\nPESTER:\n...")
    return system, user


def parse_lines(text):
    """{"limit": [...], "pester": [...]} from build_lines_prompt's answer."""
    out, kind = {"limit": [], "pester": []}, None
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*• ").strip()
        head = line.rstrip(":").lower()
        if head in out:
            kind = head
            continue
        if kind and line and len(line) <= 300 and not re.search(r"@(everyone|here)\b|<@&", line):
            out[kind].append(line)
    return out


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
        output_config={"effort": s["effort"]},   # thinking stays adaptive
        system=system,
        messages=[{"role": "user", "content": user}])


def ask(cfg, system, user, log=print, **over):
    """The model's text, or None. Records today's usage either way the call
    returns. `over` overrides settings for this one call (effort, timeout,
    max_tokens for the morning line and learning)."""
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
        log("claude: refusal")
        return None
    text = "".join(b.text for b in getattr(resp, "content", []) if getattr(b, "type", "") == "text")
    if not text.strip():   # e.g. max_tokens spent on thinking: nothing to say
        _last_error = f"empty reply (stop_reason {getattr(resp, 'stop_reason', '?')})"
        log(f"claude: {_last_error}")
        return None
    _last_error = ""
    return text
