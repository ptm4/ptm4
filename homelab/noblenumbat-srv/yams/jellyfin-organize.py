#!/usr/bin/env python3
"""Organize the Jellyfin movie library into collections + watch-order playlists.

Idempotent: safe to re-run as more movies download/import. Collections get
missing items appended; playlists are rebuilt each run to preserve order.
Movies not yet in Jellyfin (still downloading) are reported and skipped.

Usage: python3 jellyfin-organize.py
"""
import json
import re
import sys
import urllib.parse
import urllib.request

JELLYFIN = "http://192.168.1.6:8096"
TOKEN = "e6b7535cffd349d09e6ba70b235c2f9b"

# (title, year, tmdb_id_or_None) — tmdb matches first, then normalized title+year

# "The Real Timeline of Batman — Expanded": one playlist per act, in-story order
BATMAN_ACTS = {
    "Batman 00 · Prologue — Batmen of Past Ages": [
            ("Batman: Gotham by Gaslight", 2018, None),
        ("Batman: The Doom That Came to Gotham", 2023, None),
    ],
    "Batman 01 · Act 1 — Origin & Solo Years": [
        ("Batman: Year One", 2011, None),
        ("Batman: The Long Halloween, Part One", 2021, None),
        ("Batman: The Long Halloween, Part Two", 2021, None),
        ("Batman: Gotham Knight", 2008, None),
        ("Batman: Mask of the Phantasm", 1993, None),
        ("The Batman vs. Dracula", 2005, None),
        ("Batman: Soul of the Dragon", 2021, None),
    ],
    "Batman 02 · Act 2 — Dick Grayson, Robin I": [
        ("Batman & Mr. Freeze: SubZero", 1998, None),
        ("The Batman/Superman Movie: World's Finest", 1997, None),
        ("Superman/Batman: Public Enemies", 2009, None),
        ("Superman/Batman: Apocalypse", 2010, None),
    ],
    "Batman 03 · Act 3 — Jason Todd, Robin II": [
        ("Batman: The Killing Joke", 2016, None),
        ("Batman: Under the Red Hood", 2010, None),
        ("DC Showcase - Batman: Death in the Family", 2020, None),
    ],
    "Batman 04 · Act 4 — The Nightwing Era": [
        ("Batman: Mystery of the Batwoman", 2003, None),
        ("Batman and Harley Quinn", 2017, None),
        ("Batman: Assault on Arkham", 2014, None),
    ],
    "Batman 05 · Act 5 — Damian Wayne (DCAMU)": [
        ("Justice League: The Flashpoint Paradox", 2013, 183011),
        ("Justice League: War", 2014, 217993),
        ("Son of Batman", 2014, None),
        ("Justice League: Throne of Atlantis", 2015, 297556),
        ("Batman vs. Robin", 2015, None),
        ("Batman: Bad Blood", 2016, None),
        ("Justice League vs. Teen Titans", 2016, 379291),
        ("Teen Titans: The Judas Contract", 2017, 408647),
        ("Justice League Dark", 2017, 408220),
        ("Suicide Squad: Hell to Pay", 2018, 487242),
        ("The Death of Superman", 2019, 487670),
        ("Reign of the Supermen", 2019, 487672),
        ("Batman: Hush", 2019, None),
        ("Justice League Dark: Apokolips War", 2020, 618344),
        ("Batman and Superman: Battle of the Super Sons", 2022, None),
    ],
    "Batman 05.5 · Act 5.5 — The Dark What-If": [
        ("Injustice", 2021, 831405),
    ],
    "Batman 06 · Act 6 — The Endgame": [
        ("Batman: The Dark Knight Returns, Part 1", 2012, None),
        ("Batman: The Dark Knight Returns, Part 2", 2013, None),
    ],
    "Batman 07 · Act 7 — Legacy": [
        ("Batman Beyond: Return of the Joker", 2000, None),
    ],
    "Batman 08 · Outside the Timeline": [
        ("Merry Little Batman", 2023, None),
                ("Batman vs Teenage Mutant Ninja Turtles", 2019, None),
        ("Batman: Return of the Caped Crusaders", 2016, None),
        ("Batman vs. Two-Face", 2017, None),
    ],
}

# Not in the timeline playlists, but they belong on the all-Batman shelf
BATMAN_SHELF_EXTRAS = [
    ("Batman Unlimited: Animal Instincts", 2015, None),
    ("Batman Unlimited: Monster Mayhem", 2015, None),
    ("Batman Unlimited: Mechs vs. Mutants", 2016, None),
    ("Scooby-Doo! & Batman: The Brave and the Bold", 2018, None),
    ("Batman Beyond: The Movie", 1999, None),
]

BATMAN_ALL = [e for act in BATMAN_ACTS.values() for e in act] + BATMAN_SHELF_EXTRAS

STAR_WARS = [
    ("Star Wars: Episode I - The Phantom Menace", 1999, 1893),
    ("Star Wars: Episode II - Attack of the Clones", 2002, 1894),
    ("Star Wars: Episode III - Revenge of the Sith", 2005, 1895),
    ("Star Wars", 1977, 11),
    ("The Empire Strikes Back", 1980, 1891),
    ("Return of the Jedi", 1983, 1892),
]

TWILIGHT = [
    ("Twilight", 2008, 8966),
    ("The Twilight Saga: New Moon", 2009, 18239),
    ("The Twilight Saga: Eclipse", 2010, 24021),
    ("The Twilight Saga: Breaking Dawn - Part 1", 2011, 50619),
    ("The Twilight Saga: Breaking Dawn - Part 2", 2012, 50620),
]

CRITICS_HOF = [
    ("Come and See", 1985, 25237),
    ("Mulholland Drive", 2001, 1018),
    ("There Will Be Blood", 2007, 7345),
    ("In the Mood for Love", 2000, 843),
    ("Parasite", 2019, 496243),
    ("Raging Bull", 1980, 1578),
    ("Spirited Away", 2001, 129),
    ("Once Upon a Time in America", 1984, 311),
    ("Blue Velvet", 1986, 793),
    ("Schindler's List", 1993, 424),
    ("Do the Right Thing", 1989, 925),
    ("Blade Runner", 1982, 78),
    ("City of God", 2002, 598),
    ("Paris, Texas", 1984, 655),
    ("Yi Yi", 2000, 25538),
    ("Heat", 1995, 949),
    ("Se7en", 1995, 807),
    ("The Silence of the Lambs", 1991, 274),
    ("Memories of Murder", 2003, 11423),
    ("Eternal Sunshine of the Spotless Mind", 2004, 38),
    ("The Thing", 1982, 1091),
    ("Grave of the Fireflies", 1988, 12477),
    ("The Matrix", 1999, 603),
    ("Terminator 2: Judgment Day", 1991, 280),
    ("Back to the Future", 1985, 105),
]

COLLECTIONS = {
    "Batman Animated Movies": BATMAN_ALL,
    "Star Wars: The Saga": STAR_WARS,
    "The Twilight Saga": TWILIGHT,
    "Critics HOF": CRITICS_HOF,
}

# Playlists preserve arbitrary order (collections can't) — one per ordered list
PLAYLISTS = dict(BATMAN_ACTS)
PLAYLISTS["Star Wars: Saga Order"] = STAR_WARS

# Old playlists superseded by the act structure — removed if present
STALE_PLAYLISTS = ["Batman: The Watch Order"]


def req(path, data=None, method="GET"):
    r = urllib.request.Request(
        JELLYFIN + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"X-Emby-Token": TOKEN, "Content-Type": "application/json"},
        method=method,
    )
    body = urllib.request.urlopen(r).read()
    return json.loads(body) if body.strip() else None


def norm(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def build_index():
    items = req(
        "/Items?IncludeItemTypes=Movie&Recursive=true"
        "&Fields=ProviderIds,ProductionYear&EnableImages=false"
    )["Items"]
    by_tmdb, by_title = {}, {}
    for it in items:
        tmdb = it.get("ProviderIds", {}).get("Tmdb")
        if tmdb:
            by_tmdb[int(tmdb)] = it["Id"]
        by_title[(norm(it["Name"]), it.get("ProductionYear"))] = it["Id"]
    return by_tmdb, by_title


def resolve(entries, by_tmdb, by_title):
    found, missing = [], []
    for title, year, tmdb in entries:
        item_id = by_tmdb.get(tmdb) if tmdb else None
        if not item_id:
            for y in (year, year - 1, year + 1):
                item_id = by_title.get((norm(title), y))
                if item_id:
                    break
        (found if item_id else missing).append(item_id or f"{title} ({year})")
    return found, missing


def existing_boxsets():
    r = req("/Items?IncludeItemTypes=BoxSet&Recursive=true")
    return {it["Name"]: it["Id"] for it in r["Items"]}


def existing_playlists():
    r = req("/Items?IncludeItemTypes=Playlist&Recursive=true")
    return {it["Name"]: it["Id"] for it in r["Items"]}


def collection_members(coll_id):
    r = req(f"/Items?ParentId={coll_id}")
    return {it["Id"] for it in r["Items"]}


def main():
    by_tmdb, by_title = build_index()
    admin_id = req("/Users")[0]["Id"]

    boxsets = existing_boxsets()
    for name, entries in COLLECTIONS.items():
        ids, missing = resolve(entries, by_tmdb, by_title)
        if name in boxsets:
            new = [i for i in ids if i not in collection_members(boxsets[name])]
            if new:
                req(f"/Collections/{boxsets[name]}/Items?Ids={','.join(new)}", data={}, method="POST")
            print(f"collection '{name}': +{len(new)} added, {len(ids)} in library, {len(missing)} pending")
        else:
            r = req(f"/Collections?Name={urllib.parse.quote(name)}&Ids={','.join(ids)}", data={}, method="POST")
            print(f"collection '{name}': created with {len(ids)} items, {len(missing)} pending")
        for m in missing:
            print(f"    pending: {m}")

    playlists = existing_playlists()
    for name in STALE_PLAYLISTS:
        if name in playlists:
            req(f"/Items/{playlists[name]}", method="DELETE")
            print(f"playlist '{name}': removed (superseded)")

    for name, entries in PLAYLISTS.items():
        ids, missing = resolve(entries, by_tmdb, by_title)
        if name in playlists:  # rebuild to preserve order
            req(f"/Items/{playlists[name]}", method="DELETE")
        req("/Playlists", data={"Name": name, "Ids": ids, "UserId": admin_id, "MediaType": "Video"}, method="POST")
        print(f"playlist '{name}': {len(ids)} in order, {len(missing)} pending")


if __name__ == "__main__":
    sys.exit(main())
