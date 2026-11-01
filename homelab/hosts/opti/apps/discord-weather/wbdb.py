"""WBdb: Weather Bot's memory of the chat.

One SQLite file on the bot's data volume (/data/wbdb.sqlite, on opti's ZFS
pool) holding every message the bot has read from its channels, a full-text
index over them, a per-channel read position, and the running notes ("digest")
the model keeps about the group. Discord stays the source of truth: the
messages can always be re-read, so a file that fails its startup check is set
aside and rebuilt rather than trusted. The digest is the only thing that can't
be re-read, and the nightly backup (VACUUM INTO a dated copy) covers it.

Stdlib only, one connection guarded by a lock: the bot has a handful of
writers (the memory loop, a ping's refresh) and they are short.
"""
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,   -- Discord snowflake, so ordered by time
    channel_id TEXT NOT NULL,
    author_id  TEXT NOT NULL,
    author     TEXT NOT NULL,         -- the persona @handle, else @display name
    is_bot     INTEGER NOT NULL DEFAULT 0,
    ts         TEXT NOT NULL,
    content    TEXT NOT NULL          -- mentions already turned into handles
);
CREATE INDEX IF NOT EXISTS messages_channel ON messages(channel_id, id);
CREATE INDEX IF NOT EXISTS messages_author ON messages(author_id, id);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
    USING fts5(content, author, content='messages', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, author) VALUES (new.id, new.content, new.author);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, author) VALUES ('delete', old.id, old.content, old.author);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, author) VALUES ('delete', old.id, old.content, old.author);
    INSERT INTO messages_fts(rowid, content, author) VALUES (new.id, new.content, new.author);
END;
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    newest_id  INTEGER,               -- read forward from here
    oldest_id  INTEGER,               -- backfill pages back from here
    backfilled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS memory (
    scope          TEXT PRIMARY KEY,  -- the guild id
    digest         TEXT NOT NULL DEFAULT '',
    folded_through INTEGER NOT NULL DEFAULT 0,   -- newest message id in the digest
    updated_at     TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

STOPWORDS = set("""
the and you your for are was were what who why how when where this that with have has had
not but can could would should will just like about from they them their there then than
its it's i'm im you're youre dont don't does did get got out all any our ours his her she him
weather bot wb hey yo lol lmao please tell know think say said one also really very much
""".split())
DIGEST_MAX = 12000   # characters; the prompt asks for far less, this is the backstop


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
        renamed aside and replaced by an empty one, which the bot refills from
        Discord. Returns the connection."""
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
            self.note = f"set aside {os.path.basename(aside)} ({e}); rebuilding from Discord"
            conn = self._connect()
            conn.executescript(SCHEMA)
            return conn

    def close(self):
        with self.lock:
            self.conn.close()

    # -- messages --------------------------------------------------------------
    def add(self, rows):
        """Insert or refresh (edited) messages in one transaction. Returns how
        many were new."""
        if not rows:
            return 0
        with self.lock:
            before = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            self.conn.execute("BEGIN")
            try:
                self.conn.executemany(
                    "INSERT INTO messages (id, channel_id, author_id, author, is_bot, ts, content) "
                    "VALUES (:id, :channel_id, :author_id, :author, :is_bot, :ts, :content) "
                    "ON CONFLICT(id) DO UPDATE SET content = excluded.content "
                    "WHERE content != excluded.content",
                    [{**r, "id": int(r["id"]), "is_bot": int(bool(r.get("is_bot")))} for r in rows])
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            return self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] - before

    def count(self, channel_ids):
        if not channel_ids:
            return 0
        marks = ",".join("?" * len(channel_ids))
        with self.lock:
            return self.conn.execute(f"SELECT COUNT(*) FROM messages WHERE channel_id IN ({marks})",
                                     [str(c) for c in channel_ids]).fetchone()[0]

    def recent(self, channel_ids, n, before_id=None):
        """The last n messages in these channels (before a message id), oldest first."""
        if not channel_ids or n <= 0:
            return []
        marks = ",".join("?" * len(channel_ids))
        sql = f"SELECT * FROM messages WHERE channel_id IN ({marks})"
        args = [str(c) for c in channel_ids]
        if before_id:
            sql += " AND id < ?"
            args.append(int(before_id))
        with self.lock:
            rows = self.conn.execute(sql + " ORDER BY id DESC LIMIT ?", args + [n]).fetchall()
        return [dict(r) for r in reversed(rows)]

    @staticmethod
    def terms(text):
        """Search words from a ping: 3+ letters, no stopwords, at most 8."""
        out = []
        for w in re.findall(r"[a-z0-9']{3,}", (text or "").lower()):
            w = w.strip("'")
            if len(w) >= 3 and w not in STOPWORDS and w not in out:
                out.append(w)
        return out[:8]

    def search(self, text, n, exclude=()):
        """Older messages most related to `text` (full-text, best first, then
        returned oldest first), skipping ids already in the prompt."""
        words = self.terms(text)
        if not words or n <= 0:
            return []
        query = " OR ".join(f'"{w}"' for w in words)
        skip = {int(i) for i in exclude}
        with self.lock:
            rows = self.conn.execute(
                "SELECT m.* FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid "
                "WHERE messages_fts MATCH ? ORDER BY bm25(messages_fts) LIMIT ?",
                (query, n + len(skip))).fetchall()
        hits = [dict(r) for r in rows if r["id"] not in skip][:n]
        return sorted(hits, key=lambda r: r["id"])

    # -- read positions --------------------------------------------------------
    def channel(self, channel_id):
        with self.lock:
            r = self.conn.execute("SELECT * FROM channels WHERE channel_id = ?", (str(channel_id),)).fetchone()
        return dict(r) if r else {"channel_id": str(channel_id), "newest_id": None, "oldest_id": None,
                                  "backfilled": 0}

    def mark(self, channel_id, newest=None, oldest=None, backfilled=None):
        """Move a channel's positions: newest only forward, oldest only back."""
        with self.lock:
            cur = self.channel(channel_id)
            nw = max(filter(None, [cur["newest_id"], int(newest) if newest else None]), default=None)
            od = min(filter(None, [cur["oldest_id"], int(oldest) if oldest else None]), default=None)
            bf = cur["backfilled"] if backfilled is None else int(bool(backfilled))
            self.conn.execute(
                "INSERT INTO channels (channel_id, newest_id, oldest_id, backfilled) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(channel_id) DO UPDATE SET newest_id = excluded.newest_id, "
                "oldest_id = excluded.oldest_id, backfilled = excluded.backfilled",
                (str(channel_id), nw, od, bf))

    # -- the digest ------------------------------------------------------------
    def memory(self, scope):
        with self.lock:
            r = self.conn.execute("SELECT * FROM memory WHERE scope = ?", (str(scope),)).fetchone()
        return dict(r) if r else {"scope": str(scope), "digest": "", "folded_through": 0, "updated_at": None}

    def set_memory(self, scope, digest, folded_through):
        with self.lock:
            self.conn.execute(
                "INSERT INTO memory (scope, digest, folded_through, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET digest = excluded.digest, "
                "folded_through = excluded.folded_through, updated_at = excluded.updated_at",
                (str(scope), (digest or "").strip()[:DIGEST_MAX], int(folded_through), _now()))

    def unfolded(self, scope, channel_ids, limit):
        """Messages newer than the digest in these channels, oldest first."""
        if not channel_ids:
            return []
        through = self.memory(scope)["folded_through"]
        marks = ",".join("?" * len(channel_ids))
        with self.lock:
            rows = self.conn.execute(
                f"SELECT * FROM messages WHERE id > ? AND channel_id IN ({marks}) ORDER BY id LIMIT ?",
                [through] + [str(c) for c in channel_ids] + [limit]).fetchall()
        return [dict(r) for r in rows]

    def count_unfolded(self, scope, channel_ids):
        if not channel_ids:
            return 0
        through = self.memory(scope)["folded_through"]
        marks = ",".join("?" * len(channel_ids))
        with self.lock:
            return self.conn.execute(
                f"SELECT COUNT(*) FROM messages WHERE id > ? AND channel_id IN ({marks})",
                [through] + [str(c) for c in channel_ids]).fetchone()[0]

    def reset(self, scope, everything=False):
        """Forget the digest (the messages stay and get folded again), or with
        everything=True wipe messages and positions too, so it re-reads Discord."""
        with self.lock:
            self.conn.execute("BEGIN")
            self.conn.execute("DELETE FROM memory WHERE scope = ?", (str(scope),))
            if everything:
                self.conn.execute("DELETE FROM messages")
                self.conn.execute("DELETE FROM channels")
            self.conn.execute("COMMIT")

    # -- bookkeeping -----------------------------------------------------------
    def get_meta(self, key, default=None):
        with self.lock:
            r = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key, value):
        with self.lock:
            self.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                              "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    def stats(self, scope=None, channel_ids=()):
        with self.lock:
            n, newest = self.conn.execute("SELECT COUNT(*), MAX(ts) FROM messages").fetchone()
            chans = [dict(r) for r in self.conn.execute("SELECT * FROM channels ORDER BY channel_id")]
        mem = self.memory(scope) if scope else {}
        size = sum(os.path.getsize(self.path + s) for s in ("", "-wal") if os.path.exists(self.path + s))
        return {"messages": n, "newest_message_at": newest, "channels": chans, "bytes": size,
                "digest_chars": len(mem.get("digest") or ""), "digest_updated_at": mem.get("updated_at"),
                "unfolded": self.count_unfolded(scope, channel_ids) if scope else None,
                "last_ingest_at": self.get_meta("last_ingest_at"), "last_backup": self.get_meta("last_backup"),
                "note": self.note}

    def backup(self, dest_dir, day, keep=7):
        """A consistent copy as dest_dir/wbdb-<day>.sqlite (VACUUM INTO works on
        a live database), then prune to the newest `keep`. Returns the path."""
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"wbdb-{day}.sqlite")
        if not os.path.exists(dest):
            tmp = dest + ".tmp"
            if os.path.exists(tmp):
                os.remove(tmp)
            with self.lock:
                self.conn.execute("VACUUM INTO ?", (tmp,))
            os.replace(tmp, dest)
        copies = sorted(f for f in os.listdir(dest_dir) if re.fullmatch(r"wbdb-\d{4}-\d\d-\d\d\.sqlite", f))
        for old in copies[:-keep]:
            os.remove(os.path.join(dest_dir, old))
        self.set_meta("last_backup", f"{day} {dest}")
        return dest
