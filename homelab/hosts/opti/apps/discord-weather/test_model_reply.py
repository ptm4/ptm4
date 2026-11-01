"""Offline tests for the optional model-written reply path (model_reply.py).
No API calls: the one function that talks to Anthropic is stubbed."""
import importlib.util
import json
import uuid
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import model_reply as mr
import witty_messages as witty

spec = importlib.util.spec_from_file_location("bot", Path(__file__).with_name("discord-weather.py"))
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

PERSONA = {"pings": {"@tomboe": "2", "@antwah": "3", "Starks": "4"},
           "word_banks": {"me": ["WB"]},
           "replies": {"sentience": ["Statement: no, {name}.", "Query: why, {name}?"]},
           "brief": "You are WB. Deadpan."}


def response(text="Statement: no.", stop="end_turn", inp=120, out=18):
    return SimpleNamespace(usage=SimpleNamespace(input_tokens=inp, output_tokens=out),
                           stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


class ModelReplyTests(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).resolve().parent / (".test-state-" + uuid.uuid4().hex)
        folder.mkdir()
        self.folder = folder
        self.patches = [patch.object(mr, "USAGE_PATH", str(folder / "usage.json")),
                        patch.object(mr, "KEY_PATH", str(folder / "key")),
                        patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}),
                        patch.object(mr, "anthropic", object())]   # SDK "present"
        for p in self.patches:
            p.start()
        mr._last_error = ""

        def cleanup():
            for p in self.patches:
                p.stop()
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()
            witty.use_persona(None)
        self.addCleanup(cleanup)

    def cfg(self, **extra):
        return {**bot.DEFAULT_CONFIG, "timezone": "America/New_York", **extra}

    def on(self, **claude):
        return self.cfg(guild_id="123", claude={**mr.DEFAULTS, "enabled": True, **claude})

    def test_validate_gates_on_guild_and_shape(self):
        self.assertIsNone(mr.validate(self.cfg()))
        self.assertIn("guild_id", mr.validate(self.cfg(claude={"enabled": True})))
        self.assertIsNone(mr.validate(self.on()))
        for bad in ({"enabled": "yes"}, {"model": "Opus 5!"}, {"daily_cap": 5000}, {"max_tokens": 1},
                    {"history": -1}, {"kinds": "wild"}, {"nope": 1}):
            self.assertIsNotNone(mr.validate(self.cfg(claude=bad)), bad)
        # the bot's own validator applies it to the flat config and to every profile
        self.assertIn("guild_id", bot.validate_config(self.cfg(claude={"enabled": True})))
        prof = self.cfg(profiles={"t": {"claude": {"enabled": True}}})
        self.assertIn("profile 't'", bot.validate_config(prof))
        self.assertIsNone(bot.validate_config(self.cfg(profiles={"t": {"guild_id": "9", "claude": {"enabled": True}}})))

    def test_profile_switch_carries_and_resets_the_model_block(self):
        cfg = self.cfg(profiles={"live": {"guild_id": "1", "channel_id": "2"},
                                 "test": {"guild_id": "3", "channel_id": "4",
                                          "claude": {"enabled": True, "daily_cap": 5}}},
                       active_profile="test")
        self.assertIsNone(bot.validate_config(cfg))
        bot.apply_profile(cfg)
        self.assertTrue(cfg["claude"]["enabled"])
        self.assertEqual(mr.settings(cfg)["daily_cap"], 5)
        cfg["active_profile"] = "live"
        bot.apply_profile(cfg)
        self.assertFalse(cfg["claude"]["enabled"])   # live profile never inherits it

    def test_wants_needs_switch_kind_key_and_cap(self):
        self.assertFalse(mr.wants(self.on(), "wild"))            # no key anywhere
        (self.folder / "key").write_text("sk-test", encoding="utf-8")
        self.assertEqual(mr.key_source(), "file")
        self.assertFalse(mr.wants(self.cfg(), "wild"))           # disabled
        self.assertTrue(mr.wants(self.on(), "wild"))
        self.assertFalse(mr.wants(self.on(), "weather"))         # forecasts stay template/embed
        self.assertFalse(mr.wants(self.on(kinds=["opinion"]), "wild"))
        self.assertTrue(mr.wants(self.on(kinds=["opinion"]), "opinion"))
        with patch.object(mr, "_create", return_value=response()):
            for _ in range(2):
                mr.ask(self.on(daily_cap=2), "s", "u", log=lambda *_: None)
        self.assertFalse(mr.wants(self.on(daily_cap=2), "wild"))  # cap reached
        self.assertTrue(mr.wants(self.on(daily_cap=3), "wild"))
        today = mr.usage("America/New_York")
        self.assertEqual((today["calls"], today["input_tokens"], today["output_tokens"]), (2, 240, 36))
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-env"}):
            self.assertEqual(mr.key_source(), "env")

    def test_ask_returns_text_or_none_and_records(self):
        cfg = self.on()
        with patch.object(mr, "_create", return_value=response("  Statement: fine.  ")):
            self.assertEqual(mr.ask(cfg, "s", "u", log=lambda *_: None), "  Statement: fine.  ")
        with patch.object(mr, "_create", side_effect=TimeoutError("slow")):
            self.assertIsNone(mr.ask(cfg, "s", "u", log=lambda *_: None))
            self.assertIn("TimeoutError", mr._last_error)
        with patch.object(mr, "_create", return_value=response("x", stop="refusal")):
            self.assertIsNone(mr.ask(cfg, "s", "u", log=lambda *_: None))
            self.assertEqual(mr._last_error, "refusal")
        self.assertEqual(mr.usage("America/New_York")["calls"], 2)   # the refusal still cost tokens
        st = mr.status(cfg)
        self.assertEqual((st["enabled"], st["model"], st["key"], st["sdk"]), (True, "claude-haiku-5-5", "none", True))
        self.assertIsNotNone(mr.validate(self.cfg(claude={"effort": "max"})))
        with patch.object(mr, "_create", return_value=response()) as create:
            mr.ask(self.on(effort="low"), "s", "u", log=lambda *_: None)
        self.assertEqual(create.call_args.args[0]["effort"], "low")

    def test_clean_line(self):
        self.assertEqual(mr.clean_line('"Reply: Statement: no."'), "Statement: no.")
        self.assertEqual(mr.clean_line("WB: Observation: fine"), "Observation: fine")
        self.assertEqual(mr.clean_line("hi @everyone"), "")
        self.assertEqual(mr.clean_line("hi <@&55>"), "")
        self.assertEqual(mr.clean_line("<@2> and <@99>", allowed_ids=["2"]), "<@2> and someone")
        long = ("Statement: this is a sentence. " * 30).strip()
        out = mr.clean_line(long)
        self.assertLessEqual(len(out), mr.MAX_CHARS)
        self.assertTrue(out.endswith("."))
        self.assertEqual(mr.clean_line("a\n\n\n\n\nb"), "a\n\nb")

    def test_prompt_carries_brief_roster_chat_and_examples(self):
        system, user = mr.build_prompt("Be WB.", ["@tomboe"], ["@tomboe: hi", "WB: no"], "@antwah",
                                       "<@1> rate yourself", "rating",
                                       {"town": "Bellerose", "hi": 61, "lo": 48, "feels": 57, "cond": "Overcast", "rain": 10},
                                       ["Rating received: {name}."])
        self.assertTrue(system.startswith("Be WB."))
        self.assertIn("@everyone", system)                 # the rules travel with every call
        self.assertIn("Roster (the only handles you may mention): @tomboe", system)
        self.assertIn("@tomboe: hi\nWB: no", user)
        self.assertIn("@antwah just pinged you: <@1> rate yourself", user)
        self.assertIn("filed this under: rating", user)
        self.assertIn("Bellerose: high 61", user)
        self.assertIn("- Rating received: {name}.", user)
        sysd, _ = mr.build_prompt("", [], [], "@x", "p", "wild", {}, [])
        self.assertTrue(sysd.startswith(mr.DEFAULT_BRIEF[:40]))

    def test_bot_model_line_uses_persona_and_pings(self):
        self.assertIsNone(witty.use_persona(PERSONA))
        self.assertEqual(witty.BRIEF, "You are WB. Deadpan.")
        self.assertEqual(bot.handle_of("2"), "@tomboe")
        self.assertEqual(bot.handle_of("77", "@newguy"), "@newguy")
        self.assertEqual(bot.chat_line("2", "Tom", "yo <@3> and <@&9>  look", me="WB"), "@tomboe: yo @antwah and @WB look")
        self.assertEqual(bot.chat_line("1", "Weather-Bot", "", is_bot=True, me="WB"), "WB: [embed]")
        seen = {}

        def fake_ask(cfg, system, user, log=print):
            seen["system"], seen["user"] = system, user
            return '"Statement: @tomboe is wrong, <@3>. <@999> agrees."'
        facts = {"town": "Bellerose", "hi": 61, "lo": 48, "feels": 57, "cond": "Overcast", "rain": 10}
        with patch.object(mr, "ask", side_effect=fake_ask), patch.object(bot, "reply_facts", return_value=facts):
            line = bot.model_line(self.on(), "3", "<@1> are you alive", "sentience", ["@tomboe: hi"])
        self.assertEqual(line, "Statement: <@2> is wrong, <@3>. someone agrees.")
        self.assertIn("You are WB. Deadpan.", seen["system"])
        self.assertIn("@antwah, @tomboe", seen["system"])     # roster, Starks (not a handle) left out
        self.assertIn("@antwah just pinged you: are you alive", seen["user"])
        self.assertIn("- Statement: no, {name}.", seen["user"])
        with patch.object(mr, "ask", return_value=None), patch.object(bot, "reply_facts", return_value=facts):
            self.assertIsNone(bot.model_line(self.on(), "3", "x", "wild", []))
        self.assertIn("brief", witty.use_persona({**PERSONA, "brief": "x" * 6001}))


if __name__ == "__main__":
    unittest.main()
