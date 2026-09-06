#!/usr/bin/env python3
"""
ingest.py — folds everything the homelab already produces into homelab.db.

The homelab has never been short of *data*: five collectors write JSON reports on a
timer, two security auditors write more, three arch-agents push a full host fragment
every midnight, and the runbooks carry the facts none of that can observe. What it has
lacked is a way to *ask a question* — "when did that disk start filling", "what changed
on rpi this week", "have we seen this symptom before" — without a human opening files.

This script is the ETL half of the answer. It reads the existing outputs, it never
replaces them: collectors keep writing JSON exactly as before (the webapp still reads
those files, and keeps working when opti is down), and this turns them into rows.

Design rules it inherits from the rest of homelab/tools:
  - stdlib only, no deps
  - a run that cannot reach one source degrades to a finding, never an exception
  - curated and probed facts stay separable (`provenance`), so drift is a visible diff
  - the registry of datasets below is *curated* — it is the one description of the data
    plane, and it renders to both the webapp Data page and generated/92-data-flows.md

Usage:
    ingest.py                 # one cycle: latest reports, arch data, docs, freshness
    ingest.py --init          # create the database + directories, then exit
    ingest.py --backfill      # also walk every dated report file (~70 days of history)
    ingest.py --maintenance   # force the daily block (backup snapshot, prune, docs)
    ingest.py --check         # self-test: schema + registry + a fixture ingest, no I/O

Env:
    HL_DB_PATH          default /srv/red/opsdb/homelab.db
    HL_AGENT_LOGS_DIR   default: first of the known agent-logs locations that exists
    HL_REPORTS_DIR      default: likewise for security-reports
    HL_ARCH_DATA_URL    default https://webapp.rpi.lan:8443/api/architecture/data
    HL_DB_BACKUP_DIR    default <agent-logs>/../homelab-db/backup
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402  (sibling module, path set above)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

ARCH_URL = os.environ.get("HL_ARCH_DATA_URL", "https://webapp.rpi.lan:8443/api/architecture/data")
# When DNS is the thing that is broken, the hostname above is exactly what fails; the
# webapp is still there on its IP.
ARCH_URL_FALLBACK = "https://192.168.1.10:8443/api/architecture/data"

# The bot control APIs and Uptime Kuma are docker-internal on the rpi; the webapp already
# proxies both, so read them through it rather than opening more paths into that host.
WEBAPP_API = os.environ.get("HL_WEBAPP_API", "https://192.168.1.10:8443/api")

MAINTENANCE_EVERY_HOURS = 20
QUERY_AUDIT_KEEP_DAYS = 90


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _first_existing(candidates, fallback):
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return fallback


def agent_logs_dir():
    """Env override, then the known mounts, in the order session-context.py uses."""
    env = os.environ.get("HL_AGENT_LOGS_DIR")
    if env:
        return env
    return _first_existing(
        [
            "/srv/red/fs/ptm/agent-logs",        # opti native — where this normally runs
            "/home/ptm/opti/ptm/agent-logs",     # tux, over CIFS (dev only)
            "/agent-logs",                       # inside the webapp container
            os.path.join(REPO_ROOT, "..", "..", "agent-logs"),
        ],
        "/srv/red/fs/ptm/agent-logs",
    )


def reports_dir():
    env = os.environ.get("HL_REPORTS_DIR")
    if env:
        return env
    return _first_existing(
        [
            "/srv/red/fs/ptm/security-reports",
            "/home/ptm/opti/ptm/security-reports",
            "/reports",
        ],
        "/srv/red/fs/ptm/security-reports",
    )


def backup_dir():
    env = os.environ.get("HL_DB_BACKUP_DIR")
    if env:
        return env
    return os.path.join(os.path.dirname(agent_logs_dir()), "homelab-db", "backup")


# ── the curated data-plane registry ─────────────────────────────────────────────────
# This is the single description of what flows where. It is curated on purpose: the
# machine can see that a file exists, but not what it is for or who reads it. Validated
# by --check, rendered to 92-data-flows.md and the webapp's Data page.
#
# stage: producer (something that generates facts) | store (where they land) |
#        db (this database) | consumer (what reads it back out)

DATASETS = [
    # ── producers ──
    {"id": "collectors", "label": "Homelab collectors", "producer": "homelab/tools/collectors/*.py",
     "producer_host": "opti", "source": "GitHub Actions homelab-agents.yml", "format": "python",
     "cadence_hours": 0.5, "stage": "producer", "consumers": "agent-logs",
     "notes": "doctor + network every 30min; hardware + software daily 09:00 UTC. SSH fan-out via hl_agents key."},
    {"id": "security-tools", "label": "Security auditors", "producer": "homelab/tools/security/*.py",
     "producer_host": "opti", "source": "GitHub Actions homelab-agents.yml", "format": "python",
     "cadence_hours": 24, "stage": "producer", "consumers": "security-reports",
     "notes": "journald-hunter + persistence-auditor, daily 09:00 UTC, local to opti (no fan-out)."},
    {"id": "arch-agents", "label": "hl-arch-agent fleet", "producer": "homelab/tools/arch-agent/hl-arch-agent.py",
     "producer_host": "opti, rpi, noblenumbat", "source": ":8787 (push at 00:00 local)", "format": "http",
     "cadence_hours": 24, "stage": "producer", "consumers": "arch fragments, vitals",
     "notes": "Pushes a full host fragment to the webapp; also serves /vitals counters and the control POSTs."},
    {"id": "repo-curated", "label": "Curated repo facts", "producer": "humans + build-arch-data.py",
     "producer_host": "git", "source": "homelab/{agentic,tools/architecture}", "format": "markdown/json",
     "cadence_hours": None, "stage": "producer", "consumers": "docs, arch graph",
     "notes": "Runbooks, rules, skills, and the 68-node architecture graph. CI validates referential integrity."},

    # ── stores ──
    {"id": "agent-logs", "label": "agent-logs reports", "producer": "collectors via _report.py",
     "producer_host": "opti", "source": "<agent-logs>/*-latest.json + dated dirs", "format": "json",
     "cadence_hours": 0.5, "stage": "store", "consumers": "webapp, session hook, homelab-db",
     "retention": "dated files kept indefinitely (~70d so far)",
     "notes": "Atomic tmp+fsync+rename. Still the transport; the DB indexes it rather than replacing it."},
    {"id": "security-reports", "label": "security-reports", "producer": "security auditors",
     "producer_host": "opti", "source": "<security-reports>/*-latest.json", "format": "json",
     "cadence_hours": 24, "stage": "store", "consumers": "webapp, homelab-db"},
    {"id": "arch-merged", "label": "Merged architecture data", "producer": "webapp lib/arch-data.js",
     "producer_host": "rpi", "source": "GET /api/architecture/data", "format": "http",
     "cadence_hours": 24, "stage": "store", "consumers": "gen-agentic-docs, homelab-db",
     "notes": "Curated graph ⊕ per-host fragments. Fragments overwrite in place and keep no history — "
              "which is exactly the gap live_state/change_events fills."},
    {"id": "docs-corpus", "label": "Docs corpus", "producer": "humans + generators",
     "producer_host": "git", "source": "runbooks, rules, skills, generated docs", "format": "markdown",
     "cadence_hours": None, "stage": "store", "consumers": "Claude sessions, homelab-db FTS"},

    # ── expansion bundles ──
    {"id": "incidents", "label": "Incident & decision registry", "producer": "humans (curated)",
     "producer_host": "git", "source": "homelab/agentic/incidents.json", "format": "json",
     "cadence_hours": None, "stage": "producer", "consumers": "hl_incidents, Claude sessions",
     "notes": "Why a host went down and which choices are settled — the judgment no collector can observe."},
    {"id": "uptime-kuma", "label": "Uptime Kuma monitors", "producer": "uptime-kuma",
     "producer_host": "rpi", "source": "GET /api/uptime (via webapp)", "format": "http",
     "cadence_hours": 0.5, "stage": "store", "consumers": "monitor_history",
     "retention": "sampled every cycle, kept indefinitely",
     "notes": "Kuma's own history is behind an admin login; sampling the read-only /metrics view is what makes availability queryable."},
    {"id": "deploy-drift", "label": "Deployed-copy drift", "producer": "ingest.py over SSH",
     "producer_host": "opti", "source": "hash of /srv/docker/compose/webapp vs repo", "format": "ssh",
     "cadence_hours": 0.5, "stage": "producer", "consumers": "findings",
     "notes": "A direct edit to a deploy target is reverted by the next CI run — this makes that silent loss loud."},
    {"id": "bot-health", "label": "Discord bot post freshness", "producer": "bot control APIs",
     "producer_host": "rpi", "source": "GET /api/<bot>/status (via webapp)", "format": "http",
     "cadence_hours": 0.5, "stage": "producer", "consumers": "findings",
     "notes": "A dead daily bot is silent, and silence looks exactly like a quiet day."},
    {"id": "dhcp-leases", "label": "LAN device inventory", "producer": "Pi-hole DHCP",
     "producer_host": "rpi", "source": "pihole:/etc/pihole/dhcp.leases (over SSH)", "format": "text",
     "cadence_hours": 0.5, "stage": "store", "consumers": "net_devices, change_events",
     "notes": "Pi-hole is the only DHCP server on this LAN, so its leases are the whole picture. A device never seen before becomes a change event."},
    {"id": "pihole-stats", "label": "Pi-hole query stats", "producer": "Pi-hole FTL",
     "producer_host": "rpi", "source": "GET /api/pihole/summary (via webapp)", "format": "http",
     "cadence_hours": 0.5, "stage": "store", "consumers": "pihole_daily"},
    {"id": "media-counters", "label": "Media library counters", "producer": "sonarr/radarr APIs",
     "producer_host": "noblenumbat", "source": "localhost *arr APIs (queried over SSH)", "format": "http",
     "cadence_hours": 0.5, "stage": "store", "consumers": "media_counters",
     "notes": "The query runs on noblenumbat so each API key is read from its own config.xml and used against localhost — no key is copied to opti."},
    {"id": "leetify", "label": "Leetify CS2 stats", "producer": "homelab/tools/leetify/leetify-stats.py",
     "producer_host": "opti", "source": "<agent-logs>/leetify-latest.json", "format": "json",
     "cadence_hours": None, "stage": "store", "consumers": "cs2_matches, cs2_ratings",
     "notes": "Manual runs only (paid API). Broken out of the 135KB blob into columns so trends are queryable."},
    {"id": "pricewatch", "label": "PC-part price watch", "producer": "homelab/tools/pricewatch/pricewatch.py",
     "producer_host": "opti", "source": "<agent-logs>/pricewatch-latest.json", "format": "json",
     "cadence_hours": 6, "stage": "store", "consumers": "price_history, findings, webapp widget",
     "notes": "Newegg/eBay/Amazon prices for the opti hypervisor rebuild (2026-08). Items + buy "
              "targets in pricewatch/items.json; a price at/below target raises a warn finding."},

    # ── the database ──
    {"id": "homelab-db", "label": "homelab.db", "producer": "homelab/tools/homelab-db/ingest.py",
     "producer_host": "opti", "source": "/srv/red/opsdb/homelab.db", "format": "sqlite",
     "cadence_hours": 0.5, "stage": "db", "consumers": "MCP tools, webapp widgets, Data page",
     "retention": "reports + metrics indefinitely; query audit 90d; raw vitals 30d",
     "notes": "WAL. opti-local processes only — never opened over the CIFS mount. Backed up by "
              "VACUUM INTO snapshot so the weekly coldcopy never rsyncs a live WAL pair."},

    # ── consumers ──
    {"id": "mcp-server", "label": "MCP + JSON API", "producer": "homelab/tools/homelab-db/server.py",
     "producer_host": "opti", "source": ":9100 (/api, /mcp)", "format": "http",
     "cadence_hours": None, "stage": "consumer", "consumers": "Claude Code, webapp",
     "notes": "Read-only. Bearer token + Host/Origin validation. MCP pinned to spec 2025-06-18."},
    {"id": "webapp-data", "label": "Webapp widgets + Data page", "producer": "webapp routes/hldb.js",
     "producer_host": "rpi", "source": "GET /api/hldb/*", "format": "http",
     "cadence_hours": None, "stage": "consumer", "consumers": "browser"},
    {"id": "generated-flows", "label": "92-data-flows.md", "producer": "ingest.py maintenance",
     "producer_host": "opti", "source": "homelab/agentic/generated/92-data-flows.md", "format": "markdown",
     "cadence_hours": 24, "stage": "consumer", "consumers": "Claude sessions",
     "notes": "So a future session can read the data plane instead of re-deriving it."},
]

VALID_STAGES = {"producer", "store", "db", "consumer"}


def validate_registry():
    """Returns a list of problems; empty means valid. Called by --check (and CI)."""
    problems = []
    seen = set()
    for d in DATASETS:
        did = d.get("id")
        if not did:
            problems.append(f"dataset without id: {d}")
            continue
        if did in seen:
            problems.append(f"duplicate dataset id: {did}")
        seen.add(did)
        for field in ("label", "producer", "source", "stage"):
            if not d.get(field):
                problems.append(f"{did}: missing {field}")
        if d.get("stage") not in VALID_STAGES:
            problems.append(f"{did}: bad stage {d.get('stage')!r}")
        cadence = d.get("cadence_hours")
        if cadence is not None and (not isinstance(cadence, (int, float)) or cadence <= 0):
            problems.append(f"{did}: bad cadence_hours {cadence!r}")
    return problems


def sync_registry(conn):
    for d in DATASETS:
        conn.execute(
            """INSERT INTO datasets (id, label, producer, producer_host, source, format,
                                     cadence_hours, stage, consumers, retention, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                 label = excluded.label, producer = excluded.producer,
                 producer_host = excluded.producer_host, source = excluded.source,
                 format = excluded.format, cadence_hours = excluded.cadence_hours,
                 stage = excluded.stage, consumers = excluded.consumers,
                 retention = excluded.retention, notes = excluded.notes""",
            (d["id"], d["label"], d["producer"], d.get("producer_host"), d["source"],
             d.get("format"), d.get("cadence_hours"), d["stage"], d.get("consumers"),
             d.get("retention"), d.get("notes")),
        )


def mark_dataset(conn, dataset_id, source_at=None, rows=None, error=None):
    conn.execute(
        """UPDATE datasets SET last_ingested = ?, last_source_at = COALESCE(?, last_source_at),
                               last_rows = COALESCE(?, last_rows), last_error = ?
           WHERE id = ?""",
        (now_iso(), source_at, rows, error, dataset_id),
    )


# ── report ingest ───────────────────────────────────────────────────────────────────

def _to_number(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def flatten_metrics(obj, prefix="", depth=0, out=None):
    """Every numeric leaf in a host's metrics block becomes a queryable series.

    Lists collapse to a `<name>_count` rather than fanning out per element: it keeps
    cardinality bounded and predictable, and "how many containers were running" is the
    question a list actually answers here. Strings are skipped rather than coerced —
    a metric that silently parses "3 of 4" as 3.0 is worse than a missing one.
    """
    if out is None:
        out = {}
    if depth > 3:
        return out
    if isinstance(obj, dict):
        for key, value in obj.items():
            name = f"{prefix}_{key}" if prefix else str(key)
            flatten_metrics(value, name, depth + 1, out)
    elif isinstance(obj, list):
        if prefix:
            out[f"{prefix}_count"] = float(len(obj))
    else:
        number = _to_number(obj)
        if number is not None and prefix:
            out[prefix] = number
    return out


def _tool_from_path(path):
    """`<agent-logs>/coldcopy-latest.json` -> `coldcopy`. The `-latest` suffix is the
    webapp's CATALOG key, not part of the tool's identity."""
    base = os.path.basename(path)
    if base.endswith(".json"):
        base = base[: -len(".json")]
    return base[: -len("-latest")] if base.endswith("-latest") else base


def upsert_run(conn, tool, run_at, run_date, status, summary, source_path):
    """One row per (tool, day), mirroring the dated-file layout: a same-day re-run
    replaces the previous one, exactly as _report.py's dated copy does."""
    conn.execute(
        """INSERT INTO agent_runs (tool, run_at, run_date, status, summary, source_path, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (tool, run_date) DO UPDATE SET
             run_at = excluded.run_at, status = excluded.status, summary = excluded.summary,
             source_path = excluded.source_path, ingested_at = excluded.ingested_at""",
        (tool, run_at, run_date, status, summary, source_path, now_iso()),
    )
    row = conn.execute(
        "SELECT id FROM agent_runs WHERE tool = ? AND run_date = ?", (tool, run_date)
    ).fetchone()
    run_id = row["id"]
    # Replace the run's children so a re-ingest is idempotent rather than duplicating.
    conn.execute("DELETE FROM findings WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM host_reports WHERE run_id = ?", (run_id,))
    return run_id


def ingest_report(conn, path, report=None, default_tool=None):
    """Ingest one collector/security report. Returns (tool, run_at) or None if not one."""
    if report is None:
        try:
            with open(path, encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    if not isinstance(report, dict) or "run_at" not in report:
        return None

    run_at = str(report.get("run_at"))
    run_date = run_at[:10]
    # Not every report carries `tool` — coldcopy's is written by a shell script. Falling
    # back to the filename would key its dated copies by date ("2026-07-26" as a tool
    # name), so the caller passes the report family it came from instead.
    tool = report.get("tool") or default_tool or _tool_from_path(path)
    status = report.get("status")
    summary = report.get("summary")

    run_id = upsert_run(conn, tool, run_at, run_date, status, summary, path)

    for finding in report.get("findings") or []:
        if isinstance(finding, dict):
            severity = finding.get("severity")
            message = finding.get("message") or json.dumps(finding)
        else:
            severity, message = None, str(finding)
        # Collector findings prefix the host as "[noblenumbat] ..." — pull it back out so
        # the column is filterable without a LIKE.
        host = None
        match = re.match(r"^\[([a-z0-9_.-]+)\]\s*", message or "")
        if match:
            host = match.group(1)
        conn.execute(
            """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
               VALUES (?, ?, ?, ?, ?, ?, 'collector')""",
            (run_id, tool, run_at, severity, host, message),
        )

    for host_block in report.get("hosts") or []:
        if not isinstance(host_block, dict):
            continue
        host = host_block.get("host")
        if not host:
            continue
        metrics = host_block.get("metrics") or {}
        conn.execute(
            """INSERT INTO host_reports (run_id, tool, run_at, host, status, summary, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, tool, run_at, host, host_block.get("status"),
             host_block.get("summary"), json.dumps(metrics)),
        )
        for metric, value in flatten_metrics(metrics).items():
            conn.execute(
                """INSERT INTO collector_metrics (tool, host, metric, at, value)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (tool, host, metric, at) DO UPDATE SET value = excluded.value""",
                (tool, host, metric, run_at, value),
            )

    for service in report.get("services") or []:
        if not isinstance(service, dict) or not service.get("name"):
            continue
        conn.execute(
            """INSERT INTO service_checks (run_id, at, name, url, up, detail, cert_days_left)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (at, name) DO UPDATE SET
                 up = excluded.up, detail = excluded.detail,
                 cert_days_left = excluded.cert_days_left""",
            (run_id, run_at, service["name"], service.get("url"),
             1 if service.get("up") else 0, service.get("detail"),
             service.get("cert_days_left")),
        )

    return tool, run_at


def ingest_reports_dir(conn, directory, dataset_id, backfill=False):
    """Latest pointers always; every dated file too when backfilling."""
    if not os.path.isdir(directory):
        mark_dataset(conn, dataset_id, error=f"missing directory {directory}")
        return 0, None

    count, newest = 0, None
    raw_count = 0
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if name.endswith(".json") and os.path.isfile(path):
            result = ingest_report(conn, path)
            if result:
                count += 1
                newest = max(newest or "", result[1])
            else:
                # Not a report shape (hltv watchlist, cs2 knowledge, agents-state) —
                # keep it queryable anyway rather than dropping it on the floor.
                if ingest_raw_document(conn, path, "agent-logs"):
                    raw_count += 1
        elif backfill and os.path.isdir(path) and not name.startswith("."):
            # A dated history dir; its name is the report family (e.g. "coldcopy-latest").
            family = _tool_from_path(name)
            for dated in sorted(os.listdir(path)):
                if not dated.endswith(".json"):
                    continue
                if ingest_report(conn, os.path.join(path, dated), default_tool=family):
                    count += 1

    mark_dataset(conn, dataset_id, source_at=newest, rows=count)
    return count, newest


# ── architecture / inventory ────────────────────────────────────────────────────────

def fetch_json(url, timeout=20):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # self-signed, LAN-only — same trust boundary as the agents
    with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:
        return json.load(resp)


def fetch_arch_data():
    last_error = None
    for url in (ARCH_URL, ARCH_URL_FALLBACK):
        try:
            return fetch_json(url), None
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
            last_error = f"{url}: {exc}"
    return None, last_error


def ingest_arch(conn, data):
    """Curated graph into inventory tables; live decoration into live_state + changes."""
    stamp = now_iso()

    for host in data.get("hosts") or []:
        # `facts` is a list of {label, value} display rows; the machine-readable bits
        # (fqdn, mac, model, kernel, arch) sit at the top level. Keep the whole object in
        # facts_json so nothing curated is lost to a column list that will drift.
        conn.execute(
            """INSERT INTO hosts (host, label, ip, role, zone, os, facts_json,
                                  provenance, discovery_source, first_seen, last_seen, stale)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'curated', 'arch-merged', ?, ?, 0)
               ON CONFLICT (host) DO UPDATE SET
                 label = excluded.label, ip = excluded.ip, role = excluded.role,
                 zone = excluded.zone, os = excluded.os, facts_json = excluded.facts_json,
                 last_seen = excluded.last_seen""",
            (host.get("id"), host.get("label"), host.get("ip"), host.get("role"),
             host.get("zone"), host.get("os"), json.dumps(host), stamp, stamp),
        )

    for node in data.get("nodes") or []:
        live = node.get("_live") or {}
        conn.execute(
            """INSERT INTO arch_nodes (id, host, label, category, grp, kind, container, image,
                                       ports_json, sublabel, notes, critical, live_state,
                                       live_image, provenance, discovery_source, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'curated', 'arch-merged', ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                 host = excluded.host, label = excluded.label, category = excluded.category,
                 grp = excluded.grp, kind = excluded.kind, container = excluded.container,
                 image = excluded.image, ports_json = excluded.ports_json,
                 sublabel = excluded.sublabel, notes = excluded.notes,
                 critical = excluded.critical, live_state = excluded.live_state,
                 live_image = excluded.live_image, last_seen = excluded.last_seen""",
            (node.get("id"), node.get("host"), node.get("label"), node.get("category"),
             node.get("group"), node.get("kind"), node.get("container"), node.get("image"),
             json.dumps(node.get("ports") or []), node.get("sublabel"), node.get("notes"),
             1 if node.get("critical") else 0, live.get("state"), live.get("image"),
             stamp, stamp),
        )

    for edge in data.get("edges") or []:
        eid = edge.get("id") or f"{edge.get('from')}->{edge.get('to')}:{edge.get('kind')}"
        conn.execute(
            """INSERT INTO arch_edges (id, src, dst, kind, label, provenance, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, 'curated', ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                 src = excluded.src, dst = excluded.dst, kind = excluded.kind,
                 label = excluded.label, last_seen = excluded.last_seen""",
            (eid, edge.get("from"), edge.get("to"), edge.get("kind"), edge.get("label"),
             stamp, stamp),
        )

    return diff_live_state(conn, data, stamp)


def observed_state(data):
    """Build {(host, kind, key): value} from the live decoration of the merged data.

    Only hosts whose agent actually reported are represented. That distinction is the
    whole reason this is a separate function: if a host is simply missing from the
    ingest, its containers must not be diffed as "removed" — a down agent is not a
    fleet-wide teardown.
    """
    merge = data.get("live_merge") or {}
    ingested_hosts = set((merge.get("ingested") or {}).keys())
    observed = {}

    for node in data.get("nodes") or []:
        host = node.get("host")
        live = node.get("_live")
        if not host or host not in ingested_hosts or not live:
            continue
        container = node.get("container")
        if container:
            observed[(host, "container", container)] = {
                "state": live.get("state"), "image": live.get("image"), "node": node.get("id"),
            }
        for mount in live.get("mounts") or []:
            dest = mount.get("destination")
            if dest:
                observed[(host, "mount", f"{container or node.get('id')}:{dest}")] = {
                    "source": mount.get("source"), "mode": mount.get("mode"),
                }

    for entry in (merge.get("drift") or {}).get("undescribed") or []:
        host = entry.get("host")
        if host in ingested_hosts and entry.get("container"):
            observed[(host, "container", entry["container"])] = {
                "state": entry.get("state"), "image": entry.get("image"), "undescribed": True,
            }

    return observed, ingested_hosts


def _significant(value):
    """The subset of a value worth raising a 'changed' event for.

    Container mounts carry volume paths that churn on recreate; state and image are what
    a human means by "it changed".
    """
    if not isinstance(value, dict):
        return value
    return {k: value.get(k) for k in ("state", "image", "mode") if k in value}


def diff_live_state(conn, data, stamp):
    observed, ingested_hosts = observed_state(data)
    if not ingested_hosts:
        return 0

    existing = {}
    placeholders = ",".join("?" for _ in ingested_hosts)
    for row in conn.execute(
        f"SELECT host, kind, key, value_json, active FROM live_state WHERE host IN ({placeholders})",
        tuple(ingested_hosts),
    ):
        existing[(row["host"], row["kind"], row["key"])] = row

    events = 0
    for key, value in observed.items():
        host, kind, name = key
        payload = json.dumps(value, sort_keys=True)
        prior = existing.get(key)
        if prior is None:
            conn.execute(
                """INSERT INTO live_state (host, kind, key, value_json, first_seen, last_seen, active)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (host, kind, name, payload, stamp, stamp),
            )
            conn.execute(
                """INSERT INTO change_events (at, host, kind, key, change, before_json, after_json)
                   VALUES (?, ?, ?, ?, 'added', NULL, ?)""",
                (stamp, host, kind, name, payload),
            )
            events += 1
            continue

        prior_value = json.loads(prior["value_json"] or "{}")
        changed = _significant(prior_value) != _significant(value)
        reappeared = not prior["active"]
        conn.execute(
            "UPDATE live_state SET value_json = ?, last_seen = ?, active = 1 WHERE host = ? AND kind = ? AND key = ?",
            (payload, stamp, host, kind, name),
        )
        if changed or reappeared:
            conn.execute(
                """INSERT INTO change_events (at, host, kind, key, change, before_json, after_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (stamp, host, kind, name, "added" if reappeared else "changed",
                 prior["value_json"], payload),
            )
            events += 1

    for key, prior in existing.items():
        if key in observed or not prior["active"]:
            continue
        host, kind, name = key
        conn.execute(
            "UPDATE live_state SET active = 0, last_seen = ? WHERE host = ? AND kind = ? AND key = ?",
            (stamp, host, kind, name),
        )
        conn.execute(
            """INSERT INTO change_events (at, host, kind, key, change, before_json, after_json)
               VALUES (?, ?, ?, ?, 'removed', ?, NULL)""",
            (stamp, host, kind, name, prior["value_json"]),
        )
        events += 1

    return events


# ── docs corpus ─────────────────────────────────────────────────────────────────────

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


def chunk_markdown(text):
    """Split into (section_title, body) at ## / ### headings.

    A search hit should point at a section, not hand back a 200-line runbook — the MCP
    result cap makes whole-file chunks actively harmful.
    """
    title = None
    first = HEADING_RE.search(text)
    if first and first.group(1) == "#":
        title = first.group(2)

    positions = [(m.start(), m.group(1), m.group(2)) for m in HEADING_RE.finditer(text)
                 if len(m.group(1)) >= 2]
    if not positions:
        return title, [("", text.strip())]

    chunks = []
    preamble = text[: positions[0][0]].strip()
    if preamble:
        chunks.append(("", preamble))
    for index, (start, _level, heading) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        body = text[start:end].strip()
        if body:
            chunks.append((heading, body))
    return title, chunks


def doc_sources():
    agentic = os.path.join(REPO_ROOT, "homelab", "agentic")
    sources = []

    for kind, directory in (("runbook", os.path.join(agentic, "runbooks")),
                            ("rule", os.path.join(agentic, "rules")),
                            ("generated", os.path.join(agentic, "generated"))):
        if os.path.isdir(directory):
            for name in sorted(os.listdir(directory)):
                if name.endswith(".md"):
                    sources.append((kind, os.path.join(directory, name)))

    skills = os.path.join(agentic, "skills")
    if os.path.isdir(skills):
        for name in sorted(os.listdir(skills)):
            skill_md = os.path.join(skills, name, "SKILL.md")
            if os.path.isfile(skill_md):
                sources.append(("skill", skill_md))

    for extra in (os.path.join(agentic, "troubleshooting.md"),
                  os.path.join(REPO_ROOT, "CLAUDE.md")):
        if os.path.isfile(extra):
            sources.append(("note", extra))

    generated_docs = os.path.join(agent_logs_dir(), "generated-docs")
    if os.path.isdir(generated_docs):
        for name in sorted(os.listdir(generated_docs)):
            if name.endswith(".md"):
                sources.append(("agent-doc", os.path.join(generated_docs, name)))

    return sources


def ingest_docs(conn):
    """Re-chunk only files whose content hash moved, so FTS isn't rewritten every cycle."""
    indexed = 0
    for kind, path in doc_sources():
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rel = os.path.relpath(path, REPO_ROOT) if path.startswith(REPO_ROOT) else path
        state_key = f"doc-hash:{rel}"
        prior = conn.execute("SELECT value FROM ingest_state WHERE key = ?", (state_key,)).fetchone()
        if prior and prior["value"] == digest:
            continue

        title, chunks = chunk_markdown(text)
        mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat(timespec="seconds")
        conn.execute("DELETE FROM docs WHERE path = ?", (rel,))
        for section, body in chunks:
            conn.execute(
                """INSERT INTO docs (path, source_kind, title, section, content, content_hash, mtime)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (path, section) DO UPDATE SET
                     content = excluded.content, content_hash = excluded.content_hash,
                     mtime = excluded.mtime""",
                (rel, kind, title or os.path.basename(path), section, body, digest, mtime),
            )
            indexed += 1
        conn.execute(
            "INSERT INTO ingest_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (state_key, digest, now_iso()),
        )
    return indexed


def ingest_raw_document(conn, path, source_kind, label=None):
    """The catch-all: anything JSON that isn't a report still becomes queryable."""
    try:
        stat = os.stat(path)
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    rel = os.path.relpath(path, REPO_ROOT) if path.startswith(REPO_ROOT) else path
    conn.execute(
        """INSERT INTO raw_documents (path, label, source_kind, mtime, bytes, json)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (path) DO UPDATE SET
             label = excluded.label, source_kind = excluded.source_kind,
             mtime = excluded.mtime, bytes = excluded.bytes, json = excluded.json""",
        (rel, label or os.path.basename(path), source_kind,
         datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
         stat.st_size, json.dumps(payload)),
    )
    return True


def ingest_workspace(conn):
    agentic = os.path.join(REPO_ROOT, "homelab", "agentic")
    count = 0
    manifest = os.path.join(agentic, "workspace.json")
    if os.path.isfile(manifest) and ingest_raw_document(conn, manifest, "workspace"):
        count += 1
    status_dir = os.path.join(agentic, "status")
    if os.path.isdir(status_dir):
        for name in sorted(os.listdir(status_dir)):
            if name.endswith(".json") and ingest_raw_document(
                conn, os.path.join(status_dir, name), "probe-status"
            ):
                count += 1
    return count


# ── expansion bundles ───────────────────────────────────────────────────────────────

def ingest_incidents(conn):
    """The curated incident + decision registry.

    Everything else in this database is derived, and derived data cannot tell you that a
    host went down because of *cooling*, or that a token rotation was deliberately
    declined. That judgment is written by hand, versioned in git, and ingested here — the
    same curated-vs-probed split the architecture graph uses.
    """
    path = os.path.join(REPO_ROOT, "homelab", "agentic", "incidents.json")
    try:
        with open(path, encoding="utf-8") as f:
            registry = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        mark_dataset(conn, "incidents", error=str(exc))
        return 0

    stamp = now_iso()
    count = 0
    for section in ("incidents", "decisions"):
        for entry in registry.get(section) or []:
            if not entry.get("id") or not entry.get("title"):
                continue
            conn.execute(
                """INSERT INTO incidents (id, kind, occurred_on, title, hosts, symptom,
                                          cause, resolution, status, tags, source, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET
                     kind = excluded.kind, occurred_on = excluded.occurred_on,
                     title = excluded.title, hosts = excluded.hosts,
                     symptom = excluded.symptom, cause = excluded.cause,
                     resolution = excluded.resolution, status = excluded.status,
                     tags = excluded.tags, source = excluded.source,
                     ingested_at = excluded.ingested_at""",
                (entry["id"], entry.get("kind", section[:-1]), entry.get("date"),
                 entry["title"], ",".join(entry.get("hosts") or []), entry.get("symptom"),
                 entry.get("cause"), entry.get("resolution"), entry.get("status"),
                 ",".join(entry.get("tags") or []), entry.get("source"), stamp),
            )
            count += 1

    mark_dataset(conn, "incidents", source_at=stamp, rows=count)
    return count


CERT_WARN_DAYS = 30


def ingest_certificates(conn, run_id):
    """TLS expiry from what the doctor already measures, plus a finding before it bites.

    The doctor reports cert_days_left every 30 minutes but only as a number on a service
    row; nothing was watching it approach zero.
    """
    rows = conn.execute(
        """SELECT name, url, cert_days_left, at FROM service_checks
           WHERE cert_days_left IS NOT NULL
             AND at = (SELECT MAX(at) FROM service_checks)"""
    ).fetchall()
    stamp = now_iso()
    warned = 0
    for row in rows:
        days = row["cert_days_left"]
        expires = (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
        conn.execute(
            """INSERT INTO certificates (name, url, days_left, expires_on, observed_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (name) DO UPDATE SET
                 url = excluded.url, days_left = excluded.days_left,
                 expires_on = excluded.expires_on, observed_at = excluded.observed_at""",
            (row["name"], row["url"], days, expires, stamp),
        )
        if days <= CERT_WARN_DAYS:
            conn.execute(
                """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
                   VALUES (?, 'homelab-db', ?, ?, NULL, ?, 'expiry')""",
                (run_id, stamp, "critical" if days <= 7 else "warn",
                 f"[certs] {row['name']} TLS certificate expires in {days} days ({expires})"),
            )
            warned += 1
    return len(rows), warned


def check_smart(conn, run_id):
    """Reallocated and pending sectors are the precursor signal, not the temperature.

    hardware-report has been recording these per disk all along and nothing was reading
    them. A non-zero count is worth knowing about; a count that *grew* is the one that
    means the drive is actively failing.
    """
    stamp = now_iso()
    flagged = 0
    # Compare against the oldest reading, not just a month ago: these counters creep.
    # A window that is shorter than the creep reports "stable" on a drive that has been
    # steadily degrading all along, which is the exact failure this is meant to catch.
    rows = conn.execute(
        """SELECT host, metric,
                  (SELECT value FROM collector_metrics m2
                    WHERE m2.host = m.host AND m2.metric = m.metric
                    ORDER BY at DESC LIMIT 1) AS latest,
                  (SELECT value FROM collector_metrics m3
                    WHERE m3.host = m.host AND m3.metric = m.metric
                    ORDER BY at ASC LIMIT 1) AS earliest,
                  (SELECT at FROM collector_metrics m4
                    WHERE m4.host = m.host AND m4.metric = m.metric
                    ORDER BY at ASC LIMIT 1) AS since
           FROM collector_metrics m
           WHERE metric LIKE 'smart%reallocated' OR metric LIKE 'smart%pending'
           GROUP BY host, metric"""
    ).fetchall()

    for row in rows:
        latest = row["latest"] or 0
        if latest <= 0:
            continue
        earliest = row["earliest"]
        disk = row["metric"].replace("smart_", "").rsplit("_", 1)[0]
        kind = "reallocated" if row["metric"].endswith("reallocated") else "pending"
        if earliest is not None and latest > earliest:
            severity = "critical"
            detail = (f"grew from {earliest:.0f} to {latest:.0f} since "
                      f"{str(row['since'])[:10]} — this drive is degrading")
        else:
            severity = "warn"
            detail = f"{latest:.0f}, unchanged since {str(row['since'])[:10]}"
        conn.execute(
            """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
               VALUES (?, 'homelab-db', ?, ?, ?, ?, 'expiry')""",
            (run_id, stamp, severity, row["host"],
             f"[{row['host']}] {disk} SMART {kind} sectors: {detail}"),
        )
        flagged += 1
    return flagged


def ingest_monitors(conn):
    """Availability history from Uptime Kuma, via the webapp's read-only proxy.

    Kuma's own history lives behind an admin login; /api/uptime exposes the current state
    of every monitor, so sampling it each cycle is what turns it into a series.
    """
    try:
        data = fetch_json(WEBAPP_API + "/uptime", timeout=12)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        mark_dataset(conn, "uptime-kuma", error=str(exc))
        return 0

    monitors = data.get("monitors") if isinstance(data, dict) else None
    if not isinstance(monitors, list):
        mark_dataset(conn, "uptime-kuma", error="unexpected /api/uptime shape")
        return 0

    stamp = now_iso()
    for monitor in monitors:
        name = monitor.get("name")
        if not name:
            continue
        status = monitor.get("status")
        conn.execute(
            """INSERT INTO monitor_history (monitor, at, status, up, resp_ms)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (monitor, at) DO NOTHING""",
            (name, stamp, status, 1 if status == "up" else 0, monitor.get("response_time")),
        )
    mark_dataset(conn, "uptime-kuma", source_at=stamp, rows=len(monitors))
    return len(monitors)


# Deployed copies that CI overwrites. Editing one of these directly is a known way to
# lose work silently — the next deploy reverts it — so the drift is worth a finding.
DEPLOY_TARGETS = [
    {"host": "rpi", "remote": "/srv/docker/compose/webapp/backend",
     "repo": "homelab/hosts/rpi/webapp/backend", "label": "webapp backend"},
]


def _tree_hash_remote(host, path):
    """sha256 over `<relative path> <content hash>` for every file, sorted.

    Content, not size: an edit that happens to preserve the byte count is exactly the
    kind of thing a size-only check would miss.
    """
    script = (
        f"cd {path} 2>/dev/null && find . -type f -not -path './node_modules/*' "
        "-not -name '*.log' -print0 | sort -z | xargs -0 sha256sum 2>/dev/null "
        "| sha256sum | cut -d' ' -f1"
    )
    return run_ssh(host, ["sh", "-c", script])


def _tree_hash_local(path):
    """The same digest, computed the same way, so the two are comparable."""
    import hashlib
    entries = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for name in sorted(files):
            if name.endswith(".log"):
                continue
            full = os.path.join(root, name)
            rel = "./" + os.path.relpath(full, path)
            try:
                with open(full, "rb") as f:
                    digest = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                continue
            entries.append(f"{digest}  {rel}\n")
    joined = "".join(sorted(entries, key=lambda e: e.split("  ", 1)[1]))
    return hashlib.sha256(joined.encode()).hexdigest()


def _repo_path_clean(rel_path):
    """Is this repo subtree free of uncommitted changes?

    Without this the check is worthless: any work in progress makes the repo differ from
    the deployed copy, which is *normal*, and a finding that fires during every editing
    session teaches you to ignore it. Drift is only meaningful when the repo is settled —
    then a difference means someone edited the deploy target, or a deploy silently failed.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", REPO_ROOT, "status", "--porcelain", "--", rel_path],
            capture_output=True, text=True, timeout=20,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0 and not result.stdout.strip()


def run_ssh(host_name, argv):
    """Run a command on another host, through the collectors' own SSH module.

    Deliberately not hand-rolled: `_hosts.py` already owns the HL_HOSTS name→target map,
    the hl_agents key, and the timeouts, and a bare `ssh rpi` does NOT work from opti
    (there is no such alias there — that is what HL_HOSTS is for). Reusing it also means
    an unreachable host degrades to empty output instead of raising.
    """
    collectors = os.path.join(REPO_ROOT, "homelab", "tools", "collectors")
    if collectors not in sys.path:
        sys.path.append(collectors)
    try:
        import _hosts
    except ImportError:
        return None
    target = next((h for h in _hosts.hosts() if h.name == host_name), None)
    if target is None:
        return None
    out, rc = _hosts.run_on(target, argv, timeout=30)
    return out.strip() if rc == 0 else None


def ingest_deploy_drift(conn, run_id):
    """Compare each deployed copy against the repo it is built from.

    Only runs while the repo subtree is clean — see _repo_path_clean for why.
    """
    stamp = now_iso()
    checked = drifted = skipped = 0
    for target in DEPLOY_TARGETS:
        repo_path = os.path.join(REPO_ROOT, target["repo"])
        if not os.path.isdir(repo_path):
            continue
        if not _repo_path_clean(target["repo"]):
            skipped += 1
            continue
        remote_hash = _tree_hash_remote(target["host"], target["remote"])
        if not remote_hash:
            continue  # host down or path absent — not drift, just unknown
        checked += 1
        if remote_hash != _tree_hash_local(repo_path):
            drifted += 1
            conn.execute(
                """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
                   VALUES (?, 'homelab-db', ?, 'warn', ?, ?, 'drift')""",
                (run_id, stamp, target["host"],
                 f"[{target['host']}] deployed {target['label']} at {target['remote']} "
                 f"differs from the committed repo. Either it was edited in place (the next "
                 f"deploy reverts that) or a deploy did not complete — check rpi-deploy.yml."),
            )
    mark_dataset(conn, "deploy-drift", source_at=stamp, rows=checked)
    return checked, drifted, skipped


BOT_ROUTES = {
    "weather": "/weather/status",
    "healthdigest": "/healthdigest/status",
    "jellyfin": "/jellyfin/status",
    "sports": "/sports/status",
    "hltv": "/hltv/status",
}
BOT_SILENT_HOURS = 30  # daily posters; a missed day should be loud, a late one should not


def ingest_bot_health(conn, run_id):
    """Did each daily bot actually post?

    A dead bot is silent, and silence in Discord looks exactly like a quiet day. The bot
    control APIs are docker-internal on the rpi, so this goes through the webapp's
    existing proxy rather than trying to reach them directly.
    """
    stamp = now_iso()
    checked = stale = 0
    for bot, route in BOT_ROUTES.items():
        try:
            status = fetch_json(WEBAPP_API + route, timeout=10)
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
            continue
        checked += 1
        last_post = None
        for key in ("last_post", "last_posted", "last_run", "last_sent"):
            if isinstance(status, dict) and status.get(key):
                last_post = status[key]
                break
        if not last_post:
            continue
        try:
            when = datetime.fromisoformat(str(last_post).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - when).total_seconds() / 3600
        if age > BOT_SILENT_HOURS:
            stale += 1
            conn.execute(
                """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
                   VALUES (?, 'homelab-db', ?, 'warn', 'rpi', ?, 'freshness')""",
                (run_id, stamp,
                 f"[bots] discord-{bot} has not posted in {age:.0f}h "
                 f"(last {str(last_post)[:16]})"),
            )
    mark_dataset(conn, "bot-health", source_at=stamp, rows=checked)
    return checked, stale


def ingest_net_devices(conn):
    """LAN inventory from Pi-hole's DHCP leases; a new device becomes a change event.

    Read over SSH rather than through Pi-hole's API because the leases file is the
    authoritative record and needs no additional secret on opti — the collectors' key is
    already here. Pi-hole is the only DHCP server on this LAN, so this is the whole
    picture (see the incident registry for what happens when it is not).
    """
    raw = run_ssh("rpi", ["sudo", "-n", "docker", "exec", "pihole",
                          "cat", "/etc/pihole/dhcp.leases"])
    if not raw:
        mark_dataset(conn, "dhcp-leases", error="could not read pihole dhcp.leases")
        return 0, 0

    stamp = now_iso()
    seen = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        _expiry, mac, ip, hostname = parts[0], parts[1], parts[2], parts[3]
        seen[mac] = (ip, None if hostname == "*" else hostname)

    known = {row["mac"]: row for row in conn.execute(
        "SELECT mac, ip, hostname, active FROM net_devices").fetchall()}

    new_devices = 0
    for mac, (ip, hostname) in seen.items():
        prior = known.get(mac)
        if prior is None:
            new_devices += 1
            conn.execute(
                """INSERT INTO net_devices (mac, ip, hostname, first_seen, last_seen, active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (mac, ip, hostname, stamp, stamp),
            )
            conn.execute(
                """INSERT INTO change_events (at, host, kind, key, change, before_json, after_json)
                   VALUES (?, 'rpi', 'device', ?, 'added', NULL, ?)""",
                (stamp, mac, json.dumps({"ip": ip, "hostname": hostname})),
            )
        else:
            conn.execute(
                "UPDATE net_devices SET ip = ?, hostname = ?, last_seen = ?, active = 1 WHERE mac = ?",
                (ip, hostname or prior["hostname"], stamp, mac),
            )

    # A lease that has aged out is not an event worth waking anyone for — phones leave
    # all day — so departures only flip `active`.
    for mac, prior in known.items():
        if mac not in seen and prior["active"]:
            conn.execute("UPDATE net_devices SET active = 0 WHERE mac = ?", (mac,))

    mark_dataset(conn, "dhcp-leases", source_at=stamp, rows=len(seen))
    return len(seen), new_devices


def ingest_pihole_daily(conn):
    """Query/block totals per day, through the webapp's read-only Pi-hole proxy."""
    try:
        summary = fetch_json(WEBAPP_API + "/pihole/summary", timeout=12)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        mark_dataset(conn, "pihole-stats", error=str(exc))
        return 0

    if not isinstance(summary, dict):
        return 0
    queries = summary.get("queries_today") or summary.get("dns_queries_today") or summary.get("queries")
    blocked = summary.get("blocked_today") or summary.get("ads_blocked_today") or summary.get("blocked")
    if queries is None:
        mark_dataset(conn, "pihole-stats", error="unexpected /api/pihole/summary shape")
        return 0

    day = datetime.now(timezone.utc).date().isoformat()
    percent = summary.get("percent_blocked") or summary.get("ads_percentage_today")
    if percent is None and queries:
        percent = round((blocked or 0) / queries * 100, 2)
    conn.execute(
        """INSERT INTO pihole_daily (day, queries, blocked, blocked_pct, clients, domains_blocked)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (day) DO UPDATE SET
             queries = excluded.queries, blocked = excluded.blocked,
             blocked_pct = excluded.blocked_pct, clients = excluded.clients,
             domains_blocked = excluded.domains_blocked""",
        (day, queries, blocked, percent,
         summary.get("unique_clients") or summary.get("clients"),
         summary.get("domains_being_blocked") or summary.get("domains_blocked")),
    )
    mark_dataset(conn, "pihole-stats", source_at=now_iso(), rows=1)
    return 1


# Runs ON noblenumbat, so each service's API key is read from its own config.xml and
# used against localhost — the key never crosses the network and opti never stores one.
MEDIA_SCRIPT = r"""
for pair in "sonarr 8989 series" "radarr 7878 movie"; do
  set -- $pair
  svc=$1; port=$2; res=$3
  key=$(sudo -n grep -oP '(?<=<ApiKey>)[a-f0-9]+' /opt/yams/config/$svc/config.xml 2>/dev/null)
  [ -z "$key" ] && continue
  n=$(curl -s -m 8 -H "X-Api-Key: $key" "http://127.0.0.1:$port/api/v3/$res" \
      | python3 -c "import json,sys;print(len(json.load(sys.stdin)))" 2>/dev/null)
  [ -n "$n" ] && echo "$svc library $n"
  q=$(curl -s -m 8 -H "X-Api-Key: $key" "http://127.0.0.1:$port/api/v3/queue?pageSize=1" \
      | python3 -c "import json,sys;print(json.load(sys.stdin).get('totalRecords',0))" 2>/dev/null)
  [ -n "$q" ] && echo "$svc queue $q"
done
"""


def ingest_media_counters(conn):
    """Library sizes and download-queue depth for the *arr stack."""
    raw = run_ssh("noblenumbat", ["sh", "-c", MEDIA_SCRIPT])
    if not raw:
        mark_dataset(conn, "media-counters", error="could not read *arr counters")
        return 0

    stamp = now_iso()
    count = 0
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        service, metric, value = parts
        number = _to_number(int(value)) if value.isdigit() else None
        if number is None:
            continue
        conn.execute(
            """INSERT INTO media_counters (at, service, metric, value) VALUES (?, ?, ?, ?)
               ON CONFLICT (at, service, metric) DO UPDATE SET value = excluded.value""",
            (stamp, service, metric, number),
        )
        count += 1
    mark_dataset(conn, "media-counters", source_at=stamp, rows=count)
    return count


def ingest_leetify(conn):
    """Break the Leetify blob out into real columns so CS2 trends are queryable.

    It is already in raw_documents; a 135KB JSON blob is not something you can ask
    questions of.
    """
    path = os.path.join(agent_logs_dir(), "leetify-latest.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0

    stamp = data.get("run_at") or now_iso()
    count = 0
    for dimension, value in (data.get("dimensions") or {}).items():
        number = _to_number(value if not isinstance(value, dict) else value.get("value"))
        if number is None:
            continue
        conn.execute(
            """INSERT INTO cs2_ratings (at, dimension, value) VALUES (?, ?, ?)
               ON CONFLICT (at, dimension) DO UPDATE SET value = excluded.value""",
            (stamp, dimension, number),
        )
        count += 1

    for match in (data.get("demo_summaries") or [])[:200]:
        if not isinstance(match, dict):
            continue
        match_id = str(match.get("id") or match.get("match_id") or match.get("gameId") or "")
        if not match_id:
            continue
        conn.execute(
            """INSERT INTO cs2_matches (id, played_at, map, result, rating, kills, deaths, adr, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                 played_at = excluded.played_at, map = excluded.map, result = excluded.result,
                 rating = excluded.rating, kills = excluded.kills, deaths = excluded.deaths,
                 adr = excluded.adr, raw_json = excluded.raw_json""",
            (match_id, match.get("date") or match.get("played_at"),
             match.get("map") or match.get("map_name"), match.get("result"),
             _to_number(match.get("rating")), match.get("kills"), match.get("deaths"),
             _to_number(match.get("adr")), json.dumps(match)),
        )
        count += 1

    if count:
        mark_dataset(conn, "leetify", source_at=stamp, rows=count)
    return count


# ── freshness ───────────────────────────────────────────────────────────────────────

def ingest_pricewatch(conn, run_id):
    """PC-part prices → price_history, plus buy-window findings.

    Two signals fire a warn finding: an item at/below its configured target price, and a
    ≥10% drop against the item's median over the trailing 30 days (the "beginning to dip"
    signal the tracker exists for). Fetch failures land as rows with error set — Amazon
    blocks bots routinely, and a gap that looks like "unchanged" would defeat the trend."""
    path = os.path.join(agent_logs_dir(), "pricewatch-latest.json")
    try:
        with open(path, encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        mark_dataset(conn, "pricewatch", error=str(exc))
        return 0

    stamp = report.get("run_at") or now_iso()
    day = str(stamp)[:10]
    rows = 0
    for it in report.get("items", []):
        if not it.get("id") or not it.get("retailer"):
            continue
        conn.execute(
            """INSERT INTO price_history
                 (day, item, retailer, at, label, category, price, in_stock,
                  target_price, url, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (day, item, retailer) DO UPDATE SET
                 at = excluded.at, price = excluded.price, in_stock = excluded.in_stock,
                 target_price = excluded.target_price, error = excluded.error""",
            (day, it["id"], it["retailer"], it.get("fetched_at") or stamp,
             it.get("label"), it.get("category"), it.get("price"), it.get("in_stock"),
             it.get("target_price"), it.get("url"), it.get("error")),
        )
        rows += 1

        price = it.get("price")
        if price is None:
            continue
        target = it.get("target_price")
        if target is not None and price <= target:
            conn.execute(
                """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
                   VALUES (?, 'homelab-db', ?, 'warn', 'market', ?, 'pricewatch')""",
                (run_id, stamp,
                 "price-watch: %s at $%.2f (%s), at/below target $%.2f — buy window"
                 % (it.get("label") or it["id"], price, it["retailer"], target)),
            )
            continue
        med = conn.execute(
            """SELECT price FROM price_history
               WHERE item = ? AND retailer = ? AND price IS NOT NULL
                 AND day >= date('now', '-30 day') AND day < ?
               ORDER BY price LIMIT 1
               OFFSET (SELECT COUNT(*) FROM price_history
                        WHERE item = ? AND retailer = ? AND price IS NOT NULL
                          AND day >= date('now', '-30 day') AND day < ?) / 2""",
            (it["id"], it["retailer"], day, it["id"], it["retailer"], day),
        ).fetchone()
        if med and med["price"] and price <= med["price"] * 0.9:
            conn.execute(
                """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
                   VALUES (?, 'homelab-db', ?, 'warn', 'market', ?, 'pricewatch')""",
                (run_id, stamp,
                 "price-watch: %s dipping — $%.2f (%s) is %d%% under its 30-day median $%.2f"
                 % (it.get("label") or it["id"], price, it["retailer"],
                    round((1 - price / med["price"]) * 100), med["price"])),
            )

    mark_dataset(conn, "pricewatch", source_at=stamp, rows=rows)
    return rows


def freshness_findings(conn):
    """Generalises the doctor's stale-report check to every registered dataset.

    A pipeline that silently stops feeding looks exactly like a quiet homelab, which is
    the failure mode this exists to make loud.
    """
    stamp = now_iso()
    run_id = upsert_run(conn, "homelab-db", stamp, stamp[:10], "ok",
                        "data-plane freshness check", "ingest.py")
    now = datetime.now(timezone.utc)
    stale = 0

    for row in conn.execute(
        "SELECT id, label, cadence_hours, last_source_at, last_error FROM datasets "
        "WHERE cadence_hours IS NOT NULL"
    ).fetchall():
        if row["last_error"]:
            conn.execute(
                """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
                   VALUES (?, 'homelab-db', ?, 'warn', NULL, ?, 'freshness')""",
                (run_id, stamp, f"[{row['id']}] ingest error: {row['last_error']}"),
            )
            stale += 1
            continue
        if not row["last_source_at"]:
            continue
        try:
            when = datetime.fromisoformat(str(row["last_source_at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        age_hours = (now - when).total_seconds() / 3600
        budget = row["cadence_hours"] * 2
        if age_hours > budget:
            severity = "critical" if age_hours > budget * 3 else "warn"
            conn.execute(
                """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
                   VALUES (?, 'homelab-db', ?, ?, NULL, ?, 'freshness')""",
                (run_id, stamp, severity,
                 f"[{row['id']}] {row['label']} is {age_hours:.1f}h old "
                 f"(expected every {row['cadence_hours']}h)"),
            )
            stale += 1

    return stale, run_id


def _finalise_run_status(conn, run_id):
    """Roll the homelab-db run up from whatever its checks actually found."""
    counts = dict(conn.execute(
        "SELECT severity, COUNT(*) FROM findings WHERE run_id = ? GROUP BY severity",
        (run_id,),
    ).fetchall())
    critical, warn = counts.get("critical", 0), counts.get("warn", 0)
    if critical:
        status, summary = "critical", f"{critical} critical, {warn} warning(s)"
    elif warn:
        status, summary = "warn", f"{warn} warning(s)"
    else:
        status, summary = "ok", "data plane healthy"
    conn.execute("UPDATE agent_runs SET status = ?, summary = ? WHERE id = ?",
                 (status, summary, run_id))


# ── maintenance ─────────────────────────────────────────────────────────────────────

def render_data_flows(conn):
    """generated/92-data-flows.md — so a session can read the data plane, not re-derive it."""
    out_dir = os.path.join(REPO_ROOT, "homelab", "agentic", "generated")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "92-data-flows.md")

    lines = [
        "# Homelab data flows",
        "",
        "> ⚙️ **AUTO-GENERATED — do not hand-edit.** Rewritten by "
        "`homelab/tools/homelab-db/ingest.py` from the `datasets` registry in that file "
        "(the curated description of the data plane) joined with live ingest state.",
        f"> Generated: `{now_iso()}`",
        "",
        "Every fact the homelab collects flows producer → store → `homelab.db` → consumer. "
        "Query any of it with the `homelab` MCP tools (`hl_status`, `hl_query`, "
        "`hl_search_docs`), or read it on the webapp's Data page.",
        "",
    ]

    stage_titles = [
        ("producer", "Producers — what generates facts"),
        ("store", "Stores — where they land"),
        ("db", "The database"),
        ("consumer", "Consumers — what reads them back"),
    ]
    for stage, heading in stage_titles:
        rows = conn.execute(
            "SELECT * FROM datasets WHERE stage = ? ORDER BY id", (stage,)
        ).fetchall()
        if not rows:
            continue
        lines += [f"## {heading}", ""]
        lines.append("| Dataset | Host | Source | Cadence | Freshness | Consumers |")
        lines.append("|---|---|---|---|---|---|")
        for row in rows:
            cadence = f"{row['cadence_hours']}h" if row["cadence_hours"] else "on demand"
            lines.append(
                f"| **{row['label']}** | {row['producer_host'] or '—'} | `{row['source']}` | "
                f"{cadence} | {age_str(row['last_source_at'] or row['last_ingested'])} | "
                f"{row['consumers'] or '—'} |"
            )
        lines.append("")
        for row in rows:
            if row["notes"]:
                lines.append(f"- **{row['label']}** — {row['notes']}")
        lines.append("")

    counts = []
    for table in ("agent_runs", "findings", "collector_metrics", "docs", "change_events",
                  "arch_nodes", "raw_documents", "vitals_samples"):
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            continue
        counts.append(f"| `{table}` | {total:,} |")
    if counts:
        lines += ["## What is in the database right now", "",
                  "| Table | Rows |", "|---|---|"] + counts + [""]

    oldest = conn.execute("SELECT MIN(run_date) FROM agent_runs").fetchone()[0]
    if oldest:
        lines.append(f"History reaches back to **{oldest}**.")
        lines.append("")

    content = "\n".join(lines).rstrip() + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)
    return path


def age_str(iso):
    if not iso:
        return "never"
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)
    hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    if hours < 1:
        return f"{int(hours * 60)}m ago"
    if hours < 48:
        return f"{hours:.0f}h ago"
    return f"{hours / 24:.0f}d ago"


def backup_snapshot(conn):
    """VACUUM INTO a consistent snapshot, verify it, then publish it atomically.

    The weekly coldcopy rsyncs the shared tree. Copying a live database plus its -wal is
    a documented corruption path, so what lands in that tree is a snapshot taken by
    SQLite itself, integrity-checked before it replaces the previous one.
    """
    directory = backup_dir()
    os.makedirs(directory, exist_ok=True)
    final = os.path.join(directory, "homelab-snapshot.db")
    tmp = final + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)

    # VACUUM cannot run inside a transaction — this is called outside the write block.
    conn.execute("VACUUM INTO ?", (tmp,))
    check = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        os.remove(tmp)
        raise RuntimeError(f"snapshot failed integrity_check: {result}")
    os.replace(tmp, final)
    return final, os.path.getsize(final)


def maintenance(conn):
    """The daily block. Called OUTSIDE a write transaction — VACUUM INTO cannot run in one."""
    done = {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=QUERY_AUDIT_KEEP_DAYS)).isoformat()

    with db.writing(conn):
        cursor = conn.execute("DELETE FROM query_audit WHERE at < ?", (cutoff,))
        done["query_audit_pruned"] = cursor.rowcount
        conn.execute(
            "INSERT INTO ingest_state (key, value, updated_at) VALUES ('last_maintenance', ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (now_iso(), now_iso()),
        )

    try:
        done["docs"] = render_data_flows(conn)
        with db.writing(conn):
            mark_dataset(conn, "generated-flows", source_at=now_iso())
    except OSError as exc:
        done["docs_error"] = str(exc)
        with db.writing(conn):
            mark_dataset(conn, "generated-flows", error=str(exc))

    try:
        path, size = backup_snapshot(conn)
        done["snapshot"] = f"{path} ({size / 1_048_576:.1f} MiB)"
    except Exception as exc:  # noqa: BLE001 — a failed backup must not fail the cycle
        done["snapshot_error"] = str(exc)

    return done


def maintenance_due(conn):
    row = conn.execute("SELECT value FROM ingest_state WHERE key = 'last_maintenance'").fetchone()
    if not row or not row["value"]:
        return True
    try:
        when = datetime.fromisoformat(str(row["value"]).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600 >= MAINTENANCE_EVERY_HOURS


# ── cycle ───────────────────────────────────────────────────────────────────────────

def run_cycle(conn, backfill=False, force_maintenance=False, verbose=True):
    started = time.time()
    stats = {}

    with db.writing(conn):
        sync_registry(conn)

        reports, newest = ingest_reports_dir(conn, agent_logs_dir(), "agent-logs", backfill=backfill)
        stats["reports"] = reports

        security, newest_security = ingest_reports_dir(
            conn, reports_dir(), "security-reports", backfill=backfill
        )
        stats["security_reports"] = security

        newest_agent_sync = None
        data, error = fetch_arch_data()
        if data:
            stats["change_events"] = ingest_arch(conn, data)
            merge = (data.get("live_merge") or {}).get("generated_at")
            mark_dataset(conn, "arch-merged", source_at=merge or now_iso(),
                         rows=len(data.get("nodes") or []))
            # The agents' own freshness is the newest fragment they pushed, not the age
            # of the merge — a webapp that keeps serving a week-old fragment would
            # otherwise read as healthy.
            collected = [i.get("collected_at") for i in
                         ((data.get("live_merge") or {}).get("ingested") or {}).values()
                         if i.get("collected_at")]
            newest_agent_sync = max(collected) if collected else None
        else:
            stats["arch_error"] = error
            mark_dataset(conn, "arch-merged", error=error)

        stats["docs"] = ingest_docs(conn)
        newest_doc = conn.execute("SELECT MAX(mtime) FROM docs").fetchone()[0]
        mark_dataset(conn, "docs-corpus", source_at=newest_doc or now_iso(), rows=stats["docs"])
        stats["raw"] = ingest_workspace(conn)

        # Producers are graded on the freshness of what they produced, so a stalled
        # collector or a silent agent shows up as a stale dataset rather than a blank.
        mark_dataset(conn, "collectors", source_at=newest)
        mark_dataset(conn, "security-tools", source_at=newest_security)
        mark_dataset(conn, "arch-agents", source_at=newest_agent_sync)
        mark_dataset(conn, "repo-curated", source_at=newest_doc)
        mark_dataset(conn, "homelab-db", source_at=now_iso())

        # The read side has no other way to report itself: every served query writes an
        # audit row, so the newest one is when the API/MCP surface was last actually used.
        last_query = conn.execute("SELECT MAX(at) FROM query_audit").fetchone()[0]
        if last_query:
            mark_dataset(conn, "mcp-server", source_at=last_query)

        stats["incidents"] = ingest_incidents(conn)
        stats["cs2_rows"] = ingest_leetify(conn)
        stats["monitors"] = ingest_monitors(conn)
        devices, new_devices = ingest_net_devices(conn)
        stats["devices"] = f"{devices} ({new_devices} new)"
        stats["pihole_days"] = ingest_pihole_daily(conn)
        stats["media"] = ingest_media_counters(conn)

        # freshness_findings owns the homelab-db run row; the bundle checks below hang
        # their findings off the same run so "what is wrong right now" is one query.
        stats["stale_datasets"], run_id = freshness_findings(conn)
        certs, cert_warnings = ingest_certificates(conn, run_id)
        stats["certificates"] = certs
        stats["cert_warnings"] = cert_warnings
        stats["smart_flags"] = check_smart(conn, run_id)
        stats["prices"] = ingest_pricewatch(conn, run_id)
        checked, drifted, skipped = ingest_deploy_drift(conn, run_id)
        stats["deploy_drift"] = f"{drifted} drifted / {checked} checked" + (
            f" ({skipped} skipped: repo dirty)" if skipped else "")
        bots, silent = ingest_bot_health(conn, run_id)
        stats["bots_silent"] = f"{silent}/{bots}"
        _finalise_run_status(conn, run_id)

    if force_maintenance or maintenance_due(conn):
        stats["maintenance"] = maintenance(conn)

    # Keep the -wal file from growing without bound between vacuum runs.
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    stats["seconds"] = round(time.time() - started, 2)
    if verbose:
        print(f"[ingest] {json.dumps(stats, default=str)}")
    return stats


# ── self-test ───────────────────────────────────────────────────────────────────────

def self_check():
    """Schema applies, registry is valid, and a fixture report ingests. No real I/O."""
    problems = validate_registry()

    conn = db.connect_rw(":memory:", create=False)
    try:
        db.migrate(conn)
        tables = set(db.table_names(conn))
        for required in ("datasets", "agent_runs", "findings", "collector_metrics",
                         "live_state", "change_events", "docs", "raw_documents",
                         "vitals_samples", "query_audit"):
            if required not in tables:
                problems.append(f"schema missing table {required}")

        fixture = {
            "tool": "fixture-report",
            "run_at": "2026-01-01T00:00:00+00:00",
            "status": "warn",
            "summary": "fixture",
            "findings": [{"severity": "warn", "message": "[opti] something to look at"}],
            "services": [{"name": "Webapp", "url": "https://x/", "up": True, "cert_days_left": 42}],
            "hosts": [{"host": "opti", "status": "ok", "summary": "fine",
                       "metrics": {"disk_used_pct": 77.0, "pool": {"used_pct": 18.6},
                                   "containers": ["a", "b"], "governor": "powersave"}}],
        }
        with db.writing(conn):
            sync_registry(conn)
            result = ingest_report(conn, "/fixture.json", fixture)
        if not result:
            problems.append("fixture report was not ingested")

        metrics = dict(conn.execute(
            "SELECT metric, value FROM collector_metrics WHERE tool = 'fixture-report'"
        ).fetchall())
        for metric, expected in (("disk_used_pct", 77.0), ("pool_used_pct", 18.6),
                                 ("containers_count", 2.0)):
            if metrics.get(metric) != expected:
                problems.append(f"metric {metric}: expected {expected}, got {metrics.get(metric)}")
        if "governor" in metrics:
            problems.append("string metric 'governor' should have been skipped")

        finding = conn.execute("SELECT host, severity FROM findings").fetchone()
        if not finding or finding["host"] != "opti":
            problems.append("finding host prefix was not parsed")

        # Idempotence: the same report twice must not duplicate children.
        with db.writing(conn):
            ingest_report(conn, "/fixture.json", fixture)
        if conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0] != 1:
            problems.append("re-ingesting a report duplicated its findings")

        title, chunks = chunk_markdown("# Title\n\nintro\n\n## One\n\nbody\n\n## Two\n\nmore\n")
        if title != "Title" or len(chunks) != 3:
            problems.append(f"markdown chunking wrong: {title!r}, {len(chunks)} chunks")
    finally:
        conn.close()

    for problem in problems:
        print(f"[check] FAIL {problem}", file=sys.stderr)
    if not problems:
        print("[check] ok — schema, registry, ingest, metrics, chunking")
    return 1 if problems else 0


def write_readme_marker():
    """Drop the CIFS warning next to the database, where someone poking at it will see it."""
    directory = os.path.dirname(db.db_path())
    if not os.path.isdir(directory):
        return
    path = os.path.join(directory, "README")
    if os.path.exists(path):
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "homelab.db — the homelab's queryable index (see homelab/tools/homelab-db/).\n\n"
            "Only opti-local processes may open this file. It is deliberately outside\n"
            "/srv/red/fs so it is NOT reachable over the Samba share: SQLite WAL needs\n"
            "same-host shared memory, and opening it over CIFS risks torn reads even\n"
            "read-only. From tux or rpi, query http://192.168.1.11:9100 instead.\n\n"
            "Do not rsync homelab.db + homelab.db-wal; back up the snapshot that\n"
            "ingest.py writes to ../homelab-db/backup/ instead.\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--init", action="store_true", help="create database and directories, then exit")
    parser.add_argument("--backfill", action="store_true", help="also ingest every dated report file")
    parser.add_argument("--maintenance", action="store_true", help="force the daily maintenance block")
    parser.add_argument("--check", action="store_true", help="self-test against an in-memory database")
    args = parser.parse_args()

    if args.check:
        return self_check()

    problems = validate_registry()
    if problems:
        for problem in problems:
            print(f"[ingest] invalid dataset registry: {problem}", file=sys.stderr)
        return 1

    conn = db.connect_rw()
    try:
        version = db.migrate(conn, verbose=True)
        write_readme_marker()
        if args.init:
            with db.writing(conn):
                sync_registry(conn)
            print(f"[ingest] initialised {db.db_path()} (schema v{version})")
            # `--init --backfill` reads as one setup command, so fall through and run it
            # rather than making the operator invoke the script twice.
            if not args.backfill:
                return 0
        run_cycle(conn, backfill=args.backfill, force_maintenance=args.maintenance)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
