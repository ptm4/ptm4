"""Offline tests for WBdb (wbdb.py) and the bot's learning and reply path:
ingest from today on, profiles and their seed, pings and reactions, the
nightly learning, ready-made lines, forgetting, backups and the corrupt-file
rebuild. Discord and Anthropic are stubbed; the database is a real SQLite file."""
import importlib.util
import json
import os
import threading
import uuid
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import model_reply as mr
import wbdb
import witty_messages as witty

spec = importlib.util.spec_from_file_location("bot", Path(__file__).with_name("discord-weather.py"))
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

PERSONA = {"pings": {"@tomboe": "2", "@antwah": "3"}, "word_banks": {"me": ["WB"]}}
BOT_ID = "900"
NY = {"name": "Bellerose, NY", "lat": 40.73, "lon": -73.71}


def msg(mid, author="2", text="hi", name="Tom", ts="2026-11-06T12:00:00+00:00"):
    return {"id": str(mid), "content": text, "embeds": [], "timestamp": ts,
            "author": {"id": author, "global_name": name, "username": name.lower()}}


class FakeDiscord:
    """GET /channels/<id>/messages (limit, before) newest first, and /users/@me."""
    def __init__(self, channels):
        self.channels = channels
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        if path == "/users/@me":
            return {"id": BOT_ID}
        ch, qs = path.split("/")[2], path.partition("?")[2]
        q = dict(p.split("=") for p in qs.split("&") if p)
        msgs = sorted(self.channels.get(ch, []), key=lambda m: int(m["id"]), reverse=True)
        if "before" in q:
            msgs = [m for m in msgs if int(m["id"]) < int(q["before"])]
        return msgs[:int(q.get("limit", 50))]


class WBDBTests(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).resolve().parent / (".test-state-" + uuid.uuid4().hex)
        folder.mkdir()
        self.folder = folder
        self.patches = [patch.object(bot, "WBDB_PATH", str(folder / "wb.sqlite")),
                        patch.object(bot, "SEED_PATH", str(folder / "seed.json")),
                        patch.object(bot, "WBDB_BACKUP_DIR", str(folder / "backup")),
                        patch.object(bot, "BOT_TOKEN", "tok"),
                        patch.object(bot, "memory_channels", return_value=["10"]),
                        patch.object(mr, "USAGE_PATH", str(folder / "usage.json")),
                        patch.object(mr, "KEY_PATH", str(folder / "key")),
                        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}),
                        patch.object(mr, "anthropic", object()),
                        # each test file loads its own copy of the bot; log calls into this one
                        patch.object(mr, "CALL_HOOK", bot.record_call)]
        for p in self.patches:
            p.start()
        bot._self_id.clear()
        bot._self_id["id"] = BOT_ID     # never ask the real Discord
        bot._wb.update(db=None, error="")
        witty.use_persona(PERSONA)

        def cleanup():
            if bot._wb["db"]:
                bot._wb["db"].close()
            bot._wb.update(db=None, error="")
            for p in self.patches:
                p.stop()
            for root, dirs, files in os.walk(folder, topdown=False):
                for f in files:
                    os.remove(os.path.join(root, f))
                for d in dirs:
                    os.rmdir(os.path.join(root, d))
            folder.rmdir()
            witty.use_persona(None)
            bot._self_id.clear()
            mr._limited.clear()
        self.addCleanup(cleanup)

    def cfg(self, **claude):
        return {**bot.DEFAULT_CONFIG, "guild_id": "1", "channel_id": "10", "timezone": "America/New_York",
                "locations": [NY], "claude": {**mr.DEFAULTS, "enabled": True, "memory": True, **claude}}

    def db(self):
        return bot.memory_db()

    def row(self, mid, text="hi", author="@tomboe", author_id="2", ch="10", ts="2026-11-06T12:00:00+00:00",
            is_bot=False):
        return {"id": mid, "channel_id": ch, "author_id": author_id, "author": author, "is_bot": is_bot,
                "ts": ts, "content": text}

    # -- the store -------------------------------------------------------------
    def test_messages_store_learn_and_prune(self):
        db = self.db()
        self.assertEqual(db.add([self.row(1), self.row(2)]), 2)
        self.assertEqual(db.add([self.row(1)]), 0)
        self.assertEqual([r["id"] for r in db.unlearned()], [1, 2])
        db.mark_learned([1])
        self.assertEqual([r["id"] for r in db.unlearned()], [2])
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        db.add([self.row(3, ts=old), self.row(4, ts=old)])
        db.mark_learned([3])
        self.assertEqual(db.prune(), 1)                                   # learned and old only
        self.assertEqual(db.count(), 3)

    def test_positions_only_move_forward(self):
        db = self.db()
        self.assertIsNone(db.newest("10"))
        db.mark("10", 50)
        db.mark("10", 45)
        self.assertEqual(db.newest("10"), 50)

    def test_corrupt_file_is_set_aside_and_rebuilt(self):
        path = self.folder / "bad.sqlite"
        path.write_bytes(b"this is not a database" * 100)
        db = wbdb.WBDB(str(path))
        self.addCleanup(db.close)
        self.assertIn("set aside", db.note)
        self.assertEqual(db.add([self.row(1)]), 1)

    def test_backup_is_a_dated_copy_pruned_to_keep(self):
        db = self.db()
        db.set_profile("2", "keep me", "@tomboe")
        dest = self.folder / "backup"
        for day in ("2026-11-01", "2026-11-02", "2026-11-03"):
            db.backup(str(dest), day, keep=2)
        self.assertEqual(sorted(os.listdir(dest)), ["wb-2026-11-02.sqlite", "wb-2026-11-03.sqlite"])
        copy = wbdb.WBDB(str(dest / "wb-2026-11-03.sqlite"))
        self.addCleanup(copy.close)
        self.assertEqual(copy.profile("2")["notes"], "keep me")
        busy, _, _ = db.checkpoint()
        self.assertEqual(busy, 0)
        self.assertEqual(os.path.getsize(db.path + "-wal"), 0)                  # truncated after the checkpoint

    def test_concurrent_writers_do_not_collide(self):
        db = self.db()
        errors = []

        def write(base):
            try:
                for i in range(50):
                    db.add([self.row(base + i)])
                    db.log_ping(base + i, "10", "2", "@tomboe", "q", base + i + 10000, "a")
            except Exception as e:   # pragma: no cover - the assertion reports it
                errors.append(e)
        threads = [threading.Thread(target=write, args=(b,)) for b in (1000, 2000, 3000)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((errors, db.count()), ([], 150))

    # -- reading the server from today on -----------------------------------------
    def test_ingest_starts_today_then_reads_forward(self):
        fake = FakeDiscord({"10": [msg(i, text=f"m{i}") for i in range(1, 501)]})
        db = self.db()
        with patch.object(bot, "_discord_get", fake):
            self.assertEqual(bot.ingest(db, self.cfg()), 0)               # first sight: no history import
            self.assertEqual(db.newest("10"), 500)
            fake.channels["10"] += [msg(501, text="new"), msg(502, author=BOT_ID, text="me", name="WB")]
            self.assertEqual(bot.ingest(db, self.cfg()), 2)
        rows = db.unlearned()
        self.assertEqual([(r["author"], r["content"], r["is_bot"]) for r in rows],
                         [("@tomboe", "new", 0), ("@WB", "me", 1)])

    def test_one_refused_channel_does_not_stop_the_rest(self):
        self.addCleanup(bot._unreadable.clear)
        real = FakeDiscord({"11": [msg(5)]})

        def fake(path):
            if "/channels/10/" in path:
                raise RuntimeError("HTTP Error 403: Forbidden")
            return real(path)
        db = self.db()
        with patch.object(bot, "_discord_get", fake):
            bot.ingest(db, self.cfg(), channels=["10", "11"])
        self.assertIn("10", bot._unreadable)
        self.assertEqual(db.newest("11"), 5)

    def test_memory_channels_lists_the_server_minus_skips_and_refusals(self):
        self.patches[4].stop()   # the real memory_channels
        self.addCleanup(self.patches[4].start)
        self.addCleanup(lambda: (bot._channels.update(at=None, ids=[]), bot._unreadable.clear()))
        bot._channels.update(at=None, ids=[])
        listing = [{"id": "20", "type": 0, "position": 2}, {"id": "21", "type": 2, "position": 3},
                   {"id": "22", "type": 5, "position": 1}, {"id": "23", "type": 0, "position": 4}]
        cfg = self.cfg(memory_skip_channels=["23"])
        with patch.object(bot, "_discord_get", return_value=listing) as get:
            self.assertEqual(bot.memory_channels(cfg), ["10", "22", "20"])
            bot.memory_channels(cfg)
        self.assertEqual(get.call_count, 1)                                  # cached
        self.assertTrue(bot.refused("22", RuntimeError("HTTP Error 403: Forbidden")))
        self.assertEqual(bot.memory_channels(cfg), ["10", "20"])

    # -- profiles, pings, reactions, lines ----------------------------------------
    def test_seed_loads_once_and_keeps_what_was_learned(self):
        Path(bot.SEED_PATH).write_text(json.dumps({"group": "Murf time: estimates run double",
                                                   "people": {"2": {"handle": "@tomboe", "notes": "LIRR"},
                                                              "3": {"handle": "@antwah", "notes": "polls"}}}),
                                       encoding="utf-8")
        db = self.db()
        db.set_profile("3", "learned already", "@antwah")
        self.assertEqual(bot.load_seed(db), 2)
        self.assertEqual(bot.load_seed(db), 0)
        self.assertEqual((db.profile("group")["notes"], db.profile("2")["source"], db.profile("3")["notes"]),
                         ("Murf time: estimates run double", "seed", "learned already"))

    def test_pings_reactions_and_recent_replies(self):
        db = self.db()
        db.log_ping(100, "10", "2", "@tomboe", "q1", 101, "a1")
        db.log_ping(200, "10", "3", "@antwah", "q2", 201, "a2")
        self.assertTrue(db.react(101, "😂"))
        db.react(101, "😂")
        db.react(101, "👎")
        db.react(101, "👎", -1)
        self.assertFalse(db.react(999, "😂"))                               # not one of WB's replies
        self.assertEqual(json.loads(db.unlearned_pings()[0]["reactions"]), {"😂": 2})
        self.assertEqual(db.recent_replies(5), ["a1", "a2"])

    def test_lines_are_written_ahead_and_used_with_the_name(self):
        db = self.db()
        self.assertIsNone(bot.limit_line(self.cfg(), "7"))
        db.set_lines("limit", ["out of words, {name}"])
        self.assertEqual(bot.limit_line(self.cfg(), "7"), "out of words, <@7>")
        db.set_lines("limit", ["new voice, {name}"])
        self.assertEqual(bot.limit_line(self.cfg(), "7"), "new voice, <@7>")

    def test_reset_reloads_the_seed_and_health_reports(self):
        Path(bot.SEED_PATH).write_text(json.dumps({"group": "lore"}), encoding="utf-8")
        db = self.db()
        db.add([self.row(1)])
        db.set_profile("self", "me")
        h = bot.memory_health(self.cfg())
        self.assertEqual((h["enabled"], h["messages"], h["profiles"]), (True, 1, 1))
        db.reset()
        self.assertEqual((db.count(), db.profiles()), (0, []))
        self.assertEqual(bot.load_seed(db), 1)
        self.assertEqual(bot.memory_health(self.cfg(memory=False)), {"enabled": False})

    # -- the nightly learning ---------------------------------------------------
    def learn_with(self, answers):
        """Run learn() with the model stubbed; answers maps a prompt marker to text."""
        seen = []

        def fake_ask(cfg, system, user, log=print, **over):
            seen.append(user)
            for marker, text in answers.items():
                if marker in user:
                    return text
            return None
        with patch.object(mr, "ask", side_effect=fake_ask):
            calls = bot.learn(self.db(), self.cfg())
        return calls, seen

    def test_learning_updates_active_people_group_self_and_lines(self):
        db = self.db()
        db.add([self.row(i, f"tom {i}") for i in range(1, 6)] +
               [self.row(10, "ant once", "@antwah", "3")] +
               [self.row(20, "a bot post", "@WB", BOT_ID, is_bot=True)])
        db.log_ping(30, "10", "3", "@antwah", "rate my car", 31, "solid 6")
        db.react(31, "😂")
        calls, seen = self.learn_with({
            "notes on @tomboe": "@tomboe: says tom a lot", "notes on @antwah": "@antwah: rates cars",
            "on the group": "group: tom posts", "about yourself": "you: car ratings land",
            "LIMIT:": "LIMIT:\nout of words {name}\nno name line\nPESTER:\nslow down {name}"})
        self.assertEqual(calls, 5)
        self.assertEqual(db.profile("2")["notes"], "@tomboe: says tom a lot")
        self.assertEqual(db.profile("3")["notes"], "@antwah: rates cars")   # few messages, but a ping
        self.assertEqual(db.profile("group")["notes"], "group: tom posts")
        self.assertEqual(db.profile("self")["notes"], "you: car ratings land")
        self.assertIn("😂x1", next(u for u in seen if "notes on @antwah" in u))
        self.assertEqual(db.line("limit"), "out of words {name}")           # lines without {name} dropped
        self.assertEqual((db.unlearned(), db.unlearned_pings()), ([], []))

    def test_learning_stops_at_the_budget_and_resumes_tomorrow(self):
        db = self.db()
        db.add([self.row(i, "x") for i in range(1, 4)] + [self.row(10 + i, "y", "@antwah", "3") for i in range(3)])
        with patch.object(mr, "usage", return_value={"calls": 100, "input_tokens": 0, "output_tokens": 0,
                                                     "date": "d"}):
            calls, _ = self.learn_with({"": "notes"})
        self.assertEqual(calls, 0)
        self.assertEqual(len(db.unlearned()), 6)                             # nothing marked, nothing lost
        self.assertTrue(bot.learn_due(db, datetime(2026, 11, 7, 3)))
        db.set_meta("last_learn", "2026-11-07T03:00:00")
        self.assertFalse(bot.learn_due(db, datetime(2026, 11, 7, 4)))
        self.assertFalse(bot.learn_due(db, datetime(2026, 11, 8, 2)))        # before LEARN_HOUR

    # -- replies ----------------------------------------------------------------
    def test_reply_prompt_has_profiles_reply_context_and_message_last(self):
        db = self.db()
        db.set_profile("self", "you are dry")
        db.set_profile("2", "takes the LIRR", "@tomboe")
        db.set_profile("3", "makes polls", "@antwah")
        db.log_ping(1, "10", "2", "@tomboe", "q", 2, "earlier answer")
        seen = {}

        def fake_ask(cfg, system, user, log=print, **over):
            seen.update(system=system, user=user)
            return "Take the 8:12, @tomboe."
        with patch.object(mr, "ask", side_effect=fake_ask), \
                patch.object(bot, "reply_facts", side_effect=AssertionError("no weather for chat")):
            line = bot.model_answer(self.cfg(), "2", "Tom", f"<@{BOT_ID}> what train should <@3> take", "chat",
                                    ["@antwah: hi"], replied_to="WB: earlier answer", mentioned=["3"],
                                    own_id=BOT_ID)
        self.assertEqual(line, "Take the 8:12, <@2>.")
        self.assertIn("you are dry", seen["system"])
        self.assertIn("@tomboe: takes the LIRR", seen["system"])
        self.assertIn("@antwah: makes polls", seen["system"])
        self.assertIn("- earlier answer", seen["user"])
        self.assertTrue(seen["user"].endswith("@tomboe says: what train should @antwah take\n\nReply to @tomboe."))

    def test_old_forecasts_in_the_chat_are_reduced_to_a_note(self):
        self.assertEqual(bot.chat_line(BOT_ID, "WB", "@everyone Bellerose 61°, 40% rain", is_bot=True),
                         "WB: [posted a forecast]")
        self.assertEqual(bot.chat_line("5", "Daily Weather Report", "", bot_author=True),
                         "@Daily Weather Report: [posted a forecast]")
        self.assertEqual(bot.chat_line(BOT_ID, "WB", "GASP! scandalized!", is_bot=True), "WB: GASP! scandalized!")
        self.assertEqual(bot.chat_line("2", "Tom", "it's 61° and gross"), "@tomboe: it's 61° and gross")  # people stay
        self.assertIn("never state a temperature", mr.RULES.lower())

    def test_weather_numbers_only_for_a_weather_ask(self):
        facts = {"town": "Bellerose", "hi": 61, "lo": 42, "feels": 56, "cond": "Overcast", "rain": 0}
        with patch.object(mr, "ask", return_value="61 and grey.") as ask, \
                patch.object(bot, "reply_facts", return_value=facts):
            bot.model_answer(self.cfg(), "2", "Tom", "how's the laundry", "chat", [])
            self.assertNotIn("Weather numbers", ask.call_args.args[2])
            bot.model_answer(self.cfg(), "2", "Tom", "tell me my weather", "weather", [])
            self.assertIn("Bellerose: high 61", ask.call_args.args[2])

    # -- nightly notes through the Batch API ----------------------------------------
    def batch_day(self):
        db = self.db()
        db.add([self.row(i, f"tom {i}") for i in range(1, 6)] + [self.row(10, "once", "@antwah", "3")] +
               [self.row(20, "bot post", "@WB", BOT_ID, is_bot=True)])
        db.log_ping(30, "10", "2", "@tomboe", "rate my car", 31, "solid 6")
        return db, self.cfg(learn_batch=True, learn_model="claude-sonnet-5-5")

    @staticmethod
    def message(text, stop="end_turn"):
        from types import SimpleNamespace as NS
        return NS(model="claude-sonnet-5-5", stop_reason=stop, content=[NS(type="text", text=text)],
                  usage=NS(input_tokens=2000, output_tokens=500, cache_read_input_tokens=0,
                           cache_creation_input_tokens=0))

    def test_batch_submit_sends_every_job_on_the_learn_model_and_marks_nothing_yet(self):
        db, cfg = self.batch_day()
        with patch.object(mr, "batch_submit", return_value="msgbatch_1") as submit:
            self.assertEqual(bot.learn_submit(db, cfg), 4)                    # tom, group, self, lines
        reqs = submit.call_args.args[0]
        self.assertEqual(sorted(r["custom_id"] for r in reqs), ["group", "lines", "p-2", "self"])
        self.assertEqual({r["params"]["model"] for r in reqs}, {"claude-sonnet-5-5"})
        self.assertEqual([r["id"] for r in db.unlearned()], [1, 2, 3, 4, 5])  # quiet @antwah and the bot: free
        self.assertEqual(json.loads(db.get_meta("learn_batch"))["id"], "msgbatch_1")
        with patch.object(mr, "batch_status", return_value="in_progress"):
            self.assertEqual(bot.learn_collect(db, cfg, datetime(2026, 11, 10, 4, 0)), "waiting")

    def test_batch_results_are_saved_and_failures_run_on_the_regular_path(self):
        db, cfg = self.batch_day()
        with patch.object(mr, "batch_submit", return_value="msgbatch_1"):
            bot.learn_submit(db, cfg)
        results = [("p-2", "succeeded", self.message("@tomboe: says tom a lot")),
                   ("group", "errored", None),
                   ("self", "succeeded", self.message("x", stop="refusal")),
                   ("lines", "succeeded", self.message("LIMIT:\nbye {name}\nPESTER:\nslow {name}"))]
        with patch.object(mr, "batch_status", return_value="ended"), \
                patch.object(mr, "batch_results", return_value=results), \
                patch.object(mr, "ask", return_value="regular-path notes") as ask:
            self.assertEqual(bot.learn_collect(db, cfg, datetime(2026, 11, 10, 4, 0)), "done")
        self.assertEqual(db.profile("2")["notes"], "@tomboe: says tom a lot")
        self.assertEqual(sorted(c.kwargs["job"] for c in ask.call_args_list), ["learn_group", "learn_self"])
        self.assertEqual((db.profile("group")["notes"], db.profile("self")["notes"]),
                         ("regular-path notes", "regular-path notes"))
        self.assertEqual(db.line("limit"), "bye {name}")
        self.assertEqual((db.unlearned(), db.get_meta("learn_batch")), ([], ""))
        batch_rows = [r for r in db.recent_calls() if r["batch"]]
        self.assertEqual(len(batch_rows), 3)
        self.assertAlmostEqual(batch_rows[0]["cost_usd"], 0.0045)            # (2000 x $2 + 500 x $10) / M, halved

    def test_batch_still_running_at_the_deadline_is_canceled_and_done_the_regular_way(self):
        db, cfg = self.batch_day()
        with patch.object(mr, "batch_submit", return_value="msgbatch_1"):
            bot.learn_submit(db, cfg)
        with patch.object(mr, "batch_status", return_value="in_progress"), \
                patch.object(mr, "batch_cancel") as cancel, \
                patch.object(mr, "batch_results", side_effect=AssertionError("not read while running")), \
                patch.object(mr, "ask", return_value="@tomboe: late notes") as ask:
            self.assertEqual(bot.learn_collect(db, cfg, datetime(2026, 11, 10, 6, 30)), "done")
        cancel.assert_called_once_with("msgbatch_1")
        self.assertEqual(ask.call_count, 4)
        self.assertEqual(db.profile("2")["notes"], "@tomboe: late notes")
        self.assertEqual(bot.learn_collect(db, cfg), "none")

    def test_batch_submit_failure_falls_back_to_tonights_regular_learning(self):
        db, cfg = self.batch_day()
        with patch.object(mr, "batch_submit", side_effect=RuntimeError("batches down")), \
                patch.object(mr, "ask", return_value="notes") as ask:
            bot.learn_submit(db, cfg)
        self.assertGreater(ask.call_count, 0)
        self.assertEqual(db.get_meta("learn_batch"), None)
        self.assertIsNone(mr.validate(self.cfg(learn_batch=True, learn_model="claude-sonnet-5-5")))
        self.assertIsNotNone(mr.validate(self.cfg(learn_batch="yes")))
        self.assertFalse(mr.DEFAULTS["learn_batch"])                          # ships switched off

    # -- usage log -----------------------------------------------------------------
    def test_every_call_is_logged_with_job_tokens_cost_and_status(self):
        from types import SimpleNamespace as NS
        ok = NS(usage=NS(input_tokens=3000, output_tokens=400, cache_read_input_tokens=0,
                         cache_creation_input_tokens=0), stop_reason="end_turn", content=[NS(type="text", text="Hi!")])
        with patch.object(mr, "_create", return_value=ok):
            bot.model_answer(self.cfg(), "2", "Tom", "hello", "chat", [])
        rate = RuntimeError("rate limited")
        rate.status_code = 429
        with patch.object(mr, "_create", side_effect=rate):
            mr.ask(self.cfg(), "s", "u", log=lambda *_: None, job="morning")
        with patch.object(mr, "_create", return_value=ok):
            mr.ask(self.cfg(memory=False), "s", "u", log=lambda *_: None, job="chat")   # memory off: not logged
        rows = list(reversed(self.db().recent_calls()))
        self.assertEqual([(r["job"], r["status"], r["model"]) for r in rows],
                         [("chat", "ok", "claude-haiku-5-5"), ("morning", "error:429", "claude-haiku-5-5")])
        self.assertEqual((rows[0]["input_tokens"], rows[0]["output_tokens"]), (3000, 400))
        self.assertAlmostEqual(rows[0]["cost_usd"], 0.0005)                    # 3000 x $0.10 + 400 x $0.50 per M
        self.assertIsNotNone(rows[0]["latency_ms"])
        summary = self.db().call_summary()
        self.assertEqual(sorted((r["job"], r["calls"], r["failures"]) for r in summary),
                         [("chat", 1, 0), ("morning", 1, 1)])

    def test_daily_numbers_for_homelab_db_carry_no_text(self):
        db = self.db()
        day = datetime.now(timezone.utc).date().isoformat()
        for ms, status in ((100, "ok"), (300, "ok"), (2000, "error:529")):
            db.log_call({"ts": f"{day}T12:00:00+00:00", "job": "chat", "model": "claude-haiku-5-5",
                         "status": status, "input_tokens": 1000, "output_tokens": 100, "latency_ms": ms,
                         "cost_usd": 0.00015})
        db.log_ping(1, "10", "2", "@tomboe", "secret question", 2, "secret answer")
        rows = db.daily()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["day"], r["calls"], r["failures"], r["input_tokens"], r["pings"], r["p95_ms"]),
                         (day, 3, 1, 3000, 1, 2000))
        self.assertAlmostEqual(r["cost_usd"], 0.00045)
        self.assertNotIn("secret", json.dumps(rows))

    def test_cost_estimates_and_old_call_rows_are_pruned(self):
        self.assertEqual(mr.cost("claude-haiku-5-5", 1_000_000, 0), 0.1)
        self.assertEqual(mr.cost("claude-sonnet-5-5", 1_000_000, 1_000_000, batch=True), 6.0)
        self.assertEqual(mr.cost("claude-sonnet-5-5", 0, 0, cache_read=1_000_000), 0.2)
        self.assertIsNone(mr.cost("some-other-model", 10, 10))
        db = self.db()
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        db.log_call({"ts": old, "job": "chat", "model": "m", "status": "ok"})
        db.log_call({"ts": datetime.now(timezone.utc).isoformat(), "job": "chat", "model": "m", "status": "ok"})
        db.prune()
        self.assertEqual(len(db.recent_calls()), 1)

    # -- forgetting ----------------------------------------------------------------
    def forget(self):
        witty.use_persona({**PERSONA, "forget": {"terms": ["Voldemort", "just_a_thing"], "user_ids": ["666"]}})

    def test_forgotten_matches_names_ids_and_mentions_not_lookalikes(self):
        self.forget()
        for text in ("did voldemort's mom call", "JUST_A_THING said hi", "ask <@666>", "ask <@!666>"):
            self.assertTrue(witty.forgotten(text), text)
        self.assertTrue(witty.forgotten("hi", user_id="666"))
        for text in ("voldemortish vibes", "just a thing", "ask <@6667>"):
            self.assertFalse(witty.forgotten(text), text)
        self.assertEqual(witty.redact("where is Voldemort's wand"), "where is [removed] wand")
        self.assertIn("persona rejected", witty.use_persona({"forget": {"terms": ["x"]}}))
        witty.use_persona(None)
        self.assertFalse(witty.forgotten("voldemort"))

    def test_forgotten_is_never_stored_said_or_learned(self):
        db = self.db()
        db.add([self.row(1, "voldemort said hi"), self.row(2, "fine"), self.row(3, "hi", "@x", "666")])
        db.log_ping(10, "10", "2", "@tomboe", "where is voldemort", 11, "no idea")
        db.set_profile("2", "likes soup\nowes Voldemort money")
        db.set_profile("666", "gone")
        db.set_lines("limit", ["voldemort {name}", "fine {name}"])
        self.forget()
        self.assertEqual(db.purge(lambda t: witty.forgotten(t), witty.FORGET["user_ids"]), 3)
        self.assertEqual(([r["id"] for r in db.unlearned()], db.unlearned_pings()), ([2], []))
        self.assertEqual((db.profile("2")["notes"], db.profile("666")["notes"]), ("likes soup", ""))
        self.assertEqual(db.line("limit"), "fine {name}")
        for m in (msg(7, text="ask voldemort"), msg(8, author="666"), msg(9, text="hi <@666>")):
            self.assertIsNone(bot.to_row(m, "10", BOT_ID))
        seen = {}

        def fake_ask(cfg, system, user, log=print, **over):
            seen["user"] = user
            return "No comment."
        with patch.object(mr, "ask", side_effect=fake_ask):
            bot.model_answer(self.cfg(), "2", "Tom", "<@900> where's voldemort", "chat", [])
        self.assertIn("[removed]", seen["user"])
        self.assertNotIn("voldemort", seen["user"].lower())
        with patch.object(mr, "ask", return_value="Voldemort says hi."):
            self.assertIsNone(bot.model_answer(self.cfg(), "2", "Tom", "hi", "chat", []))
        db.add([self.row(i, "x") for i in range(20, 25)])
        calls, _ = self.learn_with({"notes on @tomboe": "@tomboe: soup\nVoldemort bit"})
        self.assertEqual(db.profile("2")["notes"], "@tomboe: soup")


if __name__ == "__main__":
    unittest.main()
