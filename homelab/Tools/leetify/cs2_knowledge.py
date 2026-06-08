#!/usr/bin/env python3
"""
cs2_knowledge.py — sourced CS2 stat benchmarks + pro coaching principles.

This is the runtime source of truth for the Leetify AI coach. It grounds the LLM's advice
in real, current thresholds (Leetify benchmarks, ADR/KAST/HLTV norms) and pro principles
(trading, crossfires, utility, positioning, post-plant, retake, economy) instead of letting
the model guess. `leetify-stats.py` injects `knowledge_block()` into the coaching prompt and
hands it deterministic tier labels via `tier_for()`.

The corpus has baked-in defaults (below). A monthly refresh agent
(refresh-cs2-knowledge.py) re-researches the sources and writes <agent-logs>/cs2-knowledge.json;
when present, that file overrides the matching baked-in fields so advice stays current
without code changes. The mirror of this corpus also lives in the session memory file
reference_cs2_coaching_knowledge.md — keep them roughly in sync, but THIS module is what runs.

Sources: leetify.com/blog/cs2-benchmarks, pley.gg CS2 stats guides, refrag.gg afterplant &
retake guides, cs2.eu/guides/positioning, esports.net ADR guide, HLTV stats.
"""

import json
import os

# ── Baked-in defaults ────────────────────────────────────────────────────────

# Leetify percentile bands (rank-independent color coding) — the framing model for any stat.
LEETIFY_BANDS = "Poor = bottom 10% · Subpar = 10–30% · Average = 30–70% · Good = 70–90% · Great = 90–100%"

# Each stat: ordered tiers as (label, lo, hi). `higher_better` flips comparison.
# Ranges are inclusive-lo, exclusive-hi; open ends use None.
STAT_BENCHMARKS = {
    "adr": {
        "unit": "avg damage/round (rifler)",
        "higher_better": True,
        "tiers": [("Poor", None, 65), ("Average", 65, 80), ("Good", 80, 90),
                  ("Carry", 90, 100), ("Elite", 100, None)],
        "note": "Pros (e.g. donk) sustain 105+ at majors.",
    },
    "kast": {
        "unit": "% rounds with Kill/Assist/Survived/Traded",
        "higher_better": True,
        "tiers": [("Poor", None, 65), ("Average", 65, 70), ("Good", 70, 75),
                  ("Great", 75, 80), ("Elite", 80, None)],
        "note": "70% = well-involved, 75%+ reliable, 80%+ carrying the team.",
    },
    "hltv_rating": {
        "unit": "HLTV Rating (1.0 = baseline)",
        "higher_better": True,
        "tiers": [("Below avg", None, 1.0), ("Average", 1.0, 1.1), ("Good", 1.1, 1.2),
                  ("Great", 1.2, None)],
        "note": "Rating 3.0 weights opening frags, multi-kills, eco, 1vX, round-swing.",
    },
    "headshot_pct": {
        "unit": "% kills that are headshots",
        "higher_better": True,
        "tiers": [("Low", None, 40), ("Average", 40, 50), ("Good", 50, 60),
                  ("Great", 60, None)],
    },
    "reaction_time_ms": {
        "unit": "ms to damage after spotting",
        "higher_better": False,
        "tiers": [("Great", None, 500), ("Good", 500, 550), ("Average", 550, 620),
                  ("Slow", 620, None)],
        "note": "Lower is better; pros land sub-500ms. Fix with pre-aim, not faster flicks.",
    },
    "preaim_deg": {
        "unit": "degrees off-target when enemy appears",
        "higher_better": False,
        "tiers": [("Great", None, 5), ("Good", 5, 7), ("Average", 7, 9), ("Wide", 9, None)],
        "note": "Lower = crosshair already on the head. Aim is ~80% placement, 20% reaction.",
    },
    "opening_duel_pct": {
        "unit": "% of opening/first-contact duels won",
        "higher_better": True,
        "tiers": [("Poor", None, 40), ("Average", 40, 50), ("Good", 50, 55),
                  ("Great", 55, None)],
        "note": "A large CT-vs-T gap means change role on the weaker side (anchor/support).",
    },
}

# Pro coaching principles — why rounds are won/lost. Compact markdown for the prompt.
PRO_PRINCIPLES = """\
**Crosshair placement** — aim is ~80% positioning, 20% reaction. Keep the crosshair at head
height, pre-aimed at the angle an enemy will appear, BEFORE contact. Slow reaction time is
fixed by pre-aiming, not faster flicks.

**Trading & crossfires** — two players holding the same angle is wasted; build crossfires so
if one dies the other trades. Entry takes first contact and calls for trade/flash; the second
man (trader) confirms they are trading. Win fights with tight trades + util to force close
range. Dying first-contact with no trade is the most common round-losing mistake.

**Utility** — molotovs/HE go where enemies MUST be (sites, chokes, common spots, plant-util
denial), never empty space. Flash in front of teammates (pop-flashes from behind), never blind
your own team. Use util BEFORE peeking; dying with a full kit is wasted impact and economy.

**Positioning** — high ground beats low ground; use cover; avoid tunnel vision and keep
scanning flanks; rotate on intel, not mechanical timing. Off-angles beat wide aggressive peeks
into setups. On CT, anchor deeper instead of over-peeking — let them come and trade.

**Post-plant (T)** — plant where the bomb is visible from multiple cleared angles; set
crossfires covering the defuse line. With a man advantage, play passive and burn the clock;
with a disadvantage, take aggressive/flank fights. Chain smokes + molly the bomb to deny the
retake/defuse.

**Retake (CT)** — don't take first contact alone; wait for a teammate so you can't be
isolated. Communicate util you have and util thrown at you (no duplicates). "Tap the bomb" to
force defenders to react. Use unconventional/late flank paths. On hard sites (e.g. Inferno),
preserve economy rather than force a bad retake.

**Economy** — buy WITH your team; unsynced buy/save kills trade potential. Force buys are fine
when deliberate (map control, breaking enemy eco, a timing window).
"""


# ── Runtime override from the monthly refresh agent ──────────────────────────

def _load_overrides():
    """Merge <agent-logs>/cs2-knowledge.json over the baked-in defaults, if present."""
    try:
        # Lazy import so this module has no hard dependency on the report helper path.
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "homelab"))
        from _report import agent_logs_dir  # noqa: E402
        path = os.path.join(agent_logs_dir(), "cs2-knowledge.json")
        if not os.path.exists(path):
            return
        with open(path) as f:
            data = json.load(f)
        if isinstance(data.get("stat_benchmarks"), dict):
            STAT_BENCHMARKS.update(data["stat_benchmarks"])
        if isinstance(data.get("pro_principles"), str) and data["pro_principles"].strip():
            globals()["PRO_PRINCIPLES"] = data["pro_principles"]
        if isinstance(data.get("leetify_bands"), str) and data["leetify_bands"].strip():
            globals()["LEETIFY_BANDS"] = data["leetify_bands"]
    except Exception:
        # Stale/missing/corrupt override must never break the coach — defaults stand.
        pass


_load_overrides()


# ── Public API ───────────────────────────────────────────────────────────────

def tier_for(stat, value):
    """Deterministic tier label for a player's stat value, e.g. tier_for('adr', 78) -> 'Average'.

    Returns None if the stat is unknown or value is missing/non-numeric.
    """
    spec = STAT_BENCHMARKS.get(stat)
    if spec is None or value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for label, lo, hi in spec["tiers"]:
        if (lo is None or v >= lo) and (hi is None or v < hi):
            return label
    return None


def knowledge_block():
    """The full reference block injected into the LLM coaching prompt."""
    lines = ["# REFERENCE — CS2 benchmarks & pro principles (ground every claim in these)",
             "",
             f"Leetify percentile bands: {LEETIFY_BANDS}",
             "",
             "## Stat tiers"]
    for stat, spec in STAT_BENCHMARKS.items():
        tiers = " · ".join(
            f"{lab} {'<' + str(hi) if lo is None else (str(lo) + '+' if hi is None else f'{lo}-{hi}')}"
            for lab, lo, hi in spec["tiers"]
        )
        note = f" — {spec['note']}" if spec.get("note") else ""
        lines.append(f"- **{stat}** ({spec['unit']}): {tiers}{note}")
    lines += ["", "## Pro principles (why rounds are won/lost)", "", PRO_PRINCIPLES]
    return "\n".join(lines)


if __name__ == "__main__":
    # Quick self-test: print the block and a few tier lookups.
    print(knowledge_block())
    print("\n--- tier_for checks ---")
    for stat, val in [("adr", 78), ("kast", 82), ("reaction_time_ms", 642),
                      ("preaim_deg", 9.1), ("opening_duel_pct", 35)]:
        print(f"{stat}={val} -> {tier_for(stat, val)}")
