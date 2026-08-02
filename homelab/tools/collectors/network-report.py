#!/usr/bin/env python3
"""
network-report.py — deep network status report across all homelab hosts.

For every host in HL_HOSTS (opti, rpi, noblenumbat by default), over SSH — so each
check reflects that host's real vantage point: interfaces/IPs, link state, routes,
default gateway reachability, internet egress, DNS resolvers + timed lookups,
ARP/neighbor sanity, listening-port surface (with an exposure check), and Pi-hole
stats when present. Emits a multi-host report with a per-host "watch list" and a full
markdown `log`.

Writes <agent-logs>/network-latest.json + <agent-logs>/network-latest/<date>.json
via _report.write_report. Logs dir from $HL_AGENT_LOGS_DIR; hosts/key from HL_HOSTS /
HL_SSH_KEY (see _hosts.py).

Read-only: never modifies routes, iptables, DHCP leases, or Pi-hole config.
"""

import re

from _report import write_report, now_iso
from _hosts import hosts, ensure_key, run_on, probe, MissingKeyError

REPORT_BASE = "network-latest"

# ports we expect to be bound on a host's LAN surface, common to all hosts
EXPECTED_PORTS = {22, 53, 67, 80, 443, 445, 3000, 3002, 8443, 9099,
                  8787}   # hl-arch-agent (/status /vitals /apt-status /sync /restart
                          # /update /reboot /apt-upgrade /service-restart /wake), all hosts

# additional per-host expected ports — see homelab-techdoc.md "Remote Access"
# and "Homelab Agent Platform" sections for what each of these is
PER_HOST_EXPECTED_PORTS = {
    "opti": {139, 3389, 3350, 5355, 5357},   # smb, xrdp, xrdp-sesman (loopback), llmnr, wsdd
    "rpi": {111, 9090},                       # idle rpcbind, Cockpit admin UI
    "noblenumbat": {
        111, 631,                             # rpcbind (nfs-common, client support), cupsd (loopback)
        3389, 3390,                           # gnome-remote-desktop
        5000, 6767, 7878, 8003, 8081, 8090, 8096,
        8191, 8388, 8686, 8888, 8989, 9000, 9696,
        # kavita, bazarr, radarr, gluetun-admin, qbittorrent, mylar3, jellyfin,
        # flaresolverr, gluetun-shadowsocks/http-proxy, lidarr, portainer, sonarr, prowlarr
    },
}


def _run(host, cmd, timeout=15):
    out, rc = run_on(host, cmd, timeout=timeout)
    return out if rc == 0 else ""


def interfaces(host):
    out = []
    for line in _run(host, ["ip", "-o", "-4", "addr", "show"]).splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] != "lo":
            out.append({"iface": parts[1], "addr": parts[3]})
    return out


def link_state(host):
    states = {}
    for line in _run(host, ["ip", "-br", "link"]).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] != "lo":
            states[parts[0]] = parts[1]
    return states


def routes(host):
    return [l.strip() for l in _run(host, ["ip", "route", "show"]).splitlines() if l.strip()]


def default_gateway(host):
    out = _run(host, ["ip", "route", "show", "default"]).split()
    if len(out) >= 3 and out[0] == "default":
        return out[2]
    # Fallback for hosts whose default route isn't in the main table an unprivileged
    # process can see (e.g. unrooted Android/Termux, where the OS routes per-uid) —
    # ask the kernel what it would actually use to reach the internet instead. See
    # homelab/agentic/troubleshooting.md "android: No default gateway configured".
    m = re.search(r"via (\S+)", _run(host, ["ip", "route", "get", "1.1.1.1"]))
    return m.group(1) if m else None


def ping(host, target, count=2):
    """Ping `target` FROM `host` (over SSH)."""
    out, rc = run_on(host, ["ping", "-c", str(count), "-W", "2", target], timeout=12)
    ok = rc == 0
    avg = None
    m = re.search(r"=\s*[\d.]+/([\d.]+)/", out)
    if m:
        avg = float(m.group(1))
    return ok, avg


def dns_resolvers(host):
    out = _run(host, ["resolvectl", "status"])
    resolvers = re.findall(r"DNS Servers?:\s*(.+)", out)
    if not resolvers:
        conf = _run(host, ["cat", "/etc/resolv.conf"])
        resolvers = [l.split()[1] for l in conf.splitlines()
                     if l.startswith("nameserver") and len(l.split()) > 1]
    flat = []
    for r in resolvers:
        flat += r.split()
    return flat


def timed_lookup(host, target):
    """Time a DNS lookup of `target` performed ON `host` (uses that host's resolvers)."""
    out, rc = run_on(host, ["python3", "-c",
                            "import socket,time;t=time.monotonic();"
                            "socket.setdefaulttimeout(5);socket.gethostbyname('%s');"
                            "print(round((time.monotonic()-t)*1000,1))" % target], timeout=10)
    if rc != 0:
        return None
    try:
        return float(out.strip())
    except ValueError:
        return None


def arp_sanity(host):
    failed = []
    for line in _run(host, ["ip", "neigh", "show"]).splitlines():
        if "FAILED" in line or "INCOMPLETE" in line:
            failed.append(line.strip())
    return failed


def listening_ports(host):
    ports = []
    rows = []
    for line in _run(host, ["ss", "-tlnH"]).splitlines():
        parts = line.split()
        if len(parts) >= 4:
            local = parts[3]
            port = local.rsplit(":", 1)[-1]
            if port.isdigit():
                ports.append(int(port))
                rows.append({"addr": local, "port": int(port)})
    return sorted(set(ports)), rows


# Pi-hole v6 stats. The old implementation shelled out to `pihole -c -j`, which v6
# REMOVED — it now prints "Chronometer is gone, use PADD", json.loads threw, and this
# returned None for every host. The Home page's Pi-hole card had been dead ever since
# the v6 upgrade with nothing reporting it.
#
# v6 replaces that with an authenticated REST API. Three things worth knowing:
#   1. The whole exchange runs ON the Pi-hole host over the SSH transport we already
#      have, reading the password from that host's own compose .env — so no Pi-hole
#      credential ever has to be copied to opti or into /etc/hl-agents.env.
#   2. The session MUST be released with DELETE /api/auth. v6 caps concurrent
#      sessions, and leaking one every run would eventually lock out the health bot,
#      which authenticates the same way (see discord-healthdigest.py's fetch_pihole).
#   3. Contract is unchanged: a dict on success, None on any failure. Callers
#      (docs-generator, the webapp Home card) already handle None.
_PIHOLE_SH = r'''
set -a; . /srv/docker/compose/.env 2>/dev/null; set +a
[ -n "$PIHOLE_WEB_PASSWORD" ] || exit 1
SID=$(curl -s -m 8 -X POST http://localhost/api/auth \
        -H "Content-Type: application/json" \
        -d "{\"password\":\"$PIHOLE_WEB_PASSWORD\"}" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["session"]["sid"])' 2>/dev/null)
[ -n "$SID" ] || exit 1
curl -s -m 8 http://localhost/api/stats/summary -H "X-FTL-SID: $SID"
curl -s -m 8 -X DELETE http://localhost/api/auth -H "X-FTL-SID: $SID" >/dev/null 2>&1
'''


def pihole_stats(host):
    # Only the host actually running Pi-hole; everywhere else this is correctly None.
    _, rc = run_on(host, ["sh", "-c",
                          "docker ps --format '{{.Names}}' 2>/dev/null | grep -qx pihole"],
                   timeout=10)
    if rc != 0:
        return None

    out, rc = run_on(host, ["sh", "-c", _PIHOLE_SH], timeout=30)
    if rc != 0 or not out.strip():
        return None
    try:
        import json as _json
        data = _json.loads(out)
    except Exception:
        return None

    q = (data or {}).get("queries") or {}
    if not q:
        return None
    # Flatten to the shape the Home card and docs-generator read, keeping the v5 key
    # names they already expect so nothing downstream needs to change.
    return {
        "dns_queries_today": q.get("total"),
        "ads_blocked_today": q.get("blocked"),
        "ads_percentage_today": q.get("percent_blocked"),
        "unique_domains": q.get("unique_domains"),
        "queries_forwarded": q.get("forwarded"),
        "queries_cached": q.get("cached"),
        "unique_clients": ((data.get("clients") or {}).get("active")
                           if isinstance(data.get("clients"), dict) else None),
        "gravity_domains": ((data.get("gravity") or {}).get("domains_being_blocked")
                            if isinstance(data.get("gravity"), dict) else None),
    }


def collect_host(host):
    findings = []
    recs = []

    ifaces = interfaces(host)
    links = link_state(host)
    rts = routes(host)
    gw = default_gateway(host)
    gw_up, gw_avg = ping(host, gw) if gw else (False, None)
    inet, inet_avg = ping(host, "1.1.1.1")
    resolvers = dns_resolvers(host)
    lookups = {h: timed_lookup(host, h) for h in ("github.com", "webapp.rpi.lan")}
    arp_failed = arp_sanity(host)
    ports, port_rows = listening_ports(host)
    pihole = pihole_stats(host)

    # android is a phone: Doze parks the radio and it drops off the LAN for hours at a
    # time by design (see rules/01-homelab-context.md — "Intermittent — often offline").
    # Its unreachability is expected noise, not an incident, and at `critical` it was
    # painting the whole network report (and the dashboard's fleet pill) red every time
    # the phone napped. Real hosts stay critical.
    reach_sev = "warn" if host.name == "android" else "critical"
    if not gw:
        findings.append({"severity": reach_sev, "message": f"[{host.name}] No default gateway configured"})
    elif not gw_up:
        findings.append({"severity": reach_sev, "message": f"[{host.name}] Gateway {gw} unreachable"})
    if not inet:
        findings.append({"severity": reach_sev, "message": f"[{host.name}] No internet (1.1.1.1 unreachable)"})
    if lookups.get("github.com") is None:
        findings.append({"severity": reach_sev, "message": f"[{host.name}] DNS resolution failing (github.com)"})

    allowed = EXPECTED_PORTS | PER_HOST_EXPECTED_PORTS.get(host.name, set())
    # Only flag sockets reachable from the LAN. Loopback-only listeners (VS Code
    # remote servers, xrdp-sesman and friends) are ephemeral and local by definition —
    # flagging them produced permanent "unexpected port" warnings for things no other
    # machine could ever reach (e.g. code-server picking a fresh 127.0.0.1 port daily).
    loopback = {"127.0.0.1", "[::1]", "::1", "localhost"}
    lan_ports = {r["port"] for r in port_rows
                 if r["addr"].rsplit(":", 1)[0] not in loopback}
    unexpected = sorted(p for p in lan_ports if p not in allowed)
    if unexpected:
        recs.append({"severity": "warn",
                     "message": f"[{host.name}] Unexpected listening port(s): {', '.join(map(str, unexpected))} — confirm these are intended."})
    if arp_failed:
        recs.append({"severity": "info",
                     "message": f"[{host.name}] {len(arp_failed)} ARP/neighbor entr(ies) in FAILED/INCOMPLETE state."})

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
    return ({"host": host.name, "status": status, "summary": summary, "metrics": metrics},
            findings, recs)


def _host_log(host_dict):
    m = host_dict["metrics"]
    gw_reach = "reachable" if m.get("gateway_reachable") else "UNREACHABLE"
    gw_ms = f", {m['gateway_avg_ms']}ms" if m.get("gateway_avg_ms") else ""
    inet_state = "ok" if m.get("internet") else "DOWN"
    inet_ms = f", {m['internet_avg_ms']}ms" if m.get("internet_avg_ms") else ""
    resolvers = ", ".join(m.get("dns_resolvers") or ["?"])
    L = [f"## {host_dict['host']}", "",
         f"- Default gateway: {m.get('gateway') or '—'} ({gw_reach}{gw_ms})",
         f"- Internet (1.1.1.1): {inet_state}{inet_ms}",
         f"- DNS resolvers: {resolvers}",
         ""]
    if m.get("interfaces"):
        L += ["| Iface | Address | Link |", "|---|---|---|"]
        for i in m["interfaces"]:
            L.append(f"| {i['iface']} | {i['addr']} | {m.get('links', {}).get(i['iface'], '?')} |")
        L.append("")
    L.append("DNS lookups: " + ", ".join(
        (f"{h} {ms}ms" if ms is not None else f"{h} FAILED")
        for h, ms in (m.get("dns_lookups_ms") or {}).items()))
    L.append("")
    if m.get("listening_ports"):
        L.append("Listening ports: `" + ", ".join(map(str, m["listening_ports"])) + "`")
        L.append("")
    if m.get("pihole"):
        p = m["pihole"]
        L += ["**Pi-hole (last 24h)**", "",
              f"- Queries: {p.get('dns_queries_today', '?')} · "
              f"Blocked: {p.get('ads_blocked_today', '?')} ({p.get('ads_percentage_today', '?')}%)",
              f"- Unique clients: {p.get('unique_clients', '?')}", ""]
    return L


def build_log(host_dicts, findings, recs):
    L = ["# Network Report", "", f"_Generated {now_iso()}_",
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
            "tool": "network-report", "run_at": now_iso(), "status": "critical",
            "summary": "SSH key missing — cannot collect from any host",
            "findings": [{"severity": "critical", "message": str(e)}],
            "recommendations": [], "hosts": [],
            "log": "# Network Report\n\n**SSH key missing.** " + str(e),
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
    elif findings or any(r["severity"] == "warn" for r in recs):
        status = "warn"
    else:
        status = "ok"

    reachable = [h for h in host_dicts if h["status"] != "unknown"]
    summary = f"{len(reachable)}/{len(host_dicts)} host(s) reported"

    report = {
        "tool": "network-report",
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
