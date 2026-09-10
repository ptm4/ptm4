"""Offline regression tests: no forecasts fetched and no Discord messages sent."""
import importlib.util
import json
from pathlib import Path
import uuid
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import weather_context as weather
import witty_messages as witty

spec = importlib.util.spec_from_file_location("bot", Path(__file__).with_name("discord-weather.py"))
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

NY = {"name": "Bellerose, NY", "lat": 40.73, "lon": -73.71}
NC = {"name": "Greensboro, NC", "lat": 36.07, "lon": -79.79}
NAMES = ["Matt", "Tom", "Anthony"]
START = datetime(2026, 9, 1, 7, tzinfo=ZoneInfo("America/New_York"))


def forecast(feels=78, code=0, **extra):
    return {"feels": feels, "code": code, "hi": feels, "lo": 60, "wind": 8,
            "rain": 10, "cond": bot.WMO_TEXT[code], "emoji": bot.WMO_EMOJI[code],
            "humidity": 60, "uv": 5, "sunrise": "6:00 AM", "sunset": "7:00 PM", **extra}


class WeatherTests(unittest.TestCase):
    def setUp(self):
        # Inherit the workspace ACL: Windows sandbox identities cannot re-open
        # tempfile's owner-only directories on some Python builds.
        folder = Path(__file__).resolve().parent / (".test-state-" + uuid.uuid4().hex)
        folder.mkdir()
        self.path = str(folder / "pool.json")
        def cleanup():
            for name in ("pool.json", "pool.json.tmp"):
                (folder / name).unlink(missing_ok=True)
            folder.rmdir()
        self.addCleanup(cleanup)
        self.pool = witty.WittyPool(self.path)

    def record(self, day, feels=105, loc=NC, **extra):
        context = self.pool.weather([(loc, forecast(feels, **extra))], day)
        self.pool.commit({"weather_snapshot": context["snapshot"]})
        return context

    def seed_fire(self, days=5):
        for i in range(days):
            self.record(START + timedelta(days=i))

    def test_fire_five_days_and_break_at_99(self):
        self.seed_fire(4)
        ctx = self.pool.weather([(NY, forecast()), (NC, forecast(105))], START + timedelta(days=4))
        self.assertEqual(ctx["event"]["kind"], "fire_streak")
        self.assertEqual(ctx["event"]["facts"]["days"], 5)
        self.assertEqual(ctx["event"]["facts"]["subject"], "Starks")
        entry = self.pool.peek(NAMES, event=ctx["event"])
        self.assertIn("5", entry["rendered"])
        self.assertIn("Starks", entry["rendered"])
        self.pool.commit(dict(entry, weather_snapshot=ctx["snapshot"]))
        ctx = self.pool.weather([(NC, forecast(99))], START + timedelta(days=5))
        self.assertEqual(ctx["event"]["kind"], "fire_break")
        self.assertEqual(ctx["event"]["facts"]["days"], 5)
        self.assertEqual(ctx["event"]["facts"]["gap"], "1")

    def test_badge_uses_raw_temperature_like_embed(self):
        self.assertEqual(bot.feels_emoji(99.6), "🥵")
        self.assertEqual(bot.feels_emoji(100), "🔥")
        self.seed_fire(3)
        ctx = self.pool.weather([(NC, forecast(99.6))], START + timedelta(days=3))
        self.assertEqual(ctx["event"]["kind"], "fire_break")
        self.assertEqual(ctx["event"]["facts"]["feels"], "99.6")
        self.assertEqual(ctx["event"]["facts"]["gap"], "0.4")

    def test_same_day_preview_and_restart_do_not_add_days(self):
        self.seed_fire(3)
        now = START + timedelta(days=3)
        for _ in range(3):
            ctx = self.pool.weather([(NC, forecast(105))], now)
            self.assertEqual(ctx["event"]["facts"]["days"], 4)
        entry = self.pool.peek(NAMES, event=ctx["event"])
        restarted = witty.WittyPool(self.path)
        self.assertEqual(entry, restarted.peek(NAMES, event=ctx["event"]))
        restarted.commit(dict(entry, weather_snapshot=ctx["snapshot"]))
        self.assertEqual(restarted.weather([(NC, forecast(105))], now)["event"]["facts"]["days"], 4)
        self.assertEqual(len(restarted._load()["weather_days"]), 4)

    def test_missing_day_or_failed_location_breaks_continuity(self):
        self.seed_fire(4)
        ctx = self.pool.weather([(NC, forecast(105))], START + timedelta(days=5))
        self.assertEqual(ctx["event"]["kind"], "fire")
        ctx = self.pool.weather([(NC, None), (NY, forecast())], START + timedelta(days=4))
        self.assertIsNone(ctx["event"])
        self.pool.commit({"weather_snapshot": ctx["snapshot"]})
        ctx = self.pool.weather([(NC, forecast(105))], START + timedelta(days=5))
        self.assertEqual(ctx["event"]["kind"], "fire")

    def test_location_rename_preserves_history_move_does_not(self):
        self.seed_fire(3)
        renamed = {**NC, "name": "My NC town", "witty_subject": "Starks"}
        ctx = self.pool.weather([(renamed, forecast(105))], START + timedelta(days=3))
        self.assertEqual(ctx["event"]["facts"]["days"], 4)
        ctx = self.pool.weather([({**renamed, "lat": 35}, forecast(105))], START + timedelta(days=3))
        self.assertEqual(ctx["event"]["kind"], "fire")

    def test_local_calendar_handles_dst_and_timezone_change(self):
        start = datetime(2026, 10, 30, 7, tzinfo=START.tzinfo)
        for i in range(3):
            self.record(start + timedelta(days=i))
        ctx = self.pool.weather([(NC, forecast(105))], start + timedelta(days=3))
        self.assertEqual(ctx["event"]["facts"]["days"], 4)
        ctx = self.pool.weather([(NC, forecast(105))], (start + timedelta(days=3)).astimezone(ZoneInfo("UTC")))
        self.assertEqual(ctx["event"]["kind"], "fire")

    def test_priority_and_nonfire_events(self):
        self.seed_fire(4)
        ctx = self.pool.weather([(NY, forecast(80, 95)), (NC, forecast(105))], START + timedelta(days=4))
        self.assertEqual(ctx["event"]["kind"], "storm")
        for expected, fc in [("snow", forecast(30, 73)), ("wind", forecast(78, wind=35)),
                             ("rain", forecast(75, 65)), ("cold", forecast(18))]:
            with self.subTest(expected=expected):
                ctx = weather.describe([], [(NY, fc)], START)
                self.assertEqual(ctx["event"]["kind"], expected)
        for expected, fc in [("rain_streak", forecast(70, 61)), ("snow_streak", forecast(30, 73)),
                             ("cold_streak", forecast(18)), ("hot_streak", forecast(95))]:
            history = []
            for i in range(3):
                ctx = weather.describe(history, [(NY, fc)], START + timedelta(days=i))
                history.append(ctx["snapshot"])
            self.assertEqual(ctx["event"]["kind"], expected)

    def test_ordinary_forecast_has_no_event(self):
        ctx = self.pool.weather([(NY, forecast()), (NC, forecast(85))], START)
        self.assertIsNone(ctx["event"])

    def test_event_reroll_preserves_topic_and_does_not_consume(self):
        self.seed_fire(3)
        ctx = self.pool.weather([(NC, forecast(105))], START + timedelta(days=3))
        entry = self.pool.peek(NAMES, event=ctx["event"])
        out = self.pool.reroll(NAMES, event=ctx["event"])
        self.assertEqual(out["skipped"], entry["rendered"])
        self.assertNotEqual(out["skipped"], out["next"])
        self.assertEqual(self.pool._load()["history"], [])
        self.assertEqual(self.pool.peek(NAMES, event=ctx["event"])["rendered"], out["next"])
        self.assertEqual(len(self.pool._load()["weather_days"]), 3)

    def test_event_variants_exhaust_before_repeating(self):
        ctx = self.pool.weather([(NC, forecast(105))], START)
        seen = []
        for _ in weather.EVENT_LINES["fire"]:
            entry = self.pool.peek(NAMES, event=ctx["event"])
            self.assertNotIn(entry["t"], seen)
            seen.append(entry["t"])
            self.pool.commit(entry)
        self.assertEqual(self.pool.peek(NAMES, event=ctx["event"])["t"], seen[0])

    def test_generic_cooldown_across_cycles_names_and_restarts(self):
        seen = []
        for i in range(300):
            if i == 120:
                self.pool = witty.WittyPool(self.path)
            entry = self.pool.peek(NAMES if i < 200 else NAMES + ["Joe"])
            self.assertNotIn(entry["t"], seen[-45:])
            seen.append(entry["t"])
            self.assertTrue(self.pool.commit(entry))
            self.assertFalse(self.pool.commit(entry))

    def test_empty_names_still_get_nameless_bits(self):
        entry = self.pool.peek([])
        self.assertTrue(entry["rendered"])
        self.assertNotIn("{name", entry["rendered"])

    def test_upgrade_drops_old_recipes_preserves_history_and_weather(self):
        self.seed_fire(3)
        state = self.pool._load()
        state.update(version=4, pending=[{"id": 1, "t": "a01"}], next_id=2,
                     history=[["a01", "Matt"]], last_posted={"text": "old line"})
        self.pool._save(state)
        entry = self.pool.peek(NAMES)
        self.assertTrue(entry["t"].startswith("v5_"))
        self.assertEqual(len(self.pool._load()["weather_days"]), 3)
        self.assertEqual(self.pool._load()["last_posted"]["text"], "old line")

    def test_every_template_renders_and_fits(self):
        for tpl in witty.TEMPLATES:
            line = witty._demo_render(tpl, NAMES)
            self.assertLess(len(line), 400)
            self.assertNotIn("{", line)
        facts = dict(subject="Starks", location="Greensboro, NC", badge="🔥", feels="105",
                     days=5, wind=35, gap="1", change=25, direction="down", warm="NC", cool="NY", spread=30)
        for lines in weather.EVENT_LINES.values():
            for line in lines:
                rendered = line.format(**facts)
                self.assertLess(len(rendered), 400)
                self.assertNotIn("{", rendered)

    def config(self, **extra):
        return {**bot.DEFAULT_CONFIG, "locations": [NY, NC], "witty_names": NAMES,
                "webhook_url": "https://discord.com/api/webhooks/offline-test", **extra}

    def test_payload_prioritizes_nc_even_if_first_town_fails(self):
        with patch.object(bot, "_witty", self.pool), patch.object(bot, "fetch_forecast", side_effect=[RuntimeError("offline"), forecast(105)]):
            payload, failed, receipt = bot.build_payload(self.config())
        self.assertIn("Starks", payload["content"])
        self.assertIn("🔥", payload["content"])
        self.assertEqual(failed, [NY["name"]])
        self.assertEqual(json.loads(receipt["signature"])["kind"], "fire")
        self.assertEqual(self.pool._load()["weather_days"], [])

    def test_failed_webhook_retry_preserves_joke_and_counts(self):
        with patch.object(bot, "_witty", self.pool), patch.object(bot, "fetch_forecast", return_value=forecast(105)), patch.object(bot, "post_webhook", side_effect=[RuntimeError("offline"), None]) as post:
            ok, _ = bot.post_report(self.config())
            self.assertFalse(ok)
            self.assertEqual(self.pool._load()["weather_days"], [])
            self.assertEqual(self.pool._load()["history"], [])
            ok, _ = bot.post_report(self.config())
            self.assertTrue(ok)
        self.assertEqual(post.call_args_list[0].args[1], post.call_args_list[1].args[1])
        self.assertEqual(len(self.pool._load()["weather_days"]), 1)
        self.assertEqual(len(self.pool._load()["history"]), 1)

    def test_disabled_or_overlong_joke_still_records_weather(self):
        for cfg in [self.config(witty_enabled=False), self.config(message="x" * 2000)]:
            with patch.object(bot, "_witty", self.pool), patch.object(bot, "fetch_forecast", return_value=forecast(105)), patch.object(bot, "post_webhook") as post:
                ok, _ = bot.post_report(cfg)
                self.assertTrue(ok)
                self.assertEqual(post.call_args.args[1]["content"], cfg["message"])
            self.assertEqual(len(self.pool._load()["weather_days"]), 1)
            self.assertEqual(self.pool._load().get("history", []), [])


if __name__ == "__main__":
    unittest.main()
