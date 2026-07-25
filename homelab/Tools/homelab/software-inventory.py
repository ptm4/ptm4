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
    """Running containers + image, plus which of them have a newer image published.

    The update check replaces watchtower (removed 2026-07-25, see the YAMS compose for
    why). Deliberately REPORT-ONLY: it compares digests and tells you, it never pulls or
    restarts anything. Applying an update is a `docker compose pull` in the deploy
    workflow — a decision, not a 3am surprise.

    Method: a locally-pulled tag records the *manifest-list* digest in RepoDigests, and
    `docker buildx imagetools inspect --format {{.Manifest.Digest}}` returns the same
    kind of digest for what the registry currently serves. Comparing the two needs no
    pull. (`docker pull` would answer the same question but mutates state, and
    `docker manifest inspect` returns the list body rather than its digest.)
    """
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

    return images, _image_updates(host, images)


def _image_updates(host, images):
    """Which running images have a newer digest in the registry. Best-effort: any host
    without buildx, or any image we can't resolve (private/rate-limited/offline), is
    skipped silently rather than reported as a false 'update available'."""
    if not images:
        return []
    _, rc = run_on(host, ["sh", "-c", "docker buildx version >/dev/null 2>&1"], timeout=15)
    if rc != 0:
        return []

    updates = []
    # De-dupe: several containers can share one image (and each check is a network call).
    for ref in sorted({i["image"] for i in images}):
        # A digest-pinned ref can't drift, and a bare sha isn't resolvable by tag.
        if "@" in ref or ref.startswith("sha256:"):
            continue
        local, rc_l = _run(host, ["docker", "image", "inspect", ref,
                                  "--format", "{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}"],
                           timeout=20)
        if rc_l != 0 or "@" not in local:
            continue
        remote, rc_r = _run(host, ["docker", "buildx", "imagetools", "inspect", ref,
                                   "--format", "{{.Manifest.Digest}}"], timeout=45)
        if rc_r != 0 or not remote.strip().startswith("sha256:"):
            continue

        local_digest, remote_digest = local.strip().split("@", 1)[1], remote.strip()
        if local_digest != remote_digest:
            updates.append({
                "image": ref,
                "containers": sorted(i["name"] for i in images if i["image"] == ref),
                "local_digest": local_digest[:19],
                "remote_digest": remote_digest[:19],
            })
    return updates


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
    if drift:
        # info, not warn: a newer image existing is normal and not itself a problem.
        # Applying it is a deliberate `docker compose pull`, so this is a nudge, not an alarm.
        containers = sorted(c for d in drift for c in d["containers"])
        recs.append({"severity": "info",
                     "message": f"[{host.name}] {len(drift)} container image(s) have a newer "
                                f"version published: {', '.join(containers)} — "
                                f"apply with `docker compose pull && docker compose up -d`."})

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
        "image_updates": drift,
        "image_update_count": len(drift),
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
        updated = {c for u in m.get("image_updates") or [] for c in u["containers"]}
        L += ["**Docker containers**", "", "| Image | Name | Status | Update |", "|---|---|---|---|"]
        for d in m["docker_images"]:
            L.append(f"| {d['image']} | {d['name']} | {d['status']} | "
                     f"{'**available**' if d['name'] in updated else 'up to date'} |")
        L.append("")
    if m.get("image_updates"):
        L += [f"**Image updates available ({m['image_update_count']})** — report only; apply with "
              "`docker compose pull && docker compose up -d`.", "",
              "| Image | Containers | Running | Published |", "|---|---|---|---|"]
        for u in m["image_updates"]:
            L.append(f"| {u['image']} | {', '.join(u['containers'])} | "
                     f"`{u['local_digest']}` | `{u['remote_digest']}` |")
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
