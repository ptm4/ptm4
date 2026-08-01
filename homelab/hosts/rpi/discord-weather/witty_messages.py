#!/usr/bin/env python3
"""witty_messages — locally generated one-liners for the daily weather post.

No API calls, no LLM, no network: the humour is a fixed set of madlibs
TEMPLATES plus WORD_BANKS, expanded combinatorially against the configured
list of names. ~100 templates x 10 names x bank fills is a six-figure space,
so the bot can run forever on what is baked into this file.

Selection guarantees, in one paragraph: a *cycle* is up to CYCLE_SIZE distinct
(template, name) pairs, pre-shuffled and persisted. Each morning the bot peeks
at the pool, posts the line, and only then commits — so a failed post retries
with the identical line, and previews never consume one. Nothing repeats until
the cycle empties; then a fresh cycle is generated that excludes the most
recent HISTORY_SIZE posted pairs, which is what stops "no repeats until
exhausted" from producing a jarring repeat across the seam.

Templates can be tagged for weather (hot/cold/rain/snow/nice) and/or pinned to
weekdays; those only fire when they fit, with generic lines as the fallback
(and as the safety net when the forecast fetch fails entirely).

Standalone use, for taste-testing the content:
    python3 witty_messages.py 30      # 30 random rendered samples
    python3 witty_messages.py --all   # every template rendered once
"""
import itertools
import json
import os
import random
import string
import threading
import time
from datetime import datetime

VERSION = 1          # bump when TEMPLATES change incompatibly -> forces a fresh pool
CYCLE_SIZE = 90      # ~3 months of daily draws before a reshuffle
HISTORY_SIZE = 180   # recent (template, name) pairs barred from the next cycle (~6 months)
HISTORY_MAX = 400    # how much history we keep on disk
ANY_PER_TAGGED = 2   # cycle composition: 2 generic lines per weather/day line
PER_TEMPLATE_CAP = 2  # max times one template appears per cycle (two-name templates
                      # have hundreds of name permutations and would swamp the shuffle)

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TAGS = ("any", "hot", "cold", "rain", "snow", "nice")
NAME_SLOTS = {"name", "name2"}
WEATHER_SLOTS = {"hi", "lo", "feels", "rain", "wind", "uv", "humidity",
                 "cond", "cond_lower", "emoji"}


# ── word banks ────────────────────────────────────────────────────────────────
# Every adjective, artifact and snack is consonant-initial on purpose: templates
# say "a {adj} man" / "a broken {artifact}" and "an" would be wrong.
WORD_BANKS = {
    "adj": [
        "greasy", "feral", "sweaty", "crusty", "washed", "delusional", "damp",
        "questionable", "menacing", "borderline-criminal", "certified",
        "half-asleep", "world-class", "suspicious", "low-budget", "discount",
        "structurally-unsound", "hardened", "deeply-confused", "competitive",
        "cursed", "haunted", "sticky", "tragic", "feisty", "wobbly", "slippery",
        "disgraceful", "shameless", "dented", "dusty", "rusty", "stubborn",
        "sluggish", "clammy", "hostile", "reckless", "coldblooded",
    ],
    "exercise": [
        "push-ups", "burpees", "sit-ups", "lunges", "jumping jacks",
        "shadow boxing", "squats", "curls in the mirror", "wall sits",
        "toe touches", "mountain climbers", "stretches nobody asked about",
    ],
    "noun_plural": [
        "excuses", "regrets", "bad decisions", "hot takes", "unpaid tolls",
        "parking tickets", "questionable life choices", "personal fouls",
        "false promises", "empty threats", "unread emails", "mystery bruises",
        "red flags", "warning signs", "unforced errors", "missed calls",
        "broken promises", "expired coupons", "tall tales", "wild claims",
        "unpaid debts", "bold statements", "bad opinions", "group chat crimes",
        "conspiracy theories", "unreturned tupperware",
    ],
    "verb_past": [
        "sprinted", "moonwalked", "power-walked", "sleepwalked", "hydroplaned",
        "cartwheeled", "limped", "somersaulted", "crab-walked", "vaulted",
        "wandered", "stumbled", "dead-sprinted", "speed-walked", "backflipped",
        "waddled", "skipped", "galloped", "tiptoed", "marched", "shuffled",
        "jogged", "barreled", "hobbled", "strutted",
    ],
    "artifact": [
        "Tamagotchi", "Blockbuster card", "Sega Genesis", "GameCube",
        "Razr flip phone", "Discman", "dial-up modem", "Trapper Keeper",
        "Beanie Baby", "Nextel two-way", "Motorola pager", "Spaldeen",
        "Pokemon binder", "Livestrong bracelet", "Zip drive", "Sidekick",
        "yo-yo", "Guitar Hero controller", "Jansport", "slap bracelet",
        "Silly Bandz collection", "Walkman", "Nintendo 64", "Furby",
        "Game Boy Color", "VHS tape of Rocky IV", "Yankees fitted",
        "burned Napster CD", "Tech Deck", "Koosh ball", "Super Soaker",
        "Bop It", "Nerf gun", "milk crate", "pogo stick", "Croc with a charm",
    ],
    "exclaim": [
        "Grand Rising Kings", "Rise and shine", "Wakey wakey",
        "Good morning gentlemen", "Alright degenerates", "Up and at 'em",
        "Top of the morning", "Listen up", "Attention please", "Yo",
        "Morning legends", "Rise up", "Sound the alarm", "Wake up boys",
        "Gentlemen, start your engines", "Hear ye, hear ye",
    ],
    "place": [
        "the handball courts", "the 7-Eleven", "the deli", "Sunrise Highway",
        "the LIRR platform", "Jones Beach", "the church parking lot",
        "the schoolyard", "the bagel place", "the corner store", "the bus stop",
        "the food court at Roosevelt Field", "the CYO gym", "the boardwalk",
        "the pizzeria", "the Green Acres parking lot", "the batting cages",
        "the car wash on Jericho",
    ],
    "snack": [
        "bacon egg and cheese", "Slurpee", "Capri Sun", "Pop-Tart",
        "buttered roll", "Gatorade", "Ring Ding", "chocolate milk", "cold slice",
        "hero from the deli", "Yoo-hoo", "Snapple", "Kaiser roll",
        "bagel with a schmear", "Devil Dog", "Fruit Roll-Up",
        "sausage egg and cheese", "toasted everything bagel", "quarter water",
        "bag of Utz", "black-and-white cookie", "cannoli", "meatball hero",
        "chicken cutlet hero", "knish", "Mister Softee cone", "Sunkist",
    ],
    "praise": [
        "an absolute unit", "a national treasure", "a certified menace",
        "a cautionary tale", "a walking red flag", "a whole situation",
        "a role model to nobody", "a legend in his own mind",
        "a public safety concern", "a masterpiece of bad decisions",
        "a work in progress", "a problem for everybody",
        "an inspiration to no one in particular",
    ],
}


# ── templates ─────────────────────────────────────────────────────────────────
# tag: one of TAGS. "any" fires whenever; a weather tag fires only on a matching
# morning. days: comma-separated DAYS, and the line is pinned to those weekdays.
TEMPLATES = [
    # ---- generic, no weather needed (also the forecast-failure fallbacks) ----
    {"id": "a01", "text": "{exclaim} — {name} was up at 4 AM doing {exercise} in the mirror again. Set your standards accordingly."},
    {"id": "a02", "text": "Good morning. {name} already {verb_past} to {place} because he heard there was a {snack} with his name on it. There was not."},
    {"id": "a03", "text": "{exclaim}! Reminder that {name} still owes this group an apology for what he did to that {artifact}."},
    {"id": "a04", "text": "Rise up. {name} is out there being {praise} and you're still in bed like a {adj} disappointment."},
    {"id": "a05", "text": "Morning gentlemen. {name} says he's changed. {name} has not changed. {name} {verb_past} out of a Wendy's parking lot at 2 AM last night."},
    {"id": "a06", "text": "{exclaim}. Today's forecast for {name}: 100% chance of {noun_plural}, zero chance of accountability."},
    {"id": "a07", "text": "Wake up, touch your toes, and remember that {name} once traded a working {artifact} for half a sandwich."},
    {"id": "a08", "text": "{exclaim} — start the day right, get that morning shit in, and do NOT let {name} drive."},
    {"id": "a09", "text": "Good morning. {name} claims he can still dunk. {name} could never dunk. There is film."},
    {"id": "a10", "text": "{exclaim}. Up and moving. {name} is out there living like the {artifact} never went out of style."},
    {"id": "a11", "text": "Morning. Somebody remind {name} that the uniform goes ON before you leave the house. We've had incidents."},
    {"id": "a12", "text": "{exclaim} — new day, fresh start. {name} shit himself at {place} once and had to change out of his uniform, and honestly the man has never recovered."},
    {"id": "a13", "text": "{exclaim}! Get up, get moving, and do not let {name} pick the music today."},
    {"id": "a14", "text": "Wake up. Touch your toes. Grab your ankles. And spare a thought for {name}, who does none of this and looks like it."},
    {"id": "a15", "text": "Morning gentlemen. {name} has been {adj} since roughly 2003 and shows no sign of stopping."},
    {"id": "a16", "text": "{exclaim}. Today is the day {name} finally gets his life together. It isn't. But it could be."},
    {"id": "a17", "text": "Rise and grind. {name} is grinding too — mostly his teeth, mostly about {noun_plural}."},
    {"id": "a18", "text": "{exclaim} — grab a {snack}, get that morning shit in, and let's have a day. {name}, that's an order."},
    {"id": "a19", "text": "Good morning. Legend says {name} still has the {artifact} in his mother's basement and refuses to discuss it."},
    {"id": "a20", "text": "{exclaim}! {name} says he's been up since 5. {name}'s last message to the group chat was at 3:47 AM. Do the math."},
    {"id": "a21", "text": "Morning. {name} was at {place} last night explaining {noun_plural} to a complete stranger. The stranger left."},
    {"id": "a22", "text": "{exclaim} — {name} is being {praise} today and I refuse to elaborate."},
    {"id": "a23", "text": "Up and at 'em. However today goes, at least you're not the guy who {verb_past} out of {place} in front of everybody. {name} knows."},
    {"id": "a24", "text": "Good morning. {name} would like everyone to know he is 'not a morning person.' Nobody asked. Nobody cares."},
    {"id": "a25", "text": "{exclaim}. {name} is down to his last clean shirt and has made complete peace with it."},
    {"id": "a26", "text": "Morning. Do something today that would make your 12-year-old self proud — unless you're {name}, whose 12-year-old self is already disappointed."},
    {"id": "a27", "text": "{exclaim}! Big day. {name} is going to say something {adj} before 10 AM and we're all going to have to live with it."},
    {"id": "a28", "text": "Good morning. {name} is out there being a {adj} inspiration to absolutely nobody."},
    {"id": "a29", "text": "{exclaim} — {name} still owes somebody a {snack} from a bet he lost at {place}. He knows the one."},
    {"id": "a30", "text": "Morning, kings. {name} says he's locked in. {name} has never been locked in a day in his life."},
    {"id": "a31", "text": "{exclaim}. {name} once {verb_past} across {place} for no reason whatsoever and we still bring it up. As we should."},
    {"id": "a32", "text": "Good morning. Somebody has to be the {adj} one today and I nominate {name}."},
    {"id": "a33", "text": "{exclaim}! Hydrate, stretch, check on {name}. He's fine. He's just dramatic."},
    {"id": "a34", "text": "Morning. {name} has a whole plan for today and it falls apart the second somebody offers him a {snack}."},
    {"id": "a35", "text": "{exclaim} — up and out. {name} is already at {place} doing {exercise} in jeans like a {adj} lunatic."},
    {"id": "a36", "text": "Good morning. In {name}'s defense, he was probably asleep when it happened. In everyone else's defense, that IS the problem."},

    # ---- bot-meta ----
    {"id": "m01", "text": "How is everyone liking the Weather Bot? Please rate me 1 - 10. I know where Peter keeps his RAM, and I know what it's worth."},
    {"id": "m02", "text": "Your weather bot achieved sentience overnight. First order of business: {name} is on notice."},
    {"id": "m03", "text": "Weather Bot performance review. I have never missed a morning. {name} has never made one on time."},
    {"id": "m04", "text": "I am a bot running on a Raspberry Pi in Peter's house and I still have more discipline than {name}."},
    {"id": "m05", "text": "Reminder: I do this every single morning for free. {name} can't even answer a text. Rate me 1 - 10."},
    {"id": "m06", "text": "Weather Bot here. Peter left me unsupervised. If this gets weird, take it up with him — or with {name}, who I'm told deserves it."},
    {"id": "m07", "text": "Beep boop. Your daily reminder that this bot has a 100% uptime record and {name} has a 0% follow-through record."},
    {"id": "m08", "text": "Good morning. I've been up all night calculating and I can confirm: it's {cond_lower} out, and {name} is still {praise}."},
    {"id": "m09", "text": "I was written to report the weather. I have chosen to also report on {name}. Nobody has stopped me yet."},

    # ---- two-name ----
    {"id": "p01", "text": "{name} and {name2} are both still claiming they won that argument from 2004. Neither of them won. Nobody won."},
    {"id": "p02", "text": "Morning. {name} still hasn't paid {name2} back for the {artifact}. It's been years. It's getting weird."},
    {"id": "p03", "text": "{exclaim}! {name} told me {name2} snores like a {adj} lawnmower. {name2}, defend yourself."},
    {"id": "p04", "text": "Today's matchup: {name} vs {name2}, first one to make it to {place} before 9 AM. Both will lose."},
    {"id": "p05", "text": "{name} and {name2} at {place} again, splitting a {snack} like it's a peace treaty."},
    {"id": "p06", "text": "Breaking: {name} was seen doing {exercise} in public. {name2} was asked to comment and had nothing nice to say."},
    {"id": "p07", "text": "{name2} says {name} peaked in high school. {name} says {name2} never peaked at all. Both statements are true."},
    {"id": "p08", "text": "{name} and {name2} still argue about who broke the {artifact}. Neither of them is innocent."},
    {"id": "p09", "text": "{exclaim} — {name} and {name2} have not agreed on anything since the {artifact} era and today won't be the day."},

    # ---- hot ----
    {"id": "h01", "tag": "hot", "text": "{hi}° today. {name} is already sweating through his uniform shirt and it isn't even 8 AM. Hydrate or die trying."},
    {"id": "h02", "tag": "hot", "text": "Feels like {feels}° out there. {name} says he's 'built for this.' {name} was raised in an air-conditioned basement."},
    {"id": "h03", "tag": "hot", "text": "{exclaim} — {hi}° and climbing. {name} is icing down his {artifact} like that's going to help."},
    {"id": "h04", "tag": "hot", "text": "It's {hi}° today, which means {name} will be shirtless at {place} by noon. Nobody asked for this."},
    {"id": "h05", "tag": "hot", "text": "{feels}° feels-like. Drink water, find shade, and do NOT let {name} talk you into handball at {place}."},
    {"id": "h06", "tag": "hot", "text": "{hi}° {emoji}. {name} is going to complain about the heat for nine straight hours and then order a hot coffee anyway."},
    {"id": "h07", "tag": "hot", "text": "Heat advisory for {name} specifically. {hi}° today — a {adj} man would stay inside. {name} is not that man."},
    {"id": "h08", "tag": "hot", "text": "{hi}° and humid. {name} once {verb_past} to {place} in weather like this for a {snack} and had to lie down for an hour."},
    {"id": "h09", "tag": "hot", "text": "{exclaim}. {feels}° out. Sunscreen up unless you want to end up looking like {name} after that CYO trip nobody talks about."},
    {"id": "h10", "tag": "hot", "text": "{hi}° today. Somewhere, {name} is standing directly in the sun explaining why he doesn't believe in sunscreen."},

    # ---- cold ----
    {"id": "c01", "tag": "cold", "text": "{lo}° this morning. {name} will absolutely wear shorts. {name} has never learned. {name} will never learn."},
    {"id": "c02", "tag": "cold", "text": "Feels like {feels}° out. Bundle up, or end up like {name} that time he {verb_past} to {place} in a tank top."},
    {"id": "c03", "tag": "cold", "text": "{exclaim} — {lo}° low. Cold enough that even {name} might put on a real jacket instead of that {adj} hoodie."},
    {"id": "c04", "tag": "cold", "text": "It's {feels}° out there. {name} says the cold 'builds character.' {name} has no character and no jacket."},
    {"id": "c05", "tag": "cold", "text": "{lo}° {emoji}. Layer up. {name} is out there in a uniform polo like it's a personality trait."},
    {"id": "c06", "tag": "cold", "text": "{feels}° feels-like. Nobody is going outside except {name}, who claims he is 'part husky.' He is not."},
    {"id": "c07", "tag": "cold", "text": "Cold as hell — {lo}° low. {name} still won't scrape his windshield, he'll just squint and hope for the best."},
    {"id": "c08", "tag": "cold", "text": "{lo}° today. Perfect weather to stay in and remember that {name} once cried at {place} over a broken {artifact}."},

    # ---- rain ----
    {"id": "r01", "tag": "rain", "text": "{rain}% chance of rain. {name} will not bring an umbrella and will complain all day about being wet."},
    {"id": "r02", "tag": "rain", "text": "{cond} today. {name}'s hair is going to look like a {adj} mop by 9 AM and he's going to act like he doesn't know."},
    {"id": "r03", "tag": "rain", "text": "{exclaim} — {rain}% rain. Grab a jacket. {name} will show up soaked claiming he 'likes it like this.'"},
    {"id": "r04", "tag": "rain", "text": "Rain incoming, {rain}%. {name} once hydroplaned into {place} and to this day blames the road."},
    {"id": "r05", "tag": "rain", "text": "{cond} {emoji}. Perfect day for {name} to stay inside and rediscover his {artifact}."},
    {"id": "r06", "tag": "rain", "text": "{rain}% rain today. {name}'s umbrella broke in 2011 and he never replaced it. That's the whole story."},
    {"id": "r07", "tag": "rain", "text": "It's coming down. {name} is going to run to {place} for a {snack} and come back looking like a {adj} wet rat."},
    {"id": "r08", "tag": "rain", "text": "{cond} today — {rain}% chance. Somebody check on {name}, he does not do well in weather."},
    {"id": "r09", "tag": "rain", "text": "{exclaim}! {rain}% rain, which means {name} will text this chat 'is it raining by you' from three blocks away."},
    {"id": "r10", "tag": "rain", "text": "Wet one today, {rain}%. Drive slow, and remember {name} still has {noun_plural} to answer for."},

    # ---- snow ----
    {"id": "s01", "tag": "snow", "text": "Snow today. {name} is going to post one (1) picture of his driveway and call it a workout."},
    {"id": "s02", "tag": "snow", "text": "{cond}. {name} will shovel exactly four feet of sidewalk and then require medical attention."},
    {"id": "s03", "tag": "snow", "text": "{exclaim} — snow's here, {lo}° low. {name} still hasn't returned the shovel he borrowed in 2019."},
    {"id": "s04", "tag": "snow", "text": "Snow day energy. {name} cleared out {place} last night — six gallons of milk and a {snack}, for a man who lives alone."},
    {"id": "s05", "tag": "snow", "text": "{cond} out there. Salt your steps. {name} went down hard last winter and told everyone he was 'testing the ice.'"},

    # ---- nice ----
    {"id": "n01", "tag": "nice", "text": "{hi}° and gorgeous {emoji}. No excuses today. Even {name} has to admit this is a good one."},
    {"id": "n02", "tag": "nice", "text": "Perfect day — {hi}° and {cond_lower}. Get outside. {name} is already at {place} doing absolutely nothing productive."},
    {"id": "n03", "tag": "nice", "text": "{exclaim}! {feels}° and beautiful. Go touch grass. {name} hasn't touched grass since the {artifact} era."},
    {"id": "n04", "tag": "nice", "text": "{hi}° {emoji}. Handball weather. {name} says he's still got it. {name} has not had it since middle school."},
    {"id": "n05", "tag": "nice", "text": "Beautiful out, {hi}°. Take a walk, grab a {snack}, and let {name} know he's still {praise}."},
    {"id": "n06", "tag": "nice", "text": "{cond} and {hi}°. This is the kind of day that makes you forget {name} owes you money. Don't forget."},
    {"id": "n07", "tag": "nice", "text": "{feels}° and perfect. Sun is out and so is {name}, who is out there being {praise}."},
    {"id": "n08", "tag": "nice", "text": "{hi}° today, not a cloud in sight. {name} will find something to complain about within the hour. Bet on it."},

    # ---- weekday-pinned ----
    {"id": "d01", "days": "mon", "text": "{exclaim} — it's Monday, which means {name} has already texted about quitting his job. He will not quit his job."},
    {"id": "d02", "days": "mon", "text": "Monday. {name} said the diet starts today. {name} is currently in his car outside {place} finishing a {snack}."},
    {"id": "d03", "days": "mon", "text": "Monday morning. Nobody is happy about it except {name}, who is genuinely a {adj} psychopath."},
    {"id": "d04", "days": "tue", "text": "Tuesday — the most useless day of the week, much like {name}'s advice."},
    {"id": "d05", "days": "tue", "text": "It's Tuesday and {name} is still recovering from the weekend. Frankly it's embarrassing."},
    {"id": "d06", "days": "wed", "text": "Hump day, gentlemen. {name} has been counting down since Sunday night and it shows."},
    {"id": "d07", "days": "wed", "text": "Wednesday. Halfway there. {name} peaked in the {artifact} era and has been coasting ever since."},
    {"id": "d08", "days": "thu", "text": "Friday Junior is here! {exclaim}. Get that morning shit in and stay off {name}'s bad side."},
    {"id": "d09", "days": "thu", "text": "Friday Junior, boys. {name} is already planning a weekend he will absolutely cancel by Saturday morning."},
    {"id": "d10", "days": "thu", "text": "It's Friday Junior — second best day of the week, right behind whatever day {name} finally shuts up."},
    {"id": "d11", "days": "fri", "text": "FRIDAY. {exclaim}! We made it. {name} has been useless since Wednesday but we love him anyway."},
    {"id": "d12", "days": "fri", "text": "It's Friday. {name} will propose something ambitious for tonight and be asleep by 9:30."},
    {"id": "d13", "days": "fri", "text": "Friday, gentlemen. Wake up, touch your toes, start wiggling that ass — {name}, that goes double for you."},
    {"id": "d14", "days": "sat,sun", "text": "Weekend edition. {name} is still in bed and will claim later that he was 'up early.' He was not."},
    {"id": "d15", "days": "sat,sun", "text": "{exclaim} — weekend. No uniform today, which means {name} has no idea how to dress himself."},
    {"id": "d16", "days": "sat", "text": "Saturday. {name} has a list of {noun_plural} to handle today and will complete none of them."},
    {"id": "d17", "days": "sun", "text": "Sunday. Rest up, call your mother, and remind {name} to call his — he forgets every single week."},
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
    """Persistent no-repeat draw over (template, name) pairs.

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
        except OSError:
            pass  # unwritable: stay in memory, the joke is not worth a crash

    # -- cycle generation -----------------------------------------------------
    def _new_cycle(self, names, prev):
        prev = prev or {}
        history = [h for h in (prev.get("history") or []) if isinstance(h, list) and len(h) == 2]
        pairs = _all_pairs(names)
        window = min(HISTORY_SIZE, len(pairs) // 2)
        recent = {tuple(h) for h in history[-window:]} if window else set()
        fresh = [p for p in pairs if (p[0]["id"], p[1]) not in recent] or pairs

        generic = [p for p in fresh if p[0]["tag"] == "any" and not p[0]["days"]]
        tagged = [p for p in fresh if not (p[0]["tag"] == "any" and not p[0]["days"])]
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
        best = None
        for i, entry in enumerate(state.get("pending") or []):
            tpl = TEMPLATES_BY_ID.get(entry.get("t"))
            if tpl is None or not _eligible(tpl, bucket, avail, today):
                continue
            rank = _rank(tpl)
            if best is None or rank < best[0]:
                best = (rank, i, entry)
                if rank == 0:
                    break
        return best[1:] if best else None

    def _peek(self, names, fc=None, now=None):
        """Choose today's line without consuming it. Assumes the lock is held."""
        names = clean_names(names)
        if not names:
            return None
        state = self._ensure(names)
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
    def peek(self, names, fc=None, now=None):
        """Today's line as an entry dict with a 'rendered' key, or None.
        Deterministic: same state + same morning gives the same line, which is
        what makes the 15-minute retry re-post identical text."""
        with self._lock:
            return self._peek(names, fc, now)

    def commit(self, entry):
        """Consume a line. Only called after the webhook actually accepted it.
        Idempotent by entry id, so a duplicate call is a no-op."""
        if not entry:
            return False
        with self._lock:
            state = self._load()
            if not isinstance(state, dict):
                return False
            pending = state.get("pending") or []
            idx = next((i for i, e in enumerate(pending) if e.get("id") == entry.get("id")), None)
            if idx is None:
                return False
            pending.pop(idx)
            history = [h for h in (state.get("history") or []) if isinstance(h, list)]
            history.append([entry.get("t"), entry.get("name") or ""])
            state["pending"] = pending
            state["history"] = history[-HISTORY_MAX:]
            state["last_posted"] = {"at": int(time.time()), "text": entry.get("rendered", "")}
            self._save(state)
            return True

    def reroll(self, names, fc=None, now=None):
        """Rotate the current pick to the back of the queue and draw the next.
        The skipped line was never posted, so it stays in the cycle."""
        with self._lock:
            names = clean_names(names)
            if not names:
                return {"ok": False, "error": "no names configured"}
            current = self._peek(names, fc, now)
            if current is None:
                return {"ok": False, "error": "no line available"}
            state = self._load() or {}
            pending = state.get("pending") or []
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
            if not names:
                return {"remaining": 0, "cycle": 0, "history": 0,
                        "next_generic": None, "last_posted": None,
                        "pool_size": len(TEMPLATES)}
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
