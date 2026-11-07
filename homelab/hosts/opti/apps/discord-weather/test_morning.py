"""Offline tests for the model-written morning line: the chat delta read over
Discord REST (stubbed), its cursor, the day's draft, and the post receipt.
No forecasts fetched, no Discord or Anthropic calls."""
import importlib.util
import json
import uuid
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import model_reply as mr
import witty_messages as witty

spec = importlib.util.spec_from_file_location("bot", Path(__file__).with_name("discord-weather.py"))
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

NY = {"name": "Bellerose, NY", "lat": 40.73, "lon": -73.71}
PERSONA = {"pings": {"@tomboe": "2", "@antwah": "3"}, "word_banks": {"me": ["WB"]}, "brief": "You are WB."}
BOT_ID = "900"


def forecast(feels=78, code=0):
    return {"feels": feels, "code": code, "hi": feels, "lo": 60, "wind": 8, "rain": 10,
            "cond": bot.WMO_TEXT[code], "emoji": bot.WMO_EMOJI[code], "humidity": 60, "uv": 5,
            "sunrise": "6:00 AM", "sunset": "7:00 PM"}


def msg(mid, author="2", text="hi", name="Tom"):
    return {"id": str(mid), "content": text, "embeds": [],
            "author": {"id": author, "global_name": name, "username": name.lower()}}


class FakeDiscord:
    """GET /channels/<id>/messages with limit/before, newest first like Discord."""
    def __init__(self, channels):
        self.channels = channels   # id -> list of messages
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        if path == "/users/@me":
            return {"id": BOT_ID}
        ch, _, qs = path.split("/")[2], None, path.partition("?")[2]
        q = dict(p.split("=") for p in qs.split("&") if p)
        msgs = sorted(self.channels.get(ch, []), key=lambda m: int(m["id"]), reverse=True)
        if "before" in q:
            msgs = [m for m in msgs if int(m["id"]) < int(q["before"])]
        return msgs[:int(q.get("limit", 50))]


class MorningTests(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).resolve().parent / (".test-state-" + uuid.uuid4().hex)
        folder.mkdir()
        self.folder = folder
        self.patches = [patch.object(bot, "CHAT_CURSOR_PATH", str(folder / "cursor.json")),
                        patch.object(bot, "MORNING_DRAFT_PATH", str(folder / "draft.json")),
                        patch.object(bot, "MORNING_LOG_PATH", str(folder / "mornings.jsonl")),
                        patch.object(bot, "BOT_TOKEN", "tok"),
                        patch.object(mr, "USAGE_PATH", str(folder / "usage.json")),
                        patch.object(mr, "KEY_PATH", str(folder / "key")),
                        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}),
                        patch.object(mr, "anthropic", object())]
        for p in self.patches:
            p.start()
        bot._self_id.clear()
        witty.use_persona(PERSONA)
        self.pool = witty.WittyPool(str(folder / "pool.json"))

        def cleanup():
            for p in self.patches:
                p.stop()
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()
            witty.use_persona(None)
            bot._self_id.clear()
        self.addCleanup(cleanup)

    def cfg(self, morning=True, **extra):
        return {**bot.DEFAULT_CONFIG, "locations": [NY], "witty_names": ["Tom"], "guild_id": "1",
                "channel_id": "10", "timezone": "America/New_York", "message": "@everyone",
                "claude": {**mr.DEFAULTS, "enabled": True, "morning": morning}, **extra}

    def test_snowflake_and_channels(self):
        self.assertEqual(bot.snowflake_at(1420070400), "0")
        self.assertEqual(bot.snowflake_at(1420070401), str(1000 << 22))
        self.assertEqual(bot.morning_channels({"channel_id": "10", "reply_channels": ["11", "10", "x"]}),
                         ["10", "11"])

    def test_fetch_since_pages_back_to_the_cursor_and_keeps_the_newest(self):
        fake = FakeDiscord({"10": [msg(i) for i in range(1, 251)]})
        with patch.object(bot, "_discord_get", fake):
            got = bot.fetch_since("10", "100", 500)
        self.assertEqual([int(m["id"]) for m in got], list(range(101, 251)))   # oldest first
        self.assertEqual(len(fake.calls), 2)                                    # stopped at the cursor
        with patch.object(bot, "_discord_get", FakeDiscord({"10": [msg(i) for i in range(1, 251)]})):
            got = bot.fetch_since("10", "0", 60)
        self.assertEqual([int(m["id"]) for m in got], list(range(191, 251)))   # a busy night keeps its end

    def test_chat_delta_reads_since_cursor_labels_handles_and_skips_blanks(self):
        bot.write_json(bot.CHAT_CURSOR_PATH, {"10": "5", "11": "0"})
        fake = FakeDiscord({"10": [msg(4, text="old"), msg(6, text="rate the rain <@3>"),
                                   msg(7, author=BOT_ID, text="Statement: no.", name="Weather-Bot"),
                                   msg(8, author="77", text="", name="Guest")],
                            "11": [msg(9, author="3", text="lol", name="Ant")]})
        with patch.object(bot, "_discord_get", fake), \
                patch.dict(bot._channels, {"names": {"10": "weather", "11": "gamers"}}):
            lines, newest = bot.chat_delta(self.cfg(reply_channels=["11"]), 150, now=1_800_000_000)
        # several channels: each line says where it was said, so the model keeps conversations apart
        self.assertEqual(lines, ["[#weather] @tomboe: rate the rain @antwah", "[#weather] WB: Statement: no.",
                                 "[#gamers] @antwah: lol"])
        self.assertEqual(bot.channel_tag("123456789"), "[#channel-6789] ")
        self.assertEqual(newest, {"10": "8", "11": "9"})   # the blank one still moves the cursor

    def test_morning_line_writes_a_draft_and_reuses_it_on_retry(self):
        seen = {}

        def fake_ask(cfg, system, user, log=print, **over):
            seen.update(system=system, user=user, over=over)
            return '"Statement: @tomboe rated the rain 2/10. Today it rains harder."'
        obs = [(NY, forecast(61, 61))]
        with patch.object(bot, "chat_delta", return_value=(["@tomboe: rain 2/10"], {"10": "8"})), \
                patch.object(mr, "ask", side_effect=fake_ask) as ask:
            line, cursors = bot.morning_line(self.cfg(), obs, {"event": None}, "2026-11-02")
            again = bot.morning_line(self.cfg(), obs, {"event": None}, "2026-11-02")
        self.assertEqual(line, "Statement: <@2> rated the rain 2/10. Today it rains harder.")
        self.assertEqual(cursors, {"10": "8"})
        self.assertEqual(again, (line, cursors))
        self.assertEqual(ask.call_count, 1)                                     # retry reused the draft
        self.assertIn("@tomboe: rain 2/10", seen["user"])
        self.assertIn("Bellerose: high 61°F", seen["user"])
        self.assertIn("light rain", seen["user"])
        self.assertIn("You are WB.", seen["system"])
        self.assertEqual(seen["over"]["effort"], "medium")

    def test_morning_line_off_failed_or_spent_falls_back(self):
        obs = [(NY, forecast())]
        with patch.object(mr, "ask") as ask:
            self.assertEqual(bot.morning_line(self.cfg(morning=False), obs, None, "d"), (None, None))
            ask.assert_not_called()
        with patch.object(bot, "chat_delta", side_effect=RuntimeError("discord down")), \
                patch.object(mr, "ask", return_value=None):
            self.assertEqual(bot.morning_line(self.cfg(), obs, None, "d"), (None, None))
        self.assertFalse(Path(bot.MORNING_DRAFT_PATH).exists())
        with patch.object(mr, "spent", return_value="credit"), patch.object(mr, "ask") as ask:
            self.assertEqual(bot.morning_line(self.cfg(), obs, None, "d2"), (None, None))
            ask.assert_not_called()

    def test_post_uses_model_line_keeps_template_and_advances_cursor_only_when_posted(self):
        cfg = self.cfg()
        with patch.object(bot, "_witty", self.pool), patch.object(bot, "fetch_forecast", return_value=forecast()), \
                patch.object(bot, "chat_delta", return_value=(["@antwah: hi"], {"10": "42"})), \
                patch.object(mr, "ask", return_value="Statement: @antwah said hi. Weather: fine."):
            preview, _, receipt = bot.build_payload(cfg)                     # previews never ask
            self.assertNotIn("model_morning", receipt or {})
            with patch.object(bot, "post_channel", side_effect=RuntimeError("Discord returned HTTP 500")):
                self.assertFalse(bot.post_report(cfg)[0])
            self.assertEqual(bot.read_json(bot.CHAT_CURSOR_PATH, {}), {})   # failed post: cursor unmoved
            with patch.object(bot, "post_channel") as post:
                self.assertTrue(bot.post_report(cfg)[0])
        content = post.call_args.args[1]["content"]
        self.assertEqual(content, "@everyone Statement: <@3> said hi. Weather: fine.")
        self.assertEqual(bot.read_json(bot.CHAT_CURSOR_PATH, {}), {"10": "42"})
        self.assertFalse(Path(bot.MORNING_DRAFT_PATH).exists())
        log = bot.read_jsonl(bot.MORNING_LOG_PATH)
        self.assertEqual(log[-1]["line"], "Statement: <@3> said hi. Weather: fine.")
        self.assertEqual(self.pool._load().get("history", []), [])          # template joke not consumed
        self.assertEqual(len(self.pool._load()["weather_days"]), 1)         # weather still recorded

    def test_recent_morning_lines_feed_the_next_prompt(self):
        for i in range(3):
            bot.commit_morning({"date": f"2026-11-0{i + 1}", "line": f"line {i}", "cursors": {"10": str(i)}})
        self.assertEqual(bot.read_json(bot.CHAT_CURSOR_PATH, {}), {"10": "2"})
        seen = {}
        with patch.object(bot, "chat_delta", return_value=([], {})), \
                patch.object(mr, "ask", side_effect=lambda c, s, u, **k: seen.setdefault("user", u) and None):
            bot.morning_line(self.cfg(), [], None, "2026-11-04")
        self.assertIn("- line 2", seen["user"])
        self.assertIn("nobody said anything", seen["user"])
        self.assertEqual(bot.describe_event({"event": {"kind": "fire_streak", "facts": {"days": 5}}}),
                         "fire streak (days 5)")


if __name__ == "__main__":
    unittest.main()
