#!/usr/bin/env python3
"""
refresh-cs2-knowledge.py — monthly refresh of the CS2 coaching corpus.

The Leetify AI coach grounds its advice in cs2_knowledge.py (stat benchmarks + pro
principles). The CS2 meta and Leetify's published benchmarks drift over time, so this agent
periodically re-researches the authoritative sources via Claude's web_search tool and writes
an updated <agent-logs>/cs2-knowledge.json. cs2_knowledge.py loads that file at runtime and
overrides its baked-in defaults — so the coach stays current with no code changes.

Self-contained and degrades cleanly: if ANTHROPIC_API_KEY is missing it skips (exit 0, no
write); if the model returns unparseable output it leaves the existing JSON untouched.

Schedule: monthly via .github/workflows/homelab-agents.yml; also runnable on demand through
the agent-dispatcher allowlist. Requires: requests.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "homelab"))
from _report import agent_logs_dir, now_iso  # noqa: E402

MODEL = os.environ.get("LEETIFY_REVIEW_MODEL", "claude-opus-4-8")

SOURCES = (
    "leetify.com/blog/cs2-benchmarks, HLTV.org stats, pley.gg CS2 stat guides, "
    "refrag.gg guides, and reputable pro CS2 coaching content"
)

# The shape we want back — mirrors cs2_knowledge.py's STAT_BENCHMARKS / PRO_PRINCIPLES.
SCHEMA_HINT = """\
Return ONLY a JSON object (no prose, no code fences) with this exact shape:
{
  "leetify_bands": "<one-line description of Leetify's percentile color bands>",
  "stat_benchmarks": {
    "adr": {"unit": "...", "higher_better": true,
            "tiers": [["Poor", null, 65], ["Average", 65, 80], ["Good", 80, 90],
                      ["Carry", 90, 100], ["Elite", 100, null]],
            "note": "..."},
    "kast": {...}, "hltv_rating": {...}, "headshot_pct": {...},
    "reaction_time_ms": {"higher_better": false, ...},
    "preaim_deg": {"higher_better": false, ...},
    "opening_duel_pct": {...}
  },
  "pro_principles": "<markdown block: crosshair, trading/crossfires, utility, positioning, post-plant, retake, economy>"
}
Each tier is [label, lo, hi] with null for open ends; ranges are inclusive-lo, exclusive-hi.
Use CURRENT (this year) numbers from the sources. Keep notes short. Do not invent stats not
listed above; only refine these keys.
"""


def fetch_corpus(api_key):
    """Ask Claude (with web_search) for the refreshed corpus. Returns a dict or None."""
    import requests

    prompt = (
        "You are updating a CS2 coaching knowledge base. Search the web for the CURRENT "
        f"(2026) CS2 stat benchmarks and pro principles from {SOURCES}. Find concrete numeric "
        "thresholds for: ADR, KAST, HLTV Rating, headshot %, reaction time (ms), preaim "
        "(degrees), opening-duel success %. Also summarize pro principles for crosshair "
        "placement, trading/crossfires, utility, positioning, post-plant, retake, and economy.\n\n"
        + SCHEMA_HINT
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
                "model": MODEL,
                "max_tokens": 4000,
                "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=180,
        )
    except Exception as e:
        print(f"refresh request failed: {e}", file=sys.stderr)
        return None

    if not r.ok:
        try:
            err = r.json()
        except Exception:
            err = r.text
        print(f"refresh skipped: {r.status_code} {r.reason} — {err}", file=sys.stderr)
        return None

    # Concatenate all text blocks (web_search interleaves tool blocks with text).
    data = r.json()
    text = "\n".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ).strip()
    if not text:
        print("refresh skipped: model returned no text", file=sys.stderr)
        return None

    # Extract the JSON object (model may wrap it in prose despite instructions).
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        print("refresh skipped: no JSON object in response", file=sys.stderr)
        return None
    try:
        corpus = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"refresh skipped: JSON parse error: {e}", file=sys.stderr)
        return None

    # Minimal sanity: must contain at least the benchmarks dict with a few known keys.
    sb = corpus.get("stat_benchmarks")
    if not isinstance(sb, dict) or not {"adr", "kast"} & set(sb):
        print("refresh skipped: corpus missing expected stat_benchmarks", file=sys.stderr)
        return None
    return corpus


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("CS2 knowledge refresh dormant: ANTHROPIC_API_KEY not set — skipping.")
        return

    corpus = fetch_corpus(api_key)
    if corpus is None:
        return  # leave existing cs2-knowledge.json untouched

    corpus["_refreshed_at"] = now_iso()
    logs_dir = agent_logs_dir()
    os.makedirs(logs_dir, exist_ok=True)
    path = os.path.join(logs_dir, "cs2-knowledge.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(corpus, f, indent=2)
    os.replace(tmp, path)
    n = len(corpus.get("stat_benchmarks", {}))
    print(f"CS2 knowledge refreshed: {n} stat benchmarks written to {path}")


if __name__ == "__main__":
    main()
