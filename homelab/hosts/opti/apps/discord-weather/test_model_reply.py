"""Offline tests for model_reply.py: settings, budget, prompts and the call.
No API calls: the one function that talks to Anthropic is stubbed."""
import importlib.util
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


def response(text="Sure.", stop="end_turn", inp=120, out=18):
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
        self.quiet = lambda *_: None

        def cleanup():
            for p in self.patches:
                p.stop()
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()
            mr._limited.clear()
        self.addCleanup(cleanup)

    def cfg(self, **extra):
        return {**bot.DEFAULT_CONFIG, "timezone": "America/New_York", **extra}

    def on(self, **claude):
        return self.cfg(guild_id="123", claude={**mr.DEFAULTS, "enabled": True, **claude})

    def key(self):
        (self.folder / "key").write_text("sk-test", encoding="utf-8")

    def test_validate_gates_on_guild_and_shape(self):
        self.assertIsNone(mr.validate(self.cfg()))
        self.assertIn("guild_id", mr.validate(self.cfg(claude={"enabled": True})))
        self.assertIsNone(mr.validate(self.on(morning=True, memory=True, history=50, max_tokens=8000,
                                              memory_skip_channels=["1"])))
        for bad in ({"enabled": "yes"}, {"model": "Opus 5!"}, {"daily_cap": 5000}, {"max_tokens": 1},
                    {"history": 51}, {"effort": "max"}, {"morning": "on"}, {"memory_skip_channels": ["x"]},
                    {"kinds": []}, {"memory_tail": 40}):   # retired keys are refused
            self.assertIsNotNone(mr.validate(self.cfg(claude=bad)), bad)
        self.assertEqual(bot.DEFAULT_CONFIG["claude"], mr.DEFAULTS)   # the two copies agree
        self.assertEqual(mr.DEFAULTS["model"], "claude-haiku-5-5")
        prof = self.cfg(profiles={"t": {"claude": {"enabled": True}}})
        self.assertIn("profile 't'", bot.validate_config(prof))

    def test_profile_switch_carries_and_resets_the_model_block(self):
        cfg = self.cfg(profiles={"live": {"guild_id": "1", "channel_id": "2"},
                                 "test": {"guild_id": "3", "channel_id": "4",
                                          "claude": {"enabled": True, "daily_cap": 5}}},
                       active_profile="test")
        self.assertIsNone(bot.validate_config(cfg))
        bot.apply_profile(cfg)
        self.assertEqual(mr.settings(cfg)["daily_cap"], 5)
        cfg["active_profile"] = "live"
        bot.apply_profile(cfg)
        self.assertFalse(cfg["claude"]["enabled"])

    def test_decide_needs_switch_key_and_budget(self):
        self.assertIsNone(mr.decide(self.on(), "chat"))                 # no key anywhere
        self.key()
        self.assertEqual(mr.key_source(), "file")
        self.assertIsNone(mr.decide(self.cfg(), "chat"))                # off
        for kind in ("chat", "weather", "full"):
            self.assertEqual(mr.decide(self.on(), kind), "model")
        self.assertIsNone(mr.decide(self.on(), "morning"))              # own switches
        self.assertIsNone(mr.decide(self.on(), "learn"))
        self.assertEqual(mr.decide(self.on(morning=True, memory=True), "learn"), "model")
        with patch.object(mr, "_create", return_value=response(inp=900, out=200)):
            mr.ask(self.on(), "s", "u", log=self.quiet)
        self.assertEqual(mr.decide(self.on(daily_cap=1), "chat"), "limit")
        self.assertEqual(mr.spent(self.on(daily_tokens=1000)), "tokens")
        self.assertEqual(mr.spent(self.on(daily_tokens=0)), "")         # 0 = no token cap
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-env"}):
            self.assertEqual(mr.key_source(), "env")

    def test_out_of_credit_or_rate_limited_means_limit_until_tomorrow(self):
        self.key()
        with patch.object(mr, "_create", side_effect=TimeoutError("slow")):
            self.assertIsNone(mr.ask(self.on(), "s", "u", log=self.quiet))
        self.assertEqual(mr.decide(self.on(), "chat"), "model")         # a timeout is not a limit
        with patch.object(mr, "_create", side_effect=RuntimeError("Your credit balance is too low")):
            mr.ask(self.on(), "s", "u", log=self.quiet)
        self.assertEqual(mr.decide(self.on(), "chat"), "limit")
        mr._limited.clear()
        billing = RuntimeError("payment required")
        billing.status_code = 402
        with patch.object(mr, "_create", side_effect=billing):
            mr.ask(self.on(), "s", "u", log=self.quiet)
        self.assertEqual(mr.spent(self.on()), "credit")

    def test_rate_limits_and_overloads_never_latch_for_the_day(self):
        self.key()
        for status, text in ((429, "rate_limit_error: slow down"), (529, "overloaded_error"), (500, "api_error")):
            err = RuntimeError(text)
            err.status_code = status
            with patch.object(mr, "_create", side_effect=err):
                self.assertIsNone(mr.ask(self.on(), "s", "u", log=self.quiet), status)
            self.assertEqual((mr.spent(self.on()), mr.decide(self.on(), "chat")), ("", "model"), status)
        with patch.object(mr, "_create", return_value=response("back")):
            self.assertEqual(mr.ask(self.on(), "s", "u", log=self.quiet), "back")   # the next call just works

    def test_sdk_retries_are_short_for_pings_and_longer_for_background_jobs(self):
        made = []

        class FakeClient:
            def __init__(self, **kw):
                made.append(kw)
                self.messages = SimpleNamespace(create=lambda **_: response())
        with patch.object(mr, "anthropic", SimpleNamespace(Anthropic=FakeClient)):
            mr.ask(self.on(), "s", "u", log=self.quiet)
            mr.ask(self.on(), "s", "u", log=self.quiet, retries=mr.SLOW_RETRIES, timeout=mr.SLOW_TIMEOUT)
        self.assertEqual([(m["max_retries"], m["timeout"]) for m in made],
                         [(mr.RETRIES, mr.TIMEOUT), (mr.SLOW_RETRIES, mr.SLOW_TIMEOUT)])
        self.assertGreaterEqual(mr.RETRIES, 1)

    def test_ask_returns_text_or_none_and_records(self):
        with patch.object(mr, "_create", return_value=response("  Fine.  ")):
            self.assertEqual(mr.ask(self.on(), "s", "u", log=self.quiet), "  Fine.  ")
        with patch.object(mr, "_create", return_value=response("x", stop="refusal")):
            self.assertIsNone(mr.ask(self.on(), "s", "u", log=self.quiet))
        with patch.object(mr, "_create", return_value=response("", stop="max_tokens")):
            self.assertIsNone(mr.ask(self.on(), "s", "u", log=self.quiet))
        self.assertIn("max_tokens", mr._last_error)
        self.assertEqual(mr.usage("America/New_York")["calls"], 3)       # all of them cost tokens
        with patch.object(mr, "_create", return_value=response()) as create:
            mr.ask(self.on(), "s", "u", log=self.quiet, effort="low", timeout=90.0)
        s = create.call_args.args[0]
        self.assertEqual((s["effort"], s["timeout"], s["max_tokens"], s["model"]),
                         ("low", 90.0, 4096, "claude-haiku-5-5"))
        st = mr.status(self.on())
        self.assertEqual((st["enabled"], st["key"], st["sdk"]), (True, "none", True))

    def test_clean_line(self):
        self.assertEqual(mr.clean_line('"Reply: no."'), "no.")
        self.assertEqual(mr.clean_line("hi @everyone"), "")
        self.assertEqual(mr.clean_line("hi <@&55>"), "")
        self.assertEqual(mr.clean_line("<@2> and <@99>", allowed_ids=["2"]), "<@2> and someone")
        out = mr.clean_line(("This is a sentence. " * 80).strip())
        self.assertLessEqual(len(out), mr.MAX_CHARS)
        self.assertTrue(out.endswith("."))

    def test_chat_prompt_puts_the_message_last_and_carries_what_matters(self):
        system, user = mr.build_chat_prompt(
            "", ["@tomboe", "@antwah"], ["@tomboe: car plan", "WB: noted"], "@tomboe",
            "should we all buy one car", self_notes="you are dry", group_notes="Murf time: everything runs long",
            people=[("@tomboe", "takes the LIRR"), ("@antwah", "")], replied_to="WB: noted",
            own_recent=["first reply", "second reply"])
        self.assertTrue(system.startswith(mr.SEED_BRIEF[:40]))
        for piece in ("Reply to the message at the end", "Roster (the only handles you may mention): @tomboe, @antwah",
                      "you are dry", "Murf time: everything runs long", "@tomboe: takes the LIRR"):
            self.assertIn(piece, system)
        self.assertNotIn("@antwah: ", system)                            # empty notes are left out
        self.assertTrue(user.endswith("@tomboe says: should we all buy one car\n\nReply to @tomboe."))
        self.assertIn("@tomboe is replying to this message:\nWB: noted", user)
        self.assertIn("- second reply", user)
        self.assertNotIn("Weather numbers", user)
        self.assertNotIn("filed this under", user)                       # no router label any more
        _, wx = mr.build_chat_prompt("", [], [], "@x", "weather report", facts=[
            {"town": "Bellerose", "hi": 61, "lo": 42, "feels": 56, "cond": "Overcast", "rain": 0}])
        self.assertIn("- Bellerose: high 61, low 42, feels like 56, overcast, rain 0%", wx)
        self.assertIn("(just pinged you)", mr.build_chat_prompt("", [], [], "@x", "  ")[1])

    def test_morning_and_learning_prompts(self):
        system, user = mr.build_morning_prompt("Be WB.", ["@tomboe"], ["@tomboe: rain 2/10"], ["Bellerose: high 61°F"],
                                               "fire streak (days 5)", [f"line {i}" for i in range(10)],
                                               self_notes="me", group_notes="us")
        self.assertIn("280 characters", system)
        self.assertIn("Your notes about the group:\nus", system)
        self.assertIn("- line 9", user)
        self.assertNotIn("- line 2", user)
        system, user = mr.build_person_prompt("", "@tomboe", "old", ["@tomboe: hi"], ["q -> a [reactions: 😂x2]"])
        self.assertIn("at most 250 words", system)
        self.assertIn("never invent", system)
        self.assertIn("😂x2", user)
        self.assertIn("at most 400 words", mr.build_group_prompt("", [], "", [])[0])
        self.assertIn("(none yet: you are brand new)", mr.build_self_prompt("", "", [])[1])
        parsed = mr.parse_lines("LIMIT:\n- out of words, {name}\n* bye {name}\nPESTER:\n1 at a time {name}\n"
                                "@everyone shush\n")
        self.assertEqual(parsed, {"limit": ["out of words, {name}", "bye {name}"], "pester": ["1 at a time {name}"]})

    def test_one_pester_line_per_person_per_interval(self):
        self.addCleanup(bot._last_nag.clear)
        self.assertTrue(bot.nag_ok("u1", now=1000))
        self.assertFalse(bot.nag_ok("u1", now=1000 + bot.NAG_INTERVAL - 1))
        self.assertTrue(bot.nag_ok("u1", now=1000 + bot.NAG_INTERVAL))
        self.addCleanup(bot._last_reply.clear)
        self.addCleanup(bot._burst.clear)
        self.assertFalse(bot.throttled("n1", "c", now=5000))
        self.assertEqual(bot.throttled("n1", "c", now=5001), "cooldown")
        self.assertIsNone(bot.limit_line(self.cfg(), "7"))              # nothing written yet: caller reacts


if __name__ == "__main__":
    unittest.main()
