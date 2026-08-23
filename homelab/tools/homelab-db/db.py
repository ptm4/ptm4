#!/usr/bin/env python3
"""
db.py — connection discipline and migrations for homelab.db.

Every process that touches the database goes through here, because three of the ways to
corrupt or wedge a SQLite database are easy to hit by accident and invisible until they
bite:

 1. **Network filesystems.** The database lives on ZFS dataset `red/opsdb`, deliberately
    outside the Samba-exported `red/fs` tree, so the repo's CIFS mount on tux cannot even
    see it. WAL needs same-host shared memory (the -shm file); over CIFS that is
    unsupported *by design*, including read-only opens. Only opti-local processes here.

 2. **Python's lazy BEGIN.** The stdlib driver defers the transaction to the first DML
    statement, which means a writer that SELECTs first takes a read lock, then tries to
    upgrade — and an upgrade that loses the race fails as SQLITE_BUSY_SNAPSHOT, which
    `busy_timeout` does NOT retry. With two writers (ingester + vitals logger) that is a
    when-not-if. `connect_rw()` returns autocommit connections; writers wrap their work
    in `writing(conn)`, which issues an explicit BEGIN IMMEDIATE.

 3. **"Read-only" that isn't.** `PRAGMA query_only` can be turned back off by the SQL
    being run, so it is not a boundary for untrusted queries. `connect_ro()` opens with
    URI `mode=ro` — a read-only file descriptor no statement can talk its way around —
    and `harden_untrusted()` layers a default-deny authorizer and per-statement limits on
    top for the MCP query tool.

Schema lives in schema.sql; version steps live in MIGRATIONS below and are applied under
PRAGMA user_version. No migration framework — the whole point of this tier is that it is
stdlib-only and inspectable with the sqlite3 CLI.
"""

import os
import sqlite3
import sys
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(HERE, "schema.sql")

# The pool path, not the CIFS mount. Override with HL_DB_PATH for tests/dev.
DEFAULT_DB_PATH = "/srv/red/opsdb/homelab.db"

# Distinguishes our files from any other SQLite database ('HLDB' as a big-endian int).
APPLICATION_ID = 0x484C4442

BUSY_TIMEOUT_MS = 8000


def db_path():
    return os.environ.get("HL_DB_PATH", DEFAULT_DB_PATH)


# ── migrations ──────────────────────────────────────────────────────────────────────
# Step N runs when user_version < N, in order. Each step owns its own transaction: the
# schema step uses executescript(), which implicitly commits any transaction in progress,
# so migrate() cannot wrap the steps itself. Every statement in schema.sql is
# CREATE ... IF NOT EXISTS, which is what makes a re-run against a half-applied database
# safe. Steps that ALTER should wrap themselves in `writing(conn)`.
#
# Never edit a shipped step — a database that already recorded that version will not
# re-run it. Append a new one instead.

def _apply_schema(conn):
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())


def _add_expansion_tables(conn):
    """v2 — the expansion bundles: curated incidents, certificate expiry, monitor
    availability, LAN devices, and media/CS2 counters. Split from schema.sql's original
    body so an existing database picks them up without a rebuild.

    executescript() commits implicitly, so this owns no explicit transaction — every
    statement is IF NOT EXISTS, which is what makes a re-run safe."""
    conn.executescript("""
    -- Curated in homelab/agentic/incidents.json, ingested here. "Have we seen this
    -- symptom before" is the question; the registry is the answer.
    CREATE TABLE IF NOT EXISTS incidents (
        id            TEXT PRIMARY KEY,
        kind          TEXT NOT NULL CHECK (kind IN ('incident', 'decision')),
        occurred_on   TEXT,
        title         TEXT NOT NULL,
        hosts         TEXT,
        symptom       TEXT,
        cause         TEXT,
        resolution    TEXT,
        status        TEXT,
        tags          TEXT,
        source        TEXT,
        ingested_at   TEXT
    );

    -- TLS expiry, from the doctor's per-service cert_days_left. Renewal is the kind
    -- of thing that is invisible until it is urgent.
    CREATE TABLE IF NOT EXISTS certificates (
        name            TEXT PRIMARY KEY,
        url             TEXT,
        days_left       INTEGER,
        expires_on      TEXT,
        observed_at     TEXT
    );

    -- Uptime Kuma keeps its own history behind an admin login; this snapshots the
    -- read-only /metrics view each cycle so availability becomes queryable here.
    CREATE TABLE IF NOT EXISTS monitor_history (
        monitor   TEXT NOT NULL,
        at        TEXT NOT NULL,
        status    TEXT,
        up        INTEGER,
        resp_ms   REAL,
        PRIMARY KEY (monitor, at)
    ) WITHOUT ROWID;

    -- LAN inventory from Pi-hole's DHCP leases; a new device is a change event.
    CREATE TABLE IF NOT EXISTS net_devices (
        mac         TEXT PRIMARY KEY,
        ip          TEXT,
        hostname    TEXT,
        first_seen  TEXT,
        last_seen   TEXT,
        active      INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS pihole_daily (
        day             TEXT PRIMARY KEY,
        queries         INTEGER,
        blocked         INTEGER,
        blocked_pct     REAL,
        clients         INTEGER,
        domains_blocked INTEGER
    );

    CREATE TABLE IF NOT EXISTS media_counters (
        at        TEXT NOT NULL,
        service   TEXT NOT NULL,
        metric    TEXT NOT NULL,
        value     REAL,
        PRIMARY KEY (at, service, metric)
    ) WITHOUT ROWID;

    CREATE TABLE IF NOT EXISTS cs2_matches (
        id          TEXT PRIMARY KEY,
        played_at   TEXT,
        map         TEXT,
        result      TEXT,
        rating      REAL,
        kills       INTEGER,
        deaths      INTEGER,
        adr         REAL,
        raw_json    TEXT
    );

    CREATE TABLE IF NOT EXISTS cs2_ratings (
        at          TEXT NOT NULL,
        dimension   TEXT NOT NULL,
        value       REAL,
        PRIMARY KEY (at, dimension)
    ) WITHOUT ROWID;

    CREATE INDEX IF NOT EXISTS idx_incidents_kind ON incidents (kind, occurred_on);
    CREATE INDEX IF NOT EXISTS idx_monitor_history_at ON monitor_history (at);
    """)


MIGRATIONS = [
    (1, _apply_schema),
    (2, _add_expansion_tables),
]

SCHEMA_VERSION = MIGRATIONS[-1][0]


def migrate(conn, verbose=False):
    """Bring an open read-write connection up to SCHEMA_VERSION. Returns the version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, step in MIGRATIONS:
        if current >= version:
            continue
        if verbose:
            print(f"[db] applying migration {version}", file=sys.stderr)
        step(conn)
        # Recorded only after the step succeeds, so a crash mid-migration re-runs it
        # rather than skipping it. PRAGMA does not accept a parameter binding.
        conn.execute(f"PRAGMA user_version = {int(version)}")
        current = version
    return current


# ── connections ─────────────────────────────────────────────────────────────────────

def connect_rw(path=None, create=True):
    """Read-write connection for the ingester and the vitals logger.

    Autocommit (`isolation_level=None`) so nothing starts a transaction behind our back;
    writers use `writing()` to take the write lock up front. See the module docstring.
    """
    path = path or db_path()
    if create:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA application_id").fetchone()[0] == 0:
        conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    return conn


def connect_ro(path=None):
    """Read-only connection for the server. A read-only fd, not a pragma.

    Fails loudly if the database is missing rather than creating an empty one — a server
    that silently serves an empty database looks like "the homelab has no data".
    """
    path = path or db_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"homelab.db not found at {path}; run ingest.py --init")
    uri = "file:" + path.replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


@contextmanager
def writing(conn):
    """Explicit BEGIN IMMEDIATE ... COMMIT. Batch a whole cycle's writes in one of these.

    Taking the write lock at the start makes contention a wait (covered by busy_timeout)
    instead of a mid-transaction upgrade failure that busy_timeout will not retry.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# ── hardening for untrusted SQL (the MCP query tool) ────────────────────────────────
# Layered per sqlite.org's security checklist, engine-first: the read-only fd from
# connect_ro() is the boundary, and everything below narrows what can be attempted.

_ALLOWED_ACTIONS = None


def _authorizer(action, arg1, arg2, db_name, trigger):
    """Default-deny. SELECT/READ/FUNCTION only — no PRAGMA, no ATTACH, no side effects."""
    global _ALLOWED_ACTIONS
    if _ALLOWED_ACTIONS is None:
        _ALLOWED_ACTIONS = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            # recursive CTEs and some FTS plans need these; none of them write
            getattr(sqlite3, "SQLITE_RECURSIVE", 33),
        }
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def harden_untrusted(conn, deadline_check=None):
    """Apply the untrusted-SQL guardrails to a read-only connection.

    `deadline_check` is called periodically from SQLite's progress handler and should
    return True to abort — that is the wall-clock budget, which also stops a runaway
    query from pinning the WAL end-mark and letting the -wal file grow without bound.
    """
    conn.execute("PRAGMA trusted_schema = OFF")
    conn.execute("PRAGMA cell_size_check = ON")
    conn.execute("PRAGMA mmap_size = 0")
    try:
        conn.execute("PRAGMA hard_heap_limit = 67108864")   # 64 MiB
    except sqlite3.DatabaseError:
        pass  # older SQLite: the other limits still apply

    limits = [
        ("SQLITE_LIMIT_ATTACHED", 0),
        ("SQLITE_LIMIT_VDBE_OP", 25_000_000),
        ("SQLITE_LIMIT_EXPR_DEPTH", 100),
        ("SQLITE_LIMIT_COMPOUND_SELECT", 5),
        ("SQLITE_LIMIT_SQL_LENGTH", 100_000),
        ("SQLITE_LIMIT_LIKE_PATTERN_LENGTH", 200),
        ("SQLITE_LIMIT_COLUMN", 200),
    ]
    setlimit = getattr(conn, "setlimit", None)
    if setlimit:  # Python 3.11+
        for name, value in limits:
            limit_id = getattr(sqlite3, name, None)
            if limit_id is not None:
                setlimit(limit_id, value)

    conn.set_authorizer(_authorizer)
    if deadline_check is not None:
        conn.set_progress_handler(lambda: 1 if deadline_check() else 0, 10_000)
    return conn


def table_names(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'docs_fts%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def schema_sql(conn):
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"
    ).fetchall()
    return "\n\n".join(r[0] for r in rows)
