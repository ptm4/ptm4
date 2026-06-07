#!/usr/bin/env python3
"""
homelab-doctor.py — Homelab health diagnostician.

Runs from opti and checks the things that quietly break a homelab:
  • reachability of the core services (webapp, Pi-hole, Vaultwarden, notes)
  • TLS certificate expiry on the HTTPS services
  • local disk space
  • docker containers (only if docker runs locally)
  • freshness of the agent reports themselves (stale agent = silent failure)

Writes <agent-logs>/homelab-doctor-latest.json. Dirs from $HL_AGENT_LOGS_DIR /
$HL_REPORTS_DIR.
"""

import json
import os
import shutil
import socket
import ssl
import subprocess
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_LOGS_DIR = os.environ.get(
    "HL_AGENT_LOGS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "agent-logs")
)
REPORTS_DIR = os.environ.get(
    "HL_REPORTS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "security-reports")
)
REPORT_PATH = os.path.join(AGENT_LOGS_DIR, "homelab-doctor-latest.json")

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


def disk_pct(path):
    try:
        st = os.statvfs(path)
        used = (st.f_blocks - st.f_bfree) / st.f_blocks * 100
        return round(used, 1)
    except OSError:
        return None


def docker_containers():
    if not shutil.which("docker"):
        return None
    try:
        out = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return None
        return [dict(zip(("name", "status"), l.split("\t", 1)))
                for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        return None


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


def main():
    os.makedirs(AGENT_LOGS_DIR, exist_ok=True)
    findings = []
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

    dpct = disk_pct("/")
    if dpct is not None and dpct >= DISK_WARN_PCT:
        findings.append({"severity": "warn", "message": f"Root disk {dpct}% full"})

    containers = docker_containers()

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
    if dpct is not None:
        summary += f", disk {dpct}%"
    if findings:
        summary += f", {len(findings)} flag(s)"

    report = {
        "tool": "homelab-doctor",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "services": services_state,
        "disk_used_pct": dpct,
        "containers": containers,
        "stale_reports": [{"file": f, "age_hours": a} for f, a in stale],
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} (status={status})")


if __name__ == "__main__":
    main()
