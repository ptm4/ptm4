#!/usr/bin/env python3
"""
journald-hunter.py — Linux log threat & health hunter.

Combs ALL of journald (every unit/boot in the lookback window), not just auth, and
classifies what it finds into security signals + general-health flags. Falls back to
reading /var/log/{auth,sys}.log when journalctl is unavailable.

Categories:
  security  — failed/accepted SSH logins, sudo/su, new/changed users
  service   — failed systemd units, crashes, coredumps
  oom       — out-of-memory kills
  storage   — disk / filesystem / I-O / SMART errors
  kernel    — kernel BUGs, MCE/hardware errors, segfaults, call traces

Writes <reports>/journal-hunt-latest.json. Reports dir from $HL_REPORTS_DIR
(default: ../../../security-reports relative to this file).

Usage:
  python3 journald-hunter.py [--hours 24]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.environ.get(
    "HL_REPORTS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "security-reports")
)
REPORT_PATH = os.path.join(REPORTS_DIR, "journal-hunt-latest.json")

# (category, severity, compiled-pattern, human label)
PATTERNS = [
    ("security", "warn",     re.compile(r"Failed password|authentication failure|Invalid user|Failed publickey"), "Failed SSH/auth attempt"),
    ("security", "info",     re.compile(r"Accepted (password|publickey|keyboard)"), "Successful SSH login"),
    ("security", "warn",     re.compile(r"\bsudo\b.*COMMAND="), "sudo command executed"),
    ("security", "warn",     re.compile(r"session opened for user root|su(\[|:).*session opened"), "Privilege escalation (su/root session)"),
    ("security", "critical", re.compile(r"\b(useradd|userdel|usermod|groupadd)\b"), "User/group account change"),
    ("service",  "warn",     re.compile(r"Failed with result|entered failed state|Failed to start|Main process exited.*status=[1-9]"), "systemd unit failure"),
    ("service",  "critical", re.compile(r"dumped core|systemd-coredump\[\d+\]|Process \d+ \(.+\) of user"), "Process core dump"),
    ("oom",      "critical", re.compile(r"Out of memory|oom[-_]kill|Killed process \d+|invoked oom-killer"), "Out-of-memory kill"),
    ("storage",  "critical", re.compile(r"I/O error|EXT4-fs error|XFS.*error|Buffer I/O error|critical medium error|failed command| ataX?.*error", re.I), "Disk / filesystem error"),
    ("storage",  "warn",     re.compile(r"SMART|reallocated sector|pending sector|offline uncorrectable", re.I), "SMART / disk-health warning"),
    ("kernel",   "critical", re.compile(r"Hardware Error|Machine Check Exception|mce: \[Hardware Error\]|Uncorrected error|kernel BUG|BUG: |general protection fault|Call Trace"), "Kernel / hardware fault"),
    ("kernel",   "warn",     re.compile(r"segfault|traps:|oops"), "Process crash (segfault/oops)"),
]

SEV_ORDER = {"critical": 0, "warn": 1, "info": 2}
STATUS_FROM_SEV = {"critical": "critical", "warn": "warn", "info": "ok"}


def have_journalctl():
    return shutil.which("journalctl") is not None


def journal_lines(hours):
    """Yield message strings from journald over the lookback window."""
    try:
        out = subprocess.run(
            ["journalctl", "--no-pager", "--since", f"{hours} hours ago", "-o", "cat"],
            capture_output=True, text=True, timeout=120,
        )
        if out.returncode == 0:
            return out.stdout.splitlines()
    except Exception:
        pass
    return []


def file_lines(hours):
    """Fallback: read common text logs (whole file; time filtering is best-effort)."""
    lines = []
    for path in ("/var/log/auth.log", "/var/log/syslog", "/var/log/messages", "/var/log/secure"):
        try:
            with open(path, "r", errors="replace") as f:
                lines.extend(f.read().splitlines()[-20000:])
        except (FileNotFoundError, PermissionError):
            continue
    return lines


def hunt(lines):
    cat_counts = Counter()
    # keep a few representative examples per (category,label) so the report isn't huge
    examples = {}
    worst_sev = "info"
    for line in lines:
        for category, severity, pat, label in PATTERNS:
            if pat.search(line):
                key = (category, severity, label)
                cat_counts[key] += 1
                if key not in examples:
                    examples[key] = line.strip()[:300]
                if SEV_ORDER[severity] < SEV_ORDER[worst_sev]:
                    worst_sev = severity
                break  # first matching pattern wins
    return cat_counts, examples, worst_sev


def build_findings(cat_counts, examples):
    findings = []
    for (category, severity, label), count in cat_counts.items():
        findings.append({
            "severity": severity,
            "message": f"[{category}] {label} ×{count} — e.g. {examples[(category, severity, label)]}",
        })
    findings.sort(key=lambda f: SEV_ORDER.get(f["severity"], 9))
    return findings


def main():
    ap = argparse.ArgumentParser(description="Linux log threat & health hunter")
    ap.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
    args = ap.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    used_fallback = False
    if have_journalctl():
        lines = journal_lines(args.hours)
        if not lines:  # journalctl present but returned nothing (perms?) — try files
            lines = file_lines(args.hours)
            used_fallback = bool(lines)
    else:
        lines = file_lines(args.hours)
        used_fallback = True

    cat_counts, examples, worst_sev = hunt(lines)
    findings = build_findings(cat_counts, examples)

    status = STATUS_FROM_SEV[worst_sev] if findings else "ok"
    by_cat = Counter()
    for (category, _sev, _label), count in cat_counts.items():
        by_cat[category] += count
    if findings:
        parts = ", ".join(f"{n} {c}" for c, n in sorted(by_cat.items()))
        summary = f"{len(lines)} log lines scanned over {args.hours}h — {parts}"
    else:
        summary = f"{len(lines)} log lines scanned over {args.hours}h — no errors or flags"
    if used_fallback:
        summary += " (text-log fallback)"

    report = {
        "tool": "journald-hunter",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "categories": dict(by_cat),
        "source": "auth/syslog files" if used_fallback else "journald",
        "window_hours": args.hours,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} (status={status}, {len(findings)} finding types)")


if __name__ == "__main__":
    main()
