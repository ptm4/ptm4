#!/usr/bin/env python3
"""
docs-generator.py — homelab documentation generator.

Deterministic (no LLM): reads the latest agent JSON reports and renders a set of
topic-oriented Markdown docs (overview / network / hardware / software / security)
that are consumed by the local llama.cpp assistant on the phone.

Design notes:
  - 100% faithful to the report data — no synthesis, no invention. Where a report
    lacks a field, the doc says "not collected" rather than guessing.
  - Output filenames are prefixed `2X-` and carry an AUTO-GENERATED banner so they
    never get confused with the hand-authored 0X- runbooks.
  - Stdlib-only, same convention as the other homelab agents.

Env (with sensible fallbacks so it runs anywhere):
  HL_AGENT_LOGS_DIR  dir with homelab-doctor/network/hardware/software *-latest.json
  HL_REPORTS_DIR     dir with the security *-latest.json reports
  HL_DOCS_OUT        output dir for the generated .md docs
"""

import json
import os
import sys
from datetime import datetime, timezone

# ── paths ──────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
AGENT_LOGS_DIR = os.environ.get("HL_AGENT_LOGS_DIR", os.path.join(HERE, "..", "..", "agent-logs"))
REPORTS_DIR = os.environ.get("HL_REPORTS_DIR", os.path.join(HERE, "..", "..", "security-reports"))
DOCS_OUT = os.environ.get("HL_DOCS_OUT", os.path.join(AGENT_LOGS_DIR, "generated-docs"))

# Best-effort port → service label so the network doc reads as a service map.
# Only high-confidence mappings: IANA/standard services + this homelab's known
# defaults (the *arr media stack on noblenumbat, dispatcher on opti). Unknown ports
# are left blank rather than guessed — accuracy matters more than coverage here.
PORT_NAMES = {
    # universal
    22: "SSH", 53: "DNS", 80: "HTTP", 111: "rpcbind", 139: "SMB (NetBIOS)",
    443: "HTTPS", 445: "SMB", 631: "CUPS/IPP", 3389: "RDP", 5355: "LLMNR",
    5357: "wsdd", 9090: "Cockpit",
    # this homelab's known services
    3002: "notes-api", 3350: "xrdp-sesman", 8443: "webapp (nginx TLS)",
    9099: "agent-dispatcher",
    # media stack (noblenumbat) — standard app defaults
    6767: "Bazarr", 7878: "Radarr", 8090: "Mylar3", 8096: "Jellyfin",
    8191: "FlareSolverr", 8686: "Lidarr", 8989: "Sonarr", 9000: "Portainer",
    9696: "Prowlarr",
}

NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── helpers ────────────────────────────────────────────────────────────────────
def load(directory, name):
    path = os.path.join(directory, name)
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        sys.stderr.write(f"[docs-generator] warn: could not load {path}: {e}\n")
        return None


def banner(title, sources):
    """Standard header for every generated doc."""
    src = ", ".join(f"`{s}`" for s in sources if s)
    lines = [
        f"# {title}",
        "",
        "> ⚙️ **AUTO-GENERATED — do not hand-edit.** Regenerated from the homelab agent",
        f"> reports each run. Any manual change here is overwritten. Source: {src}.",
        f"> Generated: `{NOW}`",
        "",
    ]
    return "\n".join(lines)


def host_freshness(report):
    return report.get("run_at", "unknown") if report else "unknown"


def na(v, dash="_not collected_"):
    return dash if v in (None, "", [], {}) else v


def table(headers, rows):
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out) + "\n"


def hosts_of(report):
    return report.get("hosts", []) if report else []


# ── doc: overview ───────────────────────────────────────────────────────────────
def doc_overview(doctor):
    out = [banner("Homelab Overview", ["homelab-doctor"])]
    if not doctor:
        out.append("_homelab-doctor report unavailable._\n")
        return "\n".join(out)

    out.append(f"**Overall status:** `{doctor.get('status', 'unknown')}` — {doctor.get('summary', '')}")
    out.append(f"\n_Data as of {host_freshness(doctor)}_\n")

    # Hosts summary
    out.append("## Hosts\n")
    rows = []
    for h in hosts_of(doctor):
        m = h.get("metrics", {})
        pool = m.get("pool") or {}
        pool_s = f"{pool.get('used_pct')}% of {pool.get('size_gb')}GB" if pool else "—"
        au = (m.get("autoupdate") or {})
        rows.append([
            h.get("host", "?"),
            h.get("status", "?"),
            f"{m.get('disk_used_pct', '—')}%",
            pool_s,
            au.get("result", "—"),
        ])
    out.append(table(["Host", "Status", "Root disk", "Pool /srv/pool", "Autoupdate"], rows))

    # Services matrix
    out.append("## Services\n")
    srows = []
    for s in doctor.get("services", []):
        cert = s.get("cert_days_left")
        srows.append([
            s.get("name", "?"),
            "up" if s.get("up") else "**DOWN**",
            s.get("detail", "—"),
            s.get("url", "—"),
            f"{cert}d" if cert is not None else "—",
        ])
    out.append(table(["Service", "State", "Detail", "URL", "Cert left"], srows))

    # Docker rosters (doctor carries container status text per host)
    out.append("## Containers\n")
    any_containers = False
    for h in hosts_of(doctor):
        conts = (h.get("metrics", {}) or {}).get("containers")
        if conts:
            any_containers = True
            out.append(f"### {h.get('host')}\n")
            if isinstance(conts, list):
                crows = [[c.get("name", c) if isinstance(c, dict) else c,
                          c.get("status", "") if isinstance(c, dict) else ""] for c in conts]
                out.append(table(["Container", "Status"], crows))
            else:
                out.append(f"{conts}\n")
    if not any_containers:
        out.append("_Container rosters are summarized per host in the homelab-doctor log; "
                   "see the software doc for image details._\n")

    # Concerns
    findings = doctor.get("findings", [])
    out.append("## Concerns\n")
    if findings:
        out.append(table(["Severity", "Message"],
                         [[f.get("severity", "?"), f.get("message", "")] for f in findings]))
    else:
        out.append("_None flagged._\n")
    return "\n".join(out)


# ── doc: network ────────────────────────────────────────────────────────────────
def doc_network(net):
    out = [banner("Network", ["network-report"])]
    if not net:
        out.append("_network report unavailable._\n")
        return "\n".join(out)
    out.append(f"**Status:** `{net.get('status', 'unknown')}` — {net.get('summary', '')}")
    out.append(f"\n_Data as of {host_freshness(net)}_\n")

    for h in hosts_of(net):
        m = h.get("metrics", {})
        out.append(f"## {h.get('host', '?')}\n")
        out.append(f"- **Summary:** {h.get('summary', '—')}")
        out.append(f"- **Gateway:** {na(m.get('gateway'))}"
                   + (f" (reachable, {m.get('gateway_avg_ms')} ms avg)" if m.get('gateway_reachable') else ""))
        out.append(f"- **Internet:** {'up' if m.get('internet') else 'DOWN'}"
                   + (f", {m.get('internet_avg_ms')} ms avg" if m.get('internet_avg_ms') else ""))
        # interfaces
        ifaces = m.get("interfaces") or []
        if ifaces:
            out.append("\n**Interfaces**\n")
            out.append(table(["Interface", "Address"],
                             [[i.get("iface", "?"), i.get("addr", "—")] for i in ifaces]))
        # DNS
        resolvers = m.get("dns_resolvers")
        if resolvers:
            out.append(f"**DNS resolvers:** {', '.join(resolvers)}")
        lookups = m.get("dns_lookups_ms") or {}
        if lookups:
            out.append("  \n" + ", ".join(f"{k} {v}ms" for k, v in lookups.items()))
        # listening ports (service map)
        ports = m.get("listening_ports") or []
        if ports:
            out.append("\n**Listening ports** _(service column is a best-effort guess by port number)_\n")
            prows = [[p, PORT_NAMES.get(p, "—")] for p in sorted(set(ports))]
            out.append(table(["Port", "Service (heuristic)"], prows))
        # ARP anomalies
        arp = m.get("arp_failed") or []
        if arp:
            out.append(f"**ARP anomalies:** {', '.join(arp)}\n")
        out.append("")

    recs = net.get("recommendations", [])
    if recs:
        out.append("## Recommendations\n")
        out.append(table(["Severity", "Message"],
                         [[r.get("severity", "?"), r.get("message", "")] for r in recs]))
    return "\n".join(out)


# ── doc: hardware (incl. storage) ───────────────────────────────────────────────
def doc_hardware(hw, doctor):
    out = [banner("Hardware & Storage", ["hardware-report", "homelab-doctor"])]
    if not hw:
        out.append("_hardware report unavailable._\n")
        return "\n".join(out)
    out.append(f"**Status:** `{hw.get('status', 'unknown')}` — {hw.get('summary', '')}")
    out.append(f"\n_Data as of {host_freshness(hw)}_\n")

    # pool free space from doctor (storage headline)
    pool_by_host = {}
    for h in hosts_of(doctor):
        p = (h.get("metrics", {}) or {}).get("pool")
        if p:
            pool_by_host[h.get("host")] = p

    for h in hosts_of(hw):
        m = h.get("metrics", {})
        host = h.get("host", "?")
        out.append(f"## {host}\n")
        cpu = m.get("cpu") or {}
        out.append(f"- **CPU:** {na(cpu.get('Model name'))} — {na(cpu.get('CPU(s)'))} threads, "
                   f"max {na(cpu.get('CPU max MHz'))} MHz")
        load = m.get("load")
        load_s = " / ".join(str(x) for x in load) if isinstance(load, list) else na(load)
        out.append(f"- **Load (1/5/15m):** {load_s}")
        mem = m.get("memory_gib") or {}
        out.append(f"- **Memory:** {m.get('mem_used_gib', '—')} GiB used of {mem.get('MemTotal', '—')} GiB"
                   f" (swap {m.get('swap_used_gib', '—')} GiB used)")
        out.append(f"- **Uptime:** {na(m.get('uptime'))}")
        out.append(f"- **Virtualization:** {na(m.get('virtualization'))}")
        gov = m.get("governor")
        if gov:
            out.append(f"- **CPU governor:** {gov}")

        # disks
        disks = m.get("disks") or []
        if disks:
            out.append("\n**Disks**\n")
            drows = [[d.get("mount", "?"), f"{d.get('size_gb')}GB", f"{d.get('used_gb')}GB",
                      f"{d.get('used_pct')}%"] for d in disks]
            out.append(table(["Mount", "Size", "Used", "Used %"], drows))
        if host in pool_by_host:
            p = pool_by_host[host]
            out.append(f"**mergerfs pool /srv/pool:** {p.get('used_pct')}% used, "
                       f"{p.get('avail_gb')}GB free of {p.get('size_gb')}GB\n")

        # SMART
        smart = m.get("smart") or {}
        if smart:
            out.append("**SMART**\n")
            srows = []
            for dev, s in smart.items():
                flag = ""
                if isinstance(s, dict):
                    if s.get("pending", 0) or (s.get("reallocated") or 0) > 50:
                        flag = " ⚠️"
                    srows.append([dev, s.get("health", "?"),
                                  s.get("reallocated", "—"), s.get("pending", "—"),
                                  s.get("power_on_hours", "—"),
                                  f"{s.get('temp_c', '—')}°C" + flag])
            out.append(table(["Device", "Health", "Realloc", "Pending", "Power-on hrs", "Temp"], srows))

        # thermals
        thermals = m.get("thermals") or []
        if thermals:
            out.append("**Thermals:** " + ", ".join(
                f"{t.get('sensor')} {t.get('temp_c')}°C" for t in thermals) + "\n")
        # GPUs
        gpus = m.get("gpus") or []
        if gpus:
            out.append(f"**GPU:** {', '.join(str(g) for g in gpus)}\n")
        out.append("")

    recs = hw.get("recommendations", [])
    if recs:
        out.append("## Flags & recommendations\n")
        out.append(table(["Severity", "Message"],
                         [[r.get("severity", "?"), r.get("message", "")] for r in recs]))
    return "\n".join(out)


# ── doc: software ───────────────────────────────────────────────────────────────
def doc_software(sw, doctor):
    out = [banner("Software & Updates", ["software-inventory", "homelab-doctor"])]
    if not sw:
        out.append("_software report unavailable._\n")
        return "\n".join(out)
    out.append(f"**Status:** `{sw.get('status', 'unknown')}` — {sw.get('summary', '')}")
    out.append(f"\n_Data as of {host_freshness(sw)}_\n")

    # per-host package/kernel/update summary
    out.append("## Package & kernel state\n")
    rows = []
    for h in hosts_of(sw):
        m = h.get("metrics", {})
        reboot = "**yes**" if m.get("reboot_required") else "no"
        rows.append([
            h.get("host", "?"),
            m.get("package_manager", "—"),
            m.get("installed_count", "—"),
            m.get("pending_count", "—"),
            m.get("security_count", "—"),
            m.get("running_kernel", "—"),
            m.get("unattended_upgrades", "—"),
            reboot,
        ])
    out.append(table(["Host", "Pkg mgr", "Installed", "Pending", "Security", "Kernel",
                      "Auto-upgrades", "Reboot req"], rows))

    # pending update detail where present
    for h in hosts_of(sw):
        m = h.get("metrics", {})
        pending = m.get("pending_updates") or []
        if pending:
            out.append(f"\n### {h.get('host')} — pending updates ({len(pending)})\n")
            sample = pending[:40]
            out.append("```\n" + "\n".join(str(p) for p in sample) +
                       ("\n… (truncated)" if len(pending) > 40 else "") + "\n```\n")

    # containers from doctor (richer than software docker_images here)
    out.append("## Running containers (per host)\n")
    any_c = False
    for h in hosts_of(doctor):
        conts = (h.get("metrics", {}) or {}).get("containers")
        if conts and isinstance(conts, list):
            any_c = True
            out.append(f"### {h.get('host')}\n")
            out.append(table(["Container", "Status"],
                             [[c.get("name", "?"), c.get("status", "")] if isinstance(c, dict) else [c, ""]
                              for c in conts]))
    if not any_c:
        out.append("_Container status is captured in the homelab-doctor log; "
                   "docker image lists were empty in the software report._\n")
    return "\n".join(out)


# ── doc: security ───────────────────────────────────────────────────────────────
def doc_security(journal, persistence):
    out = [banner("Security", ["journald-hunter", "persistence-auditor"])]
    for label, rep in [("Journald Threat & Health Hunter", journal),
                       ("Persistence Auditor", persistence)]:
        out.append(f"## {label}\n")
        if not rep:
            out.append("_report unavailable._\n")
            continue
        out.append(f"- **Status:** `{rep.get('status', 'unknown')}`")
        out.append(f"- **Summary:** {rep.get('summary', '—')}")
        if "tracked_count" in rep:
            out.append(f"- **Tracked baseline entries:** {rep.get('tracked_count')}")
        out.append(f"- _Data as of {host_freshness(rep)}_\n")
        findings = rep.get("findings", [])
        if findings:
            out.append(table(["Severity", "Message"],
                             [[f.get("severity", "?"), f.get("message", "")] for f in findings]))
        else:
            out.append("_No findings._\n")
        out.append("")
    return "\n".join(out)


# ── main ────────────────────────────────────────────────────────────────────────
DOCS = [
    ("20-overview.md", lambda R: doc_overview(R["doctor"])),
    ("21-network.md", lambda R: doc_network(R["network"])),
    ("22-hardware.md", lambda R: doc_hardware(R["hardware"], R["doctor"])),
    ("23-software.md", lambda R: doc_software(R["software"], R["doctor"])),
    ("24-security.md", lambda R: doc_security(R["journal"], R["persistence"])),
]


def main():
    reports = {
        "doctor": load(AGENT_LOGS_DIR, "homelab-doctor-latest.json"),
        "network": load(AGENT_LOGS_DIR, "network-latest.json"),
        "hardware": load(AGENT_LOGS_DIR, "hardware-latest.json"),
        "software": load(AGENT_LOGS_DIR, "software-latest.json"),
        "journal": load(REPORTS_DIR, "journal-hunt-latest.json"),
        "persistence": load(REPORTS_DIR, "persistence-audit-latest.json"),
    }
    os.makedirs(DOCS_OUT, exist_ok=True)
    written = []
    for name, fn in DOCS:
        content = fn(reports).rstrip() + "\n"
        path = os.path.join(DOCS_OUT, name)
        with open(path, "w") as f:
            f.write(content)
        written.append((name, len(content)))
    # index of what was generated
    idx = [banner("Homelab Docs Index", ["docs-generator"]),
           "These reference docs are regenerated from the homelab agent reports:\n"]
    for name, size in written:
        idx.append(f"- `{name}` ({size} bytes)")
    with open(os.path.join(DOCS_OUT, "2-README.md"), "w") as f:
        f.write("\n".join(idx).rstrip() + "\n")

    print(f"[docs-generator] wrote {len(written)} docs to {DOCS_OUT}")
    for name, size in written:
        print(f"  {name}: {size} bytes")


if __name__ == "__main__":
    main()
