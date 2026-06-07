#!/usr/bin/env python3
"""
network-report.py — Network status agent.

Reports interfaces/IPs, default gateway, and connectivity (gateway, internet, DNS),
plus listening TCP ports. Critical if there's no internet or DNS resolution.

Writes <agent-logs>/network-latest.json. Dir from $HL_AGENT_LOGS_DIR.
"""

import json
import os
import socket
import subprocess
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_LOGS_DIR = os.environ.get(
    "HL_AGENT_LOGS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "agent-logs")
)
REPORT_PATH = os.path.join(AGENT_LOGS_DIR, "network-latest.json")


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return out.stdout if out.returncode == 0 else ""
    except Exception:
        return ""


def interfaces():
    out = []
    for line in _run(["ip", "-o", "-4", "addr", "show"]).splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] != "lo":
            out.append({"iface": parts[1], "addr": parts[3]})
    return out


def default_gateway():
    out = _run(["ip", "route", "show", "default"]).split()
    return out[2] if len(out) >= 3 and out[0] == "default" else None


def ping(host):
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", host],
                           capture_output=True, timeout=6)
        return r.returncode == 0
    except Exception:
        return False


def dns_ok():
    try:
        socket.setdefaulttimeout(5)
        socket.gethostbyname("github.com")
        return True
    except Exception:
        return False


def listening_ports():
    ports = []
    for line in _run(["ss", "-tlnH"]).splitlines():
        parts = line.split()
        if len(parts) >= 4:
            local = parts[3]
            port = local.rsplit(":", 1)[-1]
            if port.isdigit():
                ports.append(int(port))
    return sorted(set(ports))


def main():
    os.makedirs(AGENT_LOGS_DIR, exist_ok=True)
    findings = []

    ifaces = interfaces()
    gw = default_gateway()
    gw_up = ping(gw) if gw else False
    inet = ping("1.1.1.1")
    dns = dns_ok()
    ports = listening_ports()

    if not gw:
        findings.append({"severity": "critical", "message": "No default gateway configured"})
    elif not gw_up:
        findings.append({"severity": "critical", "message": f"Gateway {gw} unreachable"})
    if not inet:
        findings.append({"severity": "critical", "message": "No internet (1.1.1.1 unreachable)"})
    if not dns:
        findings.append({"severity": "critical", "message": "DNS resolution failing"})

    status = "critical" if findings else "ok"
    summary = (f"{len(ifaces)} iface(s), gw {gw or '—'} "
               f"{'up' if gw_up else 'down'}, internet {'ok' if inet else 'down'}, "
               f"DNS {'ok' if dns else 'down'}, {len(ports)} listening port(s)")

    report = {
        "tool": "network-report",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "interfaces": ifaces,
        "gateway": gw,
        "gateway_reachable": gw_up,
        "internet": inet,
        "dns": dns,
        "listening_ports": ports,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} (status={status})")


if __name__ == "__main__":
    main()
