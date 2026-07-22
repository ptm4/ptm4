#!/usr/bin/env python3
"""Add TV series to Sonarr by title/year.

Reads one series per line from stdin: "Title (Year)" or bare "Title".
Adds each as monitored (all seasons) with an immediate episode search.
Exit code 0 if every line resolved (added or already present), 1 otherwise.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

SONARR = "http://192.168.1.6:8989/api/v3"
API_KEY = "e4260f7ab67d482aa2b3cbd2ebc7aef0"
ROOT_FOLDER = "/data/tvshows"
QUALITY_PROFILE_ID = 4  # HD-1080p


def req(path, data=None, method="GET"):
    r = urllib.request.Request(
        SONARR + path,
        data=json.dumps(data).encode() if data else None,
        headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
        method=method,
    )
    return json.loads(urllib.request.urlopen(r).read())


def parse_line(line):
    m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", line)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return line.strip(), None


def pick_match(results, year):
    if year is None:
        return results[0] if results else None
    for tolerance in (0, 1):
        for r in results:
            if abs(r.get("year", 0) - year) <= tolerance:
                return r
    return None


def main():
    lines = [l.strip() for l in sys.stdin if l.strip() and not l.strip().startswith("#")]
    if not lines:
        print("no input: pipe one 'Title (Year)' per line on stdin", file=sys.stderr)
        return 1

    existing_tvdb = {s["tvdbId"] for s in req("/series")}

    failures = 0
    for line in lines:
        title, year = parse_line(line)
        try:
            results = req("/series/lookup?term=" + urllib.parse.quote(title))
        except Exception as e:
            print(f"ERROR     | {line} | lookup failed: {e}")
            failures += 1
            continue

        match = pick_match(results, year)
        if not match:
            cands = ", ".join(f"{r['title']} ({r.get('year', '?')})" for r in results[:3]) or "none"
            print(f"NOT FOUND | {line} | candidates: {cands}")
            failures += 1
            continue

        if match["tvdbId"] in existing_tvdb:
            print(f"EXISTS    | {match['title']} ({match.get('year', '?')})")
            continue

        body = {
            "tvdbId": match["tvdbId"],
            "title": match["title"],
            "qualityProfileId": QUALITY_PROFILE_ID,
            "rootFolderPath": ROOT_FOLDER,
            "monitored": True,
            "seasonFolder": True,
            "seasons": match.get("seasons", []),
            "addOptions": {"searchForMissingEpisodes": True},
        }
        try:
            added = req("/series", body, "POST")
            existing_tvdb.add(added["tvdbId"])
            n_seasons = len([s for s in added.get("seasons", []) if s.get("seasonNumber", 0) > 0])
            print(f"ADDED     | {added['title']} ({added.get('year', '?')}) | tvdb={added['tvdbId']} | {n_seasons} season(s)")
        except Exception as e:
            print(f"ERROR     | {line} | add failed: {e}")
            failures += 1
        time.sleep(0.5)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
