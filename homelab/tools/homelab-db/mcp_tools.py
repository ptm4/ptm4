#!/usr/bin/env python3
"""
mcp_tools.py — the read-only tool surface over homelab.db.

One registry, two front doors: server.py exposes these as MCP tools (for Claude Code
sessions) and as plain JSON endpoints (for the webapp's widgets and Data page). Keeping
the implementations here rather than in either transport is deliberate — MCP has shipped
a breaking revision roughly every six months, and when the next one lands the rewrite
should be confined to the envelope, not the queries.

Tool design follows what the ecosystem converged on for database servers in 2025-26:

  - **Few, well-described tools.** A model picks better from six tools with onboarding-
    quality descriptions than from twenty terse ones. `hl_schema` exists so the model can
    write its own SQL instead of us guessing every question in advance.
  - **Layered read-only enforcement, engine first.** `PRAGMA query_only` is not a
    boundary — the SQL being run can turn it back off. The real boundary is the
    `mode=ro` file descriptor from db.connect_ro(); the authorizer, the statement limits
    and the wall-clock budget in db.harden_untrusted() narrow what can even be attempted
    on top of it.
  - **Explicit truncation.** Claude Code warns at 10k tokens and hard-caps MCP results at
    25k. A silently clipped result set is worse than a small one, so every capped result
    says so in `truncated`.
  - **Failures come back as tool results, not protocol errors** (`isError: true` with an
    actionable message), which is what lets a model correct its own SQL.
"""

import json
import re
import sqlite3
import time
from datetime import datetime, timezone

import db

MAX_ROWS = 200
MAX_BYTES = 100_000
QUERY_DEADLINE_SECONDS = 15.0

# Pinned deliberately. The 2026-07-28 revision removed the initialize handshake and
# sessions outright; a tools-only LAN server gains nothing from that wire format, and
# current Claude Code still negotiates the initialize path. See server.py.
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "homelab-db", "version": "1.0.0"}

READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

_SQL_PREFIX = re.compile(r"^\s*(?:--[^\n]*\n|/\*.*?\*/|\s)*(select|with)\b", re.IGNORECASE | re.DOTALL)


class ToolError(Exception):
    """Raised for anything the caller could fix — surfaced as isError with a hint."""


# ── hl_query ────────────────────────────────────────────────────────────────────────

def _rows_to_result(cursor, started):
    columns = [d[0] for d in cursor.description] if cursor.description else []
    rows, truncated, size = [], False, 0
    # Fetch one past the cap so "there was more" is a fact, not a guess.
    for row in cursor.fetchmany(MAX_ROWS + 1):
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        record = list(row)
        size += len(json.dumps(record, default=str))
        if size > MAX_BYTES:
            truncated = True
            break
        rows.append(record)
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "ms": round((time.time() - started) * 1000, 1),
        "note": (f"Result capped at {MAX_ROWS} rows / {MAX_BYTES // 1000}KB. "
                 "Add LIMIT, aggregate, or narrow the WHERE clause to see the rest.")
        if truncated else None,
    }


def hl_query(conn, args):
    sql = (args.get("sql") or "").strip()
    if not sql:
        raise ToolError("sql is required")
    if not _SQL_PREFIX.match(sql):
        raise ToolError("only SELECT (or WITH ... SELECT) statements are allowed — "
                        "this database is read-only. Use hl_schema to see what is queryable.")

    params = args.get("params") or []
    if isinstance(params, dict):
        bindings = params
    elif isinstance(params, list):
        bindings = tuple(params)
    else:
        raise ToolError("params must be a list or an object")

    deadline = time.time() + QUERY_DEADLINE_SECONDS
    ro = db.connect_ro()
    try:
        db.harden_untrusted(ro, deadline_check=lambda: time.time() > deadline)
        started = time.time()
        try:
            # The stdlib driver rejects multiple statements outright, so statement
            # stacking is handled for us rather than by parsing the string ourselves.
            cursor = ro.execute(sql, bindings)
        except sqlite3.OperationalError as exc:
            message = str(exc)
            if "interrupted" in message.lower():
                raise ToolError(
                    f"query exceeded the {QUERY_DEADLINE_SECONDS:.0f}s budget — "
                    "add a WHERE clause on a time column, or aggregate."
                ) from exc
            if "not authorized" in message.lower():
                raise ToolError(
                    "that statement is not permitted: only SELECT/READ are authorized "
                    "(no PRAGMA, ATTACH, or writes)."
                ) from exc
            raise ToolError(f"SQL error: {message}") from exc
        except sqlite3.Warning as exc:
            raise ToolError(f"only one statement at a time: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            raise ToolError(f"SQL error: {exc}") from exc
        return _rows_to_result(cursor, started)
    finally:
        ro.close()


# ── the rest: fixed queries, no caller-supplied SQL ─────────────────────────────────

def hl_schema(conn, args):
    tables = []
    for name in db.table_names(conn):
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        except sqlite3.DatabaseError:
            count = None
        tables.append({"table": name, "rows": count})
    return {
        "schema": db.schema_sql(conn),
        "tables": tables,
        "hints": [
            "collector_metrics is the long time series: (tool, host, metric, at, value). "
            "Useful metrics: disk_used_pct, pool_used_pct, mem_used_gib, pending_count, "
            "gateway_avg_ms, internet_avg_ms.",
            "agent_runs is one row per (tool, day); findings and host_reports hang off run_id.",
            "change_events answers 'what changed' — live_state holds the current picture.",
            "Search prose with hl_search_docs (FTS5) rather than LIKE over docs.content.",
            "Timestamps are ISO-8601 strings; compare with date()/datetime() functions.",
        ],
    }


_FTS_SYNTAX = re.compile(r'["*:()]|\b(AND|OR|NOT|NEAR)\b')
_FTS_TERM = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


def _search_strategies(query):
    """Progressively looser readings of what the caller typed.

    FTS5 treats a bare multi-word string as an implicit AND and raises a hard syntax
    error on stray punctuation — so `stale CIFS handles` finds nothing and `what broke?`
    is an error. Callers here are language models typing questions, not FTS5 operators,
    so try the literal query (which keeps real FTS syntax working), then all terms, then
    any term.
    """
    query = query.strip()
    yield "literal", query
    terms = _FTS_TERM.findall(query)
    if not terms:
        return
    if not _FTS_SYNTAX.search(query):
        quoted = [f'"{t}"' for t in terms]
        if len(terms) > 1:
            yield "all-terms", " AND ".join(quoted)
        yield "any-term", " OR ".join(quoted)


def hl_search_docs(conn, args):
    query = (args.get("query") or "").strip()
    if not query:
        raise ToolError("query is required")
    limit = max(1, min(int(args.get("k") or 8), 25))

    last_error = None
    for strategy, expression in _search_strategies(query):
        try:
            rows = conn.execute(
                """SELECT d.path, d.source_kind, d.title, d.section,
                          snippet(docs_fts, 2, '', '', ' … ', 24) AS snippet,
                          bm25(docs_fts) AS rank
                   FROM docs_fts f JOIN docs d ON d.id = f.rowid
                   WHERE docs_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (expression, limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            last_error = exc
            continue
        if rows:
            # Key set is identical whether or not anything matched: the webapp's smoke
            # test asserts response keys never shrink, and a conditional key would turn
            # "that search found nothing today" into a failed deploy.
            return {"query": query, "matched": expression, "strategy": strategy,
                    "hits": [dict(r) for r in rows], "hit_count": len(rows), "note": None}

    if last_error is not None and not _FTS_TERM.findall(query):
        raise ToolError(
            f"FTS query error: {last_error}. Use bare words, AND/OR/NOT, "
            '"quoted phrases", or prefix*.'
        )
    return {"query": query, "matched": None, "strategy": None, "hits": [], "hit_count": 0,
            "note": "No documents matched. Try fewer or more general words."}


def hl_status(conn, args):
    latest_doctor = conn.execute(
        "SELECT id, run_at, status, summary FROM agent_runs WHERE tool = 'homelab-doctor' "
        "ORDER BY run_at DESC LIMIT 1"
    ).fetchone()

    hosts = []
    if latest_doctor:
        hosts = [dict(r) for r in conn.execute(
            "SELECT host, status, summary FROM host_reports WHERE run_id = ? ORDER BY host",
            (latest_doctor["id"],),
        ).fetchall()]

    findings = [dict(r) for r in conn.execute(
        """SELECT tool, severity, host, message, run_at FROM findings
           WHERE severity IN ('critical', 'warn') AND run_at > datetime('now', '-1 day')
           ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END, run_at DESC LIMIT 25"""
    ).fetchall()]

    stale = [dict(r) for r in conn.execute(
        """SELECT id, label, cadence_hours, last_source_at, last_error FROM datasets
           WHERE cadence_hours IS NOT NULL AND last_source_at IS NOT NULL
             AND (julianday('now') - julianday(last_source_at)) * 24 > cadence_hours * 2"""
    ).fetchall()]

    services = []
    if latest_doctor:
        services = [dict(r) for r in conn.execute(
            "SELECT name, up, detail, cert_days_left FROM service_checks WHERE run_id = ? ORDER BY name",
            (latest_doctor["id"],),
        ).fetchall()]

    changes = conn.execute(
        "SELECT COUNT(*) FROM change_events WHERE at > datetime('now', '-7 day')"
    ).fetchone()[0]

    return {
        "doctor": dict(latest_doctor) if latest_doctor else None,
        "hosts": hosts,
        "services": services,
        "open_findings": findings,
        "stale_datasets": stale,
        "changes_last_7d": changes,
        "database": _database_facts(conn),
    }


def hl_host(conn, args):
    host = (args.get("host") or "").strip()
    if not host:
        raise ToolError("host is required (opti, rpi, noblenumbat, android)")

    curated = conn.execute("SELECT * FROM hosts WHERE host = ?", (host,)).fetchone()
    if curated is None:
        known = [r[0] for r in conn.execute("SELECT host FROM hosts ORDER BY host").fetchall()]
        raise ToolError(f"unknown host {host!r}; known hosts: {', '.join(known)}")

    reports = [dict(r) for r in conn.execute(
        """SELECT tool, run_at, status, summary FROM host_reports
           WHERE host = ? AND run_at > datetime('now', '-3 day')
           GROUP BY tool HAVING run_at = MAX(run_at) ORDER BY tool""",
        (host,),
    ).fetchall()]

    containers = [dict(r) for r in conn.execute(
        """SELECT key AS container, value_json, first_seen, last_seen FROM live_state
           WHERE host = ? AND kind = 'container' AND active = 1 ORDER BY key""",
        (host,),
    ).fetchall()]
    for container in containers:
        container["detail"] = json.loads(container.pop("value_json") or "{}")

    nodes = [dict(r) for r in conn.execute(
        """SELECT id, label, category, container, sublabel, critical, live_state
           FROM arch_nodes WHERE host = ? ORDER BY label""",
        (host,),
    ).fetchall()]

    changes = [dict(r) for r in conn.execute(
        """SELECT at, kind, key, change FROM change_events
           WHERE host = ? AND at > datetime('now', '-7 day') ORDER BY at DESC LIMIT 25""",
        (host,),
    ).fetchall()]

    findings = [dict(r) for r in conn.execute(
        """SELECT tool, severity, message, run_at FROM findings
           WHERE host = ? AND run_at > datetime('now', '-3 day')
             AND severity IN ('critical', 'warn') ORDER BY run_at DESC LIMIT 15""",
        (host,),
    ).fetchall()]

    facts = dict(curated)
    facts["facts"] = json.loads(facts.pop("facts_json") or "{}")
    return {
        "host": host,
        "curated": facts,
        "latest_reports": reports,
        "containers": containers,
        "nodes": nodes,
        "recent_changes": changes,
        "open_findings": findings,
    }


def hl_changes(conn, args):
    days = max(1, min(int(args.get("days") or 7), 120))
    host = args.get("host")
    sql = ("SELECT at, host, kind, key, change, before_json, after_json FROM change_events "
           "WHERE at > datetime('now', ?)")
    params = [f"-{days} day"]
    if host:
        sql += " AND host = ?"
        params.append(host)
    sql += " ORDER BY at DESC LIMIT ?"
    params.append(MAX_ROWS)

    events = []
    for row in conn.execute(sql, params).fetchall():
        event = dict(row)
        for key in ("before_json", "after_json"):
            raw = event.pop(key)
            event[key.replace("_json", "")] = json.loads(raw) if raw else None
        events.append(event)
    return {"days": days, "host": host, "events": events, "event_count": len(events)}


def hl_incidents(conn, args):
    """Prior art for a symptom, plus the decisions that should not be silently reversed.

    Matching is deliberately loose — a caller describes a symptom in their own words, not
    in the registry's vocabulary — so this scores across title, symptom, cause, tags and
    hosts rather than requiring an exact phrase.
    """
    query = (args.get("query") or "").strip()
    kind = args.get("kind")
    host = args.get("host")

    sql = "SELECT * FROM incidents WHERE 1 = 1"
    params = []
    if kind in ("incident", "decision"):
        sql += " AND kind = ?"
        params.append(kind)
    if host:
        sql += " AND (hosts = '' OR hosts LIKE ?)"
        params.append(f"%{host}%")
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY occurred_on DESC", params).fetchall()]

    if query:
        terms = [t.lower() for t in re.findall(r"[A-Za-z0-9_-]{3,}", query)]
        scored = []
        for row in rows:
            haystack = " ".join(str(row.get(f) or "").lower() for f in
                                ("title", "symptom", "cause", "resolution", "tags", "hosts"))
            score = sum(1 for term in terms if term in haystack)
            # Weight the title and tags: a hit there is about the thing itself, not a
            # passing mention in a resolution paragraph.
            focus = " ".join(str(row.get(f) or "").lower() for f in ("title", "tags"))
            score += sum(1 for term in terms if term in focus)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda pair: (-pair[0], pair[1].get("occurred_on") or ""))
        rows = [row for _score, row in scored[:15]]
        if not rows:
            return {"query": query, "matches": [], "match_count": 0,
                    "note": "Nothing in the registry matches. That is not proof it is new — "
                            "try hl_search_docs over the runbooks as well."}

    for row in rows:
        row["hosts"] = [h for h in (row.get("hosts") or "").split(",") if h]
        row["tags"] = [t for t in (row.get("tags") or "").split(",") if t]
    return {"query": query or None, "matches": rows[:15], "match_count": len(rows[:15]),
            "note": None}


def hl_dataplane(conn, args):
    datasets = [dict(r) for r in conn.execute(
        "SELECT * FROM datasets ORDER BY CASE stage WHEN 'producer' THEN 0 WHEN 'store' "
        "THEN 1 WHEN 'db' THEN 2 ELSE 3 END, id"
    ).fetchall()]
    for dataset in datasets:
        age = None
        if dataset["last_source_at"]:
            row = conn.execute(
                "SELECT (julianday('now') - julianday(?)) * 24", (dataset["last_source_at"],)
            ).fetchone()
            age = round(row[0], 2) if row and row[0] is not None else None
        dataset["age_hours"] = age
        cadence = dataset["cadence_hours"]
        dataset["stale"] = bool(cadence and age is not None and age > cadence * 2)
    return {"datasets": datasets, "database": _database_facts(conn)}


def _database_facts(conn):
    row = conn.execute(
        "SELECT MIN(run_date) AS oldest, MAX(run_date) AS newest, COUNT(*) AS runs FROM agent_runs"
    ).fetchone()
    counts = {}
    for table in ("agent_runs", "findings", "collector_metrics", "docs", "change_events",
                  "arch_nodes", "raw_documents", "vitals_samples"):
        try:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.DatabaseError:
            pass
    return {
        "history_from": row["oldest"], "history_to": row["newest"],
        "runs": row["runs"], "rows": counts, "schema_version": db.SCHEMA_VERSION,
    }


# Metrics live in two tables with very different resolutions, and which one a name
# belongs to is an implementation detail the caller should not have to learn: ask for
# cpu_pct and you get per-minute vitals, ask for pool_used_pct and you get the collector
# series. hl_metrics routes on the name.
VITALS_METRICS = {"cpu_pct", "mem_pct", "load1", "temp_c", "rx_bps", "tx_bps", "uptime_s"}
VITALS_RAW_DAYS = 2  # beyond this, read the hourly rollups instead of 60s samples


def _collector_series(conn, metric, host, days):
    sql = ("SELECT host, at, value FROM collector_metrics "
           "WHERE metric = ? AND at > datetime('now', ?)")
    params = [metric, f"-{days} day"]
    if host:
        sql += " AND host = ?"
        params.append(host)
    sql += " ORDER BY at"
    series = {}
    for row in conn.execute(sql, params).fetchall():
        series.setdefault(row["host"], []).append({"at": row["at"], "value": row["value"]})
    return series, "collector_metrics"


def _vitals_series(conn, metric, host, days):
    cutoff = int(time.time()) - days * 86400
    series = {}
    if days <= VITALS_RAW_DAYS:
        sql = f"SELECT host, at, {metric} AS value FROM vitals_samples WHERE at > ?"
        params = [cutoff]
        if host:
            sql += " AND host = ?"
            params.append(host)
        sql += " ORDER BY at"
        source = "vitals_samples (60s)"
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            series.setdefault(row["host"], []).append({
                "at": _iso(row["at"]), "value": row["value"],
            })
    else:
        sql = ("SELECT host, hour, avg_v, min_v, max_v FROM vitals_hourly "
               "WHERE metric = ? AND hour > ?")
        params = [metric, cutoff]
        if host:
            sql += " AND host = ?"
            params.append(host)
        sql += " ORDER BY hour"
        source = "vitals_hourly (1h avg/min/max)"
        for row in conn.execute(sql, params).fetchall():
            series.setdefault(row["host"], []).append({
                "at": _iso(row["hour"]), "value": row["avg_v"],
                "min": row["min_v"], "max": row["max_v"],
            })
    return series, source


def _iso(epoch):
    if epoch is None:
        return None
    return datetime.fromtimestamp(int(epoch), timezone.utc).isoformat(timespec="seconds")


def hl_metrics(conn, args):
    """Long-range series from whichever store holds the metric.

    Deliberately shaped like Prometheus' /api/v1/query_range so that if this ever
    outgrows SQLite and moves to a real TSDB, the callers do not change.
    """
    metric = (args.get("metric") or "").strip()
    if not metric:
        collector = [r[0] for r in conn.execute(
            "SELECT DISTINCT metric FROM collector_metrics ORDER BY metric LIMIT 60"
        ).fetchall()]
        raise ToolError(
            "metric is required. Per-minute host vitals: "
            f"{', '.join(sorted(VITALS_METRICS))}. Collector metrics: {', '.join(collector)}"
        )
    days = max(1, min(int(args.get("days") or 30), 400))
    host = args.get("host")

    if metric in VITALS_METRICS:
        series, source = _vitals_series(conn, metric, host, days)
    else:
        series, source = _collector_series(conn, metric, host, days)

    # Downsample per host rather than truncating: a 90-day view should keep its shape.
    downsampled = False
    for name, points in series.items():
        if len(points) > MAX_ROWS:
            stride = len(points) // MAX_ROWS + 1
            series[name] = points[::stride]
            downsampled = True

    return {"metric": metric, "days": days, "source": source, "downsampled": downsampled,
            "series": [{"host": h, "points": p} for h, p in sorted(series.items())]}


# ── registry ────────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "hl_status",
        "title": "Homelab status",
        "description": (
            "Current health of the homelab in one call: the latest homelab-doctor run "
            "(per-host status lines and service reachability), every warn/critical finding "
            "from the last 24 hours across all collectors, any data feed that has gone "
            "stale, and how much has changed in the last week. Start here when asked "
            "'how is the homelab' or 'is anything wrong'."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": hl_status,
    },
    {
        "name": "hl_host",
        "title": "Host detail",
        "description": (
            "Everything known about one host: curated facts (IP, role, hardware, notes "
            "written by a human), its latest report from each collector, the containers "
            "currently running on it, the architecture nodes assigned to it, what changed "
            "there in the last week, and its open findings. Hosts: opti, rpi, "
            "noblenumbat, android."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"host": {"type": "string", "description": "opti | rpi | noblenumbat | android"}},
            "required": ["host"], "additionalProperties": False,
        },
        "handler": hl_host,
    },
    {
        "name": "hl_search_docs",
        "title": "Search runbooks and docs",
        "description": (
            "Full-text search (SQLite FTS5, BM25-ranked) over every runbook, standing "
            "rule, skill, generated inventory doc and CLAUDE.md in the homelab repo, "
            "chunked by heading so a hit points at a section. Use this before probing a "
            "host — the answer to most 'how does X work here' or 'what breaks Y' "
            "questions is already written down. Query syntax is FTS5: bare words, "
            "AND/OR/NOT, \"quoted phrases\", prefix*."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "FTS5 query, e.g. 'gluetun port forward'"},
                "k": {"type": "integer", "description": "max hits (1-25, default 8)"},
            },
            "required": ["query"], "additionalProperties": False,
        },
        "handler": hl_search_docs,
    },
    {
        "name": "hl_changes",
        "title": "What changed",
        "description": (
            "Containers, mounts and services that were added, removed or changed across "
            "the fleet, newest first. Derived by diffing each night's agent fragments, "
            "which otherwise overwrite in place and keep no history. Answers 'what "
            "changed this week' and 'when did that container appear'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "lookback window (1-120, default 7)"},
                "host": {"type": "string", "description": "optional host filter"},
            },
            "additionalProperties": False,
        },
        "handler": hl_changes,
    },
    {
        "name": "hl_metrics",
        "title": "Metric history",
        "description": (
            "Numeric history for any metric, from whichever store holds it. Host vitals "
            "(cpu_pct, mem_pct, load1, temp_c, rx_bps, tx_bps) come at 60-second "
            "resolution for the last 30 days and hourly min/avg/max before that. "
            "Collector metrics (disk_used_pct, pool_used_pct, mem_used_gib, "
            "pending_count, gateway_avg_ms, internet_avg_ms and dozens more) go back to "
            "June 2026. Call with no metric to list what is available. Use for trends: "
            "'is opti's pool filling up', 'was the CPU pegged last Tuesday'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "e.g. disk_used_pct — omit to list all"},
                "host": {"type": "string", "description": "optional host filter"},
                "days": {"type": "integer", "description": "lookback window (1-400, default 30)"},
            },
            "additionalProperties": False,
        },
        "handler": hl_metrics,
    },
    {
        "name": "hl_incidents",
        "title": "Prior incidents and settled decisions",
        "description": (
            "Has this happened before? Searches a curated registry of things that broke "
            "(symptom, real cause, how it was resolved) and decisions that should not be "
            "silently reversed. Written by hand, because no collector can observe that a "
            "host went down from a cooling fault or that a token rotation was "
            "deliberately declined. **Check this before diagnosing an outage from "
            "scratch** — several failures here look like something they are not (healthy "
            "containers but 'services down' is usually DNS; a whole host vanishing is "
            "usually hardware). Describe the symptom in your own words."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "symptom or keywords, e.g. 'containers healthy but services down'"},
                "kind": {"type": "string", "description": "'incident' or 'decision' to filter"},
                "host": {"type": "string", "description": "optional host filter"},
            },
            "additionalProperties": False,
        },
        "handler": hl_incidents,
    },
    {
        "name": "hl_dataplane",
        "title": "Data plane and freshness",
        "description": (
            "The curated map of how homelab data flows: every producer, store, and "
            "consumer, what writes it, how often it is expected to refresh, and how stale "
            "it actually is right now. Use to answer 'where does this data come from', "
            "'is the pipeline healthy', or before adding a new data source."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": hl_dataplane,
    },
    {
        "name": "hl_schema",
        "title": "Database schema",
        "description": (
            "The full CREATE TABLE schema of homelab.db plus row counts and querying "
            "hints. Call this before hl_query so the SQL you write matches the real "
            "columns rather than guessed ones."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": hl_schema,
    },
    {
        "name": "hl_query",
        "title": "Query homelab.db (read-only SQL)",
        "description": (
            "Run a read-only SQL SELECT against homelab.db when the other tools do not "
            "shape the question you need — joins, aggregates, correlations across "
            "collectors. SQLite dialect. Call hl_schema first for tables and columns. "
            "Only SELECT / WITH are permitted: the connection is opened read-only and "
            "writes, PRAGMA and ATTACH are refused by the engine. Results cap at 200 rows "
            "and a 15-second budget, and say so when truncated — aggregate rather than "
            "paging through raw rows."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "a single SELECT or WITH…SELECT statement"},
                "params": {
                    "type": ["array", "object"],
                    "description": "optional bindings for ? or :name placeholders",
                },
            },
            "required": ["sql"], "additionalProperties": False,
        },
        "handler": hl_query,
    },
]

TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def tool_descriptors():
    """The `tools/list` payload — the registry minus the Python callables."""
    return [
        {
            "name": tool["name"],
            "title": tool.get("title", tool["name"]),
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
            "annotations": {**READ_ONLY_ANNOTATIONS, "title": tool.get("title", tool["name"])},
        }
        for tool in TOOLS
    ]


def call_tool(conn, name, arguments):
    """Returns (structured_result, is_error)."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return {"error": f"unknown tool {name!r}; available: "
                         f"{', '.join(sorted(TOOLS_BY_NAME))}"}, True
    try:
        return tool["handler"](conn, arguments or {}), False
    except ToolError as exc:
        return {"error": str(exc)}, True
    except sqlite3.DatabaseError as exc:
        return {"error": f"database error: {exc}"}, True
