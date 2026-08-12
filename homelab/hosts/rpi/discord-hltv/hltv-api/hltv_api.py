#!/usr/bin/env python3
"""
hltv-api — our own read-only HLTV.org API, because HLTV publishes none.

HLTV is Cloudflare-fronted: plain HTTP clients get a 403 interstitial. A real
browser does not, so this drives one (Playwright + Chromium) and parses the
rendered DOM. Two rules that cost a day to learn, do not undo them:

  • It must be the FULL Chromium build. Playwright's `chromium-headless-shell`
    is stripped enough that Cloudflare serves it "Just a moment…" forever.
    On arm64 Playwright ships no build at all, so we point at Debian's
    /usr/bin/chromium — also a full browser. Headless itself is fine.
  • Wait for elements `state="attached"`, never visible: .match rows live in
    collapsed day sections and are never "visible" to Playwright.

An interactive challenge (a checkbox to click) is NEVER solved automatically —
we detect it, report it in /health, and stop. See CHALLENGE_ASSIST in README.

Endpoints:
  GET /day?date=YYYY-MM-DD&tz=Area/City&max_age=<sec>   matches for that local day
  GET /vrs                                              Valve Regional Standings
  GET /selftest                                         per-selector element counts
  GET /health                                           liveness + last error

CLI:
  --once [--date D] [--tz Z]   print the day payload as JSON, exit
  --vrs                        print the VRS payload as JSON, exit
  --selftest                   print selector health, exit
"""
import argparse
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

DATA_DIR = os.environ.get("DATA_DIR", "/data")
PROFILE_DIR = os.path.join(DATA_DIR, "profile")
VRS_CACHE_PATH = os.path.join(DATA_DIR, "vrs.json")
API_PORT = int(os.environ.get("PORT", "8080"))
CHROME_PATH = os.environ.get("CHROME_PATH", "/usr/bin/chromium")
CHROME_CHANNEL = os.environ.get("CHROME_CHANNEL", "")  # "chromium" when using a PW build

BASE = "https://www.hltv.org"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/151.0.0.0 Safari/537.36")

VRS_CACHE_HOURS = 24
# Match pages per scrape. Only these get map scores and a stream link, so the cap
# has to cover a full day's notable matches — a big event fields ~16 — or the
# tail of the digest silently loses its streams.
DETAIL_CAP = int(os.environ.get("DETAIL_CAP", "24"))
PAGE_DELAY = float(os.environ.get("PAGE_DELAY", "2"))  # seconds between page loads
READY_BUDGET = 45          # seconds to wait for real content after a navigation
SCRAPE_RETRIES = 3
RETRY_SLEEP = 30

CHALLENGE_TITLES = ("just a moment", "attention required", "checking your browser")


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


_state = {"last_success_at": None, "last_error": None, "challenge_detected": False,
          "scrapes": 0}
_day_cache = {}                   # (date, tz) -> {"at": epoch, "payload": {...}}

# Playwright's sync API belongs to the thread that started it, but
# ThreadingHTTPServer answers each request on a fresh thread — calling the
# browser from those deadlocks. So every browser job is queued onto one
# dedicated worker thread, which also serializes page loads for free.
_jobs = queue.Queue()
JOB_TIMEOUT = 300


def _browser_worker():
    while True:
        fn, box, done = _jobs.get()
        try:
            box["result"] = fn()
        except Exception as e:  # noqa: BLE001 — re-raised in the caller's thread
            box["error"] = e
        finally:
            done.set()


def in_browser(fn, timeout=JOB_TIMEOUT):
    """Run fn on the browser thread and return its result here."""
    box, done = {}, threading.Event()
    _jobs.put((fn, box, done))
    if not done.wait(timeout):
        raise RuntimeError(f"browser job timed out after {timeout}s")
    if "error" in box:
        raise box["error"]
    return box["result"]


class Challenged(RuntimeError):
    """Cloudflare showed an interactive challenge. Never auto-solved."""


# ── browser ───────────────────────────────────────────────────────────────────
class Browser:
    """One long-lived Chromium with a persistent profile, so the Cloudflare
    clearance cookie survives restarts and we look like a returning visitor."""

    def __init__(self):
        self._pw = None
        self._ctx = None

    def _ensure(self):
        if self._ctx is not None:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        os.makedirs(PROFILE_DIR, exist_ok=True)
        # An unclean exit (container kill, OOM) leaves these behind, and Chromium
        # then refuses to start at all — "Failed to create a ProcessSingleton".
        # We are the only user of this profile, so a leftover lock is always stale.
        for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                os.unlink(os.path.join(PROFILE_DIR, lock))
            except OSError:
                pass
        kw = dict(
            headless=os.environ.get("CHALLENGE_ASSIST") != "1",
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage", "--no-sandbox"],
        )
        if CHROME_CHANNEL:
            kw["channel"] = CHROME_CHANNEL
        else:
            kw["executable_path"] = CHROME_PATH
        self._ctx = self._pw.chromium.launch_persistent_context(PROFILE_DIR, **kw)
        log(f"browser up ({CHROME_CHANNEL or CHROME_PATH})")

    def close(self):
        for obj, meth in ((self._ctx, "close"), (self._pw, "stop")):
            try:
                if obj:
                    getattr(obj, meth)()
            except Exception:
                pass
        self._ctx = self._pw = None

    def fetch(self, path, ready_sel, extract):
        """Load a page, wait for real content, run `extract` (a JS expression)."""
        self._ensure()
        page = self._ctx.new_page()
        try:
            page.goto(BASE + path, wait_until="domcontentloaded", timeout=45000)
            deadline = time.time() + READY_BUDGET
            while time.time() < deadline:
                if page.query_selector(ready_sel):
                    _state["challenge_detected"] = False
                    return page.evaluate(extract)
                time.sleep(1)
            title = (page.title() or "")
            if any(m in title.lower() for m in CHALLENGE_TITLES):
                _state["challenge_detected"] = True
                raise Challenged(f"Cloudflare challenge on {path} (title {title!r})")
            raise RuntimeError(f"{path}: {ready_sel} never appeared (title {title!r})")
        finally:
            try:
                page.close()
            except Exception:
                pass
            time.sleep(PAGE_DELAY)


_browser = Browser()


def scrape(fn):
    """Run a scrape with retries. Challenges are not retried — they need a human."""
    last = None
    for attempt in range(SCRAPE_RETRIES):
        try:
            out = fn()
            _state["last_success_at"] = datetime.now().isoformat(timespec="seconds")
            _state["last_error"] = None
            _state["scrapes"] += 1
            return out
        except Challenged as e:
            _state["last_error"] = str(e)
            raise
        except Exception as e:  # noqa: BLE001 — retried, then surfaced
            last = e
            log(f"scrape attempt {attempt + 1}/{SCRAPE_RETRIES} failed: {e}")
            _browser.close()          # a wedged browser is the usual culprit
            if attempt < SCRAPE_RETRIES - 1:
                time.sleep(RETRY_SLEEP)
    _state["last_error"] = str(last)
    raise RuntimeError(f"scrape failed after {SCRAPE_RETRIES} tries: {last}")


# ── extractors (JS run in the page) ───────────────────────────────────────────
# The matches page carries two things we want: the day's fixtures, and the
# sidebar's stream directory — the only place HLTV states whether a channel is a
# tournament ORGANIZER rather than a caster or a random streamer.
JS_MATCHES = """() => ({
  matches: [...document.querySelectorAll('.match')].map(m => {
    const stars = [...m.querySelectorAll('.match-rating i')];
    const a = m.querySelector('a[href^="/matches/"]');
    return {
      url: a ? a.getAttribute('href') : null,
      unix: m.querySelector('.match-time')?.getAttribute('data-unix') || null,
      bo: (m.querySelector('.match-meta')?.textContent || '').trim(),
      event: m.querySelector('.match-event')?.getAttribute('data-event-headline') || null,
      teams: [...m.querySelectorAll('.match-teamname')].map(e => e.textContent.trim()),
      stars: stars.filter(i => !i.classList.contains('faded')).length,
    };
  }),
  streams: [...document.querySelectorAll('.streams-stream')].map(s => ({
    title: s.getAttribute('data-frontpage-stream-title'),
    type: s.getAttribute('data-frontpage-stream-type'),
    flag: s.getAttribute('data-frontpage-stream-flag-name'),
    viewers: +(s.getAttribute('data-frontpage-stream-viewers') || 0),
  })),
})"""

JS_RESULTS = """() => [...document.querySelectorAll('.result-con')].map(r => {
  const a = r.querySelector('a[href^="/matches/"]');
  const teams = [...r.querySelectorAll('.team')].map(e => e.textContent.trim());
  const score = (r.querySelector('.result-score')?.textContent || '').trim();
  return {
    url: a ? a.getAttribute('href') : null,
    unix: r.getAttribute('data-zonedgrouping-entry-unix'),
    teams,
    won: r.querySelector('.team-won')?.textContent.trim() || null,
    score,
    event: r.querySelector('.event-name')?.textContent.trim() || null,
    stars: r.querySelectorAll('.stars i.fa-star:not(.faded)').length,
  };
})"""

JS_MATCH = """() => ({
  maps: [...document.querySelectorAll('.mapholder')].map(m => ({
    name: m.querySelector('.mapname')?.textContent.trim() || null,
    scores: [...m.querySelectorAll('.results-team-score')].map(s => s.textContent.trim()),
    played: !!m.querySelector('.played'),
  })),
  streamBoxes: [...document.querySelectorAll('.stream-box-embed')].map(e => ({
    name: e.textContent.trim(),
    flag: e.querySelector('img.flag')?.getAttribute('title') || null,
    embed: e.getAttribute('data-stream-embed') || null,
  })),
  team1: document.querySelector('.team1-gradient .teamName')?.textContent.trim() || null,
  team2: document.querySelector('.team2-gradient .teamName')?.textContent.trim() || null,
  score1: document.querySelector('.team1-gradient .won, .team1-gradient .lost')?.textContent.trim() || null,
  score2: document.querySelector('.team2-gradient .won, .team2-gradient .lost')?.textContent.trim() || null,
  unix: document.querySelector('.timeAndEvent .time')?.getAttribute('data-unix') || null,
  event: document.querySelector('.timeAndEvent .event a')?.textContent.trim() || null,
  countdown: document.querySelector('.countdown')?.textContent.trim() || null,
})"""

JS_VRS = """() => ({
  header: document.querySelector('.regional-ranking-header, h1')?.textContent.trim() || '',
  teams: [...document.querySelectorAll('.ranked-team')].map(r => ({
    pos: r.querySelector('.position')?.textContent.trim() || '',
    name: r.querySelector('.name')?.textContent.trim() || '',
    points: r.querySelector('.points')?.textContent.trim() || '',
  })),
})"""

JS_SELFTEST = """() => ({
  match: document.querySelectorAll('.match').length,
  match_time: document.querySelectorAll('.match-time[data-unix]').length,
  match_teamname: document.querySelectorAll('.match-teamname').length,
  match_event: document.querySelectorAll('.match-event[data-event-headline]').length,
  match_rating: document.querySelectorAll('.match-rating i').length,
})"""


# ── normalization ─────────────────────────────────────────────────────────────
def match_id(url):
    m = re.match(r"/matches/(\d+)/", url or "")
    return m.group(1) if m else None


def stream_url(box):
    """Turn HLTV's embed URL into a watchable link. Twitch is ~all of them."""
    e = box.get("embed") or ""
    m = re.search(r"[?&]channel=([^&]+)", e)
    if m:
        return f"https://twitch.tv/{m.group(1)}"
    m = re.search(r"[?&]video=v?(\d+)", e)
    if m:
        t = re.search(r"[?&]t=([0-9hms]+)", e)
        return f"https://twitch.tv/videos/{m.group(1)}" + (f"?t={t.group(1)}" if t else "")
    if e.startswith("http"):
        return e
    h = box.get("href") or ""
    return h if h.startswith("http") else None


ENGLISH_FLAGS = {"united kingdom", "united states", "other", "australia", "canada"}
# words that say nothing about *which* organizer a stream belongs to
EVENT_STOPWORDS = {"open", "closed", "qualifier", "qualifiers", "series", "season",
                   "playoffs", "finals", "final", "group", "stage", "division",
                   "league", "cup", "regional", "europe", "asia", "americas"}


def name_tokens(s):
    return [t for t in re.split(r"[^a-z0-9]+", str(s or "").lower()) if t]


def matches_event(stream_name, event):
    """True if a channel name reads like the event's own broadcast.
    'Esports World Cup' → event 'Esports World Cup 2026'. Digits are ignored so
    'CCT 1' still matches 'CCT 2026 Europe Series 7', and generic words alone
    ('Open Qualifier') never carry a match on their own."""
    ev = set(name_tokens(event))
    st = [t for t in name_tokens(stream_name) if not t.isdigit()]
    strong = [t for t in st if t not in EVENT_STOPWORDS]
    if not strong or not ev:
        return False
    return all(t in ev for t in strong)


def is_english(box, url):
    if (box.get("flag") or "").strip().lower() in ENGLISH_FLAGS:
        return True
    # organizers name their language feeds in the channel: EWC_plus_en, blast_en …
    return bool(re.search(r"[_-]en(?:g|glish)?(?:\b|_|$)", url or "", re.I))


def pick_stream(boxes, event, organizers):
    """The **official** broadcast for this match, or nothing.

    HLTV lists every stream a match has — 40+ for a big event, mostly watch
    parties and personal channels, in no useful order. Only two things identify
    the organizer's own feed: the channel name matching the event, or HLTV's
    sidebar typing that channel ORGANIZER. Anything else is somebody's stream,
    so we return None rather than link a random one."""
    best = None
    for b in boxes or []:
        name = re.sub(r"\s+", " ", (b.get("name") or "")).strip()
        low = name.lower()
        if not name or low.startswith(("demo", "no streams")):
            continue
        name = re.sub(r"\s*\(Map \d+[^)]*\)", "", name).strip(" -–—")
        url = stream_url(b)
        if not url:
            continue
        by_event = matches_event(name, event)
        by_registry = norm_key(name) in organizers
        if not (by_event or by_registry):
            continue
        # the event's own channel outranks a generically-typed organizer, and an
        # English feed outranks the same organizer's other-language channels
        rank = (by_event, is_english(b, url), organizers.get(norm_key(name), 0))
        if best is None or rank > best[0]:
            best = (rank, {"name": name[:28], "url": url})
    return best[1] if best else None


def norm_key(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def map_name(n):
    return (n or "").strip() or None


MAX_LIVE_HOURS = 6  # a series longer than this is stale data, not still playing


def norm_from_list(row, now):
    """A /matches row → normalized upcoming/live match.

    Status comes from the clock, not the DOM: /matches lists only unfinished
    matches, so anything already past its start time is live. The .matchLive
    class is also present on cards that merely advertise a stream, which made
    future matches look live."""
    try:
        start = int(row["unix"]) // 1000
    except (TypeError, ValueError, KeyError):
        return None
    live = start <= now < start + MAX_LIVE_HOURS * 3600
    teams = row.get("teams") or []
    return {
        "id": match_id(row.get("url")),
        "url": BASE + (row.get("url") or ""),
        "event": row.get("event"),
        "stars": row.get("stars") or 0,
        "bo": (row.get("bo") or "").lower(),
        "team1": teams[0] if len(teams) > 0 else "TBD",
        "team2": teams[1] if len(teams) > 1 else "TBD",
        "start_unix": start,
        "status": "live" if live else "upcoming",
        "score1": None, "score2": None, "maps": [], "stream": None,
    }


def norm_from_result(row):
    """A /results row → normalized finished match."""
    try:
        start = int(row["unix"]) // 1000
    except (TypeError, ValueError, KeyError):
        return None
    teams = row.get("teams") or []
    s = re.match(r"(\d+)\s*-\s*(\d+)", row.get("score") or "")
    return {
        "id": match_id(row.get("url")),
        "url": BASE + (row.get("url") or ""),
        "event": row.get("event"),
        "stars": row.get("stars") or 0,
        "bo": "",
        "team1": teams[0] if len(teams) > 0 else "TBD",
        "team2": teams[1] if len(teams) > 1 else "TBD",
        "start_unix": start,
        "status": "finished",
        "score1": int(s.group(1)) if s else None,
        "score2": int(s.group(2)) if s else None,
        "winner": row.get("won"),
        "maps": [], "stream": None,
    }


def apply_detail(m, d, organizers=None):
    """Fold a match page's data into a normalized match."""
    maps = []
    for mp in d.get("maps") or []:
        name = map_name(mp.get("name"))
        sc = mp.get("scores") or []
        # "Default" is HLTV's placeholder for a map awarded without play; the
        # series score already reflects it, so listing it just reads as noise.
        if (not name or name.lower() in ("tbd", "default")
                or not mp.get("played") or len(sc) < 2):
            continue
        try:
            maps.append({"name": name, "s1": int(sc[0]), "s2": int(sc[1])})
        except ValueError:
            continue
    if maps:
        m["maps"] = maps
    st = pick_stream(d.get("streamBoxes"), d.get("event") or m.get("event"),
                     organizers or {})
    if st:
        m["stream"] = st
    for key, src in (("score1", "score1"), ("score2", "score2")):
        if m.get(key) is None and (d.get(src) or "").isdigit():
            m[key] = int(d[src])
    if d.get("event") and not m.get("event"):
        m["event"] = d["event"]
    cd = (d.get("countdown") or "").lower()
    if "live" in cd and m["status"] == "upcoming":
        m["status"] = "live"
    if d.get("team1") and m["team1"] == "TBD":
        m["team1"] = d["team1"]
    if d.get("team2") and m["team2"] == "TBD":
        m["team2"] = d["team2"]
    return m


# ── day scrape ────────────────────────────────────────────────────────────────
def scrape_day(date_str, tzname):
    """All matches for one local day: upcoming + live from /matches, finished
    from /results, then match pages for detail (map scores, streams)."""
    tz = ZoneInfo(tzname)
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    day_start = int(day.timestamp())
    day_end = int((day + timedelta(days=1)).timestamp())
    # A match that began late yesterday can still be live now — keep those.
    look_back = day_start - 6 * 3600

    now = int(time.time())
    listing = _browser.fetch("/matches", ".match", JS_MATCHES)
    rows = listing.get("matches") or []
    organizers = merge_organizers(listing.get("streams"))
    matches = {}
    for r in rows:
        m = norm_from_list(r, now)
        if not m or not m["id"]:
            continue
        if day_start <= m["start_unix"] < day_end:
            matches[m["id"]] = m
        elif m["status"] == "live" and look_back <= m["start_unix"] < day_start:
            matches[m["id"]] = m  # began late yesterday, still playing

    res = _browser.fetch("/results", ".result-con", JS_RESULTS)
    for r in res:
        m = norm_from_result(r)
        if not m or not m["id"]:
            continue
        if day_start <= m["start_unix"] < day_end:
            matches.setdefault(m["id"], m)

    # Detail pages are the expensive part — spend them where they add most:
    # live first, then finished (map scores), then the soonest upcoming (streams).
    rank = {"live": 0, "finished": 1, "upcoming": 2}
    ordered = sorted(matches.values(),
                     key=lambda m: (rank.get(m["status"], 3), -m["stars"], m["start_unix"]))
    for m in ordered[:DETAIL_CAP]:
        try:
            d = _browser.fetch(f"/matches/{m['id']}/x", ".mapholder, .teamName", JS_MATCH)
            apply_detail(m, d, organizers)
        except Challenged:
            raise
        except Exception as e:
            log(f"detail {m['id']} failed: {e}")

    ordered.sort(key=lambda m: (rank.get(m["status"], 3), m["start_unix"]))
    return {
        "date": date_str,
        "tz": tzname,
        "fetched_at": int(time.time()),
        "stale": False,
        "matches": ordered,
    }


ORGANIZERS_PATH = os.path.join(DATA_DIR, "organizers.json")


def load_organizers():
    """{normalized channel name: peak viewers seen}. Only ever grows: the sidebar
    lists organizers that are live *right now*, but an event's stream must be
    recognisable hours before it goes on air, so what we learn is kept."""
    try:
        with open(ORGANIZERS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def merge_organizers(sidebar):
    known = load_organizers()
    changed = False
    for s in sidebar or []:
        if (s.get("type") or "").upper() != "ORGANIZER":
            continue
        k = norm_key(s.get("title"))
        if not k:
            continue
        v = max(int(s.get("viewers") or 0), known.get(k, 0))
        if known.get(k) != v:
            known[k] = v
            changed = True
    if changed:
        try:
            tmp = ORGANIZERS_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(known, f)
            os.replace(tmp, ORGANIZERS_PATH)
        except OSError:
            pass
    return known


def lastgood_path(date_str):
    return os.path.join(DATA_DIR, f"lastgood-{date_str}.json")


def get_day(date_str, tzname, max_age=0):
    """Cached day payload. max_age>0 serves a recent scrape instead of re-fetching."""
    key = (date_str, tzname)
    hit = _day_cache.get(key)
    if hit and max_age and time.time() - hit["at"] <= max_age:
        return hit["payload"]
    try:
        payload = scrape(lambda: scrape_day(date_str, tzname))
    except Exception:
        # Serve the last good scrape of this day rather than nothing.
        try:
            with open(lastgood_path(date_str)) as f:
                old = json.load(f)
            old["stale"] = True
            return old
        except (OSError, ValueError):
            raise
    _day_cache[key] = {"at": time.time(), "payload": payload}
    try:
        tmp = lastgood_path(date_str) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, lastgood_path(date_str))
        prune_lastgood()
    except OSError:
        pass
    return payload


def prune_lastgood(keep=5):
    try:
        files = sorted(f for f in os.listdir(DATA_DIR) if f.startswith("lastgood-"))
        for f in files[:-keep]:
            os.remove(os.path.join(DATA_DIR, f))
    except OSError:
        pass


# ── VRS ───────────────────────────────────────────────────────────────────────
def scrape_vrs():
    """Valve Regional Standings as HLTV publishes them. This is the ranking that
    matters here — HLTV's own team ranking is deliberately never used."""
    d = _browser.fetch("/valve-ranking/teams", ".ranked-team", JS_VRS)
    teams = []
    for t in d.get("teams") or []:
        name = (t.get("name") or "").strip()
        if not name:
            continue
        pos = re.sub(r"\D", "", t.get("pos") or "")
        pts = re.sub(r"\D", "", t.get("points") or "")
        teams.append({"rank": int(pos) if pos else len(teams) + 1,
                      "name": name,
                      "points": int(pts) if pts else None})
    if not teams:
        raise RuntimeError("VRS page parsed to zero teams")
    m = re.search(r"on\s+(.+?)(?:\s*Beta)?$", (d.get("header") or "").replace("\n", " ").strip())
    return {"as_of": m.group(1).strip() if m else "", "teams": teams, "stale": False}


def get_vrs():
    try:
        with open(VRS_CACHE_PATH) as f:
            cache = json.load(f)
        if (time.time() - cache["fetched_at"]) / 3600 < VRS_CACHE_HOURS:
            return cache["vrs"]
    except (OSError, ValueError, KeyError):
        cache = None
    try:
        vrs = scrape(scrape_vrs)
    except Exception:
        if cache:
            stale = dict(cache["vrs"])
            stale["stale"] = True
            return stale
        raise
    try:
        tmp = VRS_CACHE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"fetched_at": time.time(), "vrs": vrs}, f)
        os.replace(tmp, VRS_CACHE_PATH)
    except OSError:
        pass
    return vrs


def selftest():
    """Do the selectors still match anything? The DOM-drift alarm."""
    counts = _browser.fetch("/matches", ".match", JS_SELFTEST)
    checks = {k: {"count": v, "ok": v > 0} for k, v in counts.items()}
    return {"ok": all(c["ok"] for c in checks.values()), "checks": checks}


# ── HTTP API ──────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass  # access logs are noise; we log what matters ourselves

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        one = lambda k, d=None: (q.get(k) or [d])[0]
        try:
            if u.path == "/health":
                return self._send(200, {"ok": True, **_state})
            if u.path == "/day":
                tzname = one("tz", "America/New_York")
                date_str = one("date") or datetime.now(ZoneInfo(tzname)).strftime("%Y-%m-%d")
                try:
                    max_age = int(one("max_age", "0"))
                except ValueError:
                    max_age = 0
                return self._send(200, in_browser(
                    lambda: get_day(date_str, tzname, max_age)))
            if u.path == "/vrs":
                return self._send(200, in_browser(get_vrs))
            if u.path == "/selftest":
                return self._send(200, in_browser(selftest))
            return self._send(404, {"error": "not found"})
        except Challenged as e:
            return self._send(503, {"error": str(e), "challenge": True})
        except Exception as e:
            return self._send(502, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="print a day payload and exit")
    ap.add_argument("--vrs", action="store_true", help="print VRS and exit")
    ap.add_argument("--selftest", action="store_true", help="print selector health and exit")
    ap.add_argument("--date")
    ap.add_argument("--tz", default="America/New_York")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        if args.selftest:
            print(json.dumps(selftest(), indent=2))
            return 0
        if args.vrs:
            print(json.dumps(get_vrs(), indent=2))
            return 0
        if args.once:
            date_str = args.date or datetime.now(ZoneInfo(args.tz)).strftime("%Y-%m-%d")
            print(json.dumps(get_day(date_str, args.tz), indent=2))
            return 0
    finally:
        if args.once or args.vrs or args.selftest:
            _browser.close()

    threading.Thread(target=_browser_worker, daemon=True).start()
    log(f"hltv-api listening on :{API_PORT}")
    ThreadingHTTPServer(("", API_PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
