#!/usr/bin/env python3
"""
software-inventory.py — OS + package + update health report across all homelab hosts.

For every host in HL_HOSTS (opti, rpi, noblenumbat by default), over SSH: detects the
package manager (apt / pacman / dnf), lists pending updates with a security flag,
counts installed packages, records running-vs-latest kernel, reboot-required state,
unattended-upgrades posture, and Docker image drift. Emits a multi-host report with a
per-host "watch list" and a full markdown `log`.

Writes <agent-logs>/software-latest.json + <agent-logs>/software-latest/<date>.json
via _report.write_report. Logs dir from $HL_AGENT_LOGS_DIR; hosts/key from HL_HOSTS /
HL_SSH_KEY (see _hosts.py).

Read-only: never installs/upgrades anything (apt-get -s is a simulation).
"""

from _report import write_report, now_iso
from _hosts import hosts, ensure_key, run_on, probe, MissingKeyError

REPORT_BASE = "software-latest"


def _run(host, cmd, timeout=60):
    return run_on(host, cmd, timeout=timeout)


def _count(host, cmd):
    out, _ = _run(host, cmd)
    return len([l for l in out.splitlines() if l.strip()])


def _has(host, prog):
    """Remote `command -v` — is `prog` on this host's PATH?"""
    _, rc = run_on(host, ["sh", "-c", f"command -v {prog} >/dev/null 2>&1"], timeout=10)
    return rc == 0


def package_status(host):
    """Return (manager, installed_count, pending_list, security_count)."""
    if _has(host, "apt"):
        installed = _count(host, ["dpkg-query", "-f", "${binary:Package}\n", "-W"])
        out, _ = _run(host, ["apt-get", "-s", "-o", "Debug::NoLocking=true", "upgrade"])
        pending = []
        security = 0
        for l in out.splitlines():
            if l.startswith("Inst "):
                pending.append(l[5:].strip())
                if "-security" in l or "Security" in l:
                    security += 1
        return "apt", installed, pending, security
    if _has(host, "pacman"):
        installed = _count(host, ["pacman", "-Qq"])
        out, rc = _run(host, ["pacman", "-Qu"])
        pending = [l.strip() for l in out.splitlines() if l.strip()] if rc in (0, 1) else []
        return "pacman", installed, pending, 0  # pacman has no built-in security flag
    if _has(host, "dnf"):
        installed = _count(host, ["dnf", "list", "--installed", "-q"])
        out, _ = _run(host, ["dnf", "-q", "check-update"])
        pending = [l.split()[0] for l in out.splitlines()
                   if l.strip() and not l.startswith(" ") and "." in l.split()[0]]
        sec_out, _ = _run(host, ["dnf", "-q", "updateinfo", "list", "security"])
        security = len([l for l in sec_out.splitlines() if l.strip()])
        return "dnf", installed, pending, security
    return "unknown", 0, [], 0


def kernel_info(host):
    running, _ = _run(host, ["uname", "-r"])
    running = running.strip()
    latest = None
    out, _ = _run(host, ["bash", "-lc",
                         "dpkg -l 'linux-image-*' 2>/dev/null | grep '^ii' | awk '{print $2}' | sort -V | tail -1"])
    if out.strip():
        latest = out.strip()
    return running, latest


def reboot_required(host):
    _, rc = run_on(host, ["test", "-f", "/var/run/reboot-required"], timeout=10)
    if rc == 0:
        out, _ = _run(host, ["cat", "/var/run/reboot-required.pkgs"])
        pkgs = ", ".join(sorted(set(out.split()))) if out else ""
        return True, pkgs
    return False, ""


def unattended_state(host):
    out, rc = _run(host, ["systemctl", "is-active", "unattended-upgrades"])
    return out.strip() or ("inactive" if rc else "unknown")


def docker_images(host):
    """Running containers + image; drift detection is best-effort (left empty)."""
    if not _has(host, "docker"):
        return [], []
    out, rc = _run(host, ["docker", "ps", "--format", "{{.Image}}\t{{.Names}}\t{{.Status}}"])
    if rc != 0:
        return [], []
    images = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            img, name = parts[0], parts[1]
            status = parts[2] if len(parts) > 2 else ""
            images.append({"image": img, "name": name, "status": status})
    return images, []


def version_of(host, cmd, args=None):
    if not _has(host, cmd):
        return None
    out, _ = _run(host, [cmd] + (args or ["--version"]))
    return out.splitlines()[0].strip() if out else None


def python_version(host):
    out, _ = _run(host, ["python3", "-c", "import platform;print(platform.python_version())"])
    return out.strip() or None


def collect_host(host):
    findings = []
    recs = []

    manager, installed, pending, security = package_status(host)
    running_kernel, latest_kernel = kernel_info(host)
    reboot, reboot_pkgs = reboot_required(host)
    unattended = unattended_state(host)
    images, drift = docker_images(host)

    versions = {
        "kernel": running_kernel,
        "docker": version_of(host, "docker", ["--version"]),
        "nginx": version_of(host, "nginx", ["-v"]),
        "python3": python_version(host),
    }
    versions = {k: v for k, v in versions.items() if v}

    if security > 0:
        findings.append({"severity": "warn",
                         "message": f"[{host.name}] {security} pending security update(s) ({manager})"})
    if pending:
        findings.append({"severity": "warn",
                         "message": f"[{host.name}] {len(pending)} package update(s) pending ({manager})"})
    if reboot:
        findings.append({"severity": "warn",
                         "message": f"[{host.name}] Reboot required{(': ' + reboot_pkgs) if reboot_pkgs else ''}"})
    if latest_kernel and latest_kernel not in (running_kernel, f"linux-image-{running_kernel}"):
        recs.append({"severity": "info",
                     "message": f"[{host.name}] Kernel installed ({latest_kernel}) newer than running ({running_kernel}) — reboot to apply."})
    if unattended not in ("active",):
        recs.append({"severity": "info",
                     "message": f"[{host.name}] unattended-upgrades is {unattended} — consider enabling auto security updates."})

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
    return ({"host": host.name, "status": status, "summary": summary, "metrics": metrics},
            findings, recs)


def _host_log(host_dict):
    m = host_dict["metrics"]
    L = [f"## {host_dict['host']}", "",
         f"- Package manager: {m['package_manager']}",
         f"- Installed packages: {m['installed_count']}",
         f"- Pending updates: {m['pending_count']} ({m['security_count']} security)",
         f"- Kernel: running {m['running_kernel']} / latest {m.get('latest_kernel') or 'same'}",
         f"- Reboot required: {'YES — ' + m['reboot_pkgs'] if m['reboot_required'] else 'no'}",
         f"- Unattended-upgrades: {m['unattended_upgrades']}",
         ""]
    if m["versions"]:
        L.append("Key versions: " + ", ".join(f"{k} {v}" for k, v in m["versions"].items()))
        L.append("")
    if m["pending_updates"]:
        L += [f"Pending updates ({m['pending_count']}):", "", "```"]
        L += m["pending_updates"][:60]
        if m["pending_count"] > 60:
            L.append(f"... and {m['pending_count'] - 60} more")
        L += ["```", ""]
    if m["docker_images"]:
        L += ["**Docker containers**", "", "| Image | Name | Status |", "|---|---|---|"]
        for d in m["docker_images"]:
            L.append(f"| {d['image']} | {d['name']} | {d['status']} |")
        L.append("")
    return L


def build_log(host_dicts, findings, recs):
    L = ["# Software Report", "", f"_Generated {now_iso()}_",
         f" · {len(host_dicts)} host(s)", ""]
    for hd in host_dicts:
        L += _host_log(hd)
    L += ["## Concerns / watch list", ""]
    items = findings + recs
    if items:
        for it in items:
            L.append(f"- **{it['severity'].upper()}** — {it['message']}")
    else:
        L.append("- None.")
    L.append("")
    return "\n".join(L)


def main():
    all_hosts = hosts()
    host_dicts = []
    findings = []
    recs = []

    try:
        ensure_key()
    except MissingKeyError as e:
        report = {
            "tool": "software-inventory", "run_at": now_iso(), "status": "critical",
            "summary": "SSH key missing — cannot collect from any host",
            "findings": [{"severity": "critical", "message": str(e)}],
            "recommendations": [], "hosts": [],
            "log": "# Software Report\n\n**SSH key missing.** " + str(e),
        }
        latest, dated = write_report(REPORT_BASE, report)
        print(f"Report written: {latest} (status=critical, key missing)")
        return

    for host in all_hosts:
        ok, detail = probe(host)
        if not ok:
            findings.append({"severity": "warn",
                             "message": f"[{host.name}] unreachable over SSH — {detail}"})
            host_dicts.append({"host": host.name, "status": "unknown",
                               "summary": f"unreachable ({detail})", "metrics": {}})
            continue
        hd, hf, hr = collect_host(host)
        host_dicts.append(hd)
        findings += hf
        recs += hr

    if any(f["severity"] == "critical" for f in findings):
        status = "critical"
    elif findings:
        status = "warn"
    else:
        status = "ok"

    reachable = [h for h in host_dicts if h["status"] != "unknown"]
    summary = f"{len(reachable)}/{len(host_dicts)} host(s) reported"
    total_pending = sum((h.get("metrics", {}).get("pending_count") or 0) for h in host_dicts)
    if total_pending:
        summary += f" · {total_pending} update(s) total"

    report = {
        "tool": "software-inventory",
        "run_at": now_iso(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "recommendations": recs,
        "hosts": host_dicts,
        "log": build_log(host_dicts, findings, recs),
    }
    latest, dated = write_report(REPORT_BASE, report)
    print(f"Report written: {latest} + {dated} (status={status})")


if __name__ == "__main__":
    main()
