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
    HL_ARCH_DATA_URL    default https://webapp.lan:8443/api/architecture/data
    HL_WEBAPP_API       default https://webapp.lan:8443/api (falls back to opti's IP)
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
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402  (sibling module, path set above)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

# The webapp moved rpi -> opti on 2026-09-10 (rpi is DNS-only now). Everything the ingest
# reads over HTTP goes through it: the bot control APIs are docker-internal on opti, Uptime
# Kuma lives on noblenumbat, and Pi-hole v6 needs a session login — the webapp already
# holds all of that, so reading through its read-only proxies needs no secret here.
#
# Hostname first, IP second: when DNS (rpi) is the thing that is broken, webapp.lan is
# exactly what fails, and the webapp is still there on opti's IP.
WEBAPP_HOST_URL = "https://webapp.lan:8443"
WEBAPP_IP_URL = "https://192.168.1.11:8443"

WEBAPP_API = os.environ.get("HL_WEBAPP_API", WEBAPP_HOST_URL + "/api")
WEBAPP_API_FALLBACK = WEBAPP_IP_URL + "/api"

ARCH_URL = os.environ.get("HL_ARCH_DATA_URL", WEBAPP_HOST_URL + "/api/architecture/data")
ARCH_URL_FALLBACK = WEBAPP_IP_URL + "/api/architecture/data"

FETCH_ERRORS = (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError)

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
     "producer_host": "opti", "source": "systemd hl-collector-{frequent,daily}@.timer", "format": "python",
     "cadence_hours": 0.5, "stage": "producer", "consumers": "agent-logs",
     "notes": "doctor + network every 30 min (:05/:35), hardware + software daily 09:00 UTC, as "
              "hl-collector@<name>.service on opti since 2026-09-24. They were a GitHub cron that "
              "fired only every 3-6h. A failed run pushes an ntfy alert (OnFailure). SSH fan-out "
              "via the hl_agents key, one multiplexed connection per host."},
    {"id": "security-tools", "label": "Security auditors", "producer": "homelab/tools/security/*.py",
     "producer_host": "opti", "source": "systemd hl-collector-daily@.timer", "format": "python",
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
     "producer_host": "opti", "source": "GET webapp.lan:8443/api/architecture/data", "format": "http",
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
     "producer_host": "noblenumbat", "source": "GET /api/uptime (via webapp on opti)", "format": "http",
     "cadence_hours": 0.5, "stage": "store", "consumers": "monitor_history",
     "retention": "sampled every cycle, kept indefinitely",
     "notes": "Kuma runs on noblenumbat :3001 since 2026-09-10 (so it watches opti from outside). "
              "Its own history is behind an admin login; sampling the webapp's read-only proxy "
              "each cycle is what makes availability queryable."},
    {"id": "deploy-drift", "label": "Deployed-copy drift", "producer": "ingest.py",
     "producer_host": "opti", "source": "hash of /srv/docker/compose/webapp/backend vs repo webapp.v3.Fable", "format": "sha256",
     "cadence_hours": 0.5, "stage": "producer", "consumers": "findings",
     "notes": "A direct edit to a deploy target is reverted by the next CI run — this makes that silent loss loud. "
              "On opti the repo is a .git-less CI snapshot of main, which counts as clean."},
    {"id": "bot-health", "label": "Discord bot post freshness", "producer": "bot control APIs",
     "producer_host": "opti", "source": "GET /api/<bot>/status (via webapp)", "format": "http",
     "cadence_hours": 0.5, "stage": "producer", "consumers": "findings",
     "notes": "A dead daily bot is silent, and silence looks exactly like a quiet day. A bot whose "
              "status route fails, or whose last attempt failed, is a finding too."},
    {"id": "dhcp-leases", "label": "LAN device inventory", "producer": "Pi-hole FTL network table",
     "producer_host": "rpi", "source": "pihole:/etc/pihole/pihole-FTL.db network tables (over SSH)", "format": "sqlite",
     "cadence_hours": 0.5, "stage": "store", "consumers": "net_devices, change_events",
     "notes": "The router has been the DHCP server since Sept 2026, so Pi-hole's dhcp.leases is frozen "
              "(last written 2026-09-08). FTL's network table is fed from rpi's ARP cache and every "
              "DNS client, so it still sees the whole LAN; a device seen in the last 24h is active. "
              "A device never seen before becomes a change event. (id kept for history.)"},
    {"id": "pihole-stats", "label": "Pi-hole query stats", "producer": "Pi-hole FTL",
     "producer_host": "rpi", "source": "GET /api/pihole/summary (via webapp on opti)", "format": "http",
     "cadence_hours": 0.5, "stage": "store", "consumers": "pihole_daily",
     "notes": "Pi-hole v6 (session-auth /api). The webapp holds the login and proxies a summary, "
              "so the ingest needs no Pi-hole secret."},
    {"id": "media-counters", "label": "Media library counters", "producer": "sonarr/radarr APIs",
     "producer_host": "noblenumbat", "source": "localhost *arr APIs (queried over SSH)", "format": "http",
     "cadence_hours": 0.5, "stage": "store", "consumers": "media_counters",
     "notes": "The query runs on noblenumbat so each API key is read from its own config.xml and used against localhost — no key is copied to opti."},
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
    {"id": "webapp-data", "label": "Webapp widgets + Data page", "producer": "webapp.v3.Fable backend/routes/hldb.js",
     "producer_host": "opti", "source": "GET webapp.lan:8443/api/hldb/*", "format": "http",
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
    #
    # service_checks was missing from this list until 2026-09-10, and the omission was
    # invisible for as long as each run was only ever ingested once. The moment a run
    # was re-ingested (a doctor re-run inside the same bucket, so the same run_id) its
    # service rows were appended instead of replaced, and hl_status — which filters by
    # run_id and reasonably assumed that was enough — returned the same service several
    # times over, once per ingest, each carrying whatever result was true at the time.
    # That is how the dashboard came to show two "Homelab webapp" rows, one up and one
    # down: not two monitors disagreeing, just one monitor remembered twice.
    conn.execute("DELETE FROM findings WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM host_reports WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM service_checks WHERE run_id = ?", (run_id,))
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


def _first_ok(urls, timeout):
    """Try each URL in turn; returns (data, None) or (None, error naming every attempt)."""
    errors = []
    for url in dict.fromkeys(urls):  # de-dupe, keep order
        try:
            return fetch_json(url, timeout=timeout), None
        except FETCH_ERRORS as exc:
            errors.append(f"{url}: {exc}")
    return None, "; ".join(errors)


def fetch_webapp(path, timeout=12):
    """GET <webapp>/api<path>, hostname first then opti's IP. Returns (data, error)."""
    return _first_ok((WEBAPP_API + path, WEBAPP_API_FALLBACK + path), timeout)


def fetch_arch_data():
    return _first_ok((ARCH_URL, ARCH_URL_FALLBACK), 20)


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
    # Metrics are keyed by device letter (smart_sdb_reallocated), and letters are NOT
    # stable: on 2026-09-10 opti's Seagate boot disk moved sda -> sdb and the Hitachi
    # sdb -> sda, so the naive "oldest vs newest" read as "grew from 3 to 272" and paged
    # critical. The disk's own power-on hours identify it: they only ever rise, by at most
    # the wall-clock time elapsed. A reading where they fall, or jump further than time
    # allows, is a different physical disk — only readings since the last such break
    # belong to today's disk. (A counter that falls is the same signal, as a backstop.)
    #
    # Severity: pending sectors, or reallocations that grew in the last 30 days, mean
    # the drive is actively degrading (critical). Old, slow growth is a warn that still
    # shows the full trend — 8 sectors every two months is not an emergency.
    series, poh = {}, {}
    for r in conn.execute(
        """SELECT host, metric, at, value FROM collector_metrics
           WHERE metric LIKE 'smart%reallocated' OR metric LIKE 'smart%pending'
              OR metric LIKE 'smart%power_on_hours'
           ORDER BY host, metric, at"""
    ):
        if r["metric"].endswith("power_on_hours"):
            dev = r["metric"][len("smart_"):-len("_power_on_hours")]
            poh.setdefault((r["host"], dev), {})[r["at"]] = r["value"]
        else:
            series.setdefault((r["host"], r["metric"]), []).append((r["at"], r["value"] or 0))

    def _hours_between(a, b):
        try:
            return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600
        except ValueError:
            return None

    def _same_disk(hours, prev_at, at):
        h0, h1 = hours.get(prev_at), hours.get(at)
        if h0 is None or h1 is None:
            return True
        elapsed = _hours_between(prev_at, at)
        return h1 >= h0 and (elapsed is None or h1 - h0 <= elapsed + 48)

    recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    for (host, metric), points in series.items():
        dev = metric[len("smart_"):].rsplit("_", 1)[0]
        hours = poh.get((host, dev), {})
        start = 0
        for i in range(1, len(points)):
            if (points[i][1] < points[i - 1][1]
                    or not _same_disk(hours, points[i - 1][0], points[i][0])):
                start = i
        points = points[start:]
        latest = points[-1][1]
        if latest <= 0:
            continue
        since, earliest = points[0]
        disk = dev
        kind = "reallocated" if metric.endswith("reallocated") else "pending"
        grew_recently = any(points[i][1] > points[i - 1][1] and points[i][0] >= recent_cutoff
                            for i in range(1, len(points)))
        if kind == "pending" or grew_recently:
            severity = "critical"
        else:
            severity = "warn"
        if latest > earliest:
            detail = (f"{latest:.0f} (up from {earliest:.0f} since {str(since)[:10]}"
                      + ("; grew in the last 30 days" if grew_recently else "") + ")")
        else:
            detail = f"{latest:.0f}, unchanged since {str(since)[:10]}"
        conn.execute(
            """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
               VALUES (?, 'homelab-db', ?, ?, ?, ?, 'expiry')""",
            (run_id, stamp, severity, host,
             f"[{host}] {disk} SMART {kind} sectors: {detail}"),
        )
        flagged += 1
    return flagged


def ingest_monitors(conn):
    """Availability history from Uptime Kuma, via the webapp's read-only proxy.

    Kuma's own history lives behind an admin login; /api/uptime exposes the current state
    of every monitor, so sampling it each cycle is what turns it into a series.
    """
    data, error = fetch_webapp("/uptime")
    if error:
        mark_dataset(conn, "uptime-kuma", error=error)
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
        # The webapp's proxy names response time `ms`; older builds used response_time.
        resp = monitor.get("ms", monitor.get("response_time"))
        conn.execute(
            """INSERT INTO monitor_history (monitor, at, status, up, resp_ms)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (monitor, at) DO NOTHING""",
            (name, stamp, status, 1 if status == "up" else 0, resp),
        )
    mark_dataset(conn, "uptime-kuma", source_at=stamp, rows=len(monitors))
    return len(monitors)


# Deployed copies that CI overwrites. Editing one of these directly is a known way to
# lose work silently — the next deploy reverts it — so the drift is worth a finding.
#
# Since 2026-09-10 the app tier is on opti and the deployed webapp is webapp.v3.Fable
# (.github/workflows/opti-apps-deploy.yml rsyncs it to /srv/docker/compose/webapp/).
DEPLOY_TARGETS = [
    {"host": "opti", "remote": "/srv/docker/compose/webapp/backend",
     "repo": "homelab/hosts/opti/apps/webapp.v3.Fable/backend", "label": "webapp backend",
     "workflow": "opti-apps-deploy.yml"},
]
LOCAL_HOST = "opti"  # where ingest.py runs; its own deploy targets are hashed without SSH


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
            rel = "./" + os.path.relpath(full, path).replace(os.sep, "/")
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

    On opti — where this normally runs — REPO_ROOT is not a git checkout at all: it is the
    `.git`-less snapshot that opti-deploy.yml rsyncs from main on every push. Nobody edits
    it, so it IS the committed state, and counts as clean. (Before this, `git status`
    failing there made every cycle report "skipped: repo dirty" and the check never ran.)
    """
    import subprocess
    if not os.path.exists(os.path.join(REPO_ROOT, ".git")):
        return True
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
        if target["host"] == LOCAL_HOST and os.path.isdir(target["remote"]):
            remote_hash = _tree_hash_local(target["remote"])
        else:
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
                 f"deploy reverts that) or a deploy did not complete — check "
                 f"{target.get('workflow', 'the deploy workflow')}."),
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


def _bot_stopped_on_purpose(bot):
    """True when discord-<bot> is `exited` under a restart policy that would have revived
    a crash — i.e. someone ran `docker stop` (discord-hltv, 2026-09-23: it was spamming
    HLTV). Docker only leaves an unless-stopped/always container down after a manual stop.
    Any failure to ask docker returns False, so the finding still fires."""
    import subprocess
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}} {{.HostConfig.RestartPolicy.Name}}",
             f"discord-{bot}"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    state, _, policy = out.stdout.strip().partition(" ")
    return state == "exited" and policy in ("unless-stopped", "always")


def ingest_bot_health(conn, run_id):
    """Did each daily bot actually post?

    A dead bot is silent, and silence in Discord looks exactly like a quiet day. The bot
    control APIs are docker-internal on opti, so this goes through the webapp's
    existing proxy rather than trying to reach them directly.

    Three things are findings: a status route that does not answer (the bot container is
    down — nginx says 502), a last attempt that reported failure, and no post in
    BOT_SILENT_HOURS. If *no* route answers, the webapp itself is unreachable and the
    dataset records that as its error rather than looking fresh with zero rows.
    """
    stamp = now_iso()
    checked = stale = 0
    unreachable = []
    paused = []  # deliberately off: docker-stopped, or the bot reports enabled=false

    def finding(message):
        conn.execute(
            """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
               VALUES (?, 'homelab-db', ?, 'warn', 'opti', ?, 'freshness')""",
            (run_id, stamp, message),
        )

    for bot, route in BOT_ROUTES.items():
        status, error = fetch_webapp(route, timeout=10)
        if error:
            if _bot_stopped_on_purpose(bot):
                paused.append(bot)
                continue
            unreachable.append(bot)
            stale += 1
            finding(f"[bots] discord-{bot} status route unreachable: {error[:200]}")
            continue
        if isinstance(status, dict) and status.get("enabled") is False:
            paused.append(bot)
            continue
        checked += 1
        if not isinstance(status, dict):
            continue
        last_status = str(status.get("last_status") or "")
        if last_status.lower().startswith(("fail", "error")):
            stale += 1
            finding(f"[bots] discord-{bot} last attempt {status.get('last_post_at') or ''}: "
                    f"{last_status[:160]}")
        last_post = None
        for key in ("last_post_at", "last_post", "last_posted", "last_run", "last_sent"):
            if status.get(key):
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
            finding(f"[bots] discord-{bot} has not posted in {age:.0f}h "
                    f"(last {str(last_post)[:16]})")
    if paused:
        print(f"[ingest] bots deliberately off, not checked: {', '.join(paused)}", flush=True)
    if checked == 0 and unreachable:
        mark_dataset(conn, "bot-health",
                     error=f"no bot status route answered ({', '.join(unreachable)})")
    elif checked == 0:
        mark_dataset(conn, "bot-health", source_at=stamp, rows=0)
    else:
        mark_dataset(conn, "bot-health", source_at=stamp, rows=checked)
    return checked, stale


# Pi-hole FTL's device table: one row per MAC (network) with every address it has used
# (network_addresses), each with the last time rpi's ARP cache / a DNS query saw it.
# Newest address first, so the first IPv4 per MAC is its current one.
NET_DEVICES_SQL = (
    "SELECT n.hwaddr, a.ip, COALESCE(a.name, ''), a.lastSeen "
    "FROM network n JOIN network_addresses a ON a.network_id = n.id "
    "WHERE n.hwaddr LIKE '__:__:__:__:__:__' AND n.hwaddr <> '00:00:00:00:00:00' "
    "AND a.ip LIKE '192.168.1.%' "
    "ORDER BY a.lastSeen DESC"
)
NET_ACTIVE_HOURS = 24  # seen within this window = on the LAN now


def parse_net_devices(raw, now_epoch):
    """`mac|ip|name|lastSeen` lines -> {mac: (ip, hostname)} for devices seen recently."""
    seen = {}
    cutoff = now_epoch - NET_ACTIVE_HOURS * 3600
    for line in raw.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 4:
            continue
        mac, ip, name, last_seen = parts
        mac = mac.lower()
        if mac in seen or not last_seen.isdigit() or int(last_seen) < cutoff:
            continue
        hostname = name.strip() or None
        if hostname and hostname.endswith(".lan"):
            hostname = hostname[:-4]
        seen[mac] = (ip, hostname)
    return seen


def ingest_net_devices(conn):
    """LAN inventory from Pi-hole FTL's network table; a new device becomes a change event.

    This used to read Pi-hole's dhcp.leases, but the router took over DHCP in Sept 2026
    and that file has been frozen since 2026-09-08 — it kept "succeeding" with the same 9
    stale leases every cycle (and ignored the expiry column), so the inventory looked
    fresh while describing a LAN from two weeks earlier. FTL's network table is fed from
    rpi's ARP cache and from every DNS client, which is still the whole LAN.

    Read over SSH with the collectors' key (no Pi-hole API password needed on opti), with
    FTL's bundled sqlite3 in read-only mode — the container has no other sqlite binary.
    """
    raw = run_ssh("rpi", ["sudo", "-n", "docker", "exec", "pihole", "pihole-FTL", "sqlite3",
                          "-readonly", "-separator", "|", "/etc/pihole/pihole-FTL.db",
                          NET_DEVICES_SQL])
    if not raw:
        mark_dataset(conn, "dhcp-leases",
                     error="could not read pihole-FTL.db network table on rpi over SSH")
        return 0, 0

    stamp = now_iso()
    seen = parse_net_devices(raw, time.time())
    if not seen:
        mark_dataset(conn, "dhcp-leases",
                     error=f"pihole network table had no device seen in {NET_ACTIVE_HOURS}h")
        return 0, 0

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
    """Query/block totals per day, through the webapp's read-only Pi-hole proxy.

    rpi runs Pi-hole v6, whose /api needs a session login; the webapp (on opti) holds
    that login and serves this summary, so nothing here needs a Pi-hole password.
    """
    summary, error = fetch_webapp("/pihole/summary")
    if error:
        mark_dataset(conn, "pihole-stats", error=error)
        return 0

    if not isinstance(summary, dict):
        mark_dataset(conn, "pihole-stats", error="unexpected /api/pihole/summary shape")
        return 0
    if summary.get("error") and summary.get("dns_queries_today") is None:
        mark_dataset(conn, "pihole-stats", error=f"webapp pihole proxy: {summary['error']}")
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
         summary.get("domains_being_blocked") or summary.get("gravity_domains")
         or summary.get("domains_blocked")),
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


def open_health_run(conn):
    """The homelab-db agent_runs row every check of this cycle hangs its findings off,
    so "what is wrong with the data plane right now" is one query."""
    stamp = now_iso()
    return upsert_run(conn, "homelab-db", stamp, stamp[:10], "ok",
                      "data-plane freshness check", "ingest.py")


def freshness_findings(conn, run_id):
    """Generalises the doctor's stale-report check to every registered dataset.

    A pipeline that silently stops feeding looks exactly like a quiet homelab, which is
    the failure mode this exists to make loud. Runs LAST in the cycle, after every step
    has marked its dataset, so this cycle's errors are reported this cycle.

    A dataset that is erroring gets both findings: the error (why) and, once its last
    good data is past budget, the age (how long) — so a feed that has been down for two
    weeks escalates to critical instead of reading as one more "ingest error" warning.
    """
    stamp = now_iso()
    now = datetime.now(timezone.utc)
    stale = 0

    def finding(severity, message):
        conn.execute(
            """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
               VALUES (?, 'homelab-db', ?, ?, NULL, ?, 'freshness')""",
            (run_id, stamp, severity, message),
        )

    for row in conn.execute(
        "SELECT id, label, cadence_hours, last_source_at, last_error FROM datasets "
        "WHERE cadence_hours IS NOT NULL"
    ).fetchall():
        flagged = False
        if row["last_error"]:
            finding("warn", f"[{row['id']}] ingest error: {row['last_error'][:500]}")
            flagged = True
        when = None
        if row["last_source_at"]:
            try:
                when = datetime.fromisoformat(str(row["last_source_at"]).replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except ValueError:
                when = None
        if when is not None:
            age_hours = (now - when).total_seconds() / 3600
            budget = row["cadence_hours"] * 2
            if age_hours > budget:
                severity = "critical" if age_hours > budget * 3 else "warn"
                finding(severity, f"[{row['id']}] {row['label']} is {age_hours:.1f}h old "
                                  f"(expected every {row['cadence_hours']}h)")
                flagged = True
        # never produced and never failed = not wired yet; nothing to say
        stale += flagged

    return stale


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

# ── phone alerts (ntfy) ─────────────────────────────────────────────────────────────
# Each cycle computes the set of OPEN problems — the warn/critical findings of every
# tool's latest run — and pushes only the difference from last cycle: new problems in
# one grouped message, cleared ones in one quiet "resolved" message. The open set lives
# in ingest_state, so an unchanged problem never re-pages however many cycles it lasts.
#
# Everything critical pages. A warning pages only from the sources below; the rest
# (pending apt updates, journald pattern counts, ...) stays visible in hl_status without
# buzzing a phone every morning.
ALERT_WARN_TOOLS = {"homelab-doctor"}
ALERT_WARN_KINDS = {"freshness", "drift"}
ALERT_WARN_PREFIXES = ("NEW persistence entry", "[bots]")
ALERT_TOOL_MAX_AGE_DAYS = 3   # a tool that stopped running (leetify) can't hold alerts open

OPEN_FINDINGS_SQL = """
WITH latest AS (SELECT tool, MAX(julianday(run_at)) jd FROM agent_runs GROUP BY tool)
SELECT f.tool, f.severity, COALESCE(f.host, '') host, f.message, f.kind
FROM findings f JOIN latest l ON l.tool = f.tool
WHERE f.severity IN ('warn', 'critical')
  AND julianday(f.run_at) >= l.jd - (5.0 / 1440)
  AND l.jd >= julianday('now') - ?
"""


def _alert_key(row):
    # Digits collapse so "pool at 91%" -> "pool at 92%" is the same open problem, not a
    # new one every cycle.
    return "|".join((row["tool"], row["host"], re.sub(r"\d+", "#", row["message"])[:200]))


def _should_page(row):
    if row["severity"] == "critical":
        return True
    return (row["tool"] in ALERT_WARN_TOOLS or row["kind"] in ALERT_WARN_KINDS
            or row["message"].startswith(ALERT_WARN_PREFIXES))


def push_alerts(conn):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from notify import notify  # homelab/tools/notify.py

    rows = [dict(r) for r in conn.execute(OPEN_FINDINGS_SQL, (ALERT_TOOL_MAX_AGE_DAYS,))]
    current = {_alert_key(r): r for r in rows if _should_page(r)}
    prior_row = conn.execute("SELECT value FROM ingest_state WHERE key = 'alerts_open'").fetchone()
    first_run = prior_row is None
    prior = json.loads(prior_row[0]) if prior_row else {}

    new = [current[k] for k in current if k not in prior]
    resolved = [prior[k] for k in prior if k not in current]

    def line(r):
        return f"{'🔴' if r['severity'] == 'critical' else '🟡'} {r['message'][:180]}"

    sent_ok = True
    if first_run:
        sent_ok = notify(
            "homelab alerts online",
            (f"{len(current)} open issue(s) right now:\n" + "\n".join(line(r) for r in current.values()))
            if current else "Nothing open. You'll hear from this when something breaks.",
            priority="low", tags=["bell"])
    else:
        if new:
            crit = any(r["severity"] == "critical" for r in new)
            title = (new[0]["message"][:120] if len(new) == 1
                     else f"{len(new)} new homelab issues")
            sent_ok = notify(title, "\n".join(line(r) for r in new),
                             priority="high" if crit else "default",
                             tags=["rotating_light" if crit else "warning"])
        if resolved:
            notify(f"{len(resolved)} homelab issue(s) resolved",
                   "\n".join(f"✅ {r['message'][:180]}" for r in resolved),
                   priority="low", tags=["white_check_mark"])

    # Only advance the open set once the page actually went out — an ntfy outage must
    # not swallow a new problem; it gets re-sent next cycle instead.
    if sent_ok:
        slim = {k: {"tool": r["tool"], "severity": r["severity"], "message": r["message"]}
                for k, r in current.items()}
        with db.writing(conn):
            conn.execute(
                "INSERT INTO ingest_state (key, value, updated_at) VALUES ('alerts_open', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (json.dumps(slim), now_iso()),
            )
    return f"{len(current)} open, {len(new)} new, {len(resolved)} resolved" + ("" if sent_ok else " (ntfy unreachable)")


def heartbeat(stats):
    """Dead-man's switch: ping Uptime Kuma's Push monitor (HL_KUMA_PUSH_URL) each cycle.
    Kuma runs on noblenumbat, so if this ingest — or opti itself — stops, Kuma notices the
    missing heartbeat and alerts through ntfy from outside opti."""
    url = os.environ.get("HL_KUMA_PUSH_URL")
    if not url:
        return
    errors = stats.get("step_errors")
    status = "down" if errors else "up"
    msg = f"steps crashed: {', '.join(errors)}" if errors else "ok"
    try:
        sep = "&" if "?" in url else "?"
        urllib.request.urlopen(f"{url}{sep}status={status}&msg={urllib.parse.quote(msg)}", timeout=10).read()
    except Exception as exc:  # noqa: BLE001
        print(f"[ingest] kuma heartbeat failed: {exc}", flush=True)


def run_cycle(conn, backfill=False, force_maintenance=False, verbose=True):
    started = time.time()
    stats = {}

    step_errors = {}

    def step(name, fn, *args, dataset=None):
        """Run one ingest step inside a SAVEPOINT.

        One feed failing must never cost the rest of the cycle: before this, any
        exception (a changed JSON shape, a locked file) propagated out of the single
        BEGIN IMMEDIATE block and rolled back *every* feed's writes for that cycle. Now
        the failed step's partial writes roll back, its dataset records last_error (so
        freshness_findings reports it), and the cycle carries on.
        """
        conn.execute("SAVEPOINT ingest_step")
        try:
            result = fn(*args)
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            conn.execute("ROLLBACK TO ingest_step")
            conn.execute("RELEASE ingest_step")
            message = f"{type(exc).__name__}: {exc}"
            step_errors[name] = message
            if dataset:
                mark_dataset(conn, dataset, error=f"ingest step '{name}' crashed — {message}")
            return None
        conn.execute("RELEASE ingest_step")
        return result

    with db.writing(conn):
        sync_registry(conn)
        run_id = open_health_run(conn)

        r = step("agent-logs", ingest_reports_dir, conn, agent_logs_dir(), "agent-logs",
                 backfill, dataset="agent-logs")
        stats["reports"], newest = r if r else (None, None)

        r = step("security-reports", ingest_reports_dir, conn, reports_dir(),
                 "security-reports", backfill, dataset="security-reports")
        stats["security_reports"], newest_security = r if r else (None, None)

        def arch():
            data, error = fetch_arch_data()
            if not data:
                stats["arch_error"] = error
                mark_dataset(conn, "arch-merged", error=error)
                return None
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
            return max(collected) if collected else None
        newest_agent_sync = step("arch", arch, dataset="arch-merged")

        def docs():
            stats["docs"] = ingest_docs(conn)
            newest_doc = conn.execute("SELECT MAX(mtime) FROM docs").fetchone()[0]
            mark_dataset(conn, "docs-corpus", source_at=newest_doc or now_iso(), rows=stats["docs"])
            return newest_doc
        newest_doc = step("docs", docs, dataset="docs-corpus")
        stats["raw"] = step("workspace", ingest_workspace, conn)

        # Producers are graded on the freshness of what they produced, so a stalled
        # collector or a silent agent shows up as a stale dataset rather than a blank.
        # (Skipped for a producer whose store step crashed: its error must stay visible.)
        if "agent-logs" not in step_errors:
            mark_dataset(conn, "collectors", source_at=newest)
        if "security-reports" not in step_errors:
            mark_dataset(conn, "security-tools", source_at=newest_security)
        if "arch" not in step_errors:
            mark_dataset(conn, "arch-agents", source_at=newest_agent_sync)
        if "docs" not in step_errors:
            mark_dataset(conn, "repo-curated", source_at=newest_doc)

        # The read side has no other way to report itself: every served query writes an
        # audit row, so the newest one is when the API/MCP surface was last actually used.
        last_query = conn.execute("SELECT MAX(at) FROM query_audit").fetchone()[0]
        if last_query:
            mark_dataset(conn, "mcp-server", source_at=last_query)

        stats["incidents"] = step("incidents", ingest_incidents, conn, dataset="incidents")
        stats["monitors"] = step("uptime-kuma", ingest_monitors, conn, dataset="uptime-kuma")
        r = step("net-devices", ingest_net_devices, conn, dataset="dhcp-leases")
        stats["devices"] = f"{r[0]} ({r[1]} new)" if r else None
        stats["pihole_days"] = step("pihole", ingest_pihole_daily, conn, dataset="pihole-stats")
        stats["media"] = step("media", ingest_media_counters, conn, dataset="media-counters")

        r = step("certificates", ingest_certificates, conn, run_id)
        stats["certificates"], stats["cert_warnings"] = r if r else (None, None)
        stats["smart_flags"] = step("smart", check_smart, conn, run_id)
        stats["prices"] = step("pricewatch", ingest_pricewatch, conn, run_id, dataset="pricewatch")
        r = step("deploy-drift", ingest_deploy_drift, conn, run_id, dataset="deploy-drift")
        if r:
            checked, drifted, skipped = r
            stats["deploy_drift"] = f"{drifted} drifted / {checked} checked" + (
                f" ({skipped} skipped: repo dirty)" if skipped else "")
        r = step("bot-health", ingest_bot_health, conn, run_id, dataset="bot-health")
        if r:
            stats["bots_silent"] = f"{r[1]}/{r[0]}"

        mark_dataset(conn, "homelab-db", source_at=now_iso(),
                     error=("steps crashed: " + ", ".join(sorted(step_errors)))
                     if step_errors else None)
        for name, message in step_errors.items():
            conn.execute(
                """INSERT INTO findings (run_id, tool, run_at, severity, host, message, kind)
                   VALUES (?, 'homelab-db', ?, 'warn', 'opti', ?, 'freshness')""",
                (run_id, now_iso(), f"[ingest] step '{name}' crashed: {message[:400]}"),
            )

        # Last, so every dataset this cycle touched is graded on this cycle's result.
        stats["stale_datasets"] = freshness_findings(conn, run_id)
        _finalise_run_status(conn, run_id)
        if step_errors:
            stats["step_errors"] = step_errors

    # Outside the write transaction: a slow ntfy must never hold the DB lock.
    try:
        stats["alerts"] = push_alerts(conn)
    except Exception as exc:  # noqa: BLE001 — alerting is best-effort, never fatal
        stats["alerts"] = f"error: {exc}"
    heartbeat(stats)

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
