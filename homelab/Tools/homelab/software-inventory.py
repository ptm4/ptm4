#!/usr/bin/env python3
"""
software-inventory.py — Package & update inventory agent.

Detects the package manager (pacman / apt / dnf), counts installed packages and
pending updates, and records kernel + key service versions. Warns when updates are
pending.

Writes <agent-logs>/software-latest.json. Dir from $HL_AGENT_LOGS_DIR.
"""

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_LOGS_DIR = os.environ.get(
    "HL_AGENT_LOGS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "agent-logs")
)
REPORT_PATH = os.path.join(AGENT_LOGS_DIR, "software-latest.json")


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return out.stdout, out.returncode
    except Exception:
        return "", 1


def _count(cmd):
    out, _ = _run(cmd)
    return len([l for l in out.splitlines() if l.strip()])


def package_status():
    """Return (manager, installed_count, pending_count)."""
    if shutil.which("pacman"):
        installed = _count(["pacman", "-Qq"])
        # -Qu lists upgradable; needs a recent sync but works against current db
        out, rc = _run(["pacman", "-Qu"])
        pending = len([l for l in out.splitlines() if l.strip()]) if rc in (0, 1) else 0
        return "pacman", installed, pending
    if shutil.which("apt"):
        installed = _count(["dpkg-query", "-f", "${binary:Package}\n", "-W"])
        out, _ = _run(["apt-get", "-s", "-o", "Debug::NoLocking=true", "upgrade"])
        pending = len([l for l in out.splitlines() if l.startswith("Inst ")])
        return "apt", installed, pending
    if shutil.which("dnf"):
        installed = _count(["dnf", "list", "--installed", "-q"])
        out, rc = _run(["dnf", "-q", "check-update"])
        # dnf check-update returns 100 when updates available; lines are pkg rows
        pending = len([l for l in out.splitlines() if l.strip() and not l.startswith(" ")])
        return "dnf", installed, pending
    return "unknown", 0, 0


def version_of(cmd, args=None):
    if not shutil.which(cmd):
        return None
    out, _ = _run([cmd] + (args or ["--version"]))
    return out.splitlines()[0].strip() if out else None


def main():
    os.makedirs(AGENT_LOGS_DIR, exist_ok=True)
    manager, installed, pending = package_status()

    versions = {
        "kernel": platform.release(),
        "docker": version_of("docker", ["--version"]),
        "nginx": version_of("nginx", ["-v"]) or _run(["nginx", "-v"])[0],
        "python3": platform.python_version(),
    }
    versions = {k: v for k, v in versions.items() if v}

    findings = []
    if pending > 0:
        findings.append({"severity": "warn",
                         "message": f"{pending} package update(s) pending ({manager})"})

    status = "warn" if pending > 0 else "ok"
    summary = f"{installed} packages installed via {manager}, {pending} update(s) pending"

    report = {
        "tool": "software-inventory",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "package_manager": manager,
        "installed_count": installed,
        "pending_updates": pending,
        "versions": versions,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} (status={status})")


if __name__ == "__main__":
    main()
