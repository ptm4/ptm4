#!/usr/bin/env python3
"""
bb-kavita-sync — Batman Beyond story-order curation for Kavita.

Mylar downloads each run into its own raw folder under /srv/media/comics. Kavita
identifies comic series primarily by the embedded ComicInfo.xml (release-group
metadata, inconsistent across runs: five runs are all literally "Batman Beyond",
some releases omit Volume), so left alone the library becomes a merge/collision
mess. This script builds a curated tree of COPIES with rewritten ComicInfo.xml,
one Kavita series per run (mobile-friendly cards, individually downloadable):

    /srv/media/comics/Batman Beyond/<Series Name>/<Series Name> v{V} #{issue}.cbz
    ComicInfo: Series=<run name, year-disambiguated>, Volume, Number, Title

Both 1999 runs share the "Batman Beyond 1999" series (mini = vol 1, ongoing =
vol 2). Copies (not hardlinks) because rewriting a hardlinked zip would corrupt
mylar's original. The "Batman Beyond — Story Order" reading list is rebuilt by
appending each series in story order (publication order, except Beyond the
White Knight — an alternate-universe tale — goes last).

Sources of truth: mylar.db for what's downloaded and where (no filename
parsing); kavita.db (read-only) for series/reading-list lookups; all Kavita
writes go through its API.

Deployed to /usr/local/bin/bb-kavita-sync.py, run hourly by bb-kavita-sync.timer.
"""

import json
import os
import shutil
import sqlite3
import sys
import time
import urllib.request
import zipfile
from xml.sax.saxutils import escape

MYLAR_DB = "/opt/yams/config/mylar3/mylar/mylar.db"
KAVITA_DB = "/opt/yams/config/kavita/kavita.db"
KAVITA_URL = "http://localhost:5000"
KAVITA_KEY = "0fOg8hisleDdcfPm7hXQDO2D4GK95FQD"
LIBRARY_ID = 1                      # Kavita "Comics" library
# mylar's BB folders live OUTSIDE the Kavita library (/data/comics-raw) because
# Kavita indexes raw release metadata; only the curated tree is scanned
COMICS_HOST = "/srv/media/comics"   # host view of the containers' /data/comics
CURATED = os.path.join(COMICS_HOST, "Batman Beyond")
LIST_TITLE = "Batman Beyond — Story Order"

# (ComicVine volume id, Kavita series name, volume within that series, log label)
# in STORY order. Each run is its own Kavita series (mobile-friendly cards);
# years disambiguate the runs that are all literally titled "Batman Beyond".
# Both 1999 runs share one "Batman Beyond 1999" series: mini = vol 1, ongoing = vol 2.
RUNS = [
    ("6420",   "Batman Beyond 1999",                 1, "1999 mini"),
    ("6421",   "Batman Beyond 1999",                 2, "1999 ongoing"),
    ("27496",  "Batman Beyond - Return of the Joker", 1, "Return of the Joker"),
    ("34005",  "Batman Beyond 2010",                 1, "2010"),
    ("38094",  "Batman Beyond 2011",                 1, "2011"),
    ("46147",  "Batman Beyond Unlimited",            1, "Unlimited (2012)"),
    ("66022",  "Batman Beyond 2.0",                  1, "BB 2.0 (2013)"),
    ("82383",  "Batman Beyond 2015",                 1, "2015"),
    ("94407",  "Batman Beyond Rebirth",              1, "Rebirth one-shot"),
    ("95201",  "Batman Beyond 2016",                 1, "2016"),
    ("142127", "Batman Beyond - Neo-Year",           1, "Neo-Year"),
    ("152510", "Batman Beyond - Neo-Gothic",         1, "Neo-Gothic"),
    ("168403", "Batman-Static - Beyond",             1, "Batman/Static"),
    ("142034", "Batman - Beyond the White Knight",   1, "White Knight (alt-universe)"),
]


def issue_token(num_str):
    """'1' -> '001', '12.5' -> '012.5' — zero-padded so lexical == numeric order."""
    try:
        f = float(num_str)
    except (TypeError, ValueError):
        return None
    if f == int(f):
        return f"{int(f):03d}"
    whole, frac = str(f).split(".")
    return f"{int(whole):03d}.{frac}"


CI_XML = ('<?xml version="1.0" encoding="utf-8"?>\n'
          "<ComicInfo><Series>{series}</Series><Volume>{vol}</Volume>"
          "<Number>{num}</Number><Title>{title}</Title></ComicInfo>")


def curated_ok(dst, series):
    """True if dst carries our rewritten metadata AND has real page content —
    a crashed extraction once produced 419-byte husks that passed a pure
    metadata check, so demand at least a few page entries."""
    try:
        with zipfile.ZipFile(dst) as z:
            pages = [n for n in z.namelist() if not n.lower().endswith(".xml")]
            return (len(pages) >= 3
                    and f"<Series>{escape(series)}</Series>".encode()
                    in z.read("ComicInfo.xml"))
    except Exception:
        return False


def build_curated(src, dst, series, vol, num, title):
    """Copy src to dst as a cbz with ComicInfo.xml replaced by our canonical
    metadata. CBR (rar) sources are repacked to cbz via 7z."""
    tmp = dst + ".tmp"
    ci = CI_XML.format(series=escape(series), vol=vol, num=num, title=escape(title))
    try:
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for m in zin.infolist():
                if m.filename.lower().endswith("comicinfo.xml"):
                    continue
                zout.writestr(m, zin.read(m), compress_type=zipfile.ZIP_STORED)
            zout.writestr("ComicInfo.xml", ci)
        os.replace(tmp, dst)
        return "rewritten"
    except zipfile.BadZipFile:
        if os.path.exists(tmp):
            os.remove(tmp)
    import subprocess, tempfile
    with tempfile.TemporaryDirectory(dir=os.path.dirname(dst)) as ext:
        # real unrar first — p7zip's rar codec SEGFAULTS on some RAR4 archives,
        # and a mid-crash extraction once yielded 1-file husks. Judge success by
        # page count, never by exit code (7z exits 1 on mere warnings).
        pages = []
        for cmd in (["unrar", "x", "-y", "-idq", src, ext + os.sep],
                    ["7z", "x", "-y", f"-o{ext}", src]):
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except (OSError, subprocess.TimeoutExpired):
                continue
            pages = [os.path.join(r, f) for r, _, fs in os.walk(ext) for f in fs
                     if not f.lower().endswith(".xml")]
            if len(pages) >= 3:
                break
        if len(pages) < 3:
            shutil.copy2(src, dst)
            return "copied-raw (all extractors failed; original served as-is)"
        with zipfile.ZipFile(tmp, "w") as zout:
            for p in sorted(pages):
                zout.write(p, arcname=os.path.relpath(p, ext),
                           compress_type=zipfile.ZIP_STORED)
            zout.writestr("ComicInfo.xml", ci)
        os.replace(tmp, dst)
    return "repacked cbr->cbz"


def curate_downloads():
    """Materialize every downloaded issue into the curated tree. Returns per-run stats."""
    os.makedirs(CURATED, exist_ok=True)
    for fn in os.listdir(CURATED):  # flat-layout leftovers from the single-series era
        p = os.path.join(CURATED, fn)
        if os.path.isfile(p):
            os.remove(p)
    con = sqlite3.connect(f"file:{MYLAR_DB}?mode=ro", uri=True)
    stats = []
    for cvid, series, vol, label in RUNS:
        row = con.execute("SELECT ComicLocation FROM comics WHERE ComicID=?", (cvid,)).fetchone()
        if not row or not row[0]:
            stats.append((label, 0, 0, "not in mylar"))
            continue
        raw_dir = row[0].replace("/data/comics", COMICS_HOST, 1)
        issues = con.execute(
            "SELECT Issue_Number, Location FROM issues"
            " WHERE ComicID=? AND Status='Downloaded' AND Location IS NOT NULL",
            (cvid,)).fetchall()
        sdir = os.path.join(CURATED, series)
        os.makedirs(sdir, exist_ok=True)
        done = missing = 0
        notes = []
        for num, loc in issues:
            tok = issue_token(num)
            src = os.path.join(raw_dir, loc)
            if tok is None or not os.path.isfile(src):
                missing += 1
                continue
            dst = os.path.join(sdir, f"{series} v{vol} #{tok}.cbz")
            if os.path.exists(dst) and curated_ok(dst, series) \
                    and os.path.getmtime(dst) >= os.path.getmtime(src):
                done += 1
                continue
            note = build_curated(src, dst, series, vol, num, f"{series} #{num}")
            if "rewritten" not in note:
                notes.append(f"#{num} {note}")
            done += 1
        stats.append((label, done, len(issues),
                      "; ".join((f"{missing} missing on disk",) * bool(missing)) +
                      " ".join(notes)))
    con.close()
    return stats


def api(method, path, body=None, token=None, tries=3):
    url = KAVITA_URL + path
    for attempt in range(tries):
        req = urllib.request.Request(url, method=method,
                                     data=json.dumps(body).encode() if body is not None else b"")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                try:  # some Kavita endpoints answer plain text, not JSON
                    return r.status, (json.loads(raw) if raw.strip() else None)
                except ValueError:
                    return r.status, raw.decode(errors="replace")
        except Exception as e:
            if attempt == tries - 1:
                detail = getattr(e, "read", lambda: b"")()[:200] if hasattr(e, "read") else ""
                raise RuntimeError(f"{method} {path} failed: {e} {detail}") from e
            time.sleep(5)


def kavita_db(query, args=()):
    con = sqlite3.connect(f"file:{KAVITA_DB}?mode=ro", uri=True)
    rows = con.execute(query, args).fetchall()
    con.close()
    return rows


def sync_kavita(have_files):
    st, resp = api("POST", f"/api/Plugin/authenticate?apiKey={KAVITA_KEY}&pluginName=bb-sync")
    token = resp["token"]
    api("POST", f"/api/Library/scan?libraryId={LIBRARY_ID}", body={}, token=token)
    if not have_files:
        print("no curated files yet — scan kicked, skipping reading list")
        return

    # story-ordered unique series names (both 1999 runs share one series)
    ordered = []
    for _, series, _, _ in RUNS:
        if series not in ordered:
            ordered.append(series)

    found = {}
    for _ in range(30):  # scan is async; wait for our series to appear
        rows = kavita_db(
            f"SELECT Name, Id FROM Series WHERE LibraryId=? AND Name IN "
            f"({','.join('?' * len(ordered))})", (LIBRARY_ID, *ordered))
        found = dict(rows)
        if found:
            break
        time.sleep(5)
    if not found:
        print("series not indexed yet — reading list deferred to next run")
        return

    # rebuild the list: series appended in story order, chapters in series order
    for (rid,) in kavita_db("SELECT Id FROM ReadingList WHERE Title=?", (LIST_TITLE,)):
        api("DELETE", f"/api/ReadingList?readingListId={rid}", token=token)
    st, created = api("POST", "/api/ReadingList/create", body={"title": LIST_TITLE}, token=token)
    list_id = created["id"]
    for name in ordered:
        if name in found:
            api("POST", "/api/ReadingList/update-by-series",
                body={"readingListId": list_id, "seriesId": found[name]}, token=token)
    absent = [n for n in ordered if n not in found]
    print(f"reading list '{LIST_TITLE}' rebuilt (list {list_id}, "
          f"{len(found)}/{len(ordered)} series)"
          + (f"; awaiting: {', '.join(absent)}" if absent else ""))


def main():
    stats = curate_downloads()
    for label, done, dl, note in stats:
        print(f"{label:45s} curated {done}/{dl} downloaded {note}")
    have = any(os.scandir(CURATED)) if os.path.isdir(CURATED) else False
    try:
        sync_kavita(have)
    except Exception as e:
        print(f"kavita sync failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
