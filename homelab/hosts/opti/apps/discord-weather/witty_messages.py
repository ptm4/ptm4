#!/usr/bin/env python3
"""Mr. Murf's morning lines: short bits, friendly callouts and reply hooks.

Weather events take priority over the ordinary shuffled catalogue. Recipe history
suppresses repeat premises even when names change. All content is authored locally;
no model, network calls, or access to the chat. Public preview/commit/reroll methods
keep state on the existing /data volume; only accepted posts advance history.

Taste-test: python witty_messages.py --all
"""
import itertools
import json
import os
import random
import string
import threading
import time
from datetime import datetime

import weather_context

VERSION = 5          # content refresh; retire all v4 recipes on upgrade
TEMPLATE_COOLDOWN = 45  # posted jokes, regardless of which name was filled in
CYCLE_SIZE = 90      # upper bound; cooldown and catalogue determine actual size
HISTORY_SIZE = 180   # recent (template, name) pairs barred from the next cycle (~6 months)
HISTORY_MAX = 400    # how much history we keep on disk
ANY_PER_TAGGED = 2   # cycle composition: 2 generic lines per weather/day line
PER_TEMPLATE_CAP = 1  # max times one template appears per cycle (two-name templates
                      # have hundreds of name permutations and would swamp the shuffle)
SELECT_WINDOW = 12   # how far into the shuffled queue ranking looks; see _select
BIT_EVERY = 3        # cycle slots per nameless "pure bit" (CYCLE_SIZE // this)

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TAGS = ("any", "hot", "cold", "rain", "snow", "nice")
NAME_SLOTS = {"name", "name2"}
WEATHER_SLOTS = {"hi", "lo", "feels", "rain", "wind", "uv", "humidity",
                 "cond", "cond_lower", "emoji"}


# Fresh, authored lines: changing a name is not a new joke.
WORD_BANKS = {}
TEMPLATES = [
    {
        "id": "v5_chat_01",
        "text": "Morning, troop. What's today's smallest achievable victory? Getting the fitted sheet to fold is not small. Pick again."
    },
    {
        "id": "v5_chat_02",
        "text": "{name}, you're in charge of today's completely unnecessary debate: best potato format. Defend your answer."
    },
    {
        "id": "v5_chat_03",
        "text": "Everybody gets one minor complaint before breakfast. {name}, one. We have discussed this."
    },
    {
        "id": "v5_chat_04",
        "text": "{name}, what purchase under twenty bucks improved your life? If it's a second charging cable, I understand."
    },
    {
        "id": "v5_chat_05",
        "text": "Morning check-in: what's one thing you're looking forward to? It can be lunch. Lunch has earned that."
    },
    {
        "id": "v5_chat_06",
        "text": "{name}, pick the troop's road-trip snack. {name2} gets one veto and must use it responsibly."
    },
    {
        "id": "v5_chat_07",
        "text": "What game could this group cooperate in for twenty minutes without appointing a defendant?"
    },
    {
        "id": "v5_chat_08",
        "text": "{name}, you have the floor: what's a film you'd happily watch again tonight? No twenty-minute plot summary."
    },
    {
        "id": "v5_chat_09",
        "text": "Which one of you is best in an actual emergency, and which one is best when the restaurant loses our reservation? Different skills."
    },
    {
        "id": "v5_chat_10",
        "text": "{name}, breakfast for dinner: correct decision or cry for help? State your case."
    },
    {
        "id": "v5_chat_11",
        "text": "Troop poll: early departure or one more coffee? Anyone answering 'both' is the reason we never leave."
    },
    {
        "id": "v5_chat_12",
        "text": "{name}, what song gets exactly one play before the rest of the car confiscates your phone?"
    },
    {
        "id": "v5_chat_13",
        "text": "What's the most ridiculous hill you're willing to die on today? Keep it small. Sandwich geometry, for example."
    },
    {
        "id": "v5_chat_14",
        "text": "{name}, name an activity you still enjoy being terrible at. {name2}, let him finish."
    },
    {
        "id": "v5_chat_15",
        "text": "One free afternoon, no chores allowed. What are we actually doing? 'Deciding what to do' is disqualified."
    },
    {
        "id": "v5_chat_16",
        "text": "{name}, what's the last thing that made you laugh harder than it deserved? Troop morale budget is zero; we're crowdsourcing."
    },
    {
        "id": "v5_chat_17",
        "text": "Everybody nominate one food that's much better the next day. Leftover fries, you may leave the room."
    },
    {
        "id": "v5_chat_18",
        "text": "{name}, choose today's luxury: perfect parking spot, empty checkout, or nobody saying 'quick question.'"
    },
    {
        "id": "v5_chat_19",
        "text": "Which childhood snack deserves a comeback? I will hear testimony. I will not hear nutritional information."
    },
    {
        "id": "v5_chat_20",
        "text": "{name}, what's your most defensible shortcut? We're looking for efficiency, not a confession."
    },
    {
        "id": "v5_chat_21",
        "text": "Describe your morning using a game difficulty setting. {name}, 'tutorial but losing' is available."
    },
    {
        "id": "v5_chat_22",
        "text": "What's one thing this group could unanimously agree on? I'll give you until the next weather report."
    },
    {
        "id": "v5_chat_23",
        "text": "{name}, nominate a genuinely good bad movie. {name2}, your job is to bring the snacks, not fix his taste."
    },
    {
        "id": "v5_chat_24",
        "text": "Today's assignment: share something good. A sandwich qualifies. A particularly good parking job qualifies twice."
    },
    {
        "id": "v5_banter_01",
        "text": "{name}, you're troop navigator today. {name2} is in charge of noticing when we've passed the same gas station twice."
    },
    {
        "id": "v5_banter_02",
        "text": "If {name} says 'hear me out' before 9 AM, finish your coffee first. You'll want witnesses."
    },
    {
        "id": "v5_banter_03",
        "text": "{name} and {name2}, plan a simple lunch. The rest of us will reconvene after the appeals process."
    },
    {
        "id": "v5_banter_04",
        "text": "{name}, I am promoting you to assistant coffee person. There is no salary. There is considerable scrutiny."
    },
    {
        "id": "v5_banter_05",
        "text": "I need a volunteer to supervise {name}'s 'quick stop.' Pack enough food for {name2} as well."
    },
    {
        "id": "v5_banter_06",
        "text": "{name}, today's challenge is finishing one task before opening three more. I am also taking this challenge."
    },
    {
        "id": "v5_banter_07",
        "text": "If the group gets stranded, {name} handles supplies and {name2} handles explaining whose fault it was."
    },
    {
        "id": "v5_banter_08",
        "text": "{name}, you may choose the music today. This is a position of trust, not an opportunity to educate us."
    },
    {
        "id": "v5_banter_09",
        "text": "{name} and {name2} are today's planning committee. A plan is due before the activity becomes a memory."
    },
    {
        "id": "v5_banter_10",
        "text": "{name}, the troop needs a lunch recommendation. You can say the place you always say. We both know you're going to."
    },
    {
        "id": "v5_banter_11",
        "text": "I have appointed {name} chief of keeping things simple. {name2}, stop suggesting additional features."
    },
    {
        "id": "v5_banter_12",
        "text": "{name}, we're packing light today. Whatever you're about to justify bringing: no."
    },
    {
        "id": "v5_banter_13",
        "text": "If {name} starts a sentence with 'technically,' {name2} has permission to ask what actually happened."
    },
    {
        "id": "v5_banter_14",
        "text": "{name}, you get one perfectly timed nap today. Use it wisely. Staff meetings count as a high-risk deployment."
    },
    {
        "id": "v5_banter_15",
        "text": "Today {name} and {name2} must settle one disagreement without sending a link. I have cleared the schedule."
    },
    {
        "id": "v5_banter_16",
        "text": "{name}, report one completed chore. I need proof that someone in this troop is winning against the house."
    },
    {
        "id": "v5_banter_17",
        "text": "{name} gets the comfy chair today. {name2}, you can contest the decision, but you have to stand while doing it."
    },
    {
        "id": "v5_banter_18",
        "text": "{name}, you're choosing the takeaway. 'Anything' is not a restaurant, and {name2} has already tried it."
    },
    {
        "id": "v5_banter_19",
        "text": "{name}, buddy check. If your buddy is still asleep, that's a successful location confirmation."
    },
    {
        "id": "v5_banter_20",
        "text": "{name} and {name2}, you get one shopping cart and no list. I'm mostly interested in how many cheeses come back."
    },
    {
        "id": "v5_banter_21",
        "text": "{name}, the floor is yours. Preferably for a good story, but I will accept an unusually specific complaint."
    },
    {
        "id": "v5_banter_22",
        "text": "I nominate {name} to test whether this could have been a text. {name2}, time the explanation."
    },
    {
        "id": "v5_banter_23",
        "text": "{name}, today's merit badge is putting something away in the first place you looked for it."
    },
    {
        "id": "v5_banter_24",
        "text": "{name}, take a proper lunch break. Looking at a different rectangle while chewing does count. Standards have evolved."
    },
    {
        "id": "v5_bit_01",
        "text": "Morning, troop. I bought a planner to get organized. Finding the planner is tomorrow's task."
    },
    {
        "id": "v5_bit_02",
        "text": "The troop has reached the age where a cancelled plan and a confirmed delivery are equally exciting."
    },
    {
        "id": "v5_bit_03",
        "text": "I believe in being prepared. That's why the chair in my bedroom has three different outfits on standby."
    },
    {
        "id": "v5_bit_04",
        "text": "Today's briefing is short because I reheated my coffee and now have to locate it again."
    },
    {
        "id": "v5_bit_05",
        "text": "I used to carry a compass. Now I carry reading glasses into a room to look for my reading glasses."
    },
    {
        "id": "v5_bit_06",
        "text": "Whoever invented the 'easy-open' package owes this troop an explanation and a pair of scissors."
    },
    {
        "id": "v5_bit_07",
        "text": "Morning. I have a full day planned, and absolutely none of it accounts for standing in the kitchen."
    },
    {
        "id": "v5_bit_08",
        "text": "The group chat is a campsite. Some of you tend the fire. Some of you appear when the food is ready. Both are traditional roles."
    },
    {
        "id": "v5_bit_09",
        "text": "I am leaving five minutes early today. Please enjoy this brief period in which that remains possible."
    },
    {
        "id": "v5_bit_10",
        "text": "There should be a merit badge for carrying all the grocery bags in one trip. A second badge for admitting you shouldn't have."
    },
    {
        "id": "v5_bit_11",
        "text": "The forecast is below. Your actual plans will be determined by whether your good trousers are clean."
    },
    {
        "id": "v5_bit_12",
        "text": "Morning, troop. We are one good breakfast away from overestimating what we can accomplish today."
    },
    {
        "id": "v5_bit_13",
        "text": "I don't need a new hobby. I need to do one of the hobbies whose equipment I already own."
    },
    {
        "id": "v5_bit_14",
        "text": "I respect anyone who closes a browser tab and accepts that they will never read it. Courage takes many forms."
    },
    {
        "id": "v5_bit_15",
        "text": "A fitted sheet is just a tent with no instructions. I've been saying this for years and the linen closet agrees."
    },
    {
        "id": "v5_bit_16",
        "text": "I have reached the point in life where 'there's parking' is a compelling review of a restaurant."
    },
    {
        "id": "v5_bit_17",
        "text": "Troop logistics update: the reusable shopping bags remain at home, where they are completely reusable."
    },
    {
        "id": "v5_bit_18",
        "text": "Every household has a cable drawer. None of us knows what half of them do. We are preserving them for the next civilization."
    },
    {
        "id": "v5_bit_19",
        "text": "Morning. If you complete one errand today, remember to reward yourself with an entirely separate errand that sells snacks."
    },
    {
        "id": "v5_bit_20",
        "text": "I cleaned the desk. Everything is now in a pile somewhere less relevant to the camera."
    },
    {
        "id": "v5_bit_21",
        "text": "An adult sleepover is just saying 'we should visit' for four years and then discussing mattresses."
    },
    {
        "id": "v5_bit_22",
        "text": "The first person to say 'we needed the rain' has automatically volunteered to explain it to my shoes."
    },
    {
        "id": "v5_bit_23",
        "text": "I support spontaneity, provided someone gives me two days' notice and tells me where to park."
    },
    {
        "id": "v5_bit_24",
        "text": "There is no bad time for breakfast food. There are only people with unnecessary rules about eggs."
    },
    {
        "id": "v5_bit_25",
        "text": "Troop policy: if you find money in an old jacket, that is field research funding. Buy a sandwich."
    },
    {
        "id": "v5_bit_26",
        "text": "Morning. The correct number of pillows appears to be a negotiation, and I have arrived unprepared."
    },
    {
        "id": "v5_bit_27",
        "text": "A walk is exercise. A walk that ends at a bakery is exercise with a clearly defined objective."
    },
    {
        "id": "v5_bit_28",
        "text": "The hardest part of meal prep is predicting which food next Thursday's version of you won't suddenly resent."
    },
    {
        "id": "v5_bit_29",
        "text": "I have a system for remembering passwords. The system is requesting a new password."
    },
    {
        "id": "v5_bit_30",
        "text": "Today's unofficial uniform: whatever was on top of the clean pile. Inspection cancelled due to similar circumstances."
    },
    {
        "id": "v5_bit_31",
        "text": "The best part of a road trip is the first snack stop, when everyone still believes we're making good time."
    },
    {
        "id": "v5_bit_32",
        "text": "There's a special silence after someone asks a group of adults which evening they're all free."
    },
    {
        "id": "v5_bit_33",
        "text": "Morning, troop. If you forgot why you walked into the room, inspect the room. That's leadership now."
    },
    {
        "id": "v5_bit_34",
        "text": "I do enjoy a quiet morning. Unfortunately, I am also the person operating the coffee grinder."
    },
    {
        "id": "v5_bit_35",
        "text": "The phrase 'while I'm up' is responsible for half the chores in this house and most of my resentment."
    },
    {
        "id": "v5_bit_36",
        "text": "Today's survival skill: stopping the microwave before it announces your snack to the entire building."
    }
]


# ── derived template metadata ─────────────────────────────────────────────────
def _slots(text):
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def _prepare():
    known_banks = set(WORD_BANKS)
    for tpl in TEMPLATES:
        tpl.setdefault("tag", "any")
        tpl["days"] = frozenset(d.strip() for d in tpl.get("days", "").split(",") if d.strip())
        slots = _slots(tpl["text"])
        tpl["banks"] = sorted(slots & known_banks)
        tpl["weather_slots"] = frozenset(slots & WEATHER_SLOTS)
        tpl["uses_name"] = "name" in slots
        tpl["two_names"] = "name2" in slots


def _selfcheck():
    """Content sanity, at import — a typo here would otherwise surface at 7 AM."""
    seen = set()
    for tpl in TEMPLATES:
        tid = tpl.get("id")
        if not tid or tid in seen:
            raise ValueError(f"template id missing or duplicated: {tid!r}")
        seen.add(tid)
        if tpl["tag"] not in TAGS:
            raise ValueError(f"{tid}: unknown tag {tpl['tag']!r}")
        for d in tpl["days"]:
            if d not in DAYS:
                raise ValueError(f"{tid}: unknown day {d!r}")
        unknown = _slots(tpl["text"]) - NAME_SLOTS - WEATHER_SLOTS - set(WORD_BANKS)
        if unknown:
            raise ValueError(f"{tid}: unresolvable slots {sorted(unknown)}")
        if tpl["two_names"] and not tpl["uses_name"]:
            raise ValueError(f"{tid}: uses name2 without name")
    for bank, words in WORD_BANKS.items():
        if not words:
            raise ValueError(f"word bank {bank!r} is empty")


_prepare()
_selfcheck()
TEMPLATES_BY_ID = {t["id"]: t for t in TEMPLATES}


# ── rendering helpers ─────────────────────────────────────────────────────────
def clean_names(names):
    """Trim, drop blanks, de-duplicate case-insensitively, keep order."""
    out, seen = [], set()
    for n in names or []:
        n = str(n).strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def names_key(names):
    return sorted(n.lower() for n in names)


def day_key(now=None):
    return DAYS[(now or datetime.now()).weekday()]


def weather_values(fc):
    """Forecast dict -> render values. Missing/None fields are simply absent,
    and templates needing them are skipped rather than rendering 'None'."""
    out = {}
    if not fc:
        return out
    for k in ("hi", "lo", "feels", "rain", "wind", "uv", "humidity"):
        v = fc.get(k)
        if isinstance(v, (int, float)):
            out[k] = int(round(v))
    cond = fc.get("cond")
    if isinstance(cond, str) and cond:
        out["cond"] = cond
        out["cond_lower"] = cond.lower()
    emoji = fc.get("emoji")
    if isinstance(emoji, str) and emoji:
        out["emoji"] = emoji
    return out


def bucket_for(fc):
    """Which weather-tagged templates fit today, or None for 'generic only'."""
    if not fc:
        return None
    cond = str(fc.get("cond") or "").lower()
    rain = fc.get("rain") or 0
    temp = fc.get("feels")
    if not isinstance(temp, (int, float)):
        temp = fc.get("hi")
    if "snow" in cond or "flurr" in cond:
        return "snow"
    if rain >= 50 or any(w in cond for w in ("rain", "drizzle", "shower", "thunder")):
        return "rain"
    if not isinstance(temp, (int, float)):
        return None
    if temp >= 88:
        return "hot"
    if temp <= 35:
        return "cold"
    if 62 <= temp <= 84 and rain < 30:
        return "nice"
    return None


def render(entry, wvals):
    tpl = TEMPLATES_BY_ID[entry["t"]]
    vals = dict(entry.get("fills") or {})
    vals["name"] = entry.get("name") or ""
    vals["name2"] = entry.get("name2") or vals["name"]
    vals.update(wvals)
    return tpl["text"].format(**vals)


def _eligible(tpl, bucket, avail, today):
    if tpl["days"] and today not in tpl["days"]:
        return False
    if tpl["tag"] != "any" and tpl["tag"] != bucket:
        return False
    return tpl["weather_slots"] <= avail


def _rank(tpl):
    """Lower is better: weekday-pinned beats generic, weather-matched beats any."""
    return (0 if tpl["days"] else 2) + (0 if tpl["tag"] != "any" else 1)


def _log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')} witty: {msg}", flush=True)


# ── the pool ──────────────────────────────────────────────────────────────────
class WittyPool:
    """Persistent draw with premise cooldown, event variants and forecast history.

    Every public method takes the instance lock for its whole load-mutate-save
    body, so the scheduler thread and the control-API handler threads can't
    interleave. Nothing in here calls back into the bot.
    """

    def __init__(self, state_path):
        self.path = state_path
        self._lock = threading.Lock()
        self._mem = None   # fallback when /data isn't writable (dry-run outside the container)

    # -- persistence ----------------------------------------------------------
    def _load(self):
        try:
            with open(self.path) as f:
                state = json.load(f)
            if isinstance(state, dict):
                return state
        except (OSError, ValueError):
            pass
        return self._mem

    def _save(self, state):
        self._mem = state
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f)
            os.replace(tmp, self.path)
        except OSError as exc:
            _log(f"state persistence failed; using memory only: {exc}")

    # -- cycle generation -----------------------------------------------------
    def _new_cycle(self, names, prev):
        prev = prev or {}
        history = [h for h in (prev.get("history") or []) if isinstance(h, list) and len(h) == 2]
        pairs = _all_pairs(names)
        window = min(HISTORY_SIZE, len(pairs) // 2)
        recent = {tuple(h) for h in history[-window:]} if window else set()
        recent_templates = {h[0] for h in history[-TEMPLATE_COOLDOWN:]}
        # Premise cooldown takes precedence over the older (template, name)
        # rule; otherwise exhausted name pairs can force a very recent joke.
        fresh = [p for p in pairs if p[0]["id"] not in recent_templates]
        if not fresh:  # small nameless-only catalogue: repeat the oldest premise
            last_used = {h[0]: i for i, h in enumerate(history)}
            oldest = min(last_used.get(p[0]["id"], -1) for p in pairs)
            fresh = [p for p in pairs if last_used.get(p[0]["id"], -1) == oldest]
        fresh = [p for p in fresh if (p[0]["id"], p[1]) not in recent] or fresh

        bits = [p for p in fresh if not p[0]["uses_name"]]
        generic = [p for p in fresh if p[0]["uses_name"]
                   and p[0]["tag"] == "any" and not p[0]["days"]]
        tagged = [p for p in fresh if p[0]["uses_name"]
                  and not (p[0]["tag"] == "any" and not p[0]["days"])]
        random.shuffle(bits)
        random.shuffle(generic)
        random.shuffle(tagged)

        # interleave so a cycle can't fill up with lines that need snow in July,
        # capping how often any single template recurs within the cycle
        cycle, counts, used = [], {}, set()

        def take(lst):
            while lst:
                p = lst.pop()
                tid = p[0]["id"]
                key = (tid, p[1])  # (template, lead name) — the identity readers perceive
                if counts.get(tid, 0) < PER_TEMPLATE_CAP and key not in used:
                    counts[tid] = counts.get(tid, 0) + 1
                    used.add(key)
                    return p
            return None

        # A nameless bit is ONE pair (no name to permute) against thousands of
        # named ones, so left to the shuffle it shows up about once a quarter.
        # Give the bits a quota first; the final shuffle scatters them.
        for _ in range(min(len(bits), CYCLE_SIZE // BIT_EVERY)):
            p = take(bits)
            if p:
                cycle.append(p)

        while len(cycle) < CYCLE_SIZE and (generic or tagged):
            for _ in range(ANY_PER_TAGGED):
                if len(cycle) < CYCLE_SIZE:
                    p = take(generic)
                    if p:
                        cycle.append(p)
            if len(cycle) < CYCLE_SIZE:
                p = take(tagged)
                if p:
                    cycle.append(p)
        random.shuffle(cycle)

        next_id = int(prev.get("next_id") or 1)
        pending = []
        for tpl, name, name2 in cycle:
            pending.append({
                "id": next_id,
                "t": tpl["id"],
                "name": name,
                "name2": name2,
                "fills": {b: random.choice(WORD_BANKS[b]) for b in tpl["banks"]},
            })
            next_id += 1

        state = {
            "version": VERSION,
            "names_key": names_key(names),
            "cycle_num": int(prev.get("cycle_num") or 0) + 1,
            "next_id": next_id,
            "pending": pending,
            "history": history[-HISTORY_MAX:],
            "last_posted": prev.get("last_posted"),
            "weather_days": prev.get("weather_days", []),
            "pending_event": prev.get("pending_event"),
            "committed_ids": prev.get("committed_ids", []),
        }
        _log(f"generated cycle {state['cycle_num']} — {len(pending)} lines for {len(names)} name(s)")
        return state

    def _ensure(self, names):
        """Load state, regenerating when it's missing, stale or spent."""
        state = self._load()
        stale = (
            not isinstance(state, dict)
            or state.get("version") != VERSION
            or state.get("names_key") != names_key(names)
        )
        if not stale:
            pending = [e for e in (state.get("pending") or [])
                       if isinstance(e, dict) and e.get("t") in TEMPLATES_BY_ID]
            if len(pending) != len(state.get("pending") or []):
                state["pending"] = pending   # content edit dropped a template id
                self._save(state)
            stale = not pending
        if stale:
            state = self._new_cycle(names, state if isinstance(state, dict) else None)
            self._save(state)
        return state

    # -- selection ------------------------------------------------------------
    def _select(self, state, bucket, avail, today):
        """Prefer premises outside the cooldown, then rank the shuffled front.
        Generic catalogue entries have equal rank. Eligibility also supports
        weather/day restrictions for future catalogue additions.
        """
        pending = state.get("pending") or []
        recent_templates = {h[0] for h in state.get("history", [])[-TEMPLATE_COOLDOWN:]}
        fresh = [(i, e) for i, e in enumerate(pending) if e.get("t") not in recent_templates]
        if fresh:
            indexed_pending = fresh
        else:
            indexed_pending = list(enumerate(pending))

        def best_in(indexed):
            best = None
            for i, entry in indexed:
                tpl = TEMPLATES_BY_ID.get(entry.get("t"))
                if tpl is None or not _eligible(tpl, bucket, avail, today):
                    continue
                rank = _rank(tpl)
                if best is None or rank < best[0]:
                    best = (rank, i, entry)
                    if rank == 0:
                        break
            return best

        hit = best_in(indexed_pending[:SELECT_WINDOW])
        if hit is None:   # nothing eligible up front — fall back to the full queue
            hit = best_in(indexed_pending)
        return hit[1:] if hit else None

    def _peek(self, names, fc=None, now=None, event=None):
        """Choose today's line without consuming it. Assumes the lock is held."""
        names = clean_names(names)
        state = self._ensure(names)
        if event:
            return self._event_pick(state, event)
        wvals = weather_values(fc)
        avail, bucket, today = set(wvals), bucket_for(fc), day_key(now)
        for _ in range(3):
            hit = self._select(state, bucket, avail, today)
            if hit is None:
                # nothing left that fits today (e.g. only snow lines remain in July)
                state = self._new_cycle(names, state)
                self._save(state)
                continue
            idx, entry = hit
            try:
                rendered = render(entry, wvals)
            except Exception as e:
                _log(f"dropping unrenderable entry {entry.get('t')}: {e}")
                state["pending"].pop(idx)
                self._save(state)
                continue
            out = dict(entry)
            out["rendered"] = rendered
            return out
        return None

    # -- public ---------------------------------------------------------------
    def weather(self, observations, now):
        with self._lock:
            state = self._load() or {}
            return weather_context.describe(state.get("weather_days", []), observations, now)

    def _event_pick(self, state, event, skip=None):
        signature = json.dumps(event, sort_keys=True)
        cached = state.get("pending_event")
        if cached and cached.get("signature") == signature and skip is None:
            return dict(cached)
        lines = weather_context.EVENT_LINES[event["kind"]]
        candidates = [(f"event_{event['kind']}_{i}", line) for i, line in enumerate(lines)]
        history = [h[0] for h in state.get("history", [])]
        # Exhaust the event's premises before repeating, even across towns.
        last_used = {tid: i for i, tid in enumerate(history)}
        candidates = [(tid, line) for tid, line in candidates if tid != skip]
        oldest = min(last_used.get(tid, -1) for tid, _ in candidates)
        tid, line = random.choice([(tid, line) for tid, line in candidates
                                   if last_used.get(tid, -1) == oldest])
        entry = {"id": state["next_id"], "t": tid, "name": "", "event": True,
                 "signature": signature, "rendered": line.format(**event["facts"])}
        state["next_id"] += 1
        state["pending_event"] = entry
        self._save(state)
        return dict(entry)

    def peek(self, names, fc=None, now=None, event=None):
        """Today's line as an entry dict with a 'rendered' key, or None.
        Deterministic: same state + same morning gives the same line, which is
        what makes the 15-minute retry re-post identical text."""
        with self._lock:
            return self._peek(names, fc, now, event)

    def commit(self, entry):
        """Consume a line. Only called after the webhook actually accepted it.
        Idempotent by entry id, so a duplicate call is a no-op."""
        if not entry:
            return False
        with self._lock:
            state = self._load() or {}
            if "t" in entry and entry.get("id") in state.get("committed_ids", []):
                return False
            snapshot = entry.get("weather_snapshot")
            if snapshot:
                days = [d for d in state.get("weather_days", [])
                        if (d["date"], d["timezone"]) != (snapshot["date"], snapshot["timezone"])]
                days.append(snapshot)
                state["weather_days"] = sorted(days, key=lambda d: d["date"])[-400:]
            if "t" not in entry:
                self._save(state)
                return bool(snapshot)
            pending = state.get("pending") or []
            idx = next((i for i, e in enumerate(pending) if e.get("id") == entry.get("id")), None)
            if entry.get("event"):
                # A preview may have refreshed the pending event during send.
                if (state.get("pending_event") or {}).get("id") == entry.get("id"):
                    state["pending_event"] = None
            else:
                if idx is None:
                    self._save(state)
                    return False
                pending.pop(idx)
            history = [h for h in (state.get("history") or []) if isinstance(h, list)]
            history.append([entry.get("t"), entry.get("name") or ""])
            state["pending"] = pending
            state["history"] = history[-HISTORY_MAX:]
            state["last_posted"] = {"at": int(time.time()), "text": entry.get("rendered", "")}
            state["committed_ids"] = (state.get("committed_ids", []) + [entry.get("id")])[-HISTORY_MAX:]
            self._save(state)
            return True

    def reroll(self, names, fc=None, now=None, event=None):
        """Rotate the current pick to the back of the queue and draw the next.
        The skipped line was never posted, so it stays in the cycle."""
        with self._lock:
            names = clean_names(names)
            current = self._peek(names, fc, now, event)
            if current is None:
                return {"ok": False, "error": "no line available"}
            state = self._load() or {}
            pending = state.get("pending") or []
            if event:
                nxt = self._event_pick(state, event, skip=current["t"])
                return {"ok": True, "skipped": current["rendered"], "next": nxt["rendered"],
                        "remaining": len(pending)}
            idx = next((i for i, e in enumerate(pending) if e.get("id") == current.get("id")), None)
            if idx is not None:
                pending.append(pending.pop(idx))
                state["pending"] = pending
                self._save(state)
            nxt = self._peek(names, fc, now)
            out = {"ok": True, "skipped": current.get("rendered"),
                   "next": nxt.get("rendered") if nxt else None,
                   "remaining": len(pending)}
            if nxt and nxt.get("id") == current.get("id"):
                out["note"] = "only one line fits today — nothing to rotate to"
            return out

    def status(self, names):
        """Summary for the webapp card. Peeks with no weather, so it's fast and
        the 'next' line shown is the generic-fallback view."""
        with self._lock:
            names = clean_names(names)
            state = self._ensure(names)
            nxt = self._peek(names, None, None)
            return {
                "remaining": len(state.get("pending") or []),
                "cycle": state.get("cycle_num") or 0,
                "history": len(state.get("history") or []),
                "next_generic": nxt.get("rendered") if nxt else None,
                "last_posted": state.get("last_posted"),
                "pool_size": len(TEMPLATES),
            }


def _all_pairs(names):
    """Every (template, name, name2) combination available for these names."""
    pairs = []
    for tpl in TEMPLATES:
        if tpl["two_names"]:
            if len(names) >= 2:
                pairs.extend((tpl, a, b) for a, b in itertools.permutations(names, 2))
        elif tpl["uses_name"]:
            pairs.extend((tpl, n, None) for n in names)
        else:
            pairs.append((tpl, "", None))   # nameless line: one pair, not one per name
    return pairs


# ── standalone taste-test ─────────────────────────────────────────────────────
_DEMO_NAMES = ["Joe Stasi", "Matt duBourg", "Andrew Kenny", "Tommy Whisker",
               "Anthony Johnson", "Joey Oddo", "Stanley Mcombe", "Nino",
               "Ryan Ardito", "Matt Kaprowski"]

_DEMO_WEATHER = {
    "hot":  {"hi": 94, "lo": 76, "feels": 99, "rain": 5, "wind": 8, "uv": 9,
             "humidity": 61, "cond": "Clear Sky", "emoji": "☀️"},
    "cold": {"hi": 34, "lo": 21, "feels": 25, "rain": 10, "wind": 17, "uv": 2,
             "humidity": 55, "cond": "Overcast", "emoji": "☁️"},
    "rain": {"hi": 68, "lo": 59, "feels": 66, "rain": 88, "wind": 12, "uv": 3,
             "humidity": 91, "cond": "Heavy Rain", "emoji": "🌧️"},
    "snow": {"hi": 31, "lo": 22, "feels": 24, "rain": 90, "wind": 15, "uv": 1,
             "humidity": 80, "cond": "Heavy Snow", "emoji": "❄️"},
    "nice": {"hi": 76, "lo": 61, "feels": 74, "rain": 4, "wind": 7, "uv": 6,
             "humidity": 48, "cond": "Partly Cloudy", "emoji": "⛅"},
}


def _demo_entry(tpl, names):
    name = random.choice(names)
    name2 = random.choice([n for n in names if n != name]) if tpl["two_names"] else None
    return {"id": 0, "t": tpl["id"], "name": name if tpl["uses_name"] else "",
            "name2": name2,
            "fills": {b: random.choice(WORD_BANKS[b]) for b in tpl["banks"]}}


def _demo_render(tpl, names):
    """Render one template against weather/day that satisfies it."""
    bucket = tpl["tag"] if tpl["tag"] != "any" else random.choice(list(_DEMO_WEATHER))
    wvals = weather_values(_DEMO_WEATHER[bucket])
    return render(_demo_entry(tpl, names), wvals)


def _stats():
    by_tag, by_day = {}, 0
    for tpl in TEMPLATES:
        by_tag[tpl["tag"]] = by_tag.get(tpl["tag"], 0) + 1
        by_day += 1 if tpl["days"] else 0
    pairs = len(_all_pairs(_DEMO_NAMES))
    combos = sum(
        len(_DEMO_NAMES) * _fill_space(tpl) * (len(_DEMO_NAMES) - 1 if tpl["two_names"] else 1)
        for tpl in TEMPLATES if tpl["uses_name"])
    tags = " ".join(f"{k}={v}" for k, v in sorted(by_tag.items()))
    return (f"{len(TEMPLATES)} templates ({tags}, weekday-pinned={by_day}) · "
            f"{len(WORD_BANKS)} banks · {pairs} template-name pairs for "
            f"{len(_DEMO_NAMES)} names · ~{combos:,} distinct lines")


def _fill_space(tpl):
    n = 1
    for bank in tpl["banks"]:
        n *= len(WORD_BANKS[bank])
    return n


def _main(argv):
    import sys
    names = _DEMO_NAMES
    if "--all" in argv:
        for tpl in TEMPLATES:
            print(f"[{tpl['id']} {tpl['tag']}{'/' + ','.join(sorted(tpl['days'])) if tpl['days'] else ''}] "
                  f"{_demo_render(tpl, names)}")
    else:
        count = next((int(a) for a in argv if a.isdigit()), 15)
        for tpl in random.choices(TEMPLATES, k=count):
            print(f"· {_demo_render(tpl, names)}")
    print(f"\n{_stats()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
