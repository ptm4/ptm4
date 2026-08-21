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

Voice: the poster is "Mr. Murf" — the troop's 55-year-old scoutmaster. Former
70s hippie (Woodstock, a VW bus, a commune phase he half-denies), now runs a
tight ship: full uniform for ceremonies, everything by the Handbook, strict
outdoor rules, and he WILL kick your fire down if it isn't a proper build
(teepee, log cabin, lean-to). Every line is him addressing the troop.

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

VERSION = 2          # bump when TEMPLATES change incompatibly -> forces a fresh pool
                     # v2 (2026-08-21): full content refresh — Mr. Murf voice
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
# Every adjective, artifact, snack and gear item is consonant-initial on
# purpose: templates say "a {adj} man" / "a broken {artifact}" and "an" would
# be wrong. place / praise / hippie items carry their own articles.
WORD_BANKS = {
    "adj": [
        "greasy", "feral", "sweaty", "crusty", "washed-up", "delusional", "damp",
        "questionable", "menacing", "borderline-criminal", "certified",
        "half-asleep", "world-class", "suspicious", "low-budget", "discount",
        "structurally-unsound", "hardened", "deeply-confused", "cursed",
        "haunted", "sticky", "tragic", "wobbly", "slippery", "disgraceful",
        "shameless", "dented", "dusty", "rusty", "stubborn", "sluggish",
        "clammy", "hostile", "reckless", "coldblooded", "badgeless",
        "non-regulation", "sad-looking", "tentless",
    ],
    "exercise": [
        "push-ups", "burpees", "sit-ups", "lunges", "jumping jacks",
        "flutter kicks", "bear crawls", "squats", "wall sits",
        "mountain climbers", "log carries", "morning calisthenics",
        "tent-pitching drills", "orienteering drills",
    ],
    "noun_plural": [
        "excuses", "demerits", "regrets", "bad decisions",
        "uniform infractions", "safety violations", "unearned badges",
        "questionable life choices", "false promises", "empty threats",
        "mystery bruises", "red flags", "unforced errors", "broken promises",
        "curfew violations", "knot failures", "unfinished projects",
        "wild claims", "unpaid debts", "bad opinions", "group chat crimes",
        "conspiracy theories", "unreturned tupperware",
        "fire-code violations", "littering citations",
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
        "Bop It", "Nerf gun", "milk crate", "pogo stick",
        "Pinewood Derby car",
    ],
    # Deliberately no overlap with the literal openers some templates use
    # ("Reveille", "Morning, troop", …) — a bank entry duplicating a literal
    # opener makes identical back-to-back mornings likely.
    "exclaim": [
        "Rise and shine, troop", "Fall in", "Off your bunks",
        "Attention on deck", "Wakey wakey, ladies", "Sound off", "Look alive",
        "On your feet", "Let's move, people", "Daylight's burning",
        "Chins up, chests out", "Ten-hut", "Boots on", "Bugle's blown",
        "Out of the racks",
    ],
    "place": [
        "the handball courts", "the 7-Eleven", "the deli",
        "the LIRR platform", "Jones Beach", "the church parking lot",
        "the schoolyard", "the bagel place", "the corner store", "the bus stop",
        "the food court at Roosevelt Field", "the CYO gym", "the boardwalk",
        "the pizzeria", "the batting cages", "the mess hall",
        "the archery range", "the canoe launch", "the trading post",
        "the latrine trail", "the parade ground",
    ],
    "snack": [
        "bacon egg and cheese", "Slurpee", "Pop-Tart", "buttered roll",
        "Gatorade", "chocolate milk", "cold slice", "hero from the deli",
        "Snapple", "bagel with a schmear", "Devil Dog",
        "sausage egg and cheese", "toasted everything bagel",
        "black-and-white cookie", "cannoli", "meatball hero",
        "chicken cutlet hero", "knish", "Mister Softee cone",
        "bag of trail mix", "s'more", "cup of bug juice",
        "bowl of mystery stew", "government-issue granola bar",
        "canteen of warm Gatorade",
    ],
    "praise": [
        "a disgrace to the uniform", "a walking safety violation",
        "a two-demerit situation", "a cautionary tale",
        "a case study in poor preparation", "the reason we count heads twice",
        "a campfire story I tell as a warning",
        "a hazard to himself and others", "a certified menace",
        "a monument to wasted potential",
        "the reason the buddy system exists", "a public safety concern",
        "a legend in his own mind",
    ],
    "gear": [
        "canteen", "compass", "mess kit", "pocketknife", "tent stake",
        "sleeping bag", "ground tarp", "trail map", "poncho", "whistle",
        "flint and steel", "bear bag",
    ],
    "fire": [
        "teepee", "log cabin", "lean-to", "star", "council", "pyramid",
    ],
    "knot": [
        "bowline", "clove hitch", "taut-line hitch", "square knot",
        "sheet bend", "timber hitch", "figure-eight", "sheepshank",
    ],
    "badge": [
        "Fire Safety", "Orienteering", "First Aid", "Wilderness Survival",
        "Camping", "Cooking", "Personal Fitness", "Emergency Preparedness",
        "Weather",
    ],
}


# ── templates ─────────────────────────────────────────────────────────────────
# tag: one of TAGS. "any" fires whenever; a weather tag fires only on a matching
# morning. days: comma-separated DAYS, and the line is pinned to those weekdays.
# Voice: Mr. Murf, scoutmaster. First person, addressing the troop.
TEMPLATES = [
    # ---- generic, no weather needed (also the forecast-failure fallbacks) ----
    {"id": "a01", "text": "{exclaim} — I was up at 0500. Flag's up, coffee's black, {exercise} done. {name} is still horizontal. Demerits."},
    {"id": "a02", "text": "{exclaim}. Handbook, page 12: BE PREPARED. {name} once showed up to a campout with a {artifact} and a bad attitude. Zero for two."},
    {"id": "a03", "text": "Reveille. I kicked a fire down this morning purely on principle. {name}, consider that a warning shot."},
    {"id": "a04", "text": "{exclaim}! {name} calls himself an outdoorsman. I have watched that man lose a fight with a {gear}."},
    {"id": "a05", "text": "Up and at 'em. Somewhere out there {name} is being {praise}, and it reflects on this whole troop."},
    {"id": "a06", "text": "{exclaim}. Today's forecast for {name}: 100% chance of {noun_plural}, zero merit badges on the horizon."},
    {"id": "a07", "text": "Morning, troop. {name} says he's changed. And yet the man {verb_past} out of a Wendy's parking lot at 2 AM last night. I have the incident report."},
    {"id": "a08", "text": "{exclaim} — buddy check. Everyone accounted for except {name}, who is exactly where you'd expect: nowhere useful."},
    {"id": "a09", "text": "Good morning. In '78 I lived out of a bus with nine strangers and a dog, and it was still better organized than {name}'s entire life."},
    {"id": "a10", "text": "{exclaim}. Surprise uniform inspection at some point today. {name}, that's specifically for you. Tuck it in. All of it."},
    {"id": "a11", "text": "Morning, troop. {name} couldn't tie a {knot} with written instructions and a full week of daylight. This is why we drill."},
    {"id": "a12", "text": "{exclaim}! {name} built what he called a {fire} fire once. I kicked it down before it could embarrass the troop. I'd kick it down again."},
    {"id": "a13", "text": "Reveille, ladies. Touch your toes, drink some water, and pray you never end up like {name}, who is {praise} before most men have coffee."},
    {"id": "a14", "text": "{exclaim}. The {badge} merit badge exists, and {name} not having it tells you everything you need to know about the man."},
    {"id": "a15", "text": "Morning. {name} has been {adj} since roughly 2003. I've filed the paperwork. Nothing can be done."},
    {"id": "a16", "text": "{exclaim} — today {name} squares his life away. That's an order, not a prediction. My predictions are far less generous."},
    {"id": "a17", "text": "Up and at 'em. I have led men through lightning, flash floods, and one bear. None of it prepared me for supervising {name}."},
    {"id": "a18", "text": "{exclaim}. Grab a {snack}, police your area, and keep {name} away from anything with a blade, a flame, or an engine."},
    {"id": "a19", "text": "Good morning. Legend says {name} still keeps the {artifact} in his mother's basement. The Handbook has no chapter for that kind of sad."},
    {"id": "a20", "text": "{exclaim}! Lights-out was 2200. {name}'s last message to this chat was 0347. That's a curfew violation, son, and I don't forget those."},
    {"id": "a21", "text": "Morning, troop. {name} was at {place} last night explaining {noun_plural} to a total stranger. The stranger walked. Smart stranger."},
    {"id": "a22", "text": "{exclaim} — {name} is out there being {praise} this morning, and frankly the troop's insurance can't take much more of him."},
    {"id": "a23", "text": "Reveille. However today goes, remember: you are not the man who {verb_past} out of {place} in front of the whole troop. {name} is."},
    {"id": "a24", "text": "Good morning. {name} says he's 'not a morning person.' Son, I've seen you at noon. It does not get better."},
    {"id": "a25", "text": "{exclaim}. {name} is down to one clean shirt and it is not the uniform one. Inspection is coming. Sweat accordingly."},
    {"id": "a26", "text": "Morning. Do one thing today your 12-year-old self would salute. Unless you're {name} — that kid gave up at the Pinewood Derby and I was there."},
    {"id": "a27", "text": "{exclaim}! {name} will say something {adj} before 0900 and the whole troop will pay for it. Brace."},
    {"id": "a28", "text": "Good morning. I once watched {name} lose a compass. Not misread — lose. It was on a lanyard. Around his neck."},
    {"id": "a29", "text": "{exclaim} — {name} still owes somebody a {snack} from a bet he lost at {place}. A scout's word is his bond. Draw your own conclusions about {name}."},
    {"id": "a30", "text": "Morning, troop. {name} says he's locked in. Sure — the way he got locked in the latrine at summer camp. We had to fetch the key."},
    {"id": "a31", "text": "{exclaim}. {name} once {verb_past} across {place} for no reason a sober adult could explain. The Handbook calls that a pattern."},
    {"id": "a32", "text": "Good morning. Somebody has to be the {adj} one today, and {name} has seniority."},
    {"id": "a33", "text": "{exclaim}! Hydrate, stretch, check your buddy. {name}'s buddy has requested reassignment every year since '04. Denied — nobody else will take him."},
    {"id": "a34", "text": "Morning. {name} has a plan for today. So did the man who lashed the tower that fell on my truck. Plans are cheap. Discipline isn't."},
    {"id": "a35", "text": "{exclaim} — {name} is already at {place} doing {exercise} in jeans. No form, no shame, and no badge for any of it."},
    {"id": "a36", "text": "Good morning. In {name}'s defense, he was probably asleep when it happened. That defense has never once worked, but points for consistency."},

    # ---- Murf lore ----
    {"id": "m01", "text": "I am 55 years old and I was at Woodstock. Do not do the math, and do not test me — both roads end badly for you, {name}."},
    {"id": "m02", "text": "I once drove a bus with no brakes and a glovebox full of granola from Vermont to the coast. Still only the second most reckless thing I've seen. The first is {name} with an axe."},
    {"id": "m03", "text": "People ask why I run a tight ship. Because I have seen what happens when nobody's in charge. It was the seventies, and it looked like {name}."},
    {"id": "m04", "text": "Yes, there is tie-dye under my uniform shirt. It's regulation because I say it's regulation. Your cargo shorts, {name}, are not, and never will be."},
    {"id": "m05", "text": "I gave up the beads, the bus, and the beard. I kept the whistle. {name}, the whistle is for you, and you know exactly why."},
    {"id": "m06", "text": "They called me Moonbeam in 1979. The first man to call me that today does KP with {name} — a punishment for both of you."},
    {"id": "m07", "text": "I've mellowed. The old me would have kicked down {name}'s fire AND his tent. The new me kicks the fire and merely describes what he'd do to the tent."},
    {"id": "m08", "text": "Forecast says {cond_lower}. I knew before I checked — my knees have been forecasting since Nixon. They also forecast {name} being useless today. High confidence."},
    {"id": "m09", "text": "Fifty-five years on this earth and I have never once been late to reveille. {name} was late to his own surprise party. Twice."},

    # ---- two-name ----
    {"id": "p01", "text": "{name} and {name2} are still arguing about who won that argument from 2004. Gentlemen, I ruled on this in 2004. You both lost. The ruling stands."},
    {"id": "p02", "text": "Morning. {name} still hasn't paid {name2} back for the {artifact}. It's been years. A scout is trustworthy. Neither of you qualifies."},
    {"id": "p03", "text": "{exclaim}! {name} says {name2} snores like a {adj} chainsaw. I've shared a campsite with both of you. It's a chainsaw duet."},
    {"id": "p04", "text": "Today's challenge: {name} versus {name2}, first man to {place} by 0900. I've supervised you both for years. Nobody is making it."},
    {"id": "p05", "text": "{name} and {name2} shared a two-man tent at winter camp once. Neither has spoken of it since. The Handbook respects that silence and so do I."},
    {"id": "p06", "text": "Buddy system check: {name} and {name2} are paired today. God help me, that is genuinely the best I could do with this roster."},
    {"id": "p07", "text": "{name2} says {name} peaked in high school. {name} says {name2} never peaked at all. First accurate report either of you has ever filed."},
    {"id": "p08", "text": "{name} and {name2} still argue over who broke the {artifact}. I was there. It was both of you, and the flagpole never recovered either."},
    {"id": "p09", "text": "{exclaim} — {name} and {name2} once tried to co-build a {fire} fire. I kicked it down out of mercy. Some partnerships the wilderness rejects."},

    # ---- hot ----
    {"id": "h01", "tag": "hot", "text": "{hi}° today. Two canteens minimum and a real hat. {name}, a backwards cap is not sun protection, it's a cry for help."},
    {"id": "h02", "tag": "hot", "text": "Feels like {feels}°. {name} says he's 'built for the heat.' I watched that man tap out of a July car ride with the windows down."},
    {"id": "h03", "tag": "hot", "text": "{exclaim} — {hi}° and climbing. Hydrate before you feel it. {name}, that means water. The blue Gatorade is not water. We have been over this."},
    {"id": "h04", "tag": "hot", "text": "{hi}° today. Total burn ban — no fires. Which for once means {name}'s garbage fire-building can't hurt anybody."},
    {"id": "h05", "tag": "hot", "text": "{feels}° feels-like. Shade, water, sunscreen. {name} will do none of the three, then file a complaint with a man who does not accept complaints."},
    {"id": "h06", "tag": "hot", "text": "{hi}° {emoji}. I did a twenty-miler in worse with a forty-pound pack. {name} gets winded reaching for the thermostat."},
    {"id": "h07", "tag": "hot", "text": "Heat advisory, {hi}°. Check on your elders. I AM the elders and I'm fine — check on {name}, who is {adj} in any temperature."},
    {"id": "h08", "tag": "hot", "text": "{hi}° and humid. In '77 I danced through hotter than this at a Dead show in a poncho. {name} can't cross a parking lot without whining."},
    {"id": "h09", "tag": "hot", "text": "{exclaim}. {feels}° out. Sunscreen up, unless you want to end up like {name} at summer camp — the lobster year. There are photos."},
    {"id": "h10", "tag": "hot", "text": "{hi}° today. Somewhere {name} is standing directly in the sun explaining why he doesn't believe in sunscreen. Natural selection is patient."},

    # ---- cold ----
    {"id": "c01", "tag": "cold", "text": "{lo}° this morning. Layers, troop. {name} will wear shorts, because {name} has never once been prepared for anything, including this sentence."},
    {"id": "c02", "tag": "cold", "text": "Feels like {feels}°. Cotton kills, wool works — Handbook basics. {name} is out there in a hoodie he has owned since the {artifact} era."},
    {"id": "c03", "tag": "cold", "text": "{exclaim} — {lo}° low. Cold-weather rules in effect. {name}, 'I run hot' is not a jacket."},
    {"id": "c04", "tag": "cold", "text": "It's {feels}° out. They say cold builds character. {name}'s been out in it for years — some builds just fail, son, and I kick those down too."},
    {"id": "c05", "tag": "cold", "text": "{lo}° {emoji}. Layer up. {name} is in a uniform polo acting like it's a personality. It's hypothermia with extra steps."},
    {"id": "c06", "tag": "cold", "text": "{feels}° feels-like. Nobody leaves without gloves except {name}, who claims he's 'part husky.' Son, the husky part is the shedding."},
    {"id": "c07", "tag": "cold", "text": "{lo}° low. Scrape your whole windshield. {name} scrapes a porthole and drives off like a submarine captain. Demerits. So many demerits."},
    {"id": "c08", "tag": "cold", "text": "{lo}° today. Good morning to everyone except whoever let {name} plan the winter campout that ended with the frozen {artifact}. Never again."},

    # ---- rain ----
    {"id": "r01", "tag": "rain", "text": "{rain}% chance of rain. Ponchos on. {name} will bring nothing, get soaked, and blame the sky like it's the sky's first day."},
    {"id": "r02", "tag": "rain", "text": "{rain}% rain today. A prepared man packed his rain gear last night. {name} is not a prepared man. {name} is barely a punctual one."},
    {"id": "r03", "tag": "rain", "text": "{exclaim} — {rain}% rain. In the mud at Woodstock I kept a fire going for three days. {name} loses a fire indoors. With matches."},
    {"id": "r04", "tag": "rain", "text": "Rain incoming, {rain}%. {name} once hydroplaned into {place} and blamed the road, the tires, and Mercury retrograde. Take the bus, son."},
    {"id": "r05", "tag": "rain", "text": "Rain odds {rain}%. Fine day to stay in, square your gear away, and reflect. {name}, you reflect harder than the rest."},
    {"id": "r06", "tag": "rain", "text": "{rain}% rain today. {name}'s umbrella broke in 2011. A scout repairs his equipment. {name} held a funeral for it and moved on."},
    {"id": "r07", "tag": "rain", "text": "It's coming down. {name} will jog to {place} for a {snack}, come back looking like a {adj} drowned possum, and call it cardio."},
    {"id": "r08", "tag": "rain", "text": "{cond} today, {rain}%. Tarp skills separate the men from the boys. {name} thinks a taut-line hitch is a wrestling move."},
    {"id": "r09", "tag": "rain", "text": "{exclaim}! {rain}% rain, which means {name} will text 'is it raining by you' from three blocks away instead of looking up. Situational awareness: zero."},
    {"id": "r10", "tag": "rain", "text": "Wet one, {rain}%. Drive slow, headlights on. {name}, that is aimed at you — I've read the incident reports, all {noun_plural}."},

    # ---- snow ----
    {"id": "s01", "tag": "snow", "text": "Snow today. {name} will post one photo of a half-shoveled driveway and expect the Polar Bear badge for it. Denied."},
    {"id": "s02", "tag": "snow", "text": "{cond}. {name} will shovel four feet of sidewalk and need a medic. I shoveled the whole parade ground at his age. Uphill. Angry."},
    {"id": "s03", "tag": "snow", "text": "{exclaim} — snow's here, {lo}° low. {name} still hasn't returned the troop shovel from 2019. A scout is trustworthy. I keep a list, son."},
    {"id": "s04", "tag": "snow", "text": "Snow day. {name} cleared out the 7-Eleven last night — six gallons of milk and a {snack} for one man. That isn't preparedness, that's panic with a cart."},
    {"id": "s05", "tag": "snow", "text": "{cond} out there. Salt your steps. {name} went down hard last winter and told everyone he was 'testing the ice.' The ice passed. He didn't."},

    # ---- nice ----
    {"id": "n01", "tag": "nice", "text": "{hi}° and gorgeous {emoji}. Zero excuses today. Even {name} can't ruin this one, though God knows the man will try."},
    {"id": "n02", "tag": "nice", "text": "Perfect day — {hi}° and {cond_lower}. Get outside. {name} is already at {place} accomplishing nothing at a truly professional level."},
    {"id": "n03", "tag": "nice", "text": "{exclaim}! {feels}° and beautiful. Proper fire weather — teepee or log cabin. If I catch another one of {name}'s leaning garbage piles I am kicking it into the lake."},
    {"id": "n04", "tag": "nice", "text": "{hi}° {emoji}. Trail weather. {name} says he's still got it. Whatever 'it' was, he left it at {place} around 2009."},
    {"id": "n05", "tag": "nice", "text": "Beautiful out, {hi}°. Take a real hike, boots on. {name}'s idea of a hike is parking far from the door at Roosevelt Field."},
    {"id": "n06", "tag": "nice", "text": "{cond} and {hi}°. A day like this almost makes me forget {name} still owes the troop for the {artifact} incident. Almost. The ledger remembers."},
    {"id": "n07", "tag": "nice", "text": "{feels}° and perfect. Haven't seen a sky like this since the bus broke down outside Boulder in '79. Even {name} deserves this one. Barely."},
    {"id": "n08", "tag": "nice", "text": "{hi}° today and the day is wide open. {name} will still find something to complain about by 0900. Set your watch by it."},

    # ---- weekday-pinned ----
    {"id": "d01", "days": "mon", "text": "{exclaim} — Monday. {name} has already threatened to quit his job. You can't quit, son. I've seen your knots. Nobody else would take you."},
    {"id": "d02", "days": "mon", "text": "Monday. {name} said the diet starts today. He is currently in his car outside {place} finishing a {snack}. The Handbook covers honesty on page one."},
    {"id": "d03", "days": "mon", "text": "Monday morning. Nobody likes it except {name}, which should tell you everything you need to know about {name}."},
    {"id": "d04", "days": "tue", "text": "Tuesday — the most useless day of the week, though it still outranks {name} in overall contribution."},
    {"id": "d05", "days": "tue", "text": "Tuesday. {name} is still 'recovering from the weekend.' I recovered from the seventies faster."},
    {"id": "d06", "days": "wed", "text": "Hump day. Halfway there, troop. {name} has been coasting since Monday — same way he's been coasting since the {artifact} era."},
    {"id": "d07", "days": "wed", "text": "Wednesday. Two days down, two to go. {name} peaked the day he got that {artifact} and has been rolling downhill without brakes since."},
    {"id": "d08", "days": "thu", "text": "Friday Junior, troop. Get the morning constitutional in, square away your bunk, and finish the week's business. {name}, that's an order, not a suggestion."},
    {"id": "d09", "days": "thu", "text": "Friday Junior. {name} is planning a big weekend he will cancel by Saturday 0900. I have seen tighter plans in a drum circle."},
    {"id": "d10", "days": "thu", "text": "It's Friday Junior — second-best day of the week, right behind whatever day {name} finally learns to tie a {knot}."},
    {"id": "d11", "days": "fri", "text": "FRIDAY. {exclaim}! We made it. {name} has been dead weight since Wednesday, but a scout leaves no man behind. Regrettably."},
    {"id": "d12", "days": "fri", "text": "It's Friday. {name} will announce big plans tonight and be asleep by 2130. Taps plays early for that man. It always has."},
    {"id": "d13", "days": "fri", "text": "Friday, troop. Full uniform for weekend colors — and {name}, a ceremony means the neckerchief too. Yes, it's mandatory. It has always been mandatory."},
    {"id": "d14", "days": "sat,sun", "text": "Weekend edition. {name} is still in his bunk and will claim he was 'up early.' The flag went up at 0700. I saw who was there. He was not."},
    {"id": "d15", "days": "sat,sun", "text": "{exclaim} — weekend. No uniform today, and {name} dressed like it. Freedom was a mistake for some men."},
    {"id": "d16", "days": "sat", "text": "Saturday. {name} has a list of {noun_plural} to handle and will finish none of it. On the commune we called that a Tuesday. Here we call it a failure."},
    {"id": "d17", "days": "sun", "text": "Sunday. Rest, reflect, call your mother. {name}, yours calls ME asking about you, and I am running out of nice things to invent."},
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
