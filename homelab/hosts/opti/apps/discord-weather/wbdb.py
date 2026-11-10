"""WBdb: what Weather Bot knows about the group, learned day by day.

One SQLite file on the bot's data volume (/data/wb.sqlite, on opti's ZFS
pool). It holds:
  - messages: what was said in the server's channels since the bot started
    reading, until the nightly learning has used them (then kept 30 days)
  - profiles: WB's notes on each person, on the group, and on itself ("self"),
    seeded once from a private seed file and rewritten nightly by the model
  - pings: what people asked WB, what it answered, and the emoji reactions
    that answer got, so the nightly learning knows what landed
  - lines: short lines WB wrote ahead of time for when it can't call the model
    (out of words for the day, someone pinging too fast)
  - channels / meta: read positions and bookkeeping

Discord stays the source of truth for messages; a file that fails its startup
check is set aside and replaced by an empty one. The profiles are the part
that can't be re-read, and the nightly backup (VACUUM INTO a dated copy)
covers them. Stdlib only, one connection behind a lock.
"""
import json
import os
import random
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,   -- Discord snowflake, so ordered by time
    channel_id TEXT NOT NULL,
    author_id  TEXT NOT NULL,
    author     TEXT NOT NULL,         -- the persona @handle, else @display name
    is_bot     INTEGER NOT NULL DEFAULT 0,
    ts         TEXT NOT NULL,
    content    TEXT NOT NULL,         -- mentions already turned into handles
    learned    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS messages_learned ON messages(learned, id);
CREATE INDEX IF NOT EXISTS messages_author ON messages(author_id, id);
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    newest_id  INTEGER                -- read forward from here
);
CREATE TABLE IF NOT EXISTS profiles (
    subject    TEXT PRIMARY KEY,      -- a Discord user id, "group" or "self"
    handle     TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    updated_at TEXT,
    source     TEXT NOT NULL DEFAULT 'learned'   -- seed | learned | edited
);
CREATE TABLE IF NOT EXISTS pings (
    message_id TEXT PRIMARY KEY,      -- the person's message
    channel_id TEXT NOT NULL,
    author_id  TEXT NOT NULL,
    author     TEXT NOT NULL,
    text       TEXT NOT NULL,
    reply_id   TEXT,                  -- WB's answer
    reply      TEXT,
    ts         TEXT NOT NULL,
    reactions  TEXT NOT NULL DEFAULT '{}',   -- {"emoji": count}
    learned    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS pings_reply ON pings(reply_id);
CREATE TABLE IF NOT EXISTS lines (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,               -- limit | pester
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (            -- one row per Claude API call
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,          -- UTC
    job           TEXT NOT NULL,          -- chat | weather | full | morning | learn_person | ...
    model         TEXT NOT NULL,
    status        TEXT NOT NULL,          -- ok | refusal | empty | error:<status>
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read    INTEGER NOT NULL DEFAULT 0,
    cache_write   INTEGER NOT NULL DEFAULT 0,
    latency_ms    INTEGER,
    batch         INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL
);
CREATE INDEX IF NOT EXISTS calls_ts ON calls(ts);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
KEEP_DAYS = 30
CALLS_KEEP_DAYS = 90


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WBDB:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.note = ""          # what open() had to do, for /health
        self.conn = self._open()

    # -- open, check, rebuild ------------------------------------------------
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=10000")
        except Exception:
            conn.close()   # release the file so a bad one can be moved aside
            raise
        return conn

    def _open(self):
        """Connect and check. A file that fails quick_check (or won't open) is
        renamed aside and replaced by an empty one."""
        try:
            conn = self._connect()
            ok = conn.execute("PRAGMA quick_check").fetchone()[0]
            if ok != "ok":
                raise sqlite3.DatabaseError(f"quick_check: {ok}")
            conn.executescript(SCHEMA)
            return conn
        except sqlite3.DatabaseError as e:
            try:
                conn.close()
            except Exception:
                pass
            aside = f"{self.path}.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(self.path + suffix):
                    os.replace(self.path + suffix, aside + suffix)
            self.note = f"set aside {os.path.basename(aside)} ({e}); starting empty"
            conn = self._connect()
            conn.executescript(SCHEMA)
            return conn

    def close(self):
        with self.lock:
            self.conn.close()

    def _tx(self, statements):
        """Run [(sql, args), ...] in one transaction."""
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                for sql, args in statements:
                    self.conn.execute(sql, args)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # -- messages --------------------------------------------------------------
    def add(self, rows):
        """Insert messages (already filtered) in one transaction; repeats are
        ignored. Returns how many were new."""
        if not rows:
            return 0
        with self.lock:
            before = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            self._tx([("INSERT OR IGNORE INTO messages (id, channel_id, author_id, author, is_bot, ts, content) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (int(r["id"]), r["channel_id"], r["author_id"], r["author"], int(bool(r.get("is_bot"))),
                        r["ts"], r["content"])) for r in rows])
            return self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] - before

    def count(self, channel_ids=None):
        with self.lock:
            if channel_ids is None:
                return self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            marks = ",".join("?" * len(channel_ids)) or "''"
            return self.conn.execute(f"SELECT COUNT(*) FROM messages WHERE channel_id IN ({marks})",
                                     [str(c) for c in channel_ids]).fetchone()[0]

    def unlearned(self, limit=5000):
        """Messages the nightly learning hasn't used yet, oldest first."""
        with self.lock:
            rows = self.conn.execute("SELECT * FROM messages WHERE learned = 0 ORDER BY id LIMIT ?",
                                     (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_learned(self, message_ids=(), ping_ids=()):
        self._tx([("UPDATE messages SET learned = 1 WHERE id = ?", (int(i),)) for i in message_ids] +
                 [("UPDATE pings SET learned = 1 WHERE message_id = ?", (str(i),)) for i in ping_ids])

    def prune(self, now=None):
        """Drop learned messages older than KEEP_DAYS and call rows older than
        CALLS_KEEP_DAYS. Returns how many messages went."""
        now = now or datetime.now(timezone.utc)
        with self.lock:
            before = self.count()
            self.conn.execute("DELETE FROM messages WHERE learned = 1 AND ts < ?",
                              ((now - timedelta(days=KEEP_DAYS)).isoformat(),))
            self.conn.execute("DELETE FROM calls WHERE ts < ?",
                              ((now - timedelta(days=CALLS_KEEP_DAYS)).isoformat(),))
            return before - self.count()

    # -- usage log -------------------------------------------------------------
    CALL_COLS = ("ts", "job", "model", "status", "input_tokens", "output_tokens", "cache_read",
                 "cache_write", "latency_ms", "batch", "cost_usd")

    def log_call(self, row):
        """Store one API call (see model_reply.report for the shape)."""
        with self.lock:
            self.conn.execute(f"INSERT INTO calls ({', '.join(self.CALL_COLS)}) "
                              f"VALUES ({', '.join('?' * len(self.CALL_COLS))})",
                              [row.get(c) if c in ("latency_ms", "cost_usd") or c in ("ts", "job", "model", "status")
                               else int(row.get(c) or 0) for c in self.CALL_COLS])

    def daily(self, days=14, now=None):
        """One row per UTC day for homelab-db: calls, failures, tokens, $,
        latency (mean, p95) and pings answered. Numbers only, no chat text."""
        since = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
        out = {}
        with self.lock:
            for r in self.conn.execute(
                    "SELECT substr(ts, 1, 10) AS day, COUNT(*) AS calls, SUM(status != 'ok') AS failures, "
                    "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
                    "SUM(cache_read) AS cache_read, ROUND(SUM(COALESCE(cost_usd, 0)), 6) AS cost_usd, "
                    "CAST(AVG(latency_ms) AS INTEGER) AS avg_ms FROM calls WHERE ts >= ? GROUP BY day",
                    (since,)):
                out[r["day"]] = {**dict(r), "p95_ms": None, "pings": 0}
            for day, lats in self.conn.execute(
                    "SELECT substr(ts, 1, 10), GROUP_CONCAT(latency_ms) FROM calls "
                    "WHERE ts >= ? AND latency_ms IS NOT NULL GROUP BY 1", (since,)):
                vals = sorted(int(v) for v in (lats or "").split(",") if v)
                if day in out and vals:
                    out[day]["p95_ms"] = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
            for day, n in self.conn.execute(
                    "SELECT substr(ts, 1, 10), COUNT(*) FROM pings WHERE ts >= ? GROUP BY 1", (since,)):
                out.setdefault(day, {"day": day, "calls": 0, "failures": 0, "input_tokens": 0,
                                     "output_tokens": 0, "cache_read": 0, "cost_usd": 0.0,
                                     "avg_ms": None, "p95_ms": None})["pings"] = n
        return [out[d] for d in sorted(out)]

    def recent_calls(self, n=50):
        with self.lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM calls ORDER BY id DESC LIMIT ?", (n,))]

    def call_summary(self, days=14, now=None):
        """Per day (UTC) and job: calls, failures, tokens, $ and mean latency."""
        since = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT substr(ts, 1, 10) AS day, job, COUNT(*) AS calls, "
                "SUM(status != 'ok') AS failures, SUM(input_tokens) AS input_tokens, "
                "SUM(output_tokens) AS output_tokens, SUM(cache_read) AS cache_read, "
                "ROUND(SUM(COALESCE(cost_usd, 0)), 6) AS cost_usd, CAST(AVG(latency_ms) AS INTEGER) AS avg_ms "
                "FROM calls WHERE ts >= ? GROUP BY day, job ORDER BY day DESC, job", (since,))]

    # -- read positions --------------------------------------------------------
    def newest(self, channel_id):
        with self.lock:
            r = self.conn.execute("SELECT newest_id FROM channels WHERE channel_id = ?",
                                  (str(channel_id),)).fetchone()
        return r[0] if r else None

    def mark(self, channel_id, newest):
        """Move a channel's read position, forward only."""
        with self.lock:
            cur = self.newest(channel_id) or 0
            self.conn.execute("INSERT INTO channels (channel_id, newest_id) VALUES (?, ?) "
                              "ON CONFLICT(channel_id) DO UPDATE SET newest_id = excluded.newest_id",
                              (str(channel_id), max(cur, int(newest))))

    # -- profiles --------------------------------------------------------------
    def profile(self, subject):
        with self.lock:
            r = self.conn.execute("SELECT * FROM profiles WHERE subject = ?", (str(subject),)).fetchone()
        return dict(r) if r else {"subject": str(subject), "handle": "", "notes": "", "updated_at": None,
                                  "source": ""}

    def profiles(self):
        with self.lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM profiles ORDER BY subject")]

    def set_profile(self, subject, notes, handle=None, source="learned", limit=2500):
        cur = self.profile(subject)
        with self.lock:
            self.conn.execute(
                "INSERT INTO profiles (subject, handle, notes, updated_at, source) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(subject) DO UPDATE SET handle = excluded.handle, notes = excluded.notes, "
                "updated_at = excluded.updated_at, source = excluded.source",
                (str(subject), handle if handle is not None else cur["handle"], (notes or "").strip()[:limit],
                 _now(), source))

    def seed(self, data):
        """Load seed profiles once: {"group": "...", "self": "...", "people":
        {"<user id>": {"handle", "notes"}}}. Existing profiles are kept.
        Returns how many were added."""
        added = 0
        entries = [("group", "", data.get("group")), ("self", "", data.get("self"))]
        entries += [(uid, p.get("handle", ""), p.get("notes")) for uid, p in (data.get("people") or {}).items()]
        for subject, handle, notes in entries:
            if notes and not self.profile(subject)["notes"]:
                self.set_profile(subject, notes, handle, source="seed", limit=6000)
                added += 1
        return added

    # -- pings and reactions ----------------------------------------------------
    def log_ping(self, message_id, channel_id, author_id, author, text, reply_id, reply):
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO pings (message_id, channel_id, author_id, author, text, reply_id, reply, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(message_id), str(channel_id), str(author_id), author, text, str(reply_id or ""), reply, _now()))

    def react(self, reply_id, emoji, delta=1):
        """Count a reaction on one of WB's replies. False if it isn't one."""
        with self.lock:
            r = self.conn.execute("SELECT reactions FROM pings WHERE reply_id = ?", (str(reply_id),)).fetchone()
            if not r:
                return False
            counts = json.loads(r[0] or "{}")
            counts[emoji] = max(0, counts.get(emoji, 0) + delta)
            counts = {k: v for k, v in counts.items() if v}
            self.conn.execute("UPDATE pings SET reactions = ? WHERE reply_id = ?",
                              (json.dumps(counts, ensure_ascii=False), str(reply_id)))
            return True

    def recent_replies(self, n=5, channel_id=None):
        """WB's last n replies, oldest first."""
        sql, args = "SELECT reply FROM pings WHERE reply IS NOT NULL AND reply != ''", []
        if channel_id:
            sql += " AND channel_id = ?"
            args.append(str(channel_id))
        with self.lock:
            rows = self.conn.execute(sql + " ORDER BY ts DESC, rowid DESC LIMIT ?", args + [n]).fetchall()
        return [r[0] for r in reversed(rows)]

    def unlearned_pings(self):
        with self.lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM pings WHERE learned = 0 ORDER BY ts")]

    # -- canned lines ------------------------------------------------------------
    def set_lines(self, kind, texts):
        self._tx([("DELETE FROM lines WHERE kind = ?", (kind,))] +
                 [("INSERT INTO lines (kind, text) VALUES (?, ?)", (kind, t)) for t in texts])

    def line(self, kind):
        with self.lock:
            rows = [r[0] for r in self.conn.execute("SELECT text FROM lines WHERE kind = ?", (kind,))]
        return random.choice(rows) if rows else None

    # -- forgetting ----------------------------------------------------------------
    def purge(self, matches, user_ids=()):
        """Delete everything that names someone on the forget list: messages and
        pings whose text `matches(text)` or whose author is in user_ids, profile
        lines that match, and canned lines that match. Returns rows removed."""
        removed = 0
        ids = {str(u) for u in user_ids}
        with self.lock:
            msgs = [r["id"] for r in self.conn.execute("SELECT id, author_id, author, content FROM messages")
                    if r["author_id"] in ids or matches(r["content"]) or matches(r["author"])]
            pings = [r["message_id"] for r in self.conn.execute("SELECT message_id, author_id, text, reply FROM pings")
                     if r["author_id"] in ids or matches(r["text"]) or matches(r["reply"] or "")]
            stmts = [("DELETE FROM messages WHERE id = ?", (i,)) for i in msgs]
            stmts += [("DELETE FROM pings WHERE message_id = ?", (i,)) for i in pings]
            stmts += [("DELETE FROM profiles WHERE subject = ?", (u,)) for u in ids]
            for p in self.profiles():
                kept = [l for l in p["notes"].splitlines() if not matches(l)]
                if len(kept) != len(p["notes"].splitlines()):
                    stmts.append(("UPDATE profiles SET notes = ? WHERE subject = ?", ("\n".join(kept), p["subject"])))
            stmts += [("DELETE FROM lines WHERE id = ?", (r["id"],))
                      for r in self.conn.execute("SELECT id, text FROM lines") if matches(r["text"])]
            self._tx(stmts)
            removed = len(msgs) + len(pings)
        return removed

    def reset(self):
        """Forget everything (the seed loads again on the next pass)."""
        self._tx([(f"DELETE FROM {t}", ()) for t in ("messages", "channels", "profiles", "pings", "lines", "meta")])

    # -- bookkeeping -----------------------------------------------------------
    def get_meta(self, key, default=None):
        with self.lock:
            r = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key, value):
        with self.lock:
            self.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                              "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    def stats(self):
        with self.lock:
            q = lambda sql: self.conn.execute(sql).fetchone()[0]
            out = {"messages": q("SELECT COUNT(*) FROM messages"),
                   "unlearned": q("SELECT COUNT(*) FROM messages WHERE learned = 0"),
                   "profiles": q("SELECT COUNT(*) FROM profiles"),
                   "pings": q("SELECT COUNT(*) FROM pings"),
                   "lines": q("SELECT COUNT(*) FROM lines"),
                   "channels": q("SELECT COUNT(*) FROM channels")}
        size = sum(os.path.getsize(self.path + s) for s in ("", "-wal") if os.path.exists(self.path + s))
        return {**out, "bytes": size, "last_ingest_at": self.get_meta("last_ingest_at"),
                "last_learn": self.get_meta("last_learn"), "last_backup": self.get_meta("last_backup"),
                "note": self.note}

    def checkpoint(self):
        """Write the WAL back into the main file and truncate it. Returns
        (busy, wal pages, pages moved); busy=1 means a reader held it open."""
        with self.lock:
            return tuple(self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())

    def backup(self, dest_dir, day, keep=7):
        """A consistent copy as dest_dir/wb-<day>.sqlite (VACUUM INTO works on a
        live database), then prune to the newest `keep`. Returns the path."""
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"wb-{day}.sqlite")
        if not os.path.exists(dest):
            tmp = dest + ".tmp"
            if os.path.exists(tmp):
                os.remove(tmp)
            with self.lock:
                self.conn.execute("VACUUM INTO ?", (tmp,))
            os.replace(tmp, dest)
        copies = sorted(f for f in os.listdir(dest_dir) if re.fullmatch(r"wb-\d{4}-\d\d-\d\d\.sqlite", f))
        for old in copies[:-keep]:
            os.remove(os.path.join(dest_dir, old))
        self.set_meta("last_backup", f"{day} {dest}")
        return dest
