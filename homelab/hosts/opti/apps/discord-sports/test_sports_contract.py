"""Contract test for discord-sports' control API.

Pins what the dashboards and homelab-db rely on: the /health keys, /config masking,
PUT /config error strings, /preview and /send shapes, /teams, and 404s. It talks to
the bot only over HTTP and fakes the network at urllib.request.urlopen, so it holds
for any implementation of the bot (it was written against the pre-_botkit copy and
passed there before the bot moved onto _botkit).

    python3 -m unittest -v test_sports_contract.py          # from this folder
    SPORTS_BOT_FILE=/path/to/other/discord-sports.py ...    # same test, other copy
"""
import importlib.util
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest import mock
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
BOT_FILE = os.environ.get("SPORTS_BOT_FILE") or os.path.join(HERE, "discord-sports.py")
WEBHOOK = "https://discord.com/api/webhooks/123456/secretTOKENabc123"
TZ = "America/New_York"
_real_urlopen = urllib.request.urlopen


def _event(state, date="2026-11-09T00:30Z", our_score="110", their_score="100"):
    return {"date": date, "competitions": [{
        "status": {"type": {"state": state, "shortDetail": "Final" if state == "post" else ""}},
        "competitors": [
            {"team": {"id": "18", "abbreviation": "NY"}, "homeAway": "home",
             "score": our_score, "winner": state == "post"},
            {"team": {"id": "2", "abbreviation": "BOS"}, "homeAway": "away",
             "score": their_score, "winner": False},
        ]}]}


class _Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeNet:
    """Answers ESPN and Discord; passes 127.0.0.1 (the bot under test) through."""

    def __init__(self):
        self.posts = []

    def __call__(self, req, timeout=None, **kw):
        url = req.full_url if isinstance(req, urllib.request.Request) else req
        if url.startswith("http://127.0.0.1"):
            return _real_urlopen(req, timeout=timeout)
        if url.startswith("https://discord.com/api/webhooks/"):
            self.posts.append({"url": url, "ua": req.get_header("User-agent"),
                               "body": json.loads(req.data)})
            return _Resp(204, b"")
        if "/scoreboard?dates=" in url:
            today = datetime.now(ZoneInfo(TZ)).strftime("%Y%m%d")
            ev = (_event("pre", date="2026-11-10T00:30Z") if url.endswith(today)
                  else _event("post"))
            return _Resp(200, json.dumps({"events": [ev]}).encode())
        if url.endswith("/basketball/nba/teams"):
            teams = [{"team": {"id": "18", "abbreviation": "NY", "displayName": "New York Knicks"}},
                     {"team": {"id": "2", "abbreviation": "BOS", "displayName": "Boston Celtics"}}]
            return _Resp(200, json.dumps({"sports": [{"leagues": [{"teams": teams}]}]}).encode())
        raise AssertionError(f"unexpected network call: {url}")


class SportsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sports-contract-")
        cls.env = mock.patch.dict(os.environ, {"DATA_DIR": cls.tmp})
        cls.env.start()
        os.environ.pop("DISCORD_WEBHOOK_URL_SPORTS", None)
        cls.net = FakeNet()
        cls.patches = [mock.patch("urllib.request.urlopen", cls.net),
                       mock.patch("time.sleep", lambda s: None)]
        for p in cls.patches:
            p.start()
        spec = importlib.util.spec_from_file_location("discord_sports_under_test", BOT_FILE)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
        cls.mod.log = lambda msg: None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), cls.mod.Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for p in cls.patches:
            p.stop()
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with _real_urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    # ── first boot ────────────────────────────────────────────────────────────
    def test_01_health_shape(self):
        code, h = self.call("GET", "/health")
        self.assertEqual(code, 200)
        self.assertEqual(list(h), ["ok", "enabled", "post_time", "timezone",
                                   "last_post_at", "last_status", "next_post_at"])
        self.assertEqual((h["ok"], h["enabled"], h["post_time"], h["timezone"]),
                         (True, True, "09:30", TZ))
        self.assertIsNone(h["last_status"])

    def test_02_config_seeded(self):
        code, c = self.call("GET", "/config")
        self.assertEqual(code, 200)
        self.assertEqual(list(c), ["enabled", "post_time", "timezone", "message",
                                   "webhook_url", "teams", "webhook_configured"])
        self.assertEqual(c["webhook_url"], "")
        self.assertFalse(c["webhook_configured"])
        self.assertEqual(c["teams"], [{"league": "nba", "sport": "basketball", "id": "18",
                                       "abbrev": "NY", "name": "New York Knicks"}])
        with open(os.path.join(self.tmp, "config.json")) as f:
            self.assertEqual(json.load(f)["post_time"], "09:30")

    def test_03_send_without_webhook(self):
        code, r = self.call("POST", "/send")
        self.assertEqual((code, r), (502, {"ok": False,
                                           "detail": "DISCORD_WEBHOOK_URL_SPORTS / webhook_url not set"}))
        _, h = self.call("GET", "/health")
        self.assertEqual(h["last_status"],
                         "manual failed: DISCORD_WEBHOOK_URL_SPORTS / webhook_url not set")

    # ── PUT /config validation (the dashboard shows these strings verbatim) ──
    def test_04_put_errors(self):
        cases = [
            ({"enabled": "yes"}, "enabled must be true/false"),
            ({"post_time": "25:00"}, "post_time must be HH:MM (24h)"),
            ({"message": "x" * 2001}, "message must be text, max 2000 characters"),
            ({"timezone": "Mars/Base"}, "unknown timezone 'Mars/Base'"),
            ({"teams": "knicks"}, "teams must be a list"),
            ({"teams": [{"league": "nfl", "id": "1", "name": "x"}]},
             "each team needs league (nba), id, name"),
            ({"webhook_url": "https://example.com/hook"},
             "webhook_url must start with https://discord.com/api/webhooks/"),
        ]
        for body, err in cases:
            with self.subTest(body=list(body)):
                self.assertEqual(self.call("PUT", "/config", body), (400, {"error": err}))
        self.assertEqual(self.call("PUT", "/config", raw=b"{not json"),
                         (400, {"error": "invalid JSON"}))

    def test_05_put_ok_masks_and_keeps(self):
        code, c = self.call("PUT", "/config", {"webhook_url": WEBHOOK, "message": "hi",
                                               "post_time": "10:15", "evil": 1})
        self.assertEqual(code, 200)
        self.assertEqual(c["webhook_url"], "https://discord.com/api/webhooks/…abc123")
        self.assertTrue(c["webhook_configured"])
        self.assertNotIn("evil", c)
        self.assertEqual((c["message"], c["post_time"]), ("hi", "10:15"))
        # masked (or blank) webhook in a later PUT means "keep the current one"
        code, c = self.call("PUT", "/config", {"webhook_url": c["webhook_url"], "message": ""})
        self.assertEqual(code, 200)
        with open(os.path.join(self.tmp, "config.json")) as f:
            stored = json.load(f)
        self.assertEqual(stored["webhook_url"], WEBHOOK)
        self.assertEqual(stored["message"], "")
        _, h = self.call("GET", "/health")
        self.assertEqual(h["post_time"], "10:15")

    # ── preview / send / teams ────────────────────────────────────────────────
    def test_06_preview(self):
        code, p = self.call("GET", "/preview")
        self.assertEqual(code, 200)
        self.assertEqual(list(p), ["payload", "failed"])
        self.assertEqual(p["failed"], [])
        pl = p["payload"]
        self.assertEqual(pl["username"], "Daily Sports Report")
        self.assertNotIn("content", pl)
        emb = pl["embeds"][0]
        self.assertEqual((emb["title"], emb["color"], emb["footer"]),
                         ("🏟️ Scores & Schedule", 0xE67E22, {"text": "ESPN"}))
        self.assertEqual(emb["fields"][0]["name"], "🏀 NY")
        self.assertEqual(emb["fields"][0]["value"].split("\n")[0],
                         "yesterday: **W 110–100** vs BOS")
        self.assertTrue(emb["fields"][0]["value"].split("\n")[1].startswith("today: "))
        self.assertEqual(len(emb["fields"]), 3)  # one team + two spacers

    def test_07_send_posts_preview_payload(self):
        _, p = self.call("GET", "/preview")
        self.net.posts.clear()
        code, r = self.call("POST", "/send")
        self.assertEqual((code, r), (200, {"ok": True, "detail": "posted"}))
        self.assertEqual(len(self.net.posts), 1)
        post = self.net.posts[0]
        self.assertEqual(post["url"], WEBHOOK)
        self.assertEqual(post["ua"], "discord-sports (rpi homelab)")
        self.assertEqual(post["body"], p["payload"])
        _, h = self.call("GET", "/health")
        self.assertEqual(h["last_status"], "manual: posted")
        self.assertTrue(h["last_post_at"])

    def test_08_teams(self):
        self.assertEqual(self.call("GET", "/teams?q=knicks"),
                         (400, {"error": "league must be one of nba"}))
        self.assertEqual(self.call("GET", "/teams?league=nba"),
                         (400, {"error": "missing ?q="}))
        code, r = self.call("GET", "/teams?league=NBA&q=bos")
        self.assertEqual((code, r), (200, {"results": [{
            "league": "nba", "sport": "basketball", "id": "2",
            "abbrev": "BOS", "name": "Boston Celtics"}]}))

    def test_09_not_found(self):
        for method in ("GET", "PUT", "POST"):
            with self.subTest(method=method):
                self.assertEqual(self.call(method, "/nope", {} if method != "GET" else None),
                                 (404, {"error": "not found"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
