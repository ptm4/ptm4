#!/usr/bin/env python3
"""
leetify-stats.py — CS2 coaching review from the Leetify public API.

Pulls profile + recent matches, then runs a deterministic analysis engine
(per-map win rates + CT/T splits, dimension strengths/focus, trade/flash/opening
signals, spot/role recommendations) and writes a full markdown coaching report.

If ANTHROPIC_API_KEY is set, the aggregates are additionally sent to Claude
(claude-opus-4-8 by default, override via LEETIFY_REVIEW_MODEL) for a natural-
language coaching narrative prepended to the report. The heuristic review always
runs and is complete on its own — the LLM call is pure enrichment, and any error
or missing key falls back silently.

Auth: LEETIFY_API_KEY (Bearer) + STEAM64_ID. If either is missing the agent skips
cleanly (exit 0, no write). Writes <agent-logs>/leetify-latest.json + a dated
history copy via the shared _report helper. Requires: pip install requests.
"""

import json
import os
import sys
from datetime import datetime, timezone

# Shared dated-report writer lives in Tools/homelab/. Add it to the path.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "homelab"))
from _report import write_report, now_iso, agent_logs_dir  # noqa: E402
# Positional (demo-parsing) analysis lives alongside this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_positions  # noqa: E402

BASE_URL = "https://api-public.cs-prod.leetify.com"
MATCH_COUNT = 25
REPORT_BASE = "leetify-latest"

# Dimension thresholds (Leetify sub-ratings are roughly 0-100; CT/T leetify are small +/- numbers).
DIM_STRONG = 60.0   # >= strong
DIM_FOCUS = 52.0    # < focus area
# Stat thresholds for callouts
PREAIM_GOOD = 5.0           # degrees; lower better
REACTION_GOOD_MS = 550      # ms; lower better
HS_GOOD = 0.45              # headshot kill ratio
FLASH_FRIEND_BAD = 0.30     # team-flashes per flashbang


def get(path, key, params=None):
    r = requests.get(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        params=params or {}, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def my_row(match, steam_id):
    for s in match.get("stats", []):
        if str(s.get("steam64_id")) == str(steam_id):
            return s
    return None


def per_map(matches, steam_id):
    """Aggregate per-map: matches, wins, avg rating, CT/T avg rating."""
    agg = {}
    for m in matches:
        mp = m.get("map_name") or "unknown"
        row = my_row(m, steam_id)
        if not row:
            continue
        a = agg.setdefault(mp, {
            "map": mp, "matches": 0, "wins": 0,
            "rating_sum": 0.0, "ct_sum": 0.0, "t_sum": 0.0, "n": 0,
        })
        a["matches"] += 1
        won = (row.get("rounds_won") or 0) > (row.get("rounds_lost") or 0)
        if won:
            a["wins"] += 1
        r = _num(row.get("leetify_rating"))
        if r is not None:
            a["rating_sum"] += r
            a["n"] += 1
        ct = _num(row.get("ct_leetify_rating"))
        t = _num(row.get("t_leetify_rating"))
        if ct is not None:
            a["ct_sum"] += ct
        if t is not None:
            a["t_sum"] += t
    out = []
    for a in agg.values():
        n = max(a["n"], 1)
        out.append({
            "map": a["map"],
            "matches": a["matches"],
            "win_rate": round(100 * a["wins"] / a["matches"]) if a["matches"] else 0,
            "avg_rating": round(a["rating_sum"] / n, 3),
            "ct_rating": round(a["ct_sum"] / a["matches"], 3) if a["matches"] else 0,
            "t_rating": round(a["t_sum"] / a["matches"], 3) if a["matches"] else 0,
        })
    out.sort(key=lambda x: (-x["matches"], -x["win_rate"]))
    return out


def map_verdict(row):
    if row["matches"] < 2:
        return "low sample"
    if row["win_rate"] >= 55 and row["avg_rating"] >= 0:
        return "strong"
    if row["win_rate"] <= 40 or row["avg_rating"] < -0.03:
        return "avoid / practice"
    return "even"


def dimension_review(profile):
    rating = profile.get("rating") or {}
    dims = {
        "aim": _num(rating.get("aim")),
        "positioning": _num(rating.get("positioning")),
        "utility": _num(rating.get("utility")),
    }
    strengths, focus = [], []
    for name, val in dims.items():
        if val is None:
            continue
        if val >= DIM_STRONG:
            strengths.append((name, val))
        elif val < DIM_FOCUS:
            focus.append((name, val))
    # clutch/opening are small +/- numbers; report directionally
    clutch = _num(rating.get("clutch"))
    opening = _num(rating.get("opening"))
    ct_l = _num(rating.get("ct_leetify"))
    t_l = _num(rating.get("t_leetify"))
    return {
        "dims": dims, "strengths": strengths, "focus": focus,
        "clutch": clutch, "opening": opening, "ct_leetify": ct_l, "t_leetify": t_l,
    }


def build_findings(profile, dim, stats):
    findings, recs = [], []

    # Side imbalance
    ct, t = dim.get("ct_leetify"), dim.get("t_leetify")
    if ct is not None and t is not None and abs(ct - t) >= 0.02:
        weak = "T" if t < ct else "CT"
        recs.append({"severity": "warn",
                     "message": f"{weak} side is your weaker side (CT {ct:+.3f} vs T {t:+.3f}) — "
                                f"review {weak}-side setups and default positions on your common maps."})

    # Focus dimensions
    for name, val in dim["focus"]:
        recs.append({"severity": "warn",
                     "message": f"{name.capitalize()} is a focus area ({val:.0f}) — "
                                + {"aim": "drill prefire/spray-control routines and crosshair placement.",
                                   "positioning": "watch your deaths: avoid over-peeking and isolate duels.",
                                   "utility": "pre-round nade plans; throw lineups before contact."}.get(name, "")})

    # Stat callouts
    preaim = _num(stats.get("preaim"))
    if preaim is not None and preaim > PREAIM_GOOD:
        recs.append({"severity": "info",
                     "message": f"Preaim {preaim:.1f}° is wide — work crosshair placement at head level "
                                f"(aim_botz / prefire maps)."})
    reaction = _num(stats.get("reaction_time_ms"))
    if reaction is not None and reaction > REACTION_GOOD_MS:
        recs.append({"severity": "info",
                     "message": f"Reaction time {reaction:.0f}ms is slow — pre-aim more so duels are click-not-flick."})
    hs = _num(stats.get("accuracy_head"))
    if hs is not None and hs < HS_GOOD:
        recs.append({"severity": "info",
                     "message": f"Headshot ratio {hs*100:.0f}% is low — lower your crosshair and tap/burst at range."})
    ff = _num(stats.get("flashbang_hit_friend_per_flashbang"))
    if ff is not None and ff > FLASH_FRIEND_BAD:
        findings.append({"severity": "warn",
                         "message": f"Team-flashing too often ({ff*100:.0f}% of flashes hit teammates) — "
                                    f"communicate pops and flash over/around, not into, teammates."})
    util_death = _num(stats.get("utility_on_death_avg"))
    if util_death is not None and util_death > 200:
        recs.append({"severity": "info",
                     "message": f"You die with ~${util_death:.0f} of utility unused on average — use nades earlier."})

    # Opening duels
    t_open = _num(stats.get("t_opening_duel_success_percentage"))
    ct_open = _num(stats.get("ct_opening_duel_success_percentage"))
    for side, val in (("T", t_open), ("CT", ct_open)):
        if val is not None and val < 45:
            recs.append({"severity": "info",
                         "message": f"{side} opening-duel win rate {val:.0f}% — take fewer dry entries; "
                                    f"trade with a teammate or use flashes to enter."})
    return findings, recs


def headline(dim, rating_val):
    if dim["focus"]:
        name = dim["focus"][0][0]
        return f"Leetify {rating_val:+.2f} · focus: {name}"
    if dim["strengths"]:
        return f"Leetify {rating_val:+.2f} · strong {dim['strengths'][0][0]}"
    return f"Leetify rating {rating_val:+.2f}"


def build_log(profile, maps, dim, stats, findings, recs, name, ai_review=None):
    ranks = profile.get("ranks") or {}
    L = []
    if ai_review:
        L += ["## AI Coaching Review", "", ai_review.strip(), "", "---", ""]
    L += [f"# CS2 / Leetify Report — {name}", "", f"_Generated {now_iso()}_", "",
          "## Ranks & ratings", "",
          f"- Leetify: {dim.get('ct_leetify', 0):+.3f} CT / {dim.get('t_leetify', 0):+.3f} T",
          f"- Premier: {ranks.get('premier', '?')} · Faceit: {ranks.get('faceit', '?')} · "
          f"Wingman: {ranks.get('wingman', '?')}",
          ""]
    d = dim["dims"]
    L += ["## Skill dimensions", "",
          "| Dimension | Score | Verdict |", "|---|---|---|"]
    for k in ("aim", "positioning", "utility"):
        v = d.get(k)
        if v is None:
            continue
        verdict = "strong" if v >= DIM_STRONG else ("focus" if v < DIM_FOCUS else "ok")
        L.append(f"| {k.capitalize()} | {v:.0f} | {verdict} |")
    L.append("")
    if maps:
        L += ["## Per-map (last 25)", "",
              "| Map | Matches | Win % | CT | T | Verdict |", "|---|---|---|---|---|---|"]
        for r in maps:
            L.append(f"| {r['map']} | {r['matches']} | {r['win_rate']}% | "
                     f"{r['ct_rating']:+.3f} | {r['t_rating']:+.3f} | {map_verdict(r)} |")
        L.append("")
    if dim["strengths"]:
        L += ["## Strengths", ""]
        L += [f"- {n.capitalize()} ({v:.0f})" for n, v in dim["strengths"]]
        L.append("")
    L += ["## Focus areas & recommendations", ""]
    items = findings + recs
    if items:
        L += [f"- **{it['severity'].upper()}** — {it['message']}" for it in items]
    else:
        L.append("- Nothing pressing — keep playing your strong maps and reviewing demos.")
    L.append("")
    return "\n".join(L)


def llm_review(digest, positions_digest=None, demos_digest=None):
    """Optional: send the digest to Claude for a coaching narrative. Returns text or None.

    When positions_digest (per-map death hotspots from demo parsing) is provided, the
    prompt additionally asks for concrete where-to-reposition advice per hotspot.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("LEETIFY_REVIEW_MODEL", "claude-opus-4-8")
    prompt = (
        "You are a CS2 coach. Below is a player's aggregated Leetify data (skill dimensions, "
        "per-map win rates and CT/T ratings, and key stats). Write a concise, specific coaching "
        "review: 1) top 2-3 strengths, 2) top 2-3 focus areas with concrete drills, 3) a map plan "
        "(which to queue, which to practice/avoid and why), 4) one positioning/role insight from the "
        "CT vs T split. Use short markdown sections. Be direct and actionable.\n\n"
        f"DATA:\n{digest}"
    )
    if demos_digest:
        prompt += (
            "\n\nRECENT DEMOS (date, map, result, K/D, rating, top death spots from parsing):\n"
            f"{demos_digest}\n\n"
            "Reference specific demos by date+map when you spot patterns (e.g. 'In your 2026-06-04 "
            "dust2 loss you died 3x on ARamp CT-side — ...'). Note trends across demos."
        )
    if positions_digest:
        prompt += (
            "\n\nDEATH HOTSPOTS AGGREGATE (per map across all parsed demos — area, % of deaths, side):\n"
            f"{positions_digest}\n\n"
            "Add a final markdown section '## Positional fixes'. For each map's top death "
            "hotspots, name the SPECIFIC spot/angle the player is dying at and exactly where to "
            "reposition or how to play it instead (safer angle, off-angle, default position, "
            "trade setup, or utility to use first). Use your CS2 map knowledge of callouts."
        )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        if not r.ok:
            try:
                err_body = r.json()
            except Exception:
                err_body = r.text
            print(f"LLM review skipped: {r.status_code} {r.reason} — {err_body}", file=sys.stderr)
            return None
        data = r.json()
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        text = "\n".join(p for p in parts if p).strip()
        return text or None
    except Exception as e:
        print(f"LLM review skipped: {e}", file=sys.stderr)
        return None


def build_digest(name, profile, maps, dim, stats):
    d = dim["dims"]
    lines = [f"Player: {name}",
             f"Dimensions: aim={d.get('aim')}, positioning={d.get('positioning')}, utility={d.get('utility')}",
             f"Clutch={dim.get('clutch')}, Opening={dim.get('opening')}, "
             f"CT_leetify={dim.get('ct_leetify')}, T_leetify={dim.get('t_leetify')}",
             "Per-map (map, matches, win%, ct_rating, t_rating):"]
    for r in maps:
        lines.append(f"  {r['map']}: {r['matches']}m, {r['win_rate']}%, CT {r['ct_rating']}, T {r['t_rating']}")
    keys = ["preaim", "reaction_time_ms", "accuracy_head", "spray_accuracy",
            "t_opening_duel_success_percentage", "ct_opening_duel_success_percentage",
            "trade_kills_success_percentage", "traded_deaths_success_percentage",
            "flashbang_hit_friend_per_flashbang", "utility_on_death_avg"]
    lines.append("Stats: " + ", ".join(f"{k}={stats.get(k)}" for k in keys if k in stats))
    return "\n".join(lines)


def analyze(profile, matches, steam_id):
    """Pure analysis — returns the full report dict. Unit-testable without network."""
    name = profile.get("name") or profile.get("nickname") or str(steam_id)
    rating_val = _num((profile.get("ranks") or {}).get("leetify")) \
        or _num(profile.get("leetify_rating")) or 0.0
    stats = profile.get("stats") or {}
    maps = per_map(matches, steam_id)
    dim = dimension_review(profile)
    findings, recs = build_findings(profile, dim, stats)

    # Positional "where you die" analysis (heavy, opt-in: LEETIFY_PARSE_DEMOS=1).
    positions = {}
    demo_summaries = []
    if os.environ.get("LEETIFY_PARSE_DEMOS") in ("1", "true", "yes"):
        try:
            positions, demo_summaries = demo_positions.analyze_positions(
                matches, steam_id, heatmap_dir=agent_logs_dir())
        except Exception as e:
            print(f"positional analysis skipped: {e}", file=sys.stderr)

    positions_digest = demo_positions.hotspots_digest(positions) if positions else None
    demos_dig = demo_positions.demos_digest(demo_summaries) if demo_summaries else None
    digest = build_digest(name, profile, maps, dim, stats)
    ai = llm_review(digest, positions_digest=positions_digest, demos_digest=demos_dig)

    status = "warn" if findings else "ok"
    log = build_log(profile, maps, dim, stats, findings, recs, name, ai_review=ai)
    if positions:
        log += "\n\n---\n\n" + demo_positions.positions_markdown(positions)

    return {
        "tool": "leetify-stats",
        "run_at": now_iso(),
        "status": status,
        "summary": f"{name}: {headline(dim, rating_val)}",
        "findings": findings,
        "recommendations": recs,
        "log": log,
        "steam64_id": str(steam_id),
        "maps": maps,
        "dimensions": dim["dims"],
        "positions": positions,
        "demo_summaries": demo_summaries,
        "ai_review": bool(ai),
        # keep raw blobs for the page / future use
        "profile": profile,
        "matches": matches,
    }


def main():
    api_key = os.environ.get("LEETIFY_API_KEY")
    steam_id = os.environ.get("STEAM64_ID")
    if not api_key or not steam_id:
        print("Leetify agent dormant: LEETIFY_API_KEY and/or STEAM64_ID not set — skipping.")
        return

    try:
        import requests  # noqa: F401 (lazy: only needed when actually configured)
    except ImportError:
        print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
        sys.exit(1)
    globals()["requests"] = requests

    try:
        profile = get("/v3/profile", api_key, {"steam64_id": steam_id})
        all_matches = get("/v3/profile/matches", api_key, {"steam64_id": steam_id})
        matches = sorted(
            all_matches if isinstance(all_matches, list) else [],
            key=lambda m: m.get("finished_at", ""), reverse=True,
        )[:MATCH_COUNT]
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        report = {
            "tool": "leetify-stats",
            "run_at": now_iso(),
            "status": "warn",
            "summary": f"Leetify API error (HTTP {code})",
            "findings": [{"severity": "warn", "message": f"Leetify request failed: HTTP {code}"}],
            "recommendations": [],
            "log": f"# Leetify\n\nAPI request failed: HTTP {code}.",
        }
        write_report(REPORT_BASE, report)
        print(f"Report written (error): HTTP {code}")
        return

    report = analyze(profile, matches, steam_id)
    latest, dated = write_report(REPORT_BASE, report)
    print(f"Report written: {latest} + {dated} "
          f"({len(matches)} matches, ai_review={report['ai_review']})")


if __name__ == "__main__":
    main()
