#!/usr/bin/env python3
"""
homelab-doctor.py — Homelab health diagnostician.

Two layers of checks:
  • Network-wide (run once, from the orchestrator) — the "can the homelab reach its own
    services" view: reachability of the core services (webapp, Pi-hole, Vaultwarden,
    notes), TLS certificate expiry, and freshness of the agent reports themselves
    (a stale agent is a silent failure).
  • Per-host (over SSH, for every host in HL_HOSTS) — the box-intrinsic view: local disk
    space and docker container health on opti, rpi and noblenumbat.

Service reachability stays a single vantage point on purpose: "is the webapp up?" is one
question, not three. Disk/docker are per-box because they differ per machine.

Writes <agent-logs>/homelab-doctor-latest.json + a dated history copy via
_report.write_report. Dirs from $HL_AGENT_LOGS_DIR / $HL_REPORTS_DIR; hosts/key from
HL_HOSTS / HL_SSH_KEY (see _hosts.py).
"""

import os
import shutil
import ssl
import subprocess
import urllib.request
from datetime import datetime, timezone

from _report import write_report, now_iso
from _hosts import hosts, ensure_key, run_on, probe, MissingKeyError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_LOGS_DIR = os.environ.get(
    "HL_AGENT_LOGS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "agent-logs")
)
REPORTS_DIR = os.environ.get(
    "HL_REPORTS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "security-reports")
)
REPORT_BASE = "homelab-doctor-latest"

# name -> (url, https-host:port for cert check or None)
SERVICES = [
    ("Homelab webapp", "https://webapp.rpi.lan:8443/api/health", ("webapp.rpi.lan", 8443)),
    ("Vaultwarden",    "https://bitwarden.rpi.lan/",             ("bitwarden.rpi.lan", 443)),
    ("Pi-hole admin",  "http://rpi.lan/admin/",                  None),
    ("Notes",          "http://rpi.lan:3002/notes",              None),
]

DISK_WARN_PCT = 90
STALE_HOURS = 36


def _unverified_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def check_service(url):
    """Return (up, detail). 'up' if any HTTP response comes back."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=6, context=_unverified_ctx()) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return True, f"HTTP {e.code}"  # responded → service is up
    except Exception as e:
        return False, type(e).__name__


def cert_days_left_openssl(host, port):
    if not shutil.which("openssl"):
        return None
    try:
        p = subprocess.run(
            ["openssl", "s_client", "-connect", f"{host}:{port}", "-servername", host],
            input="", capture_output=True, text=True, timeout=8,
        )
        end = subprocess.run(["openssl", "x509", "-noout", "-enddate"],
                             input=p.stdout, capture_output=True, text=True, timeout=8)
        # notAfter=Jun  5 12:00:00 2027 GMT
        line = end.stdout.strip()
        if line.startswith("notAfter="):
            dt = datetime.strptime(line.split("=", 1)[1].strip(), "%b %d %H:%M:%S %Y %Z")
            return (dt.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
    except Exception:
        return None
    return None


def host_disk_pct(host):
    """Root-fs used % on `host`, over SSH. None if unavailable."""
    out, rc = run_on(host, ["df", "-P", "/"], timeout=15)
    if rc != 0:
        return None
    lines = out.splitlines()
    if len(lines) >= 2:
        parts = lines[1].split()
        if len(parts) >= 5:
            try:
                return float(parts[4].rstrip("%"))
            except ValueError:
                return None
    return None


def host_containers(host):
    """Docker containers on `host`, over SSH. None if docker absent/unavailable."""
    _, rc = run_on(host, ["sh", "-c", "command -v docker >/dev/null 2>&1"], timeout=10)
    if rc != 0:
        return None
    out, rc = run_on(host, ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"], timeout=15)
    if rc != 0:
        return None
    return [dict(zip(("name", "status"), l.split("\t", 1)))
            for l in out.splitlines() if l.strip()]


def report_freshness():
    stale = []
    now = datetime.now(timezone.utc).timestamp()
    for d in (REPORTS_DIR, AGENT_LOGS_DIR):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith("-latest.json") or fn == "homelab-doctor-latest.json":
                continue
            age_h = (now - os.path.getmtime(os.path.join(d, fn))) / 3600
            if age_h > STALE_HOURS:
                stale.append((fn, round(age_h, 1)))
    return stale


def collect_host(host):
    """Per-host disk + docker over SSH. Returns (host_dict, findings)."""
    findings = []
    dpct = host_disk_pct(host)
    if dpct is not None and dpct >= DISK_WARN_PCT:
        findings.append({"severity": "warn", "message": f"[{host.name}] Root disk {dpct}% full"})
    containers = host_containers(host)
    down = [c for c in (containers or []) if "Up" not in (c.get("status") or "")]
    for c in down:
        findings.append({"severity": "warn",
                         "message": f"[{host.name}] container {c['name']} not up: {c['status']}"})

    parts = []
    if dpct is not None:
        parts.append(f"disk {dpct}%")
    if containers is not None:
        parts.append(f"{len(containers)} container(s)")
    summary = ", ".join(parts) or "no disk/docker data"
    status = "warn" if findings else "ok"
    return ({"host": host.name, "status": status, "summary": summary,
             "metrics": {"disk_used_pct": dpct, "containers": containers}}, findings)


def build_log(services_state, host_dicts, stale, findings):
    L = ["# Homelab Doctor", "", f"_Generated {now_iso()}_", "",
         "## Services (network-wide)", "",
         "| Service | Up | Detail | Cert days left |", "|---|---|---|---|"]
    for s in services_state:
        L.append(f"| {s['name']} | {'✅' if s['up'] else '❌'} | {s['detail']} | "
                 f"{s.get('cert_days_left', '—')} |")
    L.append("")
    L.append("## Hosts (disk + docker)")
    L.append("")
    for hd in host_dicts:
        m = hd["metrics"]
        L.append(f"### {hd['host']}")
        L.append("")
        L.append(f"- Root disk: {m.get('disk_used_pct') if m.get('disk_used_pct') is not None else '?'}%")
        containers = m.get("containers")
        if containers is None:
            L.append("- Docker: not present / unavailable")
        elif containers:
            L += ["", "| Container | Status |", "|---|---|"]
            for c in containers:
                L.append(f"| {c['name']} | {c['status']} |")
        else:
            L.append("- Docker: no running containers")
        L.append("")
    if stale:
        L += ["## Stale reports", ""]
        for fn, age in stale:
            L.append(f"- {fn} — {age}h old")
        L.append("")
    L += ["## Concerns / watch list", ""]
    if findings:
        for it in findings:
            L.append(f"- **{it['severity'].upper()}** — {it['message']}")
    else:
        L.append("- None.")
    L.append("")
    return "\n".join(L)


def main():
    os.makedirs(AGENT_LOGS_DIR, exist_ok=True)
    findings = []

    # ── Network-wide: services + certs (single vantage point) ──
    services_state = []
    for name, url, cert in SERVICES:
        up, detail = check_service(url)
        entry = {"name": name, "url": url, "up": up, "detail": detail}
        if cert:
            days = cert_days_left_openssl(*cert)
            if days is not None:
                entry["cert_days_left"] = days
                if days < 14:
                    findings.append({"severity": "warn" if days >= 0 else "critical",
                                     "message": f"{name} TLS cert expires in {days} day(s)"})
        services_state.append(entry)
        if not up:
            findings.append({"severity": "critical",
                             "message": f"{name} unreachable ({detail})"})

    # ── Per-host: disk + docker over SSH ──
    host_dicts = []
    try:
        ensure_key()
        for host in hosts():
            ok, detail = probe(host)
            if not ok:
                findings.append({"severity": "warn",
                                 "message": f"[{host.name}] unreachable over SSH — {detail}"})
                host_dicts.append({"host": host.name, "status": "unknown",
                                   "summary": f"unreachable ({detail})", "metrics": {}})
                continue
            hd, hf = collect_host(host)
            host_dicts.append(hd)
            findings += hf
    except MissingKeyError as e:
        findings.append({"severity": "warn",
                         "message": f"Per-host disk/docker checks skipped — {e}"})

    # ── Report freshness (local agent-logs) ──
    stale = report_freshness()
    for fn, age in stale:
        findings.append({"severity": "warn",
                         "message": f"Stale report: {fn} last updated {age}h ago"})

    if any(f["severity"] == "critical" for f in findings):
        status = "critical"
    elif findings:
        status = "warn"
    else:
        status = "ok"

    up_count = sum(1 for s in services_state if s["up"])
    summary = f"{up_count}/{len(services_state)} services up"
    reachable = [h for h in host_dicts if h["status"] != "unknown"]
    summary += f", {len(reachable)}/{len(host_dicts)} host(s)"
    if findings:
        summary += f", {len(findings)} flag(s)"

    report = {
        "tool": "homelab-doctor",
        "run_at": now_iso(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "services": services_state,
        "hosts": host_dicts,
        "stale_reports": [{"file": f, "age_hours": a} for f, a in stale],
        "log": build_log(services_state, host_dicts, stale, findings),
    }
    latest, dated = write_report(REPORT_BASE, report)
    print(f"Report written: {latest} + {dated} (status={status})")


if __name__ == "__main__":
    main()
