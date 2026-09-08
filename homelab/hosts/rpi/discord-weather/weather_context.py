"""Facts for the morning bit, derived only from successfully posted forecasts.

Forecast streaks are not observations or official weather alerts. No network IO.
"""
from datetime import timedelta


def feels_emoji(f):
    for threshold, emoji in ((100, "🔥"), (90, "🥵"), (75, "😎"), (60, "🙂"),
                             (40, "🧥"), (20, "🥶")):
        if f >= threshold:
            return emoji
    return "🧊"


def traits(fc):
    code = fc.get("code")
    cond = str(fc.get("cond", "")).lower()
    out = {"badge": feels_emoji(fc["feels"])}
    out["storm"] = code in (95, 96, 99) or "thunder" in cond
    out["snow"] = code in (71, 73, 75, 77, 85, 86) or "snow" in cond
    out["rain"] = (code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82)
                   or any(w in cond for w in ("rain", "drizzle", "shower"))) and not out["snow"]
    return out


def describe(history, observations, now):
    """Return a candidate snapshot and highest-priority event; never save here.

    observations contains (location, forecast) pairs, including failed forecasts.
    A missing day/location breaks continuity; same-day sends cannot add a day.
    """
    today = now.date()
    timezone = str(now.tzinfo)
    previous = {row["date"]: row["locations"] for row in history
                if row.get("timezone") == timezone and row.get("date", "") < today.isoformat()}
    locations, events = {}, []

    def run(key, trait, value):
        count, day = 0, today - timedelta(days=1)
        while previous.get(day.isoformat(), {}).get(key, {}).get(trait) == value:
            count += 1
            day -= timedelta(days=1)
        return count

    for loc, fc in observations:
        if not fc or not isinstance(fc.get("feels"), (int, float)):
            continue
        key = f"{loc['lat']:.5f},{loc['lon']:.5f}"
        current = traits(fc)
        current["feels"] = fc["feels"]
        locations[key] = current
        # The user supplied this mapping. Other locations use their town name;
        # no guessing which configured roast name lives where.
        subject = loc.get("witty_subject") or (
            "Starks" if loc["name"].strip().casefold() == "greensboro, nc" else loc["name"])
        facts = {"subject": subject, "location": loc["name"], "badge": current["badge"],
                 "feels": f"{fc['feels']:g}", "wind": round(fc.get("wind") or 0)}

        def add(kind, priority, **extra):
            events.append({"kind": kind, "priority": priority, "key": key,
                           "facts": {**facts, **extra}})

        fire_days = run(key, "badge", "🔥")
        if current["storm"]:
            add("storm", 100)
        if current["badge"] == "🔥":
            if fire_days >= 2:
                add("fire_streak", 90, days=fire_days + 1)
            else:
                add("fire", 75)
        elif fire_days >= 3:
            add("fire_break", 95, days=fire_days, gap=f"{100 - fc['feels']:.1f}".removesuffix(".0"))
        if current["badge"] == "🥵":
            days = run(key, "badge", "🥵") + 1
            if days >= 3:
                add("hot_streak", 68, days=days)
        if current["snow"]:
            days = run(key, "snow", True) + 1
            add("snow_streak" if days >= 3 else "snow", 80, days=days)
        if current["badge"] in ("🥶", "🧊"):
            days = run(key, "badge", current["badge"]) + 1
            add("cold_streak" if days >= 3 else "cold", 70, days=days)
        if current["rain"]:
            days = run(key, "rain", True) + 1
            if days >= 3:
                add("rain_streak", 65, days=days)
            elif fc.get("code") in (65, 67, 82) or (fc.get("rain") or 0) >= 80:
                add("rain", 50)
        if (fc.get("wind") or 0) >= 30:
            add("wind", 85)
        yesterday = previous.get((today - timedelta(days=1)).isoformat(), {}).get(key)
        if yesterday and abs(fc["feels"] - yesterday["feels"]) >= 20:
            diff = fc["feels"] - yesterday["feels"]
            add("swing", 60, change=round(abs(diff)), direction="up" if diff > 0 else "down")

    if len(locations) >= 2:
        cold_key = min(locations, key=lambda k: locations[k]["feels"])
        hot_key = max(locations, key=lambda k: locations[k]["feels"])
        spread = locations[hot_key]["feels"] - locations[cold_key]["feels"]
        if spread >= 25:
            labels = {f"{loc['lat']:.5f},{loc['lon']:.5f}": loc["name"] for loc, _ in observations}
            events.append({"kind": "split", "priority": 40, "key": hot_key,
                           "facts": {"warm": labels[hot_key], "cool": labels[cold_key],
                                     "spread": round(spread)}})
    event = max(events, key=lambda e: (e["priority"], e["facts"].get("days", 0)), default=None)
    return {"snapshot": {"date": today.isoformat(), "timezone": timezone, "locations": locations},
            "event": event}


EVENT_LINES = {
    "hot_streak": [
        "{subject}: day {days} of 🥵. Consistently miserable, still below the 🔥 cutoff. A difficult division to compete in.",
        "{days} straight 🥵 days for {subject}. {feels}° feels-like today. Who's checking whether the 🔥 gets called up tomorrow?",
        "{subject} keeps 🥵 for day {days}. The weather has found an annoying setting and saved it as a preset.",
        "Day {days} of 🥵 for {subject}. I would like a review of the local air conditioning situation.",
    ],
    "fire_streak": [
        "{subject}: day {days} of 🔥. At what point do we stop calling this a forecast and start calling it a residency?",
        "Day {days} of {subject} being on fire. Somebody keep the count; I don't trust him to report his own score.",
        "{subject} has held the 🔥 for {days} straight days. The rest of you can't even hold a conversation about where to eat.",
        "🔥 Day {days} for {subject}. Does the streak end tomorrow, or are we retiring the jersey?",
        "{subject}: {days} consecutive 🔥 days. The emoji has unpacked. It lives there now.",
        "Day {days}, still 🔥 for {subject}. I'd offer a merit badge, but the backing would melt.",
        "{subject} is on day {days} of 🔥. Someone who isn't actively cooking, please take attendance.",
        "🔥 WATCH: {subject} reaches day {days}. Who had this turning into the chat's longest-running sport?",
        "{days} straight 🔥 days for {subject}. Forecast says {feels}° feels-like; scoreboard says dynasty.",
        "Day {days} of 🔥 for {subject}. I'm beginning to suspect the sun has a personal issue with him.",
        "{subject}: 🔥 for {days} days running. We need a commentator. Preferably someone with air conditioning.",
        "The streak is alive: {subject}, day {days} of 🔥. What's the celebration if this hits double digits?",
    ],
    "fire_break": [
        "{subject}'s {days}-day 🔥 streak is over. {feels}° feels-like, {gap}° short of the cutoff. Take it up with the thermometer.",
        "Day 0 of {subject} being on fire. The {days}-day run ends at {feels}° feels-like. Please respect the fans' privacy.",
        "{subject} drops from 🔥 to {badge}. {days} days of work, gone. Who's demanding a recount?",
        "Final score: {subject}, {days} straight 🔥 days. Today: {feels}° feels-like. A heartbreaking result for people watching a weather emoji.",
        "The 🔥 has left {subject} after {days} days. {feels}° feels-like today. Somebody save the commemorative screenshot.",
        "{subject}'s 🔥 streak ends at {days}. {gap}° below the line today. I expect a completely reasonable response from this chat.",
    ],
    "fire": [
        "{subject} draws 🔥 today: {feels}° feels-like. Who's starting the counter?",
        "🔥 for {subject}, {feels}° feels-like. The weather report now has a designated oven section.",
        "{subject}: {feels}° feels-like and a 🔥. The rest of you may now compete for second-most uncomfortable.",
        "{subject} has entered the 🔥 bracket. {feels}° feels-like. Is this a one-off or the start of a problem?",
        "Today's 🔥 belongs to {subject}. {feels}° feels-like. I will accept a welfare check in the form of a cold-drink review.",
        "{subject}: 🔥, {feels}° feels-like. I asked for a weather report and got air-fryer settings.",
    ],
    "storm": [
        "Thunderstorms in {location}'s forecast. {subject}, indoor activities today. Arguing in here qualifies.",
        "{subject} has thunderstorms on the card. The sky gets one loud opinion; this chat will supply the other forty.",
        "Thunderstorms forecast for {location}. {subject}, what's the indoor plan? 'Stand at the door and watch' is already taken.",
        "{location}: thunderstorms forecast. {subject}, I am moving the troop meeting indoors. Snacks are now the main event.",
    ],
    "snow": [
        "Snow in {location}'s forecast. {subject}, are we excited or are we the person who has to shovel?",
        "{subject} gets snow on the weather card. Scenic from a window, a personal insult from a driveway.",
        "{location} has snow forecast. {subject}, I need your official position on this before it turns to slush.",
        "Snow forecast for {subject}. The troop is split between 'beautiful' and 'I have to drive in that.'",
    ],
    "snow_streak": [
        "Day {days} of snow in {location}'s forecast. {subject}, is the shovel getting its own chair at dinner?",
        "{subject}: {days} straight snow forecasts. The winter scenery has become a recurring chore.",
        "{location} keeps the snow forecast for day {days}. {subject}, give us the driveway morale report.",
        "Snow again for {subject}, day {days}. Who's still calling this cozy? Identify yourself.",
    ],
    "cold": [
        "{subject} draws {badge}: {feels}° feels-like. How many layers before getting dressed counts as packing?",
        "{subject}: {feels}° feels-like {badge}. The walk to the car now requires an expedition leader.",
        "{location} gets {badge} today. {subject}, I authorize complaining before you've even opened the door.",
        "{subject} has {feels}° feels-like weather. Name one errand worth losing the warmth you've already built up.",
    ],
    "cold_streak": [
        "{subject}: day {days} with {badge}. At this point the coat is part of the uniform.",
        "{days} straight {badge} days for {subject}. The blanket has seniority over the rest of the household.",
        "The {badge} streak reaches {days} for {subject}. What's the minimum temperature for you to participate in society?",
        "{subject} keeps {badge} for day {days}. I assume all plans now include the phrase 'but indoors.'",
    ],
    "rain_streak": [
        "Rain in {location}'s forecast for day {days}. {subject}, has the umbrella earned a name yet?",
        "{subject}: {days} straight rainy forecasts. The lawn is thriving. Please confirm someone else is.",
        "Day {days} of rain forecasts for {location}. {subject}, rank your shoes by remaining dryness.",
        "{subject} draws rain again, day {days}. I'm replacing the troop hike with standing at a window making noises.",
    ],
    "rain": [
        "{location} has a wet forecast. {subject}, what's the rainy-day meal? This is more useful than arguing about umbrellas.",
        "Rain takes the lead in {location}. {subject}, excellent conditions for cancelling the errand you never wanted to do.",
        "{subject} gets the wet end of today's report. Everyone with dry socks should show some humility.",
        "{location}: indoor-plan weather. {subject}, pick a film before this becomes a two-hour committee meeting.",
    ],
    "wind": [
        "{location} has winds forecast up to {wind} mph. {subject}, secure the patio furniture before it visits somebody.",
        "{subject}: winds up to {wind} mph. The bins may have a more active social life than us today.",
        "Up to {wind} mph in {location}'s forecast. {subject}, bad day for the hat you're emotionally attached to.",
        "{subject} gets winds up to {wind} mph. The troop flag is doing more exercise than anyone in this chat.",
    ],
    "swing": [
        "{subject}'s feels-like forecast is {direction} {change}° from yesterday's report. The wardrobe committee would like some notice.",
        "{location}: feels-like forecast {direction} {change}° since yesterday's post. {subject}, how many seasons are in your laundry basket?",
        "{subject} swings {direction} {change}° feels-like from yesterday's report. That's a costume change, not a minor adjustment.",
        "{subject}: {direction} {change}° feels-like compared with yesterday's card. Anyone who laid clothes out last night has grounds to complain.",
    ],
    "split": [
        "{warm} and {cool} are {spread}° apart in today's feels-like forecast. Same chat, different dress codes.",
        "A {spread}° feels-like gap between {warm} and {cool}. Trade weather for a day: who's accepting?",
        "{warm} is {spread}° ahead of {cool} on feels-like. Discussing the weather in here now requires specifying which weather.",
        "{spread}° separates {warm} and {cool} today. I need both delegations to explain what they're wearing.",
    ],
}
