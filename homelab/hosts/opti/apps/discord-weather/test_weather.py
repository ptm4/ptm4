"""Offline regression tests: no forecasts fetched and no Discord messages sent."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
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

    def persona(self, **extra):
        self.addCleanup(witty.use_persona, None)
        data = {"templates": [{"id": "p_tom", "text": "{name}, on at 10 means midnight.", "who": "@tom"},
                              {"id": "p_any", "text": "Query: {name}, explain yourself."},
                              {"id": "p_bit", "text": "Statement: {me} endures."}],
                "event_lines": {"fire": ["{subject} is cooking at {feels}°."],
                                "wind": ["{me} reports {wind} mph."]},
                "word_banks": {"me": ["WB"]},
                "pings": {"@tom": "111", "Starks": "222"},
                "embed": {"title": "MURF", "username": "{me}"}, **extra}
        return witty.use_persona(data)

    def test_persona_who_lines_pings_and_events(self):
        self.assertIsNone(self.persona())
        pairs = witty._all_pairs(["@tom", "@matt"])
        self.assertEqual([p[1] for p in pairs if p[0]["id"] == "p_tom"], ["@tom"])
        self.assertEqual(witty._all_pairs(["@matt"])[0][0]["id"], "p_any")  # who-line skipped
        self.assertEqual(witty.apply_pings("@tom and Starks, not @tomboe"), "<@111> and <@222>, not @tomboe")
        ctx = self.pool.weather([(NC, forecast(105))], START)
        self.assertEqual(self.pool.peek(NAMES, event=ctx["event"])["rendered"], "Starks is cooking at 105°.")
        self.assertEqual(witty._demo_render(witty.TEMPLATES_BY_ID["p_bit"], NAMES), "Statement: WB endures.")
        wind = weather.describe([], [(NY, forecast(wind=35))], START)["event"]
        self.assertEqual(self.pool.peek(NAMES, event=wind)["rendered"], "WB reports 35 mph.")
        with patch.object(bot, "_witty", self.pool), patch.object(bot, "fetch_forecast", side_effect=[forecast(), forecast(105)]):
            payload, _, _ = bot.build_payload(self.config())
        self.assertEqual(payload["content"], "@everyone")       # no template joke under @everyone
        self.assertEqual(payload["embeds"][0]["title"], "MURF")
        self.assertEqual(payload["username"], "WB")

    def test_posts_as_bot_when_token_and_channel_else_webhook(self):
        with patch.object(bot, "_witty", self.pool), patch.object(bot, "fetch_forecast", return_value=forecast()), \
                patch.object(bot, "post_channel") as chan, patch.object(bot, "post_webhook") as hook:
            with patch.object(bot, "BOT_TOKEN", "t"):
                self.assertTrue(bot.post_report(self.config(channel_id="42"))[0])
            self.assertEqual(chan.call_args.args[0], "42")
            hook.assert_not_called()
            self.assertTrue(bot.post_report(self.config(channel_id="42"))[0])  # no token
            hook.assert_called_once()
            ok, detail = bot.post_report(self.config(webhook_url=""))
            self.assertFalse(ok)
        self.assertIn("channel_id", bot.validate_config(self.config(channel_id="#weather")))

    def test_weather_asks_pick_town_home_or_everyone(self):
        self.persona(homes={"7": "Greensboro, NC"})
        cfg = self.config()
        with patch.object(bot, "fetch_forecast", side_effect=lambda loc, tz: forecast(80 if loc is NY else 90)):
            bot._forecasts.clear()
            self.assertEqual(bot.weather_facts(cfg, 5, "<@99> weather in bellerose?")["town"], "Bellerose")
            self.assertEqual(bot.weather_facts(cfg, 5, "weather for starks?")["town"], "Greensboro")
            self.assertEqual(bot.weather_facts(cfg, 7, "<@99> weather?")["town"], "Greensboro")   # home
            every = bot.weather_facts(cfg, 5, "<@99> weather?")
            self.assertEqual([f["town"] for f in every], ["Bellerose", "Greensboro"])
            line = bot.plain_weather("<@5>", every)
        self.assertEqual(line, "<@5> Bellerose 80°/60°, feels 80°, rain 10% · Greensboro 90°/60°, feels 90°, rain 10%")
        for text, kind in {"<@1> weather report": "weather", "<@1> full report": "full",
                           "<@1> thanks wb": "chat", "<@1> it's raining": "chat", "<@1> bellerose": "chat"}.items():
            self.assertEqual(bot.classify_ping(text), kind, text)

    def test_classify_precedence_and_persona_patterns(self):
        towns = ["Bellerose", "Starks"]
        cases = {"weather?": "weather", "weather report": "weather", "tell me my weather": "weather",
                 "tell me the weather": "weather", "what's the weather": "weather", "weather in bellerose": "weather",
                 "how's starks": "wild", "is it hot out": "wild", "it's raining again": "wild",
                 "the weather sucks": "wild", "bellerose": "wild", "full report": "full",
                 "I'm full": "wild", "report him": "wild", "everything is fine": "wild",
                 "it feels like I'm melting, turn the thermostat down": "control",
                 "everytime you type e say hi": "command",
                 "blink twice if you're held against your will": "sentience",
                 "I rate the experience a 6 out of 10": "rating", "murfbot lied": "complaint",
                 "I burned the files": "files", "phones on a camping trip?": "outdoors",
                 "any daymers?": "gaming", "what do you think of the percolator": "lore",
                 "you clanker": "name", "thanks wb": "thanks", "half and half or whole milk?": "opinion",
                 "no bless yous for giacomo?": "wild"}
        for text, kind in cases.items():
            self.assertEqual(witty.classify(text, towns), kind, text)
        self.persona(reply_patterns={"lore": [r"\bgiacomo\b"]})
        self.assertEqual(witty.classify("no bless yous for giacomo?"), "lore")
        for bad in ({"reply_patterns": {"wild": ["x"]}}, {"reply_patterns": {"lore": ["("]}},
                    {"replies": {"nope": ["x"]}}, {"replies": {"wild": ["{nothere}"]}}):
            self.assertIn("persona rejected", witty.use_persona(bad), bad)
        witty.use_persona(None)

    def test_reply_lines_rotate_without_repeating(self):
        self.persona(replies={"wild": ["a {name}", "b {name}", "c {name}"]},
                     pings={"@tom": "111", "@pete": "222"})
        seen = [witty.reply_line("wild", "<@5>") for _ in range(6)]
        self.assertEqual(sorted(seen[:3]), ["a <@5>", "b <@5>", "c <@5>"])
        self.assertEqual(sorted(seen[3:]), ["a <@5>", "b <@5>", "c <@5>"])
        self.assertNotEqual(seen[2], seen[3])
        self.assertEqual(witty.pick_name("111"), "<@222>")
        self.assertIn(witty.pick_name(), ("<@111>", "<@222>"))
        witty.use_persona(None)
        self.assertEqual(witty.pick_name(), "someone")

    def test_addressed_scope_and_throttle(self):
        me = SimpleNamespace(id=1)
        role = SimpleNamespace(tags=SimpleNamespace(bot_id=1))
        other = SimpleNamespace(tags=None)

        def msg(**kw):
            return SimpleNamespace(**{"mentions": [], "role_mentions": [], "reference": None,
                                      "guild": SimpleNamespace(id=10), "channel": SimpleNamespace(id=20), **kw})
        self.assertTrue(bot.addressed(msg(mentions=[me]), me))
        self.assertTrue(bot.addressed(msg(role_mentions=[other, role]), me))
        self.assertTrue(bot.addressed(msg(reference=SimpleNamespace(resolved=SimpleNamespace(author=me))), me))
        self.assertFalse(bot.addressed(msg(role_mentions=[other]), me))
        self.assertFalse(bot.addressed(msg(mentions=[SimpleNamespace(id=2)]), me))
        self.assertTrue(bot.in_scope(self.config(), msg()))
        self.assertTrue(bot.in_scope(self.config(guild_id="10", reply_channels=["20"]), msg()))
        self.assertFalse(bot.in_scope(self.config(guild_id="11"), msg()))
        self.assertFalse(bot.in_scope(self.config(reply_channels=["21"]), msg()))
        bot._last_reply.clear()
        bot._burst.clear()
        self.assertFalse(bot.throttled("u1", "c", now=100))
        self.assertTrue(bot.throttled("u1", "c", now=104))      # inside the per-person cooldown
        self.assertFalse(bot.throttled("u1", "c", now=109))
        for i in range(2, 6):
            self.assertFalse(bot.throttled(f"u{i}", "c", now=110 + i))
        self.assertTrue(bot.throttled("u9", "c", now=120))      # 6 replies in the window: capped
        self.assertFalse(bot.throttled("u9", "d", now=120))     # another channel is unaffected
        self.assertFalse(bot.throttled("u9", "c", now=200))     # window has passed

    def test_inbox_and_say(self):
        inbox = str(Path(self.path).with_name("inbox.jsonl"))
        self.addCleanup(lambda: [Path(p).unlink(missing_ok=True) for p in (inbox, inbox + ".tmp")])
        with patch.object(bot, "INBOX_PATH", inbox):
            bot.inbox_add({"id": "1", "text": "hi", "kind": "wild"})
            bot.inbox_add({"id": "2", "text": "yo", "kind": "thanks"})
            self.assertEqual([e["id"] for e in bot.inbox_pending()], ["1", "2"])
            self.assertEqual(bot.inbox_mark(["1"]), 1)
            self.assertEqual([e["id"] for e in bot.inbox_pending()], ["2"])
            cfg = self.config(channel_id="42")
            with patch.object(bot, "BOT_TOKEN", "t"), \
                    patch.object(bot, "http_json", return_value=(200, {"id": "77"})) as post:
                self.assertEqual(bot.say(cfg, "Statement: hello", reply_to="2"), "77")
                self.assertIn("/channels/42/messages", post.call_args.args[0])
                body = post.call_args.kwargs["body"]
                self.assertEqual(body["message_reference"]["message_id"], "2")
                self.assertEqual(body["allowed_mentions"]["parse"], ["users"])
                self.assertEqual(bot.inbox_pending(), [])
                for bad in ("", "x" * 2001, "hey @everyone", "@here now", "@everyone"):
                    with self.assertRaises(ValueError):
                        bot.say(cfg, bad)
                with self.assertRaises(ValueError):
                    bot.say(self.config(channel_id=""), "no channel")
            with self.assertRaises(RuntimeError):
                bot.say(cfg, "no token")

    def test_profiles_switch_server_fields(self):
        cfg = self.config(profiles={"live": {"guild_id": "1", "channel_id": "2", "persona": "persona.json"},
                                    "test": {"guild_id": "3", "channel_id": "4", "reply_channels": ["4"],
                                             "persona": "persona-test.json"}},
                          active_profile="test")
        self.assertIsNone(bot.validate_config(cfg))
        bot.apply_profile(cfg)
        self.assertEqual((cfg["guild_id"], cfg["channel_id"], cfg["reply_channels"], cfg["persona"]),
                         ("3", "4", ["4"], "persona-test.json"))
        cfg["active_profile"] = "live"
        bot.apply_profile(cfg)
        self.assertEqual((cfg["guild_id"], cfg["channel_id"], cfg["reply_channels"]), ("1", "2", []))
        for bad in (dict(active_profile="nope"), dict(guild_id="abc"), dict(persona="../x.json"),
                    dict(persona="x.txt"), dict(reply_channels=["x"]), dict(profiles={"bad name!": {}}),
                    dict(profiles={"p": {"webhook_url": "x"}}), dict(profiles={"p": {"guild_id": "q"}})):
            self.assertIsNotNone(bot.validate_config(self.config(**bad)), bad)

    def test_bad_persona_keeps_defaults(self):
        for bad in [{"pings": {"@tom": "not-an-id"}}, {"event_lines": {"fire": ["{nope}"]}},
                    {"templates": [{"id": "x", "text": "no name here", "who": "@tom"}]}]:
            with self.subTest(bad=bad):
                self.assertIn("persona rejected", witty.use_persona(bad))
                self.assertTrue(witty.TEMPLATES[0]["id"].startswith("v5_"))
                self.assertEqual(witty.PINGS, {})
                self.assertEqual(witty.WORD_BANKS, {})
        witty.use_persona(None)

    def config(self, **extra):
        return {**bot.DEFAULT_CONFIG, "locations": [NY, NC], "witty_names": NAMES,
                "webhook_url": "https://discord.com/api/webhooks/offline-test", **extra}

    def test_payload_prioritizes_nc_even_if_first_town_fails(self):
        with patch.object(bot, "_witty", self.pool), patch.object(bot, "fetch_forecast", side_effect=[RuntimeError("offline"), forecast(105)]):
            payload, failed, receipt = bot.build_payload(self.config())
        self.assertEqual(payload["content"], "@everyone")
        self.assertEqual(failed, [NY["name"]])
        self.assertIn("snapshot", json.dumps(sorted(receipt)) + "snapshot")
        self.assertNotIn("t", receipt)                           # nothing from the joke pool
        self.assertEqual((self.pool._load() or {}).get("weather_days", []), [])

    def test_failed_post_retries_identically_and_records_weather_once(self):
        with patch.object(bot, "_witty", self.pool), patch.object(bot, "fetch_forecast", return_value=forecast(105)), patch.object(bot, "post_webhook", side_effect=[RuntimeError("offline"), None]) as post:
            ok, _ = bot.post_report(self.config())
            self.assertFalse(ok)
            self.assertEqual((self.pool._load() or {}).get("weather_days", []), [])
            ok, _ = bot.post_report(self.config())
            self.assertTrue(ok)
        self.assertEqual(post.call_args_list[0].args[1], post.call_args_list[1].args[1])
        self.assertEqual(post.call_args.args[1]["content"], "@everyone")
        self.assertEqual(len(self.pool._load()["weather_days"]), 1)
        self.assertEqual(self.pool._load().get("history", []), [])   # the template pool is not used


if __name__ == "__main__":
    unittest.main()
