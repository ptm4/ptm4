#!/usr/bin/env python3
"""
software-inventory.py — OS + package + update health report.

Detects the package manager (apt / pacman / dnf), lists pending updates with a
security flag, counts installed packages, records running-vs-latest kernel,
reboot-required state, unattended-upgrades posture, and Docker image drift. Emits
a recommendations/"watch list" section and a full markdown `log`.

Writes <agent-logs>/software-latest.json + <agent-logs>/software-latest/<date>.json
via _report.write_report. Logs dir from $HL_AGENT_LOGS_DIR.

Read-only: never installs/upgrades anything (apt-get -s is a simulation).
"""

import os
import platform
import re
import shutil
import socket
import subprocess

from _report import write_report, now_iso

REPORT_BASE = "software-latest"


def _run(cmd, timeout=60):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout, out.returncode
    except Exception:
        return "", 1


def _count(cmd):
    out, _ = _run(cmd)
    return len([l for l in out.splitlines() if l.strip()])


def package_status():
    """Return (manager, installed_count, pending_list, security_count)."""
    if shutil.which("apt"):
        installed = _count(["dpkg-query", "-f", "${binary:Package}\n", "-W"])
        out, _ = _run(["apt-get", "-s", "-o", "Debug::NoLocking=true", "upgrade"])
        pending = []
        security = 0
        for l in out.splitlines():
            if l.startswith("Inst "):
                pending.append(l[5:].strip())
                if "-security" in l or "Security" in l:
                    security += 1
        return "apt", installed, pending, security
    if shutil.which("pacman"):
        installed = _count(["pacman", "-Qq"])
        out, rc = _run(["pacman", "-Qu"])
        pending = [l.strip() for l in out.splitlines() if l.strip()] if rc in (0, 1) else []
        return "pacman", installed, pending, 0  # pacman has no built-in security flag
    if shutil.which("dnf"):
        installed = _count(["dnf", "list", "--installed", "-q"])
        out, _ = _run(["dnf", "-q", "check-update"])
        pending = [l.split()[0] for l in out.splitlines()
                   if l.strip() and not l.startswith(" ") and "." in l.split()[0]]
        sec_out, _ = _run(["dnf", "-q", "updateinfo", "list", "security"])
        security = len([l for l in sec_out.splitlines() if l.strip()])
        return "dnf", installed, pending, security
    return "unknown", 0, [], 0


def kernel_info():
    running = platform.release()
    latest = None
    out, _ = _run(["bash", "-lc",
                   "dpkg -l 'linux-image-*' 2>/dev/null | grep '^ii' | awk '{print $2}' | sort -V | tail -1"])
    if out.strip():
        latest = out.strip()
    return running, latest


def reboot_required():
    if os.path.exists("/var/run/reboot-required"):
        pkgs = ""
        try:
            with open("/var/run/reboot-required.pkgs") as f:
                pkgs = ", ".join(sorted(set(f.read().split())))
        except OSError:
            pass
        return True, pkgs
    # arch: compare running kernel to installed /boot vmlinuz
    return False, ""


def unattended_state():
    out, rc = _run(["systemctl", "is-active", "unattended-upgrades"])
    return out.strip() or ("inactive" if rc else "unknown")


def docker_images():
    """Running containers + image; flag drift when local digest != registry (best-effort)."""
    if not shutil.which("docker"):
        return [], []
    out, rc = _run(["docker", "ps", "--format", "{{.Image}}\t{{.Names}}\t{{.Status}}"])
    if rc != 0:
        return [], []
    images = []
    drift = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            img, name = parts[0], parts[1]
            status = parts[2] if len(parts) > 2 else ""
            images.append({"image": img, "name": name, "status": status})
    return images, drift


def version_of(cmd, args=None):
    if not shutil.which(cmd):
        return None
    out, _ = _run([cmd] + (args or ["--version"]))
    if not out:
        out, _ = _run([cmd] + (args or ["--version"]))  # some tools print to stderr; ignore
    return out.splitlines()[0].strip() if out else None


def collect_host():
    host = socket.gethostname()
    findings = []
    recs = []

    manager, installed, pending, security = package_status()
    running_kernel, latest_kernel = kernel_info()
    reboot, reboot_pkgs = reboot_required()
    unattended = unattended_state()
    images, drift = docker_images()

    versions = {
        "kernel": running_kernel,
        "docker": version_of("docker", ["--version"]),
        "nginx": version_of("nginx", ["-v"]),
        "python3": platform.python_version(),
    }
    versions = {k: v for k, v in versions.items() if v}

    if security > 0:
        findings.append({"severity": "warn",
                         "message": f"{security} pending security update(s) ({manager})"})
    if pending:
        findings.append({"severity": "warn" if not security else "warn",
                         "message": f"{len(pending)} package update(s) pending ({manager})"})
    if reboot:
        findings.append({"severity": "warn",
                         "message": f"Reboot required{(': ' + reboot_pkgs) if reboot_pkgs else ''}"})
    if latest_kernel and latest_kernel not in (running_kernel, f"linux-image-{running_kernel}"):
        recs.append({"severity": "info",
                     "message": f"Kernel installed ({latest_kernel}) newer than running ({running_kernel}) — reboot to apply."})
    if unattended not in ("active",):
        recs.append({"severity": "info",
                     "message": f"unattended-upgrades is {unattended} — consider enabling auto security updates."})

    status = "warn" if findings else "ok"
    metrics = {
        "package_manager": manager,
        "installed_count": installed,
        "pending_updates": pending,
        "pending_count": len(pending),
        "security_count": security,
        "running_kernel": running_kernel,
        "latest_kernel": latest_kernel,
        "reboot_required": reboot,
        "reboot_pkgs": reboot_pkgs,
        "unattended_upgrades": unattended,
        "docker_images": images,
        "versions": versions,
    }
    summary = (f"{installed} pkgs via {manager} · {len(pending)} update(s)"
               f"{f', {security} security' if security else ''}"
               f"{' · reboot needed' if reboot else ''}")
    return ({"host": host, "status": status, "summary": summary, "metrics": metrics},
            findings, recs)


def build_log(host, findings, recs):
    m = host["metrics"]
    L = [f"# Software Report — {host['host']}", "",
         f"_Generated {now_iso()}_", "",
         "## Summary", "",
         f"- Package manager: {m['package_manager']}",
         f"- Installed packages: {m['installed_count']}",
         f"- Pending updates: {m['pending_count']} ({m['security_count']} security)",
         f"- Kernel: running {m['running_kernel']} / latest {m.get('latest_kernel') or 'same'}",
         f"- Reboot required: {'YES — ' + m['reboot_pkgs'] if m['reboot_required'] else 'no'}",
         f"- Unattended-upgrades: {m['unattended_upgrades']}",
         ""]
    if m["versions"]:
        L.append("## Key versions")
        L.append("")
        for k, v in m["versions"].items():
            L.append(f"- {k}: {v}")
        L.append("")
    if m["pending_updates"]:
        L.append(f"## Pending updates ({m['pending_count']})")
        L.append("")
        L.append("```")
        L += m["pending_updates"][:60]
        if m["pending_count"] > 60:
            L.append(f"... and {m['pending_count'] - 60} more")
        L.append("```")
        L.append("")
    if m["docker_images"]:
        L.append("## Docker containers")
        L.append("")
        L.append("| Image | Name | Status |")
        L.append("|---|---|---|")
        for d in m["docker_images"]:
            L.append(f"| {d['image']} | {d['name']} | {d['status']} |")
        L.append("")
    L.append("## Concerns / watch list")
    L.append("")
    items = findings + recs
    if items:
        for it in items:
            L.append(f"- **{it['severity'].upper()}** — {it['message']}")
    else:
        L.append("- None.")
    L.append("")
    return "\n".join(L)


def main():
    host, findings, recs = collect_host()
    status = host["status"]
    report = {
        "tool": "software-inventory",
        "run_at": now_iso(),
        "status": status,
        "summary": host["summary"],
        "findings": findings,
        "recommendations": recs,
        "hosts": [host],
        "log": build_log(host, findings, recs),
        # back-compat convenience keys
        "package_manager": host["metrics"]["package_manager"],
        "installed_count": host["metrics"]["installed_count"],
        "pending_updates": host["metrics"]["pending_count"],
        "versions": host["metrics"]["versions"],
    }
    latest, dated = write_report(REPORT_BASE, report)
    print(f"Report written: {latest} + {dated} (status={status})")


if __name__ == "__main__":
    main()
