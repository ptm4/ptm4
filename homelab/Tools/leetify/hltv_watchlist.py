#!/usr/bin/env python3
"""
hltv_watchlist.py — "players to watch" from the HLTV VRS top-15 teams.

The Leetify page shows an AI coaching review; this module adds a role-matched watchlist
beneath it. It asks Claude (with the web_search tool) to read the CURRENT HLTV Valve
Regional Standings (VRS) ranking — the source of truth for the team order — take the top 15
teams, and for each pick 1-2 players to watch FOR THE USER'S ROLE (a lurk-on-T / anchor-on-CT
trade rifler by default). Studying role-peers is what transfers, so the picks are the teams'
own lurkers / trade-riflers / site-anchors, each with a one-line "why this helps your game".

There is no structured public DB of CS2 pro roles (HLTV and Liquipedia publish rosters but no
role field), so role is resolved from current HLTV/Liquipedia/coverage via web_search, and the
model is told to flag low-confidence calls rather than invent them.

Cost is paid ~weekly: get_watchlist() caches to <agent-logs>/hltv-watchlist.json and only
re-queries when the cache is older than WATCHLIST_MAX_AGE_DAYS. It NEVER raises — on any
failure it returns the last good cache (or None), so leetify-stats.py can embed it blindly.

Requires: requests. Uses ANTHROPIC_API_KEY (+ optional LEETIFY_REVIEW_MODEL, MY_CS2_ROLES).
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "homelab"))
from _report import agent_logs_dir, now_iso  # noqa: E402

MODEL = os.environ.get("LEETIFY_REVIEW_MODEL", "claude-opus-4-8")
CACHE_NAME = "hltv-watchlist.json"
WATCHLIST_MAX_AGE_DAYS = 7  # weekly — VRS moves ~weekly and each refresh is a web_search call.

# Default assumption when MY_CS2_ROLES is unset. The user is a pack/trade rifler who lurks on
# T and anchors a site on CT.
MY_ROLES_DEFAULT = "pack/trade rifler; lurk on T, site anchor on CT"

VRS_URL = "https://www.hltv.org/valve-ranking/teams"

SCHEMA_HINT = """\
Return ONLY a JSON object (no prose, no code fences) with this exact shape:
{
  "vrs_as_of": "<the date/label HLTV's VRS ranking shows>",
  "my_roles": "<echo back the exact roles string you matched against>",
  "teams": [
    {"rank": 1, "team": "<team name>",
     "players": [
       {"player": "<in-game name>",
        "role": "<AWPer|IGL|entry|lurker|support|rifler|... best-fit label>",
        "why_for_you": "<ONE line: what to steal for a lurk-on-T / anchor-on-CT rifler — "
                       "positioning, timing, trade setups, util usage>",
        "confidence": "high|medium|low"}
     ]}
  ]
}
Exactly 15 teams, in HLTV's VRS order (rank 1..15). 1-2 players per team. Do NOT invent roles:
if unsure, use the closest fit and set confidence "low". Keep why_for_you concrete and short.
"""


def _prompt(my_roles):
    return (
        "You are building a CS2 'players to watch' list for a specific player so they can "
        "study pros who share their role. The player's role and positions:\n"
        f"  {my_roles}\n\n"
        f"STEP 1 — Open the CURRENT HLTV Valve Regional Standings (VRS) ranking at {VRS_URL} "
        "(this is the SOURCE OF TRUTH for the team order). Take the TOP 15 teams in that exact "
        "ranking order.\n"
        "STEP 2 — For each team, find the current active roster and each player's in-game role "
        "from HLTV, Liquipedia, and recent coverage. There is no structured role database, so "
        "read the rosters/coverage and assign the best-fit role; flag low confidence rather than "
        "guessing wildly.\n"
        "STEP 3 — For each team pick the 1-2 players MOST WORTH WATCHING FOR THIS USER'S ROLE — "
        "i.e. the team's own lurker / trade-rifler / site-anchor-type players (not their AWPer or "
        "IGL unless that player is also the role-peer). For each, write a one-line 'why_for_you' "
        "saying concretely what to steal for a lurk-on-T / anchor-on-CT rifler: positioning, "
        "timing the lurk/flank, trade discipline, when to anchor vs rotate, util before contact.\n\n"
        "Ground the team order in the live HLTV VRS ranking; ground rosters/roles in current "
        "sources. Use this year's (2026) data.\n\n"
        + SCHEMA_HINT
    )


def _fetch(api_key, my_roles):
    """Ask Claude (with web_search) for the watchlist. Returns a dict or None."""
    import requests

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 6000,
                "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
                "messages": [{"role": "user", "content": _prompt(my_roles)}],
            },
            timeout=240,
        )
    except Exception as e:
        print(f"watchlist request failed: {e}", file=sys.stderr)
        return None

    if not r.ok:
        try:
            err = r.json()
        except Exception:
            err = r.text
        print(f"watchlist skipped: {r.status_code} {r.reason} — {err}", file=sys.stderr)
        return None

    # Concatenate all text blocks (web_search interleaves tool blocks with text).
    data = r.json()
    text = "\n".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ).strip()
    if not text:
        print("watchlist skipped: model returned no text", file=sys.stderr)
        return None

    # Extract the JSON object (model may wrap it in prose despite instructions).
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        print("watchlist skipped: no JSON object in response", file=sys.stderr)
        return None
    try:
        wl = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"watchlist skipped: JSON parse error: {e}", file=sys.stderr)
        return None

    # Minimal sanity: a non-empty list of teams, each with at least a name.
    teams = wl.get("teams")
    if not isinstance(teams, list) or not teams or not any(t.get("team") for t in teams):
        print("watchlist skipped: response missing expected teams", file=sys.stderr)
        return None
    return wl


def _cache_path():
    return os.path.join(agent_logs_dir(), CACHE_NAME)


def _load_cache():
    try:
        with open(_cache_path()) as f:
            return json.load(f)
    except Exception:
        return None


def _is_fresh(cache):
    ts = (cache or {}).get("_refreshed_at")
    if not ts:
        return False
    try:
        when = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - when).total_seconds() / 86400
    return age_days < WATCHLIST_MAX_AGE_DAYS


def _save_cache(wl):
    wl["_refreshed_at"] = now_iso()
    logs_dir = agent_logs_dir()
    os.makedirs(logs_dir, exist_ok=True)
    path = _cache_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(wl, f, indent=2)
    os.replace(tmp, path)
    return wl


def get_watchlist(api_key):
    """Return the HLTV VRS watchlist dict, refreshing the cache only when stale (weekly).

    Never raises: on a missing key or any fetch/parse failure, falls back to the last good
    cache (which may itself be None if we've never succeeded).
    """
    cache = _load_cache()
    if _is_fresh(cache):
        return cache
    if not api_key:
        return cache  # can't refresh — serve whatever we have (possibly None).

    my_roles = os.environ.get("MY_CS2_ROLES", MY_ROLES_DEFAULT)
    wl = _fetch(api_key, my_roles)
    if wl is None:
        return cache  # keep the last good cache rather than dropping the section.
    try:
        return _save_cache(wl)
    except Exception as e:
        print(f"watchlist cache write failed: {e}", file=sys.stderr)
        wl["_refreshed_at"] = now_iso()
        return wl


if __name__ == "__main__":
    # Manual check: print the watchlist (refreshing the cache if stale).
    out = get_watchlist(os.environ.get("ANTHROPIC_API_KEY"))
    if out is None:
        print("No watchlist (no API key and no cache, or fetch failed).", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(out, indent=2))
