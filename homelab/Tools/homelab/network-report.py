#!/usr/bin/env python3
"""
network-report.py — deep network status report.

Reports interfaces/IPs, link state, routes, default gateway reachability, internet
egress, DNS resolvers + timed lookups, ARP/neighbor sanity, listening-port surface
(with an exposure check), and Pi-hole stats when present. Emits a recommendations/
"watch list" section and a full markdown `log`.

Writes <agent-logs>/network-latest.json + <agent-logs>/network-latest/<date>.json
via _report.write_report. Logs dir from $HL_AGENT_LOGS_DIR.

Read-only: never modifies routes, iptables, DHCP leases, or Pi-hole config.
"""

import os
import re
import shutil
import socket
import subprocess
import time

from _report import write_report, now_iso

REPORT_BASE = "network-latest"

# ports we expect to be bound on this host's LAN surface
EXPECTED_PORTS = {22, 53, 67, 80, 443, 445, 3000, 3002, 8443, 9099}


def _run(cmd, timeout=15):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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


def link_state():
    states = {}
    for line in _run(["ip", "-br", "link"]).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] != "lo":
            states[parts[0]] = parts[1]
    return states


def routes():
    return [l.strip() for l in _run(["ip", "route", "show"]).splitlines() if l.strip()]


def default_gateway():
    out = _run(["ip", "route", "show", "default"]).split()
    return out[2] if len(out) >= 3 and out[0] == "default" else None


def ping(host, count=2):
    try:
        r = subprocess.run(["ping", "-c", str(count), "-W", "2", host],
                           capture_output=True, text=True, timeout=10)
        ok = r.returncode == 0
        avg = None
        m = re.search(r"=\s*[\d.]+/([\d.]+)/", r.stdout)
        if m:
            avg = float(m.group(1))
        return ok, avg
    except Exception:
        return False, None


def dns_resolvers():
    out = _run(["resolvectl", "status"])
    resolvers = re.findall(r"DNS Servers?:\s*(.+)", out)
    if not resolvers:
        try:
            with open("/etc/resolv.conf") as f:
                resolvers = [l.split()[1] for l in f if l.startswith("nameserver")]
        except OSError:
            resolvers = []
    flat = []
    for r in resolvers:
        flat += r.split()
    return flat


def timed_lookup(host):
    t0 = time.monotonic()
    try:
        socket.setdefaulttimeout(5)
        socket.gethostbyname(host)
        return round((time.monotonic() - t0) * 1000, 1)
    except Exception:
        return None


def arp_sanity():
    failed = []
    for line in _run(["ip", "neigh", "show"]).splitlines():
        if "FAILED" in line or "INCOMPLETE" in line:
            failed.append(line.strip())
    return failed


def listening_ports():
    ports = []
    rows = []
    for line in _run(["ss", "-tlnH"]).splitlines():
        parts = line.split()
        if len(parts) >= 4:
            local = parts[3]
            port = local.rsplit(":", 1)[-1]
            if port.isdigit():
                ports.append(int(port))
                rows.append({"addr": local, "port": int(port)})
    return sorted(set(ports)), rows


def pihole_stats():
    if not shutil.which("docker"):
        return None
    out = _run(["docker", "exec", "pihole", "pihole", "-c", "-j"], timeout=15)
    if not out:
        return None
    try:
        import json as _json
        return _json.loads(out)
    except Exception:
        return None


def collect_host():
    host = socket.gethostname()
    findings = []
    recs = []

    ifaces = interfaces()
    links = link_state()
    rts = routes()
    gw = default_gateway()
    gw_up, gw_avg = ping(gw) if gw else (False, None)
    inet, inet_avg = ping("1.1.1.1")
    resolvers = dns_resolvers()
    lookups = {h: timed_lookup(h) for h in ("github.com", "webapp.rpi.lan")}
    arp_failed = arp_sanity()
    ports, port_rows = listening_ports()
    pihole = pihole_stats()

    if not gw:
        findings.append({"severity": "critical", "message": "No default gateway configured"})
    elif not gw_up:
        findings.append({"severity": "critical", "message": f"Gateway {gw} unreachable"})
    if not inet:
        findings.append({"severity": "critical", "message": "No internet (1.1.1.1 unreachable)"})
    if lookups.get("github.com") is None:
        findings.append({"severity": "critical", "message": "DNS resolution failing (github.com)"})

    unexpected = sorted(p for p in ports if p not in EXPECTED_PORTS)
    if unexpected:
        recs.append({"severity": "warn",
                     "message": f"Unexpected listening port(s): {', '.join(map(str, unexpected))} — confirm these are intended."})
    if arp_failed:
        recs.append({"severity": "info",
                     "message": f"{len(arp_failed)} ARP/neighbor entr(ies) in FAILED/INCOMPLETE state."})

    status = "ok"
    if any(f["severity"] == "critical" for f in findings):
        status = "critical"
    elif findings or any(r["severity"] == "warn" for r in recs):
        status = "warn"

    metrics = {
        "interfaces": ifaces,
        "links": links,
        "routes": rts,
        "gateway": gw,
        "gateway_reachable": gw_up,
        "gateway_avg_ms": gw_avg,
        "internet": inet,
        "internet_avg_ms": inet_avg,
        "dns_resolvers": resolvers,
        "dns_lookups_ms": lookups,
        "arp_failed": arp_failed,
        "listening_ports": ports,
        "listening_detail": port_rows,
        "pihole": pihole,
    }
    summary = (f"{len(ifaces)} iface(s) · gw {gw or '—'} {'up' if gw_up else 'down'} · "
               f"internet {'ok' if inet else 'down'} · "
               f"DNS {'ok' if lookups.get('github.com') is not None else 'down'} · "
               f"{len(ports)} port(s)")
    return ({"host": host, "status": status, "summary": summary, "metrics": metrics},
            findings, recs)


def build_log(host, findings, recs):
    m = host["metrics"]
    gw_reach = "reachable" if m.get("gateway_reachable") else "UNREACHABLE"
    gw_ms = f", {m['gateway_avg_ms']}ms" if m.get("gateway_avg_ms") else ""
    inet_state = "ok" if m.get("internet") else "DOWN"
    inet_ms = f", {m['internet_avg_ms']}ms" if m.get("internet_avg_ms") else ""
    resolvers = ", ".join(m.get("dns_resolvers") or ["?"])
    L = [f"# Network Report — {host['host']}", "",
         f"_Generated {now_iso()}_", "",
         "## Summary", "",
         f"- Default gateway: {m.get('gateway') or '—'} ({gw_reach}{gw_ms})",
         f"- Internet (1.1.1.1): {inet_state}{inet_ms}",
         f"- DNS resolvers: {resolvers}",
         ""]
    if m.get("interfaces"):
        L.append("## Interfaces")
        L.append("")
        L.append("| Iface | Address | Link |")
        L.append("|---|---|---|")
        for i in m["interfaces"]:
            L.append(f"| {i['iface']} | {i['addr']} | {m.get('links', {}).get(i['iface'], '?')} |")
        L.append("")
    L.append("## DNS lookups")
    L.append("")
    for h, ms in (m.get("dns_lookups_ms") or {}).items():
        L.append(f"- {h}: {ms}ms" if ms is not None else f"- {h}: FAILED")
    L.append("")
    if m.get("listening_ports"):
        L.append("## Listening ports")
        L.append("")
        L.append(f"`{', '.join(map(str, m['listening_ports']))}`")
        L.append("")
    if m.get("routes"):
        L.append("## Routes")
        L.append("")
        L.append("```")
        L += m["routes"]
        L.append("```")
        L.append("")
    if m.get("pihole"):
        p = m["pihole"]
        L.append("## Pi-hole (last 24h)")
        L.append("")
        L.append(f"- Queries: {p.get('dns_queries_today', '?')} · "
                 f"Blocked: {p.get('ads_blocked_today', '?')} "
                 f"({p.get('ads_percentage_today', '?')}%)")
        L.append(f"- Unique clients: {p.get('unique_clients', '?')}")
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
        "tool": "network-report",
        "run_at": now_iso(),
        "status": status,
        "summary": host["summary"],
        "findings": findings,
        "recommendations": recs,
        "hosts": [host],
        "log": build_log(host, findings, recs),
        # back-compat convenience keys
        "interfaces": host["metrics"]["interfaces"],
        "gateway": host["metrics"]["gateway"],
        "internet": host["metrics"]["internet"],
        "listening_ports": host["metrics"]["listening_ports"],
    }
    latest, dated = write_report(REPORT_BASE, report)
    print(f"Report written: {latest} + {dated} (status={status})")


if __name__ == "__main__":
    main()
