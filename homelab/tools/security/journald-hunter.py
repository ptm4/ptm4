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

Journal access: an unprivileged user outside the systemd-journal / adm group sees only
its own user journal (no kernel, no smartd). The hunter checks for that and reports a
warn finding rather than silently scanning a fraction of the log. On opti the collector
units grant it with SupplementaryGroups=systemd-journal.

Self-matching: the homelab's own collectors log through journald too. Lines that are
the hunter's/collectors' own output (ingest stats, cron/sudo PAM session lines) are
skipped, and sudo audit lines ("... ; COMMAND=...") are checked against the security
rules only — a command line naming smartctl is not a disk error. Tests:
  python -m unittest discover -s homelab/tools/security -v

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
    ("storage",  "critical", re.compile(r"I/O error|EXT4-fs error|XFS.*error|Buffer I/O error|critical medium error|failed command| ataX?.*error|^ata\d+(\.\d+)?:.*\berror", re.I), "Disk / filesystem error"),
    # smartd's own wording only. A bare "SMART" also matched ingest's "smart_flags" stats
    # line and sudo audit lines for smartctl; smartd's temperature/airflow/raw-read-rate
    # attribute chatter is deliberately not listed.
    ("storage",  "critical", re.compile(r"FAILED SMART self-check|Failed SMART (usage|prefailure) Attribute|self-assessment test result: FAILED", re.I), "SMART health failure"),
    ("storage",  "warn",     re.compile(
        r"Currently unreadable \(pending\) sectors|Offline uncorrectable sectors|ATA error count increased"
        r"|Self-Test Log error count increased"
        r"|SMART (Prefailure|Usage) Attribute: \d+ (Reallocated_Sector_Ct|Reallocated_Event_Count|Current_Pending_Sector|Offline_Uncorrectable|Reported_Uncorrect) changed"
        r"|reallocated sector|pending sector|offline uncorrectable", re.I), "SMART / disk-health warning"),
    # \bBUG: so sshd's "send DEBUG: Broken pipe" no longer reads as a kernel BUG.
    ("kernel",   "critical", re.compile(r"Hardware Error|Machine Check Exception|mce: \[Hardware Error\]|Uncorrected error|kernel BUG|\bBUG: |general protection fault|Call Trace"), "Kernel / hardware fault"),
    # The kernel prints "Oops:"; lowercase "oops" never matched a real one.
    ("kernel",   "warn",     re.compile(r"segfault|traps:|\bOops\b"), "Process crash (segfault/oops)"),
]

# Lines that are the homelab's own bookkeeping, never a finding:
#  - ingest.py's per-cycle stats dict ("[ingest] {... smart_flags ...}")
#  - PAM session lines for cron jobs and sudo: every collector's sudo and every root
#    cron job opens one. sshd/su root sessions are still counted.
SKIP_LINE = re.compile(r"^\[ingest\] \{|pam_unix\((cron|sudo|sudo-i):session\)")

# sudo's audit line as journalctl -o cat prints it (no "sudo:" prefix):
#   "    ptm : PWD=/home/ptm ; USER=root ; COMMAND=/usr/sbin/smartctl -H -A /dev/sda"
# It records a command, not an event, so only the security rules apply to it.
SUDO_AUDIT = re.compile(r"^\s*\S+ : (TTY=\S+ ; )?PWD=.* ; USER=\S+ ; .*COMMAND=")

JOURNAL_GROUPS = ("systemd-journal", "adm", "wheel")

SEV_ORDER = {"critical": 0, "warn": 1, "info": 2}
STATUS_FROM_SEV = {"critical": "critical", "warn": "warn", "info": "ok"}


def have_journalctl():
    return shutil.which("journalctl") is not None


def journal_cmd(hours):
    """argv for reading the journal; a remote read can prefix it (e.g. ["ssh", host])."""
    return ["journalctl", "--no-pager", "--since", f"{hours} hours ago", "-o", "cat"]


def journal_access():
    """'full' if this process can read the system journal, else 'partial'.

    Root, or membership of systemd-journal / adm / wheel (the groups journald's ACLs
    grant), sees everything. Anyone else gets only their own user journal.
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:          # not a POSIX host; journald does not apply
        return "full"
    if geteuid() == 0:
        return "full"
    try:
        import grp
    except ImportError:
        return "full"
    gids = set(os.getgroups()) | {os.getegid()}
    for name in JOURNAL_GROUPS:
        try:
            if grp.getgrnam(name).gr_gid in gids:
                return "full"
        except KeyError:
            continue
    return "partial"


def journal_lines(hours, cmd=None):
    """Return message strings from journald over the lookback window."""
    try:
        out = subprocess.run(
            cmd or journal_cmd(hours),
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


def read_lines(hours):
    """(lines, used_fallback): journald if it yields anything, else the text logs."""
    if have_journalctl():
        lines = journal_lines(hours)
        if lines:
            return lines, False
        # journalctl present but returned nothing (perms?) — try files
        lines = file_lines(hours)
        return lines, bool(lines)
    return file_lines(hours), True


def classify(line):
    """The (category, severity, pattern, label) rule a line counts under, or None."""
    if SKIP_LINE.search(line):
        return None
    audit = SUDO_AUDIT.match(line) is not None
    for rule in PATTERNS:
        if audit and rule[0] != "security":
            continue
        if rule[2].search(line):
            return rule  # first matching pattern wins
    return None


def hunt(lines):
    cat_counts = Counter()
    # keep a few representative examples per (category,label) so the report isn't huge
    examples = {}
    worst_sev = "info"
    for line in lines:
        rule = classify(line)
        if rule is None:
            continue
        category, severity, _pat, label = rule
        key = (category, severity, label)
        cat_counts[key] += 1
        if key not in examples:
            examples[key] = line.strip()[:300]
        if SEV_ORDER[severity] < SEV_ORDER[worst_sev]:
            worst_sev = severity
    return cat_counts, examples, worst_sev


PARTIAL_READ_FINDING = {
    "severity": "warn",
    "message": "[hunter] Partial journal read — this user is not in systemd-journal/adm, "
               "so kernel and smartd lines are not visible and disk errors cannot be seen",
}


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

    lines, used_fallback = read_lines(args.hours)
    access = "files" if used_fallback else journal_access()

    cat_counts, examples, worst_sev = hunt(lines)
    findings = build_findings(cat_counts, examples)
    if access == "partial":
        findings.append(dict(PARTIAL_READ_FINDING))
        if SEV_ORDER["warn"] < SEV_ORDER[worst_sev]:
            worst_sev = "warn"
        findings.sort(key=lambda f: SEV_ORDER.get(f["severity"], 9))

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
    elif access == "partial":
        summary += " (partial journal: own user journal only)"

    report = {
        "tool": "journald-hunter",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "categories": dict(by_cat),
        "source": "auth/syslog files" if used_fallback else "journald",
        "journal_access": access,
        "window_hours": args.hours,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} (status={status}, {len(findings)} finding types)")


if __name__ == "__main__":
    main()
