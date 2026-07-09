#!/usr/bin/env python3
"""Add movies to Radarr by title/year.

Reads one movie per line from stdin: "Title (Year)" or bare "Title".
Adds each as monitored with an immediate download search.
Exit code 0 if every line resolved (added or already present), 1 otherwise.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

RADARR = "http://192.168.1.6:7878/api/v3"
API_KEY = "f93e83c7f91e46319c73e6d0508e4ecd"
ROOT_FOLDER = "/data/movies"


def req(path, data=None, method="GET"):
    r = urllib.request.Request(
        RADARR + path,
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


def pick_match(results, title, year):
    if year is None:
        return results[0] if results else None
    for tolerance in (0, 1):
        for r in results:
            if abs(r["year"] - year) <= tolerance:
                return r
    return None


def main():
    lines = [l.strip() for l in sys.stdin if l.strip() and not l.strip().startswith("#")]
    if not lines:
        print("no input: pipe one 'Title (Year)' per line on stdin", file=sys.stderr)
        return 1

    existing_tmdb = {m["tmdbId"] for m in req("/movie")}
    profile_id = req("/movie")[0]["qualityProfileId"] if existing_tmdb else 1

    failures = 0
    for line in lines:
        title, year = parse_line(line)
        try:
            results = req("/movie/lookup?term=" + urllib.parse.quote(title))
        except Exception as e:
            print(f"ERROR     | {line} | lookup failed: {e}")
            failures += 1
            continue

        match = pick_match(results, title, year)
        if not match:
            cands = ", ".join(f"{r['title']} ({r['year']})" for r in results[:3]) or "none"
            print(f"NOT FOUND | {line} | candidates: {cands}")
            failures += 1
            continue

        if match["tmdbId"] in existing_tmdb:
            print(f"EXISTS    | {match['title']} ({match['year']})")
            continue

        body = {
            "tmdbId": match["tmdbId"],
            "title": match["title"],
            "year": match["year"],
            "qualityProfileId": profile_id,
            "rootFolderPath": ROOT_FOLDER,
            "monitored": True,
            "addOptions": {"searchForMovie": True},
        }
        try:
            added = req("/movie", body, "POST")
            existing_tmdb.add(added["tmdbId"])
            print(f"ADDED     | {added['title']} ({added['year']}) | tmdb={added['tmdbId']}")
        except Exception as e:
            print(f"ERROR     | {line} | add failed: {e}")
            failures += 1
        time.sleep(0.5)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
