#!/usr/bin/env python3
"""
_report.py — shared report writer for the homelab collectors.

Every collector writes its report twice:
  <agent-logs>/<name>-latest.json        the "current" pointer the webapp + Leetify read
  <agent-logs>/<name>/<YYYY-MM-DD>.json  a dated copy so the webapp's History view works

The dated layout mirrors the old markdown agents (~/.claude/agent-logs/<agent>/<date>.md).
Same-day re-runs overwrite the dated file, matching the old append-per-day behaviour.

The report dict is expected to carry (all backward-compatible with the old flat schema):
  tool, run_at, status, summary, findings[]        (existing keys — unchanged)
  hosts[]            per-host detail   [{host, status, summary, metrics:{...}}]
  recommendations[]  the "Concerns / watch list"   [{severity, message}]
  log                full human-readable report body (markdown), shown in the full-log viewer
plus any tool-specific arrays.

Env: HL_AGENT_LOGS_DIR overrides the logs dir (default ../../../agent-logs from a collector).
"""

import json
import os
from datetime import datetime, timezone

# default relative to a collector in Tools/homelab/ -> repo-root/../agent-logs
_DEFAULT_LOGS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agent-logs"
)


def agent_logs_dir():
    return os.environ.get("HL_AGENT_LOGS_DIR", _DEFAULT_LOGS_DIR)


def write_report(report_base, report):
    """Write the latest pointer and a dated history copy.

    `report_base` is the webapp CATALOG key, e.g. "hardware-latest". It produces:
      <agent-logs>/hardware-latest.json          (latest pointer)
      <agent-logs>/hardware-latest/<today>.json  (dated history — subdir name == base)
    so the backend's history endpoint can list <agent-logs>/<base>/*.json.
    Returns (latest_path, dated_path).
    """
    logs_dir = agent_logs_dir()
    os.makedirs(logs_dir, exist_ok=True)

    latest_path = os.path.join(logs_dir, f"{report_base}.json")
    _dump(latest_path, report)

    dated_dir = os.path.join(logs_dir, report_base)
    os.makedirs(dated_dir, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dated_path = os.path.join(dated_dir, f"{today}.json")
    _dump(dated_path, report)

    return latest_path, dated_path


def _dump(path, report):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(report, f, indent=2)
    os.replace(tmp, path)


def now_iso():
    return datetime.now(timezone.utc).isoformat()
