"""Unit tests for _botkit.   python3 -m unittest -v test_botkit.py   (from this folder)"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _botkit import Bot, ConfigStore, http_json, mask_webhook, post_webhook  # noqa: E402
from _botkit import scheduler as sched  # noqa: E402

TZ = ZoneInfo("America/New_York")
WEBHOOK = "https://discord.com/api/webhooks/1/abcdefXYZ789"
DEFAULTS = {"enabled": True, "post_time": "09:00", "timezone": "America/New_York",
            "message": "", "webhook_url": "", "api_key": "", "max_items": 5}


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class TmpDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="botkit-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        env = mock.patch.dict(os.environ, {"HOOK": WEBHOOK, "KEY": "k-123"})
        env.start()
        self.addCleanup(env.stop)

    def store(self, **kw):
        kw.setdefault("env", {"webhook_url": "HOOK", "api_key": "KEY"})
        kw.setdefault("secret_fields", ("api_key",))
        kw.setdefault("extra_keys", ("max_items",))
        return ConfigStore(self.dir, DEFAULTS, **kw)


class ConfigStoreTest(TmpDir):
    def test_first_boot_seeds_from_env(self):
        with quiet():
            cfg = self.store().load()
        self.assertEqual((cfg["webhook_url"], cfg["api_key"]), (WEBHOOK, "k-123"))
        with open(os.path.join(self.dir, "config.json")) as f:
            self.assertEqual(json.load(f)["api_key"], "k-123")

    def test_env_fills_blank_and_new_keys_get_defaults(self):
        with open(os.path.join(self.dir, "config.json"), "w") as f:
            json.dump({"enabled": False, "post_time": "07:00", "webhook_url": ""}, f)
        cfg = self.store().load()
        self.assertEqual(cfg["webhook_url"], WEBHOOK)
        self.assertEqual((cfg["enabled"], cfg["post_time"], cfg["max_items"]), (False, "07:00", 5))

    def test_fallback(self):
        self.assertEqual(self.store().fallback()["api_key"], "k-123")

    def test_validate_order_and_strings(self):
        st = self.store(validate_extra=lambda c: None if c.get("max_items") == 5 else "max_items bad")
        ok = dict(DEFAULTS)
        self.assertIsNone(st.validate(ok))
        self.assertEqual(st.validate([]), "config must be an object")
        # common checks win over the bot's own; the webhook is checked last
        self.assertEqual(st.validate({**ok, "post_time": "9:00", "max_items": 0}),
                         "post_time must be HH:MM (24h)")
        self.assertEqual(st.validate({**ok, "max_items": 0, "webhook_url": "http://x"}), "max_items bad")
        self.assertEqual(st.validate({**ok, "webhook_url": "http://x"}),
                         "webhook_url must start with https://discord.com/api/webhooks/")
        self.assertEqual(st.validate({**ok, "timezone": "Nope/Zone"}), "unknown timezone 'Nope/Zone'")

    def test_public_masks_and_merge_keeps_secrets(self):
        st = self.store()
        cur = {**DEFAULTS, "webhook_url": WEBHOOK, "api_key": "k-123"}
        pub = st.public(cur)
        self.assertEqual(pub["webhook_url"], mask_webhook(WEBHOOK))
        self.assertEqual(pub["webhook_url"], "https://discord.com/api/webhooks/…XYZ789")
        self.assertEqual((pub["webhook_configured"], pub["api_key"], pub["api_key_configured"]),
                         (True, "", True))
        merged = st.merge(cur, {"webhook_url": pub["webhook_url"], "api_key": "",
                                "max_items": 9, "rogue": 1})
        self.assertEqual((merged["webhook_url"], merged["api_key"], merged["max_items"]),
                         (WEBHOOK, "k-123", 9))
        self.assertNotIn("rogue", merged)
        self.assertEqual(st.merge(cur, {"api_key": "new"})["api_key"], "new")


class _Resp:
    def __init__(self, status, body=b""):
        self.status, self.body = status, body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class NetTest(unittest.TestCase):
    def test_ua_only_when_asked(self):
        seen = []

        def fake(req, timeout=None):
            seen.append(req)
            return _Resp(200, b'{"a": 1}')
        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(http_json("https://x/y"), (200, {"a": 1}))
            http_json("https://x/y", body={"b": 2}, ua="bot (homelab)", headers={"X-T": "1"})
        self.assertIsNone(seen[0].get_header("User-agent"))
        self.assertIsNone(seen[0].data)
        self.assertEqual(seen[1].get_header("User-agent"), "bot (homelab)")
        self.assertEqual(seen[1].get_header("X-t"), "1")
        self.assertEqual(json.loads(seen[1].data), {"b": 2})

    def test_retries_then_raises(self):
        calls = []

        def boom(req, timeout=None):
            calls.append(timeout)
            raise OSError("down")
        with mock.patch("urllib.request.urlopen", boom), mock.patch("time.sleep") as sl:
            with self.assertRaises(RuntimeError) as cm:
                http_json("https://x/y?secret=1", tries=3, timeout=7)
        self.assertEqual(str(cm.exception), "https://x/y failed: down")
        self.assertEqual((calls, sl.call_count), ([7, 7, 7], 2))

    def test_post_webhook_status(self):
        with mock.patch("urllib.request.urlopen", lambda r, timeout=None: _Resp(204)):
            post_webhook(WEBHOOK, {"content": "x"})
        with mock.patch("urllib.request.urlopen", lambda r, timeout=None: _Resp(302)):
            with self.assertRaisesRegex(RuntimeError, "webhook returned HTTP 302"):
                post_webhook(WEBHOOK, {"content": "x"})


class FakeClock:
    def __init__(self, start):
        self.t = start

    def __call__(self, tz):
        return self.t.astimezone(tz)


class FakeWake:
    """wait() advances the clock by the timeout instead of sleeping."""

    def __init__(self, clock, set_on_wait=False):
        self.clock, self.waits, self.set_on_wait = clock, [], set_on_wait

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.set_on_wait:
            return True
        self.clock.t += timedelta(seconds=timeout)
        return False

    def clear(self):
        pass


class SchedulerTest(TmpDir):
    def make(self, start, results=None, enabled=True, set_on_wait=False):
        st = self.store()
        with quiet():
            st.save({**st.load(), "enabled": enabled})
        clock = FakeClock(start)
        wake = FakeWake(clock, set_on_wait)
        self.posts = []
        results = list(results or [])

        def post(cfg):
            self.posts.append(clock.t)
            return results.pop(0) if results else (True, "posted")
        s = sched.DailyScheduler(st, post, {"last_post_at": None, "last_status": None,
                                            "next_post_at": None}, threading.Lock(), wake,
                                 os.path.join(self.dir, "last_post"), clock=clock)
        return s, clock, wake

    def step(self, s, n=1):
        with quiet():
            for _ in range(n):
                s.step()

    def test_waits_for_slot_then_posts_and_stamps(self):
        s, clock, wake = self.make(datetime(2026, 11, 9, 8, 0, tzinfo=TZ))
        self.step(s)
        self.assertEqual(s.status["next_post_at"], "2026-11-09T09:00:00-05:00")
        self.assertEqual(wake.waits, [3600])
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(s.read_last_post(), "2026-11-09")
        self.assertEqual(s.status["last_status"], "posted")
        self.step(s)  # stamped: next is tomorrow, capped at an hour of sleep
        self.assertEqual(s.status["next_post_at"], "2026-11-10T09:00:00-05:00")
        self.assertEqual(len(self.posts), 1)

    def test_catch_up_after_restart(self):
        s, clock, wake = self.make(datetime(2026, 11, 9, 14, 0, tzinfo=TZ))
        self.step(s)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(wake.waits, [])
        self.assertEqual(s.read_last_post(), "2026-11-09")

    def test_failure_retries_every_15_minutes(self):
        s, clock, wake = self.make(datetime(2026, 11, 9, 9, 0, tzinfo=TZ),
                                   results=[(False, "boom"), (True, "posted")])
        self.step(s)
        self.assertEqual(s.status["last_status"], "failed: boom")
        self.assertEqual(s.read_last_post(), "")
        clock.t += timedelta(minutes=5)
        self.step(s)  # paced: waits the remaining 10 min, no post
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(wake.waits, [600])
        self.assertEqual(s.status["next_post_at"], "2026-11-09T09:15:00-05:00")
        self.step(s)  # 15 min after the failure: retry lands
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(s.read_last_post(), "2026-11-09")

    def test_disabled_idles(self):
        s, clock, wake = self.make(datetime(2026, 11, 9, 14, 0, tzinfo=TZ), enabled=False)
        self.step(s)
        self.assertEqual((self.posts, wake.waits, s.status["next_post_at"]), ([], [3600], None))

    def test_config_change_recomputes_without_posting(self):
        s, clock, wake = self.make(datetime(2026, 11, 9, 8, 59, tzinfo=TZ), set_on_wait=True)
        self.step(s)
        self.assertEqual((self.posts, wake.waits), ([], [60]))

    def test_next_post_dt_across_dst(self):
        # 2026-11-01 is the US fall-back day; the slot stays at local wall-clock 09:00,
        # now in EST (the day before it was EDT)
        now = datetime(2026, 10, 31, 10, 0, tzinfo=TZ)
        self.assertEqual(sched.next_post_dt({"post_time": "09:00"}, now).isoformat(),
                         "2026-11-01T09:00:00-05:00")


class ApiTest(TmpDir):
    """Kit-level API behaviour; discord-sports/test_sports_contract.py pins a real bot."""

    def setUp(self):
        super().setUp()
        self.sent = []
        self.bot = Bot(
            name="t", defaults=DEFAULTS, data_dir=self.dir,
            env={"webhook_url": "HOOK", "api_key": "KEY"}, secret_fields=("api_key",),
            extra_keys=("max_items",),
            validate=lambda c: None if isinstance(c.get("max_items"), int) else "max_items must be a number",
            post_report=lambda cfg, force=False: (self.sent.append(force) or True, "posted"),
            preview=lambda cfg: {"payload": {"content": "hi"}, "failed": [], "has_items": True},
            routes={"/check": lambda cfg, q: (200, {"q": q})},
            health_extra=lambda cfg: {"extra": 1})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.bot.Handler)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with quiet(), urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_routes(self):
        code, h = self.call("GET", "/health")
        self.assertEqual(list(h), ["ok", "enabled", "post_time", "timezone", "extra",
                                   "last_post_at", "last_status", "next_post_at"])
        code, c = self.call("GET", "/config")
        self.assertEqual((c["api_key"], c["api_key_configured"], c["webhook_configured"]), ("", True, True))
        self.assertEqual(self.call("GET", "/check?a=1"), (200, {"q": "a=1"}))
        self.assertEqual(self.call("GET", "/preview")[1]["has_items"], True)
        self.assertEqual(self.call("PUT", "/config", {"max_items": "x"}),
                         (400, {"error": "max_items must be a number"}))
        code, c = self.call("PUT", "/config", {"max_items": 3, "api_key": ""})
        self.assertEqual((code, c["max_items"], c["api_key_configured"]), (200, 3, True))
        self.assertTrue(self.bot.wake.is_set())
        self.assertEqual(self.call("POST", "/send"), (200, {"ok": True, "detail": "posted"}))
        self.assertEqual(self.sent, [True])  # Send now is always forced
        self.assertEqual(self.call("GET", "/health")[1]["last_status"], "manual: posted")
        self.assertEqual(self.call("POST", "/nope"), (404, {"error": "not found"}))

    def test_dry_run(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(self.bot.main(["--dry-run"]), 0)
        printed = out.getvalue()  # a first-boot "seeded" log line may come first
        self.assertEqual(json.loads(printed[printed.index("{"):]), {"content": "hi"})
        self.assertIn("has_items: True", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
