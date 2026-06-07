#!/usr/bin/env python3
"""
persistence-auditor.py — Linux persistence / autostart integrity auditor.

Enumerates the common places Linux persistence hides — cron, systemd timers &
enabled units, desktop autostart, and shell rc / profile files — and on first run
saves a baseline. On later runs it diffs against the baseline and flags new, changed,
or removed entries (the Linux analogue of the Windows registry-persist + scheduled-task
auditors).

Writes <reports>/persistence-audit-latest.json. Reports dir from $HL_REPORTS_DIR;
baseline stored under $HL_DATA_DIR (default ../../data relative to this file).

Usage:
  python3 persistence-auditor.py [--save-baseline]
"""

import argparse
import glob
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.environ.get(
    "HL_REPORTS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "security-reports")
)
DATA_DIR = os.environ.get("HL_DATA_DIR", os.path.join(BASE_DIR, "..", "data"))
REPORT_PATH = os.path.join(REPORTS_DIR, "persistence-audit-latest.json")
BASELINE_PATH = os.path.join(DATA_DIR, "persistence-baseline.json")

HOME = os.path.expanduser("~")


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return out.stdout if out.returncode == 0 else ""
    except Exception:
        return ""


def _file_sig(path):
    """A stable signature for a file: sha256 of its contents (or a marker)."""
    try:
        with open(path, "rb") as f:
            return "sha256:" + hashlib.sha256(f.read()).hexdigest()[:16]
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return "unreadable"


def collect():
    """Return {item_key: signature} across all persistence surfaces."""
    items = {}

    # ── cron ──────────────────────────────────────────────────────────────
    cron_paths = ["/etc/crontab"]
    for pat in ("/etc/cron.d/*", "/etc/cron.hourly/*", "/etc/cron.daily/*",
                "/etc/cron.weekly/*", "/etc/cron.monthly/*", "/var/spool/cron/*",
                "/var/spool/cron/crontabs/*"):
        cron_paths.extend(glob.glob(pat))
    for p in cron_paths:
        if os.path.isfile(p):
            items[f"cron:{p}"] = _file_sig(p)
    user_cron = _run(["crontab", "-l"])
    if user_cron.strip():
        items[f"cron:user:{os.environ.get('USER', 'me')}"] = \
            "sha256:" + hashlib.sha256(user_cron.encode()).hexdigest()[:16]

    # ── systemd: enabled units + timers + custom unit files ───────────────
    for line in _run(["systemctl", "list-unit-files", "--state=enabled",
                       "--no-legend", "--no-pager"]).splitlines():
        unit = line.split()[0] if line.split() else ""
        if unit:
            items[f"systemd-enabled:{unit}"] = "enabled"
    for line in _run(["systemctl", "list-timers", "--all", "--no-legend",
                      "--no-pager"]).splitlines():
        parts = line.split()
        # timer unit name is the column ending in .timer
        timer = next((c for c in parts if c.endswith(".timer")), "")
        if timer:
            items[f"systemd-timer:{timer}"] = "present"
    for p in glob.glob("/etc/systemd/system/*.service") + \
             glob.glob("/etc/systemd/system/*.timer"):
        items[f"systemd-unitfile:{p}"] = _file_sig(p)

    # ── desktop autostart ─────────────────────────────────────────────────
    for pat in (os.path.join(HOME, ".config/autostart/*.desktop"),
                "/etc/xdg/autostart/*.desktop"):
        for p in glob.glob(pat):
            items[f"autostart:{p}"] = _file_sig(p)

    # ── shell rc / profile / rc.local ─────────────────────────────────────
    rc_files = ["/etc/rc.local", "/etc/profile",
                os.path.join(HOME, ".bashrc"), os.path.join(HOME, ".bash_profile"),
                os.path.join(HOME, ".profile"), os.path.join(HOME, ".zshrc"),
                os.path.join(HOME, ".zprofile")]
    rc_files.extend(glob.glob("/etc/profile.d/*.sh"))
    for p in rc_files:
        if os.path.isfile(p):
            items[f"rc:{p}"] = _file_sig(p)

    return items


def load_baseline():
    try:
        with open(BASELINE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_baseline(items):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BASELINE_PATH, "w") as f:
        json.dump(items, f, indent=2)


def main():
    ap = argparse.ArgumentParser(description="Linux persistence / autostart auditor")
    ap.add_argument("--save-baseline", action="store_true",
                    help="Force re-save the baseline (overwrites existing)")
    args = ap.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)
    current = collect()
    baseline = load_baseline()

    findings = []
    if baseline is None or args.save_baseline:
        save_baseline(current)
        status = "ok"
        summary = f"{len(current)} persistence entries baselined ({'reset' if baseline else 'first run'})"
    else:
        new = {k: v for k, v in current.items() if k not in baseline}
        removed = {k: v for k, v in baseline.items() if k not in current}
        changed = {k: v for k, v in current.items()
                   if k in baseline and baseline[k] != v}
        for k in sorted(new):
            findings.append({"severity": "warn", "message": f"NEW persistence entry: {k}"})
        for k in sorted(changed):
            findings.append({"severity": "warn", "message": f"CHANGED: {k}"})
        for k in sorted(removed):
            findings.append({"severity": "info", "message": f"removed since baseline: {k}"})
        status = "warn" if (new or changed) else "ok"
        summary = (f"{len(current)} entries tracked — {len(new)} new, "
                   f"{len(changed)} changed, {len(removed)} removed since baseline")

    report = {
        "tool": "persistence-auditor",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "tracked_count": len(current),
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} (status={status}, {len(findings)} findings)")


if __name__ == "__main__":
    main()
