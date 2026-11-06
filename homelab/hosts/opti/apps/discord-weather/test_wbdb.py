"""Offline tests for WBdb (wbdb.py) and the bot's memory path: ingest,
backfill, folding, prompts, backups and the corrupt-file rebuild. Discord and
Anthropic are stubbed; the database is a real SQLite file in a temp folder."""
import importlib.util
import os
import threading
import uuid
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import model_reply as mr
import wbdb
import witty_messages as witty

spec = importlib.util.spec_from_file_location("bot", Path(__file__).with_name("discord-weather.py"))
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

PERSONA = {"pings": {"@tomboe": "2", "@antwah": "3"}, "word_banks": {"me": ["WB"]}}
BOT_ID = "900"


def snow(seconds_after_epoch):
    """A snowflake for a unix time, so message ages are controllable."""
    return int(bot.snowflake_at(seconds_after_epoch))


def msg(mid, author="2", text="hi", name="Tom"):
    return {"id": str(mid), "content": text, "embeds": [], "timestamp": "2026-11-01T12:00:00+00:00",
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
        self.patches = [patch.object(bot, "WBDB_PATH", str(folder / "wbdb.sqlite")),
                        patch.object(bot, "WBDB_BACKUP_DIR", str(folder / "backup")),
                        patch.object(bot, "BOT_TOKEN", "tok"),
                        patch.object(bot, "memory_channels", return_value=["10"]),
                        patch.object(mr, "USAGE_PATH", str(folder / "usage.json")),
                        patch.object(mr, "KEY_PATH", str(folder / "key")),
                        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}),
                        patch.object(mr, "anthropic", object())]
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
        self.addCleanup(cleanup)

    def cfg(self, **claude):
        return {**bot.DEFAULT_CONFIG, "guild_id": "1", "channel_id": "10", "timezone": "America/New_York",
                "claude": {**mr.DEFAULTS, "enabled": True, "memory": True, **claude}}

    def db(self):
        return bot.memory_db()

    def row(self, mid, text="hi", author="@tomboe", ch="10", author_id="2"):
        return {"id": mid, "channel_id": ch, "author_id": author_id, "author": author, "is_bot": False,
                "ts": "t", "content": text}

    # -- the store itself --------------------------------------------------------
    def test_add_is_idempotent_and_takes_edits(self):
        db = self.db()
        self.assertEqual(db.add([self.row(1), self.row(2, "rain again")]), 2)
        self.assertEqual(db.add([self.row(1), self.row(2, "rain AGAIN (edited)")]), 0)
        self.assertEqual([r["content"] for r in db.recent(["10"], 5)], ["hi", "rain AGAIN (edited)"])
        self.assertEqual([r["id"] for r in db.search("edited", 5)], [2])   # the index followed the edit

    def test_search_finds_old_bits_and_skips_whats_already_shown(self):
        db = self.db()
        db.add([self.row(1, "the great umbrella incident of july"), self.row(2, "nothing here"),
                self.row(3, "umbrella guy strikes again", "@antwah", author_id="3"), self.row(4, "lol")])
        self.assertEqual([r["id"] for r in db.search("what happened with the umbrella?", 5)], [1, 3])
        self.assertEqual([r["id"] for r in db.search("umbrella", 5, exclude=[3])], [1])
        self.assertEqual([r["id"] for r in db.search("antwah", 5)], [3])        # by handle
        self.assertEqual(db.search("the and what", 5), [])                     # stopwords only
        self.assertEqual(wbdb.WBDB.terms('"quoted" OR drop*'), ["quoted", "drop"])   # no FTS syntax leaks

    def test_positions_only_move_outward(self):
        db = self.db()
        db.mark("10", newest=50, oldest=40)
        db.mark("10", newest=45, oldest=42)
        self.assertEqual((db.channel("10")["newest_id"], db.channel("10")["oldest_id"]), (50, 40))
        db.mark("10", newest=60, oldest=30, backfilled=True)
        self.assertEqual(db.channel("10"), {"channel_id": "10", "newest_id": 60, "oldest_id": 30, "backfilled": 1})

    def test_corrupt_file_is_set_aside_and_rebuilt(self):
        path = self.folder / "bad.sqlite"
        path.write_bytes(b"this is not a database" * 100)
        db = wbdb.WBDB(str(path))
        self.addCleanup(db.close)
        self.assertIn("set aside", db.note)
        self.assertEqual(db.add([self.row(1)]), 1)
        self.assertTrue(any(f.startswith("bad.sqlite.corrupt-") for f in os.listdir(self.folder)))

    def test_backup_is_a_dated_consistent_copy_pruned_to_keep(self):
        db = self.db()
        db.add([self.row(1, "keep me")])
        dest = Path(self.folder / "backup")
        for day in ("2026-11-01", "2026-11-02", "2026-11-03"):
            db.backup(str(dest), day, keep=2)
        self.assertEqual(sorted(os.listdir(dest)), ["wbdb-2026-11-02.sqlite", "wbdb-2026-11-03.sqlite"])
        copy = wbdb.WBDB(str(dest / "wbdb-2026-11-03.sqlite"))
        self.addCleanup(copy.close)
        self.assertEqual(copy.recent(["10"], 5)[0]["content"], "keep me")
        self.assertTrue(db.get_meta("last_backup").startswith("2026-11-03"))
        self.assertFalse(bot.backup_due(db, datetime(2026, 11, 3, 4)))          # done today
        self.assertTrue(bot.backup_due(db, datetime(2026, 11, 4, 4)))
        self.assertFalse(bot.backup_due(db, datetime(2026, 11, 4, 2)))          # before BACKUP_HOUR

    def test_concurrent_writers_do_not_collide(self):
        db = self.db()
        errors = []

        def write(base):
            try:
                for i in range(50):
                    db.add([self.row(base + i)])
            except Exception as e:   # pragma: no cover - the assertion reports it
                errors.append(e)
        threads = [threading.Thread(target=write, args=(b,)) for b in (1000, 2000, 3000)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(db.count(["10"]), 150)

    # -- the bot's memory path ---------------------------------------------------
    def test_ingest_reads_forward_then_backfill_reaches_the_start(self):
        fake = FakeDiscord({"10": [msg(i, text=f"m{i}") for i in range(1, 1301)]})
        db = self.db()
        with patch.object(bot, "_discord_get", fake):
            self.assertEqual(bot.ingest(db, self.cfg()), 1000)                 # a new channel: last 1000
            self.assertEqual(db.channel("10")["oldest_id"], 301)
            bot.backfill(db, self.cfg(), pages=2, pause=0)
            self.assertEqual(db.count(["10"]), 1200)                         # two pages a pass
            self.assertFalse(db.channel("10")["backfilled"])
            bot.backfill(db, self.cfg(), pages=5, pause=0)
            self.assertTrue(db.channel("10")["backfilled"])
            fake.channels["10"].append(msg(1301, text="new one"))
            self.assertEqual(bot.ingest(db, self.cfg()), 1)
        self.assertEqual(db.recent(["10"], 1)[0]["content"], "new one")
        self.assertIsNotNone(db.get_meta("last_ingest_at"))

    def test_backfill_stops_at_the_configured_cap(self):
        fake = FakeDiscord({"10": [msg(i) for i in range(1, 3001)]})
        db = self.db()
        with patch.object(bot, "_discord_get", fake):
            bot.ingest(db, self.cfg(memory_backfill=1200))
            bot.backfill(db, self.cfg(memory_backfill=1200), pages=50, pause=0)
        self.assertLessEqual(db.count(["10"]), 1300)
        self.assertTrue(db.channel("10")["backfilled"])

    def test_rows_use_handles_and_label_the_bot(self):
        r = bot.to_row(msg(5, author="2", text="yo <@3> <@&8>"), "10", BOT_ID)
        self.assertEqual((r["author"], r["content"], r["is_bot"]), ("@tomboe", "yo @antwah @role", False))
        me = bot.to_row(msg(6, author=BOT_ID, text="", name="Weather-Bot") | {"embeds": [{}]}, "10", BOT_ID)
        self.assertEqual(bot.row_line(me, BOT_ID, "WB"), "WB: [embed]")

    def test_fold_waits_for_enough_then_moves_the_digest(self):
        db = self.db()
        now = 1_800_000_000
        db.add([self.row(snow(now - 60) + i, f"bit {i}") for i in range(10)])
        db.mark("10", backfilled=True)
        cfg = self.cfg()
        with patch.object(mr, "ask", return_value="NOTES: @tomboe keeps saying bit.") as ask:
            self.assertEqual(bot.fold(db, cfg, now=now), 0)                    # 10 new, 1 min old: wait
            ask.assert_not_called()
            self.assertEqual(bot.fold(db, cfg, now=now + bot.FOLD_MAX_AGE), 1)  # old enough now
        mem = db.memory("1")
        self.assertEqual(mem["digest"], "NOTES: @tomboe keeps saying bit.")
        self.assertEqual(mem["folded_through"], snow(now - 60) + 9)
        self.assertIn("bit 9", ask.call_args.args[2])
        self.assertIn("(empty: this is the start)", ask.call_args.args[2])
        self.assertEqual(db.count_unfolded(), 0)

    def test_fold_failure_keeps_the_old_digest_and_backlog(self):
        db = self.db()
        db.set_memory("1", "old notes")
        db.add([self.row(snow(1_800_000_000) + i) for i in range(50)])
        db.mark("10", backfilled=True)
        with patch.object(mr, "ask", return_value=None):
            self.assertEqual(bot.fold(db, self.cfg(), now=1_800_000_000), 0)
        self.assertEqual(db.memory("1")["digest"], "old notes")
        self.assertEqual(db.count_unfolded(), 50)

    def test_fold_backlog_is_chunked_and_leaves_calls_for_pings(self):
        db = self.db()
        db.add([self.row(snow(1_800_000_000) + i) for i in range(bot.FOLD_CHUNK * 7)])
        db.mark("10", backfilled=True)
        with patch.object(mr, "ask", return_value="notes") as ask:
            self.assertEqual(bot.fold(db, self.cfg(), now=1_800_000_000), bot.FOLDS_PER_PASS)
        self.assertEqual(ask.call_count, bot.FOLDS_PER_PASS)
        self.assertEqual(db.count_unfolded(), bot.FOLD_CHUNK * 2)
        with patch.object(mr, "usage", return_value={"calls": 100, "input_tokens": 0, "output_tokens": 0,
                                                     "date": "d"}), \
                patch.object(mr, "ask") as ask:
            self.assertEqual(bot.fold(db, self.cfg(daily_cap=150), now=1_800_000_000), 0)
            ask.assert_not_called()                                            # 100 >= 150 - 50
        heavy = {"calls": 10, "input_tokens": 200000, "output_tokens": 70000, "date": "d"}
        with patch.object(mr, "usage", return_value=heavy):
            self.assertFalse(bot.fold_ok(self.cfg(daily_tokens=400000)))       # a third kept for pings
            self.assertTrue(bot.fold_ok(self.cfg(daily_tokens=1500000)))
            self.assertTrue(bot.fold_ok(self.cfg(daily_tokens=0)))
        self.assertFalse(bot.fold_ok(self.cfg(memory=False)))

    def test_ping_context_has_notes_recent_and_related(self):
        db = self.db()
        db.set_memory("1", "@tomboe is the umbrella guy.")
        fake = FakeDiscord({"10": [msg(1, text="the umbrella saga begins"), msg(2, text="unrelated"),
                                   msg(3, author="3", text="cold today", name="Ant"),
                                   msg(4, text="<@900> what about the umbrella?")]})
        with patch.object(bot, "_discord_get", fake):
            digest, recent, related = bot.memory_context(self.cfg(memory_tail=2), "10", 4,
                                                         "<@900> what about the umbrella?")
        self.assertEqual(digest, "@tomboe is the umbrella guy.")
        self.assertEqual(recent, ["@tomboe: unrelated", "@antwah: cold today"])  # before the ping
        self.assertEqual(related, ["@tomboe: the umbrella saga begins"])         # the ping itself excluded
        self.assertIsNone(bot.memory_context(self.cfg(memory=False), "10", 4, "x"))
        with patch.object(bot, "memory_db", return_value=None):
            self.assertIsNone(bot.memory_context(self.cfg(), "10", 4, "x"))     # falls back to live history

    def test_prompts_carry_memory_and_the_honesty_rule(self):
        system, user = mr.build_prompt("Be WB.", ["@tomboe"], ["@tomboe: hi"], "@antwah", "umbrella?",
                                       "wild", {}, [], digest="@tomboe is the umbrella guy.",
                                       related=["@tomboe: the umbrella saga begins"])
        self.assertIn("Your notes on this group", system)
        self.assertIn("@tomboe is the umbrella guy.", system)
        self.assertIn("never present made-up logs", system)
        self.assertIn("don't disclaim", system)
        self.assertIn("Do not talk about the weather unless", system)
        self.assertIn("matching", user.replace("that match this ping", "matching"))
        self.assertIn("oldest first:\n@tomboe: the umbrella saga begins", user)
        self.assertIn("Recent chat, oldest first:\n@tomboe: hi", user)
        system, _ = mr.build_morning_prompt("Be WB.", [], [], [], "", [], digest="notes!")
        self.assertIn("notes!", system)
        _, plain = mr.build_prompt("Be WB.", [], [], "@x", "p", "wild", {}, [])
        self.assertNotIn("Older messages", plain)
        self.assertIsNone(mr.validate(self.cfg(memory_tail=100, memory_related=60, memory_backfill=0)))
        for bad in ({"memory": "on"}, {"memory_tail": 101}, {"memory_backfill": -1}):
            self.assertIsNotNone(mr.validate({"claude": bad}), bad)

    def test_reset_and_health(self):
        db = self.db()
        db.add([self.row(1)])
        db.set_memory("1", "notes", [1])
        h = bot.memory_health(self.cfg())
        self.assertEqual((h["enabled"], h["messages"], h["digest_chars"], h["unfolded"]), (True, 1, 5, 0))
        db.reset("1")
        self.assertEqual((db.memory("1")["digest"], db.count(["10"])), ("", 1))   # notes only
        db.reset("1", everything=True)
        self.assertEqual((db.count(["10"]), db.channel("10")["newest_id"]), (0, None))
        self.assertEqual(bot.memory_health(self.cfg(memory=False)), {"enabled": False})

    # -- every channel, in any order ---------------------------------------------
    def test_memory_channels_lists_the_server_minus_skips_and_refusals(self):
        self.patches[3].stop()   # the real memory_channels
        self.addCleanup(self.patches[3].start)
        self.addCleanup(lambda: (bot._channels.update(at=None, ids=[]), bot._unreadable.clear()))
        bot._channels.update(at=None, ids=[])
        listing = [{"id": "20", "type": 0, "position": 2}, {"id": "21", "type": 2, "position": 3},   # voice
                   {"id": "22", "type": 5, "position": 1}, {"id": "23", "type": 0, "position": 4}]
        cfg = self.cfg(memory_skip_channels=["23"])
        with patch.object(bot, "_discord_get", return_value=listing) as get:
            self.assertEqual(bot.memory_channels(cfg), ["10", "22", "20"])   # post channel first
            bot.memory_channels(cfg)
        self.assertEqual(get.call_count, 1)                                  # cached
        self.assertTrue(bot.refused("22", RuntimeError("HTTP Error 403: Forbidden")))
        self.assertFalse(bot.refused("20", RuntimeError("HTTP Error 500")))
        self.assertEqual(bot.memory_channels(cfg), ["10", "20"])
        bot._channels.update(at=None)
        with patch.object(bot, "_discord_get", side_effect=RuntimeError("down")):
            self.assertEqual(bot.memory_channels(cfg), ["10", "20"])         # last list stands

    def test_one_refused_channel_does_not_stop_the_rest(self):
        self.addCleanup(bot._unreadable.clear)
        real = FakeDiscord({"11": [msg(5, text="still read")]})

        def fake(path):
            if "/channels/10/" in path:
                raise RuntimeError("HTTP Error 403: Forbidden")
            return real(path)
        db = self.db()
        with patch.object(bot, "_discord_get", fake):
            self.assertEqual(bot.ingest(db, self.cfg(), channels=["10", "11"]), 1)
        self.assertIn("10", bot._unreadable)
        with patch.object(bot, "_discord_get", FakeDiscord({})):
            bot.ingest(db, self.cfg(), channels=["12"])
        self.assertTrue(db.channel("12")["backfilled"])                      # empty channel: nothing to wait for

    def test_notes_wait_for_history_and_older_messages_still_fold(self):
        db = self.db()
        now = 1_800_000_000
        db.add([self.row(snow(now) + i) for i in range(50)])
        with patch.object(mr, "ask", return_value="notes") as ask:
            self.assertEqual(bot.fold(db, self.cfg(), now=now), 0)           # history still loading
            ask.assert_not_called()
            db.mark("10", backfilled=True)
            self.assertEqual(bot.fold(db, self.cfg(), now=now), 1)
        db.add([self.row(snow(now - 86400), "from an older channel", ch="11")])
        self.assertEqual(db.count_unfolded(), 1)                             # older than the digest, still counted

    def test_old_file_migrates_to_the_folded_flag(self):
        path = str(self.folder / "old.sqlite")
        import sqlite3
        old = sqlite3.connect(path)
        schema = wbdb.SCHEMA.replace("    folded     INTEGER NOT NULL DEFAULT 0   -- already in the digest\n", "")
        schema = schema.replace("content    TEXT NOT NULL,  ", "content    TEXT NOT NULL   ")
        self.assertNotIn("folded  ", schema)
        old.executescript(schema)
        old.execute("INSERT INTO messages (id, channel_id, author_id, author, ts, content) "
                    "VALUES (1,'10','2','@a','t','in notes'), (9,'10','2','@a','t','not yet')")
        old.execute("INSERT INTO memory (scope, digest, folded_through) VALUES ('1', 'notes', 5)")
        old.commit()
        old.close()
        db = wbdb.WBDB(path)
        self.addCleanup(db.close)
        self.assertEqual([r["content"] for r in db.unfolded(10)], ["not yet"])

    # -- the persona's forget list ----------------------------------------------
    def forget(self):
        witty.use_persona({**PERSONA, "forget": {"terms": ["Voldemort", "Tom Riddle"], "user_ids": ["666"]}})

    def test_forgotten_matches_names_not_lookalikes(self):
        self.forget()
        self.assertTrue(witty.forgotten("did voldemort's mom call"))
        self.assertTrue(witty.forgotten("TOM RIDDLE again"))
        self.assertTrue(witty.forgotten("hi", user_id="666"))
        self.assertFalse(witty.forgotten("voldemortish vibes", "tom", user_id="2"))
        self.assertEqual(witty.redact("where is Voldemort's wand"), "where is [removed] wand")
        self.assertTrue(witty.forgotten("ask <@666> about it"))                 # an @mention counts
        self.assertTrue(witty.forgotten("ask <@!666> about it"))
        self.assertFalse(witty.forgotten("ask <@6667> about it"))
        self.assertIsNone(bot.to_row(msg(7, text="ask <@666>"), "10", BOT_ID))
        witty.use_persona({**PERSONA, "forget": {"terms": ["just_a_thing"]}})
        self.assertTrue(witty.forgotten("JUST_A_THING said hi"))                # usernames with underscores
        self.assertFalse(witty.forgotten("just a thing"))
        self.forget()
        self.assertIn("persona rejected", witty.use_persona({"forget": {"terms": ["x"]}}))
        self.assertIn("persona rejected", witty.use_persona({"forget": {"user_ids": ["bob"]}}))
        witty.use_persona(None)
        self.assertFalse(witty.forgotten("voldemort"))

    def test_forgotten_messages_are_never_stored_and_old_ones_are_purged(self):
        db = self.db()
        db.add([self.row(1, "voldemort said hi"), self.row(2, "fine"), self.row(3, "hi", "@x", author_id="666")])
        db.set_memory("1", "@tomboe likes soup.\nVoldemort owes @tomboe money.\n@antwah is late.", [1])
        self.forget()
        self.assertEqual(db.purge(witty.FORGET["terms"], witty.FORGET["user_ids"]), 2)
        self.assertEqual([r["id"] for r in db.recent(["10"], 5)], [2])
        self.assertEqual(db.search("voldemort", 5), [])
        self.assertEqual(db.memory("1")["digest"], "@tomboe likes soup.\n@antwah is late.")
        self.assertIsNone(bot.to_row(msg(7, text="ask voldemort"), "10", BOT_ID))
        self.assertIsNone(bot.to_row(msg(8, author="666"), "10", BOT_ID))
        self.assertIsNone(bot.to_row(msg(9, name="Voldemort"), "10", BOT_ID))
        fake = FakeDiscord({"10": [msg(20, text="ok"), msg(21, text="voldemort lol"), msg(22, text="ok too")]})
        db2 = wbdb.WBDB(str(self.folder / "two.sqlite"))
        self.addCleanup(db2.close)
        with patch.object(bot, "_discord_get", fake):
            bot.ingest(db2, self.cfg())
            self.assertEqual(db2.channel("10")["newest_id"], 22)             # the cursor still moves past it
            lines, _ = bot.chat_delta(self.cfg(memory=False), 50, now=0)
        self.assertEqual(db2.count(["10"]), 2)
        self.assertFalse(any("voldemort" in l for l in lines))

    def test_forgotten_names_never_reach_the_model_or_the_chat(self):
        self.forget()
        seen = {}

        def fake_ask(cfg, system, user, log=print, **over):
            seen["user"] = user
            return "Statement: no comment."
        with patch.object(mr, "ask", side_effect=fake_ask):
            self.assertEqual(bot.model_line(self.cfg(), "3", "<@1> where's voldemort", "wild", []),
                             "Statement: no comment.")
        self.assertNotIn("voldemort", seen["user"].lower())
        self.assertIn("[removed]", seen["user"])
        with patch.object(mr, "ask", return_value="Voldemort sends regards."):
            self.assertIsNone(bot.model_line(self.cfg(), "3", "<@1> hi", "wild", []))   # template instead
        db = self.db()
        db.add([self.row(snow(1_800_000_000) + i) for i in range(50)])
        db.mark("10", backfilled=True)
        with patch.object(mr, "ask", return_value="@tomboe soup.\nVoldemort bit.\n@antwah late."):
            bot.fold(db, self.cfg(), now=1_800_000_000)
        self.assertEqual(db.memory("1")["digest"], "@tomboe soup.\n@antwah late.")

    def test_weather_facts_only_for_an_explicit_ask(self):
        with patch.object(mr, "ask", return_value="ok"), patch.object(bot, "reply_facts", return_value={}) as facts:
            bot.model_line(self.cfg(), "3", "<@1> how's the laundry", "wild", [])
            facts.assert_not_called()
            bot.model_line(self.cfg(), "3", "<@1> tell me my weather", "weather", [])
            facts.assert_called_once()
        _, user = mr.build_prompt("", [], [], "@x", "laundry?", "wild", {}, [])
        self.assertNotIn("Weather right now", user)


if __name__ == "__main__":
    unittest.main()
