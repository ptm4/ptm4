#!/usr/bin/env python3
"""
leetify-stats.py — Pull CS2 stats from the Leetify public API into an agent report.

Python port of Get-LeetifyStats.ps1. Fetches profile + recent matches and writes a
webapp-friendly report. Auth via the LEETIFY_API_KEY env var (Authorization: Bearer);
player via STEAM64_ID. If either is missing, the agent skips cleanly (exit 0, no write)
so it stays dormant until configured.

Writes <agent-logs>/leetify-latest.json. Dir from $HL_AGENT_LOGS_DIR.

Requires: pip install requests
"""

import json
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_LOGS_DIR = os.environ.get(
    "HL_AGENT_LOGS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "agent-logs")
)
REPORT_PATH = os.path.join(AGENT_LOGS_DIR, "leetify-latest.json")

BASE_URL = "https://api-public.cs-prod.leetify.com"
MATCH_COUNT = 25


def get(path, key, params=None):
    r = requests.get(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        params=params or {}, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def main():
    api_key = os.environ.get("LEETIFY_API_KEY")
    steam_id = os.environ.get("STEAM64_ID")
    if not api_key or not steam_id:
        print("Leetify agent dormant: LEETIFY_API_KEY and/or STEAM64_ID not set — skipping.")
        return  # exit 0, no report written; no dependency needed

    try:
        import requests  # noqa: F401 (lazy: only needed when actually configured)
    except ImportError:
        print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
        sys.exit(1)
    globals()["requests"] = requests

    os.makedirs(AGENT_LOGS_DIR, exist_ok=True)

    try:
        profile = get("/v3/profile", api_key, {"steam64_id": steam_id})
        all_matches = get("/v3/profile/matches", api_key, {"steam64_id": steam_id})
        matches = sorted(
            all_matches if isinstance(all_matches, list) else [],
            key=lambda m: m.get("finished_at", ""), reverse=True,
        )[:MATCH_COUNT]
        status, findings = "ok", []
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        report = {
            "tool": "leetify-stats",
            "run_at": datetime.now(timezone.utc).isoformat(),
            "status": "warn",
            "summary": f"Leetify API error (HTTP {code})",
            "findings": [{"severity": "warn", "message": f"Leetify request failed: HTTP {code}"}],
        }
        with open(REPORT_PATH, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Report written (error): {REPORT_PATH}")
        return

    name = profile.get("name") or profile.get("nickname") or steam_id
    rating = (profile.get("ranks") or {}).get("leetify") or profile.get("leetify_rating")
    summary = f"{name}: {len(matches)} recent match(es) pulled"
    if rating is not None:
        summary += f", Leetify rating {rating}"

    report = {
        "tool": "leetify-stats",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "steam64_id": steam_id,
        "profile": profile,
        "matches": matches,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} ({len(matches)} matches)")


if __name__ == "__main__":
    main()
