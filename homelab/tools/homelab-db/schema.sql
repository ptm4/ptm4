-- schema.sql — homelab.db, the queryable index of everything the homelab already knows.
--
-- READ THIS BEFORE OPENING THE DATABASE FROM ANYWHERE:
-- This file lives on ZFS dataset red/opsdb, deliberately OUTSIDE the Samba-exported
-- red/fs subtree. SQLite's WAL mode requires shared memory between processes on the
-- same machine (the -shm file); over CIFS/SMB that is impossible by design, and even a
-- read-only open of a WAL database over a network filesystem can read torn pages.
-- So: only opti-local processes ever open this file. tux and rpi go through :9100.
--
-- Design invariant carried over from build-arch-data.py / lib/arch-data.js:
-- curated facts (human judgment, versioned in git) and probed state (what a collector
-- observed) never blend into one row. Every inventory row carries `provenance`, and
-- disagreement between the two shows up as drift, not as a silent overwrite.

PRAGMA journal_mode = WAL;

-- ── the self-documenting data plane ─────────────────────────────────────────────
-- Curated in ingest.py's DATASETS constant, validated by --check, rendered to the
-- webapp Data page and generated/92-data-flows.md. One description of every flow.
CREATE TABLE IF NOT EXISTS datasets (
    id              TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    producer        TEXT NOT NULL,      -- what writes it (script, daemon, human)
    producer_host   TEXT,
    source          TEXT NOT NULL,      -- path or endpoint it is read from
    format          TEXT,               -- json | markdown | http | sqlite
    cadence_hours   REAL,               -- expected refresh; NULL = manual/on-demand
    stage           TEXT NOT NULL,      -- producer | store | db | consumer
    consumers       TEXT,               -- comma-separated
    retention       TEXT,
    notes           TEXT,
    last_ingested   TEXT,               -- ISO; NULL until first successful ingest
    last_source_at  TEXT,               -- ISO run_at/mtime of the data itself
    last_rows       INTEGER,
    last_error      TEXT
);

-- ── inventory (curated ⊕ probed) ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hosts (
    host            TEXT PRIMARY KEY,
    label           TEXT,
    ip              TEXT,
    role            TEXT,
    zone            TEXT,
    os              TEXT,
    facts_json      TEXT,
    provenance      TEXT NOT NULL CHECK (provenance IN ('curated', 'probed')),
    discovery_source TEXT,
    first_seen      TEXT,
    last_seen       TEXT,
    stale           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS arch_nodes (
    id              TEXT PRIMARY KEY,
    host            TEXT,
    label           TEXT,
    category        TEXT,
    grp             TEXT,
    kind            TEXT,
    container       TEXT,
    image           TEXT,
    ports_json      TEXT,
    sublabel        TEXT,
    notes           TEXT,
    critical        INTEGER NOT NULL DEFAULT 0,
    live_state      TEXT,               -- running | exited | NULL (not container / no agent)
    live_image      TEXT,
    provenance      TEXT NOT NULL CHECK (provenance IN ('curated', 'probed')),
    discovery_source TEXT,
    first_seen      TEXT,
    last_seen       TEXT
);
CREATE INDEX IF NOT EXISTS idx_arch_nodes_host ON arch_nodes (host);

-- Edge kinds borrow Backstage vocabulary (dependsOn / partOf / consumes) where the
-- curated graph's own kind doesn't already say it.
CREATE TABLE IF NOT EXISTS arch_edges (
    id              TEXT PRIMARY KEY,
    src             TEXT NOT NULL,
    dst             TEXT NOT NULL,
    kind            TEXT,
    label           TEXT,
    provenance      TEXT NOT NULL CHECK (provenance IN ('curated', 'probed')),
    first_seen      TEXT,
    last_seen       TEXT
);
CREATE INDEX IF NOT EXISTS idx_arch_edges_src ON arch_edges (src);
CREATE INDEX IF NOT EXISTS idx_arch_edges_dst ON arch_edges (dst);

-- ── collector runs ──────────────────────────────────────────────────────────────
-- One row per (tool, day) mirroring the dated-file layout collectors already write;
-- the same-day re-run overwrites, exactly like _report.py's dated copy does.
CREATE TABLE IF NOT EXISTS agent_runs (
    id              INTEGER PRIMARY KEY,
    tool            TEXT NOT NULL,
    run_at          TEXT NOT NULL,
    run_date        TEXT NOT NULL,
    status          TEXT,
    summary         TEXT,
    source_path     TEXT,
    ingested_at     TEXT NOT NULL,
    UNIQUE (tool, run_date)
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_tool_at ON agent_runs (tool, run_at);

CREATE TABLE IF NOT EXISTS findings (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    tool            TEXT NOT NULL,
    run_at          TEXT NOT NULL,
    severity        TEXT,
    host            TEXT,
    message         TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'collector'   -- collector | freshness | drift | expiry
);
CREATE INDEX IF NOT EXISTS idx_findings_run_at ON findings (run_at);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings (severity);

CREATE TABLE IF NOT EXISTS host_reports (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    tool            TEXT NOT NULL,
    run_at          TEXT NOT NULL,
    host            TEXT NOT NULL,
    status          TEXT,
    summary         TEXT,
    metrics_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_host_reports_host ON host_reports (host, tool, run_at);

-- Numeric series lifted out of the reports. Every ingested run appends, so doctor and
-- network metrics land at 30-minute resolution instead of the 1/day the dated files kept.
CREATE TABLE IF NOT EXISTS collector_metrics (
    tool            TEXT NOT NULL,
    host            TEXT NOT NULL,
    metric          TEXT NOT NULL,
    at              TEXT NOT NULL,
    value           REAL,
    PRIMARY KEY (tool, host, metric, at)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_metrics_lookup ON collector_metrics (metric, host, at);

-- Service reachability as the doctor saw it, per run.
CREATE TABLE IF NOT EXISTS service_checks (
    run_id          INTEGER NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    at              TEXT NOT NULL,
    name            TEXT NOT NULL,
    url             TEXT,
    up              INTEGER,
    detail          TEXT,
    cert_days_left  INTEGER,
    PRIMARY KEY (at, name)
) WITHOUT ROWID;

-- ── what changed, and when ──────────────────────────────────────────────────────
-- The nightly fragments overwrite in place and keep no history; this pair is where
-- "what changed this week" finally becomes answerable.
CREATE TABLE IF NOT EXISTS live_state (
    host            TEXT NOT NULL,
    kind            TEXT NOT NULL,      -- container | port | mount | timer | service
    key             TEXT NOT NULL,
    value_json      TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (host, kind, key)
);

CREATE TABLE IF NOT EXISTS change_events (
    id              INTEGER PRIMARY KEY,
    at              TEXT NOT NULL,
    host            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    key             TEXT NOT NULL,
    change          TEXT NOT NULL CHECK (change IN ('added', 'removed', 'changed')),
    before_json     TEXT,
    after_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_change_events_at ON change_events (at);

-- ── docs corpus ─────────────────────────────────────────────────────────────────
-- Runbooks, rules, skills, generated docs — chunked by heading so a search hit points
-- at a section, not a 200-line file.
CREATE TABLE IF NOT EXISTS docs (
    id              INTEGER PRIMARY KEY,
    path            TEXT NOT NULL,
    source_kind     TEXT NOT NULL,      -- runbook | rule | skill | generated | agent-doc | note
    title           TEXT,
    section         TEXT,
    content         TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    mtime           TEXT,
    UNIQUE (path, section)
);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5 (
    title, section, content,
    content = 'docs',
    content_rowid = 'id',
    tokenize = 'porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
    INSERT INTO docs_fts (rowid, title, section, content)
    VALUES (new.id, new.title, new.section, new.content);
END;
CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
    INSERT INTO docs_fts (docs_fts, rowid, title, section, content)
    VALUES ('delete', old.id, old.title, old.section, old.content);
END;
CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN
    INSERT INTO docs_fts (docs_fts, rowid, title, section, content)
    VALUES ('delete', old.id, old.title, old.section, old.content);
    INSERT INTO docs_fts (rowid, title, section, content)
    VALUES (new.id, new.title, new.section, new.content);
END;

-- Catch-all so nothing the homelab produces is un-queryable, even before it has a
-- purpose-built table: hltv watchlist, cs2 knowledge, workspace manifest, probe status.
CREATE TABLE IF NOT EXISTS raw_documents (
    path            TEXT PRIMARY KEY,
    label           TEXT,
    source_kind     TEXT,
    mtime           TEXT,
    bytes           INTEGER,
    json            TEXT
);

-- ── vitals (durable replacement for the webapp's lossy 48h in-memory rings) ──────
CREATE TABLE IF NOT EXISTS vitals_samples (
    host            TEXT NOT NULL,
    at              INTEGER NOT NULL,   -- epoch seconds
    cpu_pct         REAL,
    mem_pct         REAL,
    load1           REAL,
    temp_c          REAL,
    rx_bps          REAL,
    tx_bps          REAL,
    uptime_s        INTEGER,
    PRIMARY KEY (host, at)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS vitals_hourly (
    host            TEXT NOT NULL,
    hour            INTEGER NOT NULL,   -- epoch seconds truncated to the hour
    metric          TEXT NOT NULL,
    min_v           REAL,
    max_v           REAL,
    avg_v           REAL,
    samples         INTEGER,
    PRIMARY KEY (host, hour, metric)
) WITHOUT ROWID;

-- ── ops ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingest_state (
    key             TEXT PRIMARY KEY,
    value           TEXT,
    updated_at      TEXT
);

-- Every MCP/API query is logged. Read-only access is necessary but not sufficient:
-- rows and ingested docs are an injection channel into an agent, so there is a trail.
CREATE TABLE IF NOT EXISTS query_audit (
    id              INTEGER PRIMARY KEY,
    at              TEXT NOT NULL,
    client          TEXT,
    tool            TEXT,
    detail          TEXT,
    rows_returned   INTEGER,
    ms              REAL,
    ok              INTEGER,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_query_audit_at ON query_audit (at);
