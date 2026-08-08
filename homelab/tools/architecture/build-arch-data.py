#!/usr/bin/env python3
"""
Build the homelab architecture map's data.json.

The map at webapp.rpi.lan/architecture/ is fully data-driven: index.html contains
no facts about the homelab, only rendering logic. Everything the page draws comes
from the JSON this script emits.

Why a builder instead of hand-written JSON: the graph is ~60 nodes and ~100 edges,
and an edge pointing at a node id that doesn't exist fails silently in the browser
(the edge just never draws). `validate()` below catches that class of typo, plus
unknown hosts/categories and orphan nodes, before the file is ever written.

The facts here are *curated*, not auto-probed — descriptions, flows and roles can't
be derived from `docker ps`. They were captured from a live SSH sweep of every host
(see PROBED_AT) and hand-checked against homelab/homelab-techdoc.md. Live *state*
(container up/down, uptime, disk) is deliberately NOT baked in — the page overlays
that at runtime from /api/architecture/live, so this file stays valid between runs.

Refresh procedure when the homelab changes:
    1. Re-probe the affected host (docker ps, ss -tulnp, df -h, mount, timers).
    2. Edit the relevant NODES/EDGES/HOSTS entries here.
    3. Bump PROBED_AT.
    4. python3 build-arch-data.py     # validates, then writes data.json
    5. Deploy per the add-to-rpi-webapp skill.

Usage:
    python3 build-arch-data.py [--out PATH] [--check]

    --check   validate and report, but don't write (for CI / pre-commit)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# When the facts below were last confirmed against the live hosts over SSH.
PROBED_AT = "2026-08-08T03:00:00Z"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "homelab/hosts/rpi/webapp/frontend/architecture/data.json"


# ─────────────────────────────────────────────────────────────────────────────
# Palette — validated, do not eyeball-edit
#
# Four chromatic "planes" + recessive neutrals. Ran through the dataviz skill's
# validate_palette.js with --pairs all (a topology map can place any two colors
# side by side, so adjacent-pair validation is not enough):
#
#   light (surface #f7f8fa): CVD all-pairs ΔE 12.9 PASS · contrast WARN on
#       storage/media → relief satisfied (every node carries a visible text
#       label + category glyph, and the Inventory tab is a full table view)
#   dark  (surface #1a1d27): CVD all-pairs ΔE 10.2 → the 8–12 floor band, legal
#       ONLY with secondary encoding, which is present (glyph + label + table)
#
# Seven chromatic categories was attempted and FAILED hard (violet↔blue ΔE 2.5
# under protanopia). Identity for the non-chromatic groups is carried by position
# (zone/rack) and glyph instead of hue — that is the intended fix, not a shortcut.
# If you change a hue, re-run the validator before committing.
# ─────────────────────────────────────────────────────────────────────────────
CATEGORIES = [
    {
        "key": "network",
        "label": "Network & DNS",
        "glyph": "◈",
        "light": "#2a78d6",
        "dark": "#3987e5",
        "description": "Name resolution, DHCP, reverse proxies, VPN tunnel, gateway.",
    },
    {
        "key": "storage",
        "label": "Storage",
        "glyph": "▤",
        "light": "#1baf7a",
        "dark": "#1bab7d",
        "description": "Physical disks, the ZFS pool, the attic cold copy, the Samba export and every CIFS mount that consumes it.",
    },
    {
        "key": "media",
        "label": "Media",
        "glyph": "▶",
        "light": "#eda100",
        "dark": "#c98500",
        "description": "Jellyfin, Kavita, the *arr automation stack and the download clients.",
    },
    {
        "key": "apps",
        "label": "Apps & data",
        "glyph": "●",
        "light": "#e87ba4",
        "dark": "#c4477a",
        "description": "The dashboard webapp, notes, the password manager and the Discord bot fleet.",
    },
    {
        "key": "infra",
        "label": "Platform",
        "glyph": "⚙",
        "light": "#6b7280",
        "dark": "#8b93a7",
        "description": "Container engines, CI runners, the agent control plane, timers and remote access. Deliberately recessive.",
    },
    {
        "key": "external",
        "label": "Off-LAN",
        "glyph": "☁",
        "light": "#9aa1ae",
        "dark": "#6e768a",
        "description": "Services outside the LAN — upstream DNS, GitHub, Discord, the VPN exit and content APIs.",
    },
    {
        "key": "client",
        "label": "Clients",
        "glyph": "▣",
        "light": "#7c8698",
        "dark": "#7f8798",
        "description": "Workstations, phones and TVs that consume the homelab.",
    },
]

EDGE_KINDS = [
    {"key": "dns", "label": "DNS / DHCP", "dash": "3 3"},
    {"key": "http", "label": "HTTP / API", "dash": None},
    {"key": "storage", "label": "Filesystem / CIFS", "dash": "7 4"},
    {"key": "vpn", "label": "VPN-tunnelled", "dash": "1 4"},
    {"key": "control", "label": "Control / orchestration", "dash": "5 3"},
    {"key": "ci", "label": "CI / deploy", "dash": "9 3 2 3"},
]

# ─────────────────────────────────────────────────────────────────────────────
# Hosts — the physical/logical machines. `zone` places them on the map.
# ─────────────────────────────────────────────────────────────────────────────
HOSTS = [
    {
        # Not a machine — a band on the map for everything outside the perimeter, so
        # off-LAN services don't get drawn as if they lived on the gateway.
        "id": "wan",
        "label": "Off-LAN",
        "zone": "wan",
        "role": "Outside the perimeter",
        "notes": "Nothing here is reachable inbound. Every link crossing this boundary is "
                 "outbound-initiated from inside the LAN.",
        "facts": [],
    },
    {
        "id": "router",
        "label": "Router / Gateway",
        "ip": "192.168.1.1",
        "zone": "edge",
        "role": "Internet gateway",
        "os": "Verizon-supplied firmware",
        "notes": "Upstream DNS target for Pi-hole. Its DHCP server must stay OFF — "
                 "two DHCP servers on this LAN causes the 'servers down' race.",
        "facts": [],
    },
    {
        "id": "rpi",
        "label": "rpi",
        "fqdn": "rpi.lan",
        "ip": "192.168.1.10",
        "mac": "e4:5f:01:89:b6:4d",
        "zone": "servers",
        "role": "DNS, DHCP & web services",
        "model": "Raspberry Pi 4",
        "os": "Ubuntu 22.04.5 LTS",
        "kernel": "5.15.0-1105-raspi",
        "arch": "aarch64",
        "facts": [
            {"label": "CPU", "value": "Cortex-A72 · 4 cores"},
            {"label": "RAM", "value": "3.7 GiB · no swap"},
            {"label": "Root disk", "value": "117 GB SD card · 16% used"},
            {"label": "Network", "value": "eth0 wired · static lease"},
            {"label": "Containers", "value": "12"},
        ],
        "notes": "Lowest-powered host but the most load-bearing: it is the LAN's sole "
                 "DNS and DHCP server. If it goes down, name resolution goes with it. "
                 "Runs on an SD card — the single biggest hardware risk in the homelab.",
    },
    {
        "id": "opti",
        "label": "opti",
        "fqdn": "opti.lan",
        "ip": "192.168.1.11",
        "mac": "34:17:eb:d1:eb:f8",
        "zone": "servers",
        "role": "Storage / NAS & control plane",
        "model": "Custom x86 tower",
        "os": "Debian 12 (Bookworm)",
        "kernel": "6.12.94+deb12-amd64",
        "arch": "x86_64",
        "facts": [
            {"label": "CPU", "value": "Intel i5-3570 · 4 cores"},
            {"label": "RAM", "value": "5.7 GiB"},
            {"label": "Root disk", "value": "457 GB ext4 · 66% used"},
            {"label": "Pool", "value": "3.6 TB ZFS (red) · 16% used"},
            {"label": "Share config", "value": "/etc/homelab/samba-red.conf"},
        ],
        "notes": "Every other host mounts its Samba export, so it is the storage "
                 "single point of failure. Since the 2026-07-25 ZFS migration the live "
                 "share [red] is configured in /etc/homelab/samba-red.conf — OMV is "
                 "UI/monitoring only and no longer owns the share. Also hosts the agent "
                 "control plane and the x86 CI runner.",
    },
    {
        "id": "noblenumbat",
        "label": "noblenumbat",
        "fqdn": "noblenumbat.lan",
        "ip": "192.168.1.6",
        "mac": "14:f6:d8:ea:e3:22",
        "zone": "servers",
        "role": "Media stack",
        "model": "Dell Latitude 7400",
        "os": "Ubuntu 24.04.4 LTS",
        "kernel": "7.0.0-28-generic",
        "arch": "x86_64",
        "facts": [
            {"label": "CPU", "value": "Intel i7-8665U · 8 threads"},
            {"label": "RAM", "value": "15 GiB"},
            {"label": "Root disk", "value": "468 GB NVMe · 15% used"},
            {"label": "GPU", "value": "UHD 620 · QuickSync VAAPI"},
            {"label": "Network", "value": "USB ethernet (enx207bd262…)"},
            {"label": "Containers", "value": "15"},
        ],
        "notes": "A laptop with sleep masked. Hardware-transcodes for Jellyfin via "
                 "/dev/dri/renderD128. Suffered a whole-host outage from a cooling "
                 "problem on 2026-07-16 — thermals are the thing to watch here.",
    },
    {
        "id": "tux",
        "label": "tux",
        "fqdn": "tux.lan",
        "ip": "192.168.1.3",
        "mac": "d8:5e:d3:0c:13:f2",
        "zone": "clients",
        "role": "Workstation — where the code is written",
        "os": "CachyOS (Linux 7.1.3)",
        "arch": "x86_64",
        "facts": [
            {"label": "Repo", "value": "ptm4 via CIFS at ~/opti"},
            {"label": "Agent", "value": "Claude Code runs here"},
        ],
        "notes": "Edits the repo over the CIFS mount of opti's pool, so a write here "
                 "lands directly on opti's disk. Not a server — nothing depends on it.",
    },
    {
        "id": "android",
        "label": "android (S10)",
        "fqdn": "android.lan",
        "ip": "192.168.1.54",
        "zone": "clients",
        "role": "Local LLM host",
        "os": "Android + Termux",
        "arch": "arm64",
        "facts": [
            {"label": "SSH", "value": "port 8022 (non-default)"},
            {"label": "Model", "value": "Qwen2.5-3B via llama.cpp"},
        ],
        "notes": "Intermittent by nature — a phone. Its DNS record is static but it "
                 "drops off the LAN often; the webapp's LLM tab degrades gracefully. "
                 "Was unreachable during the probe that produced this map.",
        "intermittent": True,
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Nodes.
#
# `container` is the real Docker container name and is what the live overlay
# matches on — it must match `docker ps` exactly or the node shows no health.
# `group` clusters nodes visually inside a host rack.
# ─────────────────────────────────────────────────────────────────────────────
def N(id, label, host, category, group, **kw):
    n = {"id": id, "label": label, "host": host, "category": category, "group": group}
    n.update(kw)
    return n


NODES = [
    # ── Off-LAN ──────────────────────────────────────────────────────────────
    N("internet", "Internet", "wan", "external", "wan",
      sublabel="Everything beyond the gateway", kind="cloud"),
    N("cloudflare", "Cloudflare DNS", "wan", "external", "wan",
      sublabel="1.1.1.1 — Pi-hole fallback upstream", kind="cloud"),
    N("github", "GitHub", "wan", "external", "wan",
      sublabel="ptm4 repo + Actions control plane", kind="cloud",
      notes="Both self-hosted runners poll GitHub outbound over HTTPS, so no inbound "
            "port is ever opened. This is the only path by which outside code reaches the LAN."),
    N("discord", "Discord API", "wan", "external", "wan",
      sublabel="Gateway + webhooks for 5 bots", kind="cloud"),
    N("vpn-exit", "VPN exit — Netherlands", "wan", "external", "wan",
      sublabel="Public IP 46.29.25.130", kind="cloud",
      notes="All torrent/usenet/indexer traffic egresses here, never via the LAN's own WAN IP."),
    N("content-apis", "Content APIs", "wan", "external", "wan",
      sublabel="Weather · HLTV · sports · indexers · usenet", kind="cloud"),
    N("phone-remote", "Phone · away from home", "wan", "external", "wan",
      sublabel="WireGuard client · tunnel IP 10.213.87.2", kind="device",
      notes="The Archer's exported config points DNS at 10.213.87.1 (its own forwarder — "
            "no LAN names). It is hand-edited to DNS = 192.168.1.10, and a re-export "
            "from the router silently reverts that edit."),

    # ── Gateway ──────────────────────────────────────────────────────────────
    N("gateway", "Gateway 192.168.1.1", "router", "network", "edge",
      sublabel="TP-Link Archer · DHCP disabled · WireGuard :51820", kind="device",
      notes="DHCP must remain disabled here. When it is re-enabled it races Pi-hole and "
            "hands out leases pointing at the wrong DNS — the classic 'servers are down' symptom. "
            "Also the LAN's WireGuard server: UDP :51820 on the WAN side, tunnel subnet "
            "10.213.87.0/24, routed into the LAN without NAT — no homelab host runs wg."),

    # ── rpi · network plane ──────────────────────────────────────────────────
    N("pihole", "Pi-hole", "rpi", "network", "net",
      sublabel="DNS :53 · DHCP · admin :80", container="pihole",
      image="pihole/pihole:latest", ports=["53/tcp", "53/udp", "80/tcp"],
      kind="container", critical=True,
      notes="v6 (FTL v6.7). Serves DNS *and* DHCP for the whole 192.168.1.0/24. "
            "15 local A records, 6 static MAC reservations, scope .2–.250. "
            "Whitelist with `pihole allow`."),
    N("nginx-webapp", "nginx (webapp)", "rpi", "network", "net",
      sublabel="TLS :8443 → webapp / notes", container="nginx-webapp",
      image="nginx:stable-alpine", ports=["192.168.1.10:8443→443"], kind="container",
      notes="Terminates TLS for webapp.rpi.lan using a cert read off opti's pool. "
            "Raises proxy_read_timeout to 240s for /api/llama/ only — cold LLM prompts "
            "legitimately exceed nginx's 60s default."),
    N("nginx-bitwarden", "nginx (vault)", "rpi", "network", "net",
      sublabel="TLS :443 → Vaultwarden", container="nginx-bitwarden",
      image="nginx:stable-alpine", ports=["443/tcp"], kind="container"),
    N("rpi-internal-net", "docker net · internal", "rpi", "network", "net",
      sublabel="172.18.0.0/16 — all rpi containers", kind="network",
      notes="Every rpi service shares this bridge. Bot control APIs bind :8080 on it and "
            "are NOT published to the host, so only the webapp can reach them."),

    # ── rpi · apps plane ─────────────────────────────────────────────────────
    N("webapp", "Dashboard webapp", "rpi", "apps", "apps",
      sublabel="Node/Express :3000 · this page's server", container="webapp",
      image="node:lts-alpine", ports=["3000 (internal)"], url="https://webapp.rpi.lan:8443/",
      kind="container",
      notes="Bind-mounts the repo's webapp/ directory, so deploying frontend files is a "
            "file copy — no rebuild. Reads opti's agent-logs and security-reports read-only "
            "and proxies the bot control APIs, the opti dispatcher and the phone's LLM."),
    N("notes-api", "Notes app", "rpi", "apps", "apps",
      sublabel="Express + JSON store :3002", container="notes-api",
      image="compose-notes-api", ports=["192.168.1.10:3002"], kind="container",
      notes="Published directly on the host as well as proxied, so phones can skip the "
            "self-signed-cert prompt."),
    N("bitwarden", "Vaultwarden", "rpi", "apps", "apps",
      sublabel="Password manager", container="bitwarden",
      image="vaultwarden/server:latest", url="https://bitwarden.rpi.lan/", kind="container",
      critical=True),
    N("bitwarden-db", "MariaDB", "rpi", "apps", "apps",
      sublabel="Vaultwarden datastore :3306", container="bitwarden-db",
      image="mariadb:11", kind="container", critical=True,
      notes="Holds the password vault. The single most backup-critical dataset here."),
    N("bot-weather", "discord-weather", "rpi", "apps", "bots",
      sublabel="Daily 7AM ET forecast", container="discord-weather", kind="container",
      notes="Manage via the webapp's #weather tab — never by editing files on the rpi."),
    N("bot-health", "discord-healthdigest", "rpi", "apps", "bots",
      sublabel="Homelab health summary", container="discord-healthdigest", kind="container"),
    N("bot-jellyfin", "discord-jellyfin", "rpi", "apps", "bots",
      sublabel="New-media announcements", container="discord-jellyfin", kind="container"),
    N("bot-sports", "discord-sports", "rpi", "apps", "bots",
      sublabel="Scores & fixtures", container="discord-sports", kind="container"),
    N("bot-hltv", "discord-hltv", "rpi", "apps", "bots",
      sublabel="CS2 news & match results", container="discord-hltv", kind="container",
      notes="The container is `discord-hltv`, not `discord-cs2` — the compose service and "
            "the container name differ from what the CS2 naming elsewhere suggests."),

    # ── rpi · platform ───────────────────────────────────────────────────────
    N("rpi-docker", "Docker engine", "rpi", "infra", "platform",
      sublabel="12 containers · compose at /srv/docker/compose", kind="daemon"),
    N("rpi-runner", "Actions runner (ARM64)", "rpi", "infra", "platform",
      sublabel="self-hosted · deploys the rpi stack", kind="service",
      notes="Pinned to [self-hosted, ARM64] because a bare 'self-hosted' label also "
            "matched opti's x86 runner."),
    N("rpi-mount", "/mnt/opti-fs", "rpi", "storage", "platform",
      sublabel="CIFS 3.0 ← //opti/red", kind="mount",
      notes="How the rpi reads agent logs, security reports, TLS certs and the repo. "
            "If opti is down this mount hangs and the webapp's data tabs empty out."),
    N("rpi-sshd", "sshd :22", "rpi", "infra", "platform", kind="service"),
    N("rpi-timers", "systemd timers", "rpi", "infra", "platform",
      sublabel="autoreboot 03:00 · autoupdate", kind="timer"),
    N("uptime-kuma", "Uptime Kuma", "rpi", "infra", "platform",
      sublabel="Synthetic monitors :3001", container="uptime-kuma",
      image="louislam/uptime-kuma:1", ports=["192.168.1.10:3001"],
      url="http://rpi.lan:3001/", kind="container",
      notes="Part of the 2026-08-02 control-hub work: probes every service on its own "
            "schedule, independent of the collector cadence."),
    N("dozzle", "Dozzle", "rpi", "infra", "platform",
      sublabel="Live container logs :9999", container="dozzle",
      image="amir20/dozzle:latest", ports=["192.168.1.10:9999"],
      url="http://rpi.lan:9999/", kind="container",
      notes="Streams local containers directly and noblenumbat's via the dozzle-agent "
            "on :7007. opti has no docker, so nothing to stream there."),

    # ── opti · storage plane (ZFS since 2026-07-25; replaced the mergerfs pool) ──
    N("opti-sdc", "sdc · 4 TB WD Red Plus", "opti", "storage", "disks",
      sublabel="WD40EFZZ · ZFS vdev", kind="disk",
      notes="The single vdev backing pool red. One disk = no redundancy; the attic cold "
            "copy is the only second copy of this data."),
    N("zfs-red", "ZFS pool · red", "opti", "storage", "disks",
      sublabel="/srv/red · 3.6 TB · 16% used", kind="volume", critical=True,
      notes="Replaced the mergerfs pool on 2026-07-25. Datasets: red/fs (the Samba share "
            "root) and red/media. This is the homelab's primary dataset — media, repo, "
            "certs, agent logs, security reports all live here. Single-vdev: a scrub "
            "(clean 2026-07-25) verifies integrity but nothing self-heals without a mirror."),
    N("samba", "Samba · share [red]", "opti", "storage", "disks",
      sublabel=":445 → /srv/red/fs", kind="service", critical=True,
      notes="Exports red/fs as \\\\opti\\red. Config lives in /etc/homelab/samba-red.conf "
            "— hand-managed since the ZFS migration; OMV no longer owns the live share."),
    N("attic", "attic · cold copy", "opti", "storage", "disks",
      sublabel="old sda+sdb pair · noauto · weekly", kind="volume",
      notes="The retired mergerfs disks, repurposed as a cold second copy. Mounted only "
            "during the weekly homelab-coldcopy run (rsync --delete red→attic, with an "
            "empty-source interlock so a failed pool import can't erase the last copy), "
            "so /srv/attic doesn't exist between runs and nothing can write into it."),
    N("opti-sda", "sda · 466 GB HDD", "opti", "storage", "disks",
      sublabel="ST500DM002 · ext4 root + attic branch", kind="disk"),
    N("opti-sdb", "sdb · 596 GB HDD", "opti", "storage", "disks",
      sublabel="Hitachi HTS5475 · NTFS · attic branch (ro)", kind="disk",
      notes="Held the mergerfs data before the migration; now an attic branch kept ro "
            "in steady state and flipped rw only during the coldcopy window."),
    N("omv", "OpenMediaVault", "opti", "infra", "platform",
      sublabel="NAS UI/monitoring · web UI :80", kind="service",
      notes="Demoted at the ZFS migration: disk/SMART monitoring and UI only. The live "
            "share is NOT in OMV's smb.conf anymore."),

    # ── opti · control plane ─────────────────────────────────────────────────
    N("dispatcher", "Agent dispatcher", "opti", "infra", "control",
      sublabel="Python :9099 · enable/disable + run-now", kind="service",
      notes="The LAN control plane the webapp's Agents tab drives. Runs from the repo "
            "checkout on the OMV data disk."),
    N("agents", "Homelab agents", "opti", "infra", "control",
      sublabel="doctor · hardware · software · network · docs", kind="service",
      notes="SSH out to every host, then write JSON reports into the pool. The "
            "homelab-doctor report is what this page's live overlay reads."),
    N("agent-logs", "agent-logs/", "opti", "storage", "control",
      sublabel="JSON reports on the pool", kind="dataset",
      notes="hardware-latest · software-latest · network-latest · homelab-doctor-latest. "
            "The rpi webapp mounts this read-only at /agent-logs."),
    N("opti-runner", "Actions runner (x86)", "opti", "infra", "control",
      sublabel="self-hosted · runs the agent workflow", kind="service"),
    N("opti-timers", "systemd timers", "opti", "infra", "control",
      sublabel="docs 05:16 · health-digest 06:30 · autoreboot · coldcopy Sun 04:00 · zfs-scrub monthly", kind="timer"),
    N("opti-remote", "Remote access", "opti", "infra", "control",
      sublabel="sshd :22 · xrdp :3389", kind="service"),

    # ── noblenumbat · VPN plane ──────────────────────────────────────────────
    N("gluetun", "Gluetun VPN", "noblenumbat", "network", "vpn",
      sublabel="WireGuard → NL · port-fwd 42328", container="gluetun",
      image="qmcgaw/gluetun:v3.41.0",
      ports=["8888 proxy", "8388 shadowsocks", "8003→8000 admin"], kind="container",
      critical=True,
      notes="Five containers share this network namespace, so if gluetun stops they lose "
            "all connectivity — that is the intended kill-switch. Its NAT-PMP port "
            "forwarding dies silently; the vpn-stack-heal timer exists to catch that."),
    N("vpn-heal", "vpn-stack-heal", "noblenumbat", "infra", "vpn",
      sublabel="timer · every 2 min", kind="timer",
      notes="Watchdog added 2026-07-11 after Gluetun's forwarded port kept dying without "
            "any error. Re-syncs the forwarded port into qBittorrent. Status at "
            "/var/lib/vpn-stack-heal/status.json."),
    N("nn-vpn-net", "netns · service:gluetun", "noblenumbat", "network", "vpn",
      sublabel="qbittorrent · sabnzbd · prowlarr · mylar3 · flaresolverr", kind="network"),

    # ── noblenumbat · media plane ────────────────────────────────────────────
    N("jellyfin", "Jellyfin", "noblenumbat", "media", "serve",
      sublabel="Media server :8096 · HW transcode", container="jellyfin",
      image="lscr.io/linuxserver/jellyfin:latest", ports=["8096/tcp"],
      url="http://jellyfin.lan:8096/", kind="container", critical=True),
    N("kavita", "Kavita", "noblenumbat", "media", "serve",
      sublabel="Comics & books :5000", container="kavita",
      image="lscr.io/linuxserver/kavita:latest", ports=["5000/tcp"],
      url="http://comics.lan:5000/", kind="container"),
    N("stream-station", "stream-station", "noblenumbat", "media", "serve",
      sublabel="Live streams → HLS :8098 · 4 slots", container="stream-station",
      image="yams-stream-station (built locally)", ports=["8098/tcp"], kind="container",
      notes="Server-side vlcwatcher, added 2026-08-07: streamlink resolves a Twitch/"
            "YouTube/Kick channel (skipping the site player and its ads) and headless VLC "
            "remuxes it to HLS for the dashboard's Streams page. Four independent slots. "
            "REMUX ONLY, never transcode — the sources are already H.264+AAC, so a live "
            "1080p stream costs ~3.5% CPU; that is deliberate, this host has a cooling "
            "outage on record (2026-07-16). Segments live on a 256M tmpfs at /hls and "
            "never touch the NVMe. The ONLY built-not-pulled service in the YAMS stack "
            "(python:3.12-slim + VLC + pip streamlink, runs as uid 1000 because VLC "
            "refuses to run as root), so the deploy workflow copies its build context and "
            "runs `docker compose build`. Plain yams_network, NOT gluetun — VPN is opt-in "
            "there. POST /start|/stop are bearer-token gated (HL_STREAM_TOKEN, matched "
            "against the rpi webapp's env); GET /hls/* is open so browsers can fetch "
            "segments through nginx. An idle reaper stops any slot whose playlist has not "
            "been fetched for 5 minutes, so nothing pulls a stream unattended. It is the "
            "only container in this stack with mem_limit/cpus caps."),
    N("sonarr", "Sonarr", "noblenumbat", "media", "arr",
      sublabel="TV automation :8989", container="sonarr", ports=["8989/tcp"], kind="container"),
    N("radarr", "Radarr", "noblenumbat", "media", "arr",
      sublabel="Movie automation :7878", container="radarr", ports=["7878/tcp"], kind="container"),
    N("lidarr", "Lidarr", "noblenumbat", "media", "arr",
      sublabel="Music automation :8686", container="lidarr", ports=["8686/tcp"], kind="container"),
    N("bazarr", "Bazarr", "noblenumbat", "media", "arr",
      sublabel="Subtitles :6767", container="bazarr", ports=["6767/tcp"], kind="container"),
    N("mylar3", "Mylar3", "noblenumbat", "media", "arr",
      sublabel="Comics automation :8090 via VPN", container="mylar3", kind="container"),
    N("prowlarr", "Prowlarr", "noblenumbat", "media", "arr",
      sublabel="Indexer manager :9696 via VPN", container="prowlarr", kind="container",
      notes="Feeds indexers to every *arr. Published through gluetun's port map, not its own."),
    N("qbittorrent", "qBittorrent", "noblenumbat", "media", "dl",
      sublabel="Torrents · pinned 4.6.3 · via VPN", container="qbittorrent",
      image="lscr.io/linuxserver/qbittorrent:4.6.3", kind="container",
      notes="Version-pinned deliberately. Its listen port must track Gluetun's forwarded "
            "port or nothing seeds — that sync is what vpn-stack-heal maintains."),
    N("sabnzbd", "SABnzbd", "noblenumbat", "media", "dl",
      sublabel="Usenet :8081 via VPN", container="sabnzbd", kind="container"),
    N("flaresolverr", "FlareSolverr", "noblenumbat", "media", "dl",
      sublabel="Captcha solver :8191 via VPN", container="flaresolverr", kind="container"),

    # ── noblenumbat · platform ───────────────────────────────────────────────
    N("portainer", "Portainer", "noblenumbat", "infra", "nn-platform",
      sublabel="Container UI :9000", container="portainer", ports=["9000/tcp"], kind="container"),
    N("dozzle-agent", "Dozzle agent", "noblenumbat", "infra", "nn-platform",
      sublabel="Log stream for rpi's Dozzle :7007", container="dozzle-agent",
      image="amir20/dozzle:latest", ports=["7007/tcp"], kind="container"),
    N("nn-docker", "Docker engine", "noblenumbat", "infra", "nn-platform",
      sublabel="15 containers · YAMS compose", kind="daemon",
      notes="Stack lives at /opt/yams/docker-compose.yaml. Watchtower was removed "
            "2026-07-25; image updates are now report-only (software-inventory) and "
            "applied deliberately via docker compose pull. Since 2026-08-07 the deploy "
            "workflow also copies build contexts and runs `docker compose build` — "
            "stream-station is built here, not pulled, so the pull step passes "
            "--ignore-buildable."),
    N("nn-yams-net", "docker net · yams_network", "noblenumbat", "network", "nn-platform",
      sublabel="172.60.0.0/24", kind="network"),
    N("nn-mounts", "opti CIFS mounts", "noblenumbat", "storage", "nn-platform",
      sublabel="/mnt/opti-library · -shows · -media", kind="mount", critical=True,
      notes="Movies, Shows and the import inbox all live on opti, not locally. Jellyfin's "
            "libraries are these mounts — if opti or the LAN blips, playback stops."),
    N("media-import", "media-import", "noblenumbat", "infra", "nn-platform",
      sublabel="timer · every 2 min", kind="timer",
      notes="Sweeps the Media-Import inbox on opti's pool into the library."),
    N("kavita-sync", "bb-kavita-sync", "noblenumbat", "infra", "nn-platform",
      sublabel="timer · hourly", kind="timer"),
    N("nn-remote", "Remote access", "noblenumbat", "infra", "nn-platform",
      sublabel="sshd :22 · RDP :3389", kind="service"),

    # ── clients ──────────────────────────────────────────────────────────────
    N("workstation", "tux workstation", "tux", "client", "clients",
      sublabel="Editor + Claude Code · CIFS to opti", kind="device"),
    N("browser", "Browsers & phones", "tux", "client", "clients",
      sublabel="Dashboard · Jellyfin · vault · notes", kind="device"),
    N("llama", "llama-server", "android", "apps", "clients",
      sublabel="Qwen2.5-3B :8080 · LAN-only", kind="service",
      notes="Offline local inference, ~40s warm. The webapp's LLM tab and the `ask` "
            "runbook helper both target it. Was offline during this probe."),
    N("other-clients", "Other LAN devices", "tux", "client", "clients",
      sublabel="twah.lan .4 · ptmshc.lan .5", kind="device"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Edges. `kind` drives the line style; `label` should say what actually crosses.
# ─────────────────────────────────────────────────────────────────────────────
def E(id, src, dst, label, kind, **kw):
    e = {"id": id, "from": src, "to": dst, "label": label, "kind": kind}
    e.update(kw)
    return e


EDGES = [
    # DNS / DHCP
    E("e-gw-wan", "gateway", "internet", "NAT to the WAN", "http"),
    E("e-phone-wan", "phone-remote", "internet", "encrypted UDP from anywhere", "vpn"),
    E("e-wan-wg", "internet", "gateway", "WireGuard endpoint UDP :51820", "vpn"),
    E("e-wg-pihole", "gateway", "pihole", "tunnel DNS → :53", "vpn"),
    E("e-wg-nginx", "gateway", "nginx-webapp", "tunnel HTTPS → :8443", "vpn"),
    E("e-wg-samba", "gateway", "samba", "tunnel SMB → opti :445", "vpn"),
    E("e-clients-dns", "browser", "pihole", "DNS :53 — every LAN lookup", "dns"),
    E("e-ws-dns", "workstation", "pihole", "DNS :53", "dns"),
    E("e-others-dns", "other-clients", "pihole", "DNS :53 + DHCP lease", "dns"),
    E("e-pihole-gw", "pihole", "gateway", "upstream DNS :53", "dns"),
    E("e-pihole-cf", "pihole", "cloudflare", "fallback upstream 1.1.1.1", "dns"),
    E("e-pihole-dhcp", "pihole", "gateway", "DHCP offers router .1 as gateway", "dns"),

    # rpi web edge
    E("e-browser-nginx", "browser", "nginx-webapp", "HTTPS :8443 webapp.rpi.lan", "http"),
    E("e-nginx-webapp", "nginx-webapp", "webapp", "proxy → :3000", "http"),
    E("e-nginx-notes", "nginx-webapp", "notes-api", "proxy /notes → :3002", "http"),
    E("e-browser-notes", "browser", "notes-api", "direct :3002 (no cert prompt)", "http"),
    E("e-browser-vault", "browser", "nginx-bitwarden", "HTTPS :443 bitwarden.rpi.lan", "http"),
    E("e-vaultnginx-vault", "nginx-bitwarden", "bitwarden", "proxy → :80", "http"),
    E("e-vault-db", "bitwarden", "bitwarden-db", "MySQL :3306", "http"),
    E("e-rpinet", "rpi-internal-net", "webapp", "shared docker bridge", "control"),

    # webapp fan-out
    E("e-webapp-bots", "webapp", "bot-weather", "control API :8080", "control"),
    E("e-webapp-health", "webapp", "bot-health", "control API :8080", "control"),
    E("e-webapp-jf", "webapp", "bot-jellyfin", "control API :8080", "control"),
    E("e-webapp-sports", "webapp", "bot-sports", "control API :8080", "control"),
    E("e-webapp-hltv", "webapp", "bot-hltv", "control API :8080", "control"),
    E("e-webapp-dispatch", "webapp", "dispatcher", "enable/disable + run-now :9099", "control"),
    E("e-webapp-llama", "webapp", "llama", "chat + runbook Q&A :8080", "http"),
    E("e-webapp-mount", "webapp", "rpi-mount", "reads /agent-logs, /reports, /workspace", "storage"),

    # bots outbound
    E("e-bots-discord", "bot-weather", "discord", "bot gateway", "http"),
    E("e-health-discord", "bot-health", "discord", "bot gateway", "http"),
    E("e-jfbot-discord", "bot-jellyfin", "discord", "bot gateway", "http"),
    E("e-sportsbot-discord", "bot-sports", "discord", "bot gateway", "http"),
    E("e-hltvbot-discord", "bot-hltv", "discord", "bot gateway", "http"),
    E("e-weather-api", "bot-weather", "content-apis", "forecast fetch", "http"),
    E("e-sports-api", "bot-sports", "content-apis", "scores fetch", "http"),
    E("e-hltv-api", "bot-hltv", "content-apis", "HLTV scrape", "http"),
    E("e-jfbot-jellyfin", "bot-jellyfin", "jellyfin", "library poll :8096", "http"),
    E("e-health-logs", "bot-health", "rpi-mount", "reads agent-logs", "storage"),

    # rpi platform
    E("e-rpidocker", "rpi-docker", "rpi-internal-net", "manages the bridge", "control"),
    E("e-rpimount-samba", "rpi-mount", "samba", "CIFS 3.0 :445", "storage"),
    E("e-nginx-certs", "nginx-webapp", "rpi-mount", "TLS cert from the pool", "storage"),

    # opti storage
    E("e-sdc-pool", "opti-sdc", "zfs-red", "single vdev", "storage"),
    E("e-pool-samba", "zfs-red", "samba", "red/fs exported as \\\\opti\\red", "storage"),
    E("e-pool-attic", "zfs-red", "attic", "weekly cold copy · Sun 04:00", "storage"),
    E("e-sda-attic", "opti-sda", "attic", "attic branch", "storage"),
    E("e-sdb-attic", "opti-sdb", "attic", "attic branch (ro)", "storage"),
    E("e-omv-monitor", "omv", "opti-sdc", "SMART / disk monitoring only", "control"),
    E("e-logs-pool", "agent-logs", "zfs-red", "stored on the pool", "storage"),

    # opti control plane
    E("e-dispatch-agents", "dispatcher", "agents", "starts a run", "control"),
    E("e-agents-logs", "agents", "agent-logs", "writes JSON reports", "storage"),
    E("e-agents-rpi", "agents", "rpi-sshd", "SSH probe", "control"),
    E("e-agents-nn", "agents", "nn-remote", "SSH probe", "control"),
    E("e-timers-agents", "opti-timers", "agents", "scheduled runs", "control"),
    E("e-optirunner-agents", "opti-runner", "agents", "workflow-triggered run", "ci"),

    # CI / deploy
    E("e-ws-repo", "workstation", "samba", "edits the repo over CIFS", "storage"),
    E("e-ws-github", "workstation", "github", "git push main", "ci"),
    E("e-github-rpirunner", "github", "rpi-runner", "outbound poll → job", "ci"),
    E("e-github-optirunner", "github", "opti-runner", "outbound poll → job", "ci"),
    E("e-rpirunner-docker", "rpi-runner", "rpi-docker", "compose pull + up -d", "ci"),
    E("e-rpirunner-webapp", "rpi-runner", "webapp", "copies webapp/ then restarts", "ci"),

    # noblenumbat media
    E("e-prowlarr-sonarr", "prowlarr", "sonarr", "indexer feed", "http"),
    E("e-prowlarr-radarr", "prowlarr", "radarr", "indexer feed", "http"),
    E("e-prowlarr-lidarr", "prowlarr", "lidarr", "indexer feed", "http"),
    E("e-prowlarr-mylar", "prowlarr", "mylar3", "indexer feed", "http"),
    E("e-flare-prowlarr", "flaresolverr", "prowlarr", "solves protected indexers", "http"),
    E("e-sonarr-qbt", "sonarr", "qbittorrent", "sends torrents", "http"),
    E("e-radarr-qbt", "radarr", "qbittorrent", "sends torrents", "http"),
    E("e-lidarr-qbt", "lidarr", "qbittorrent", "sends torrents", "http"),
    E("e-sonarr-sab", "sonarr", "sabnzbd", "sends NZBs", "http"),
    E("e-radarr-sab", "radarr", "sabnzbd", "sends NZBs", "http"),
    E("e-bazarr-sonarr", "bazarr", "sonarr", "reads series list", "http"),
    E("e-bazarr-radarr", "bazarr", "radarr", "reads movie list", "http"),

    # VPN namespace
    E("e-qbt-vpnnet", "qbittorrent", "nn-vpn-net", "network_mode: service:gluetun", "vpn"),
    E("e-sab-vpnnet", "sabnzbd", "nn-vpn-net", "network_mode: service:gluetun", "vpn"),
    E("e-prowlarr-vpnnet", "prowlarr", "nn-vpn-net", "network_mode: service:gluetun", "vpn"),
    E("e-mylar-vpnnet", "mylar3", "nn-vpn-net", "network_mode: service:gluetun", "vpn"),
    E("e-flare-vpnnet", "flaresolverr", "nn-vpn-net", "network_mode: service:gluetun", "vpn"),
    E("e-vpnnet-gluetun", "nn-vpn-net", "gluetun", "all egress via the tunnel", "vpn"),
    E("e-gluetun-exit", "gluetun", "vpn-exit", "WireGuard tunnel", "vpn"),
    E("e-exit-apis", "vpn-exit", "content-apis", "indexers + usenet + peers", "vpn"),
    E("e-heal-gluetun", "vpn-heal", "gluetun", "checks forwarded port", "control"),
    E("e-heal-qbt", "vpn-heal", "qbittorrent", "re-syncs listen port", "control"),

    # noblenumbat storage + serving
    E("e-nnmounts-samba", "nn-mounts", "samba", "CIFS 3.1.1 :445", "storage"),
    E("e-jellyfin-mounts", "jellyfin", "nn-mounts", "libraries live on opti", "storage"),
    E("e-kavita-mounts", "kavita", "nn-mounts", "comics from the pool", "storage"),
    E("e-qbt-mounts", "qbittorrent", "nn-mounts", "writes completed downloads", "storage"),
    E("e-sab-mounts", "sabnzbd", "nn-mounts", "writes completed downloads", "storage"),
    E("e-sonarr-mounts", "sonarr", "nn-mounts", "imports into the library", "storage"),
    E("e-radarr-mounts", "radarr", "nn-mounts", "imports into the library", "storage"),
    E("e-import-mounts", "media-import", "nn-mounts", "sweeps the import inbox", "control"),
    E("e-kavitasync-kavita", "kavita-sync", "kavita", "triggers a library scan", "control"),
    E("e-browser-jellyfin", "browser", "jellyfin", "streams :8096", "http"),
    E("e-browser-kavita", "browser", "kavita", "reads :5000", "http"),
    # Streams page — the video and control planes deliberately take different routes.
    E("e-nginx-streamstation", "nginx-webapp", "stream-station", "proxy /hls → :8098 (video)", "http",
      notes="Same-origin on purpose: the dashboard is https, so a <video> pointed straight "
            "at http://192.168.1.6:8098 would be blocked as mixed content. These are "
            "unauthenticated GETs — playlists and segments only."),
    E("e-webapp-streamstation", "webapp", "stream-station", "/api/streams → :8098 (control)", "control",
      notes="Start/stop/status/presets/keepalive. The bearer token is injected here, "
            "server-side, so it never reaches the browser and only the dashboard can "
            "start a stream."),
    E("e-streamstation-wan", "stream-station", "content-apis", "streamlink resolves twitch/youtube/kick", "http",
      notes="Direct LAN egress, not through gluetun — VPN membership on this host is "
            "opt-in per service. A geo-locked source would use gluetun's HTTP proxy on "
            ":8888 rather than joining its netns."),
    E("e-browser-portainer", "browser", "portainer", "container UI :9000", "http"),
    E("e-browser-kuma", "browser", "uptime-kuma", "monitors UI :3001", "http"),
    E("e-browser-dozzle", "browser", "dozzle", "logs UI :9999", "http"),
    E("e-dozzle-docker", "dozzle", "rpi-docker", "docker socket", "control"),
    E("e-dozzle-agent", "dozzle", "dozzle-agent", "remote agent :7007", "control"),
    E("e-dozzleagent-docker", "dozzle-agent", "nn-docker", "docker socket", "control"),
    E("e-nndocker-yams", "nn-docker", "nn-yams-net", "manages the bridge", "control"),
    E("e-portainer-docker", "portainer", "nn-docker", "docker socket", "control"),

    # misc platform
    E("e-ws-remote", "workstation", "opti-remote", "SSH + RDP", "control"),
    E("e-ws-nnremote", "workstation", "nn-remote", "SSH + RDP", "control"),
    E("e-rpitimers-docker", "rpi-timers", "rpi-docker", "nightly reboot + updates", "control"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Flows — narrated end-to-end journeys. Each step names an edge id, so selecting
# a flow can light up the exact path on the map.
# ─────────────────────────────────────────────────────────────────────────────
FLOWS = [
    {
        "id": "flow-movie",
        "name": "A movie, from request to playback",
        "summary": "The full media path — and the reason the VPN and the NAS both sit in the middle of it.",
        "steps": [
            ("e-prowlarr-radarr", "Prowlarr feeds indexers to Radarr",
             "Prowlarr holds the indexer definitions centrally; each *arr asks it rather than keeping its own copies."),
            ("e-radarr-qbt", "Radarr hands the release to qBittorrent",
             "Radarr picks a release and pushes it to the download client over the shared docker network."),
            ("e-qbt-vpnnet", "qBittorrent has no network of its own",
             "It runs with network_mode: service:gluetun, so its only route out is the tunnel. Stop gluetun and it goes dark — that is the kill-switch working."),
            ("e-gluetun-exit", "Gluetun egresses in the Netherlands",
             "Public IP 46.29.25.130, with NAT-PMP forwarded port 42328 mapped back to qBittorrent's listen port."),
            ("e-qbt-mounts", "The finished file is written to opti, not locally",
             "Downloads land on the CIFS mount, so the 468 GB NVMe never fills with media."),
            ("e-radarr-mounts", "Radarr imports it into the library",
             "Rename and move within opti's pool — a metadata operation on the same filesystem."),
            ("e-jellyfin-mounts", "Jellyfin sees it via /mnt/opti-library",
             "Its libraries ARE the opti mounts; there is no local copy of the media."),
            ("e-browser-jellyfin", "You stream it on :8096",
             "Transcoding, when needed, is hardware-accelerated on the UHD 620 via /dev/dri/renderD128."),
        ],
    },
    {
        "id": "flow-stream",
        "name": "Watching a live stream in the browser",
        "summary": "The Streams page: why the video and the controls reach the same container by two different routes.",
        "steps": [
            ("e-browser-nginx", "You open /streams/ on the dashboard",
             "A standalone page with four slot tabs. Only the active tab holds a player; the other slots keep running on the server."),
            ("e-webapp-streamstation", "Pressing a preset POSTs /api/streams/start",
             "The Express backend forwards it to stream-station on noblenumbat and injects the bearer token server-side, so the browser never sees a credential and only this dashboard can start a stream."),
            ("e-streamstation-wan", "streamlink resolves the channel",
             "It pulls the raw stream from Twitch/YouTube/Kick instead of the site's web player, which is what skips the ads. Egress is direct over the LAN — this container is deliberately not in gluetun's netns."),
            ("e-nndocker-yams", "VLC remuxes it to HLS on a tmpfs",
             "cvlc cuts the H.264+AAC source into 2-second segments under /hls on a 256M tmpfs. Nothing is transcoded and nothing is written to the NVMe — ~3.5% CPU for a live 1080p stream, which is what keeps this thermally safe on a laptop."),
            ("e-nginx-streamstation", "The browser fetches segments back through nginx",
             "Served same-origin at /hls so the https page can play them; hls.js rides ~2 segments behind the edge, putting you roughly 8-12 seconds behind live. Stop watching and the idle reaper stops the slot after 5 minutes."),
        ],
    },
    {
        "id": "flow-deploy",
        "name": "Shipping a change to this dashboard",
        "summary": "How code on the workstation becomes a running container on the rpi — with no inbound port ever opened.",
        "steps": [
            ("e-ws-repo", "Edit the repo on tux, over CIFS",
             "The working copy at ~/opti/ptm/repo/ptm4 is a CIFS mount of opti's pool, so saving a file writes straight to opti's disk."),
            ("e-ws-github", "git push to main",
             "Pushing paths under homelab/hosts/rpi/** is what triggers the deploy workflow."),
            ("e-github-rpirunner", "The rpi's runner picks up the job",
             "The runner polls GitHub outbound over HTTPS. Nothing is exposed inbound — this is the only way external code enters the LAN. Pinned to [self-hosted, ARM64] so it can't land on opti."),
            ("e-rpirunner-webapp", "Files are copied into the bind mount",
             "webapp/ is copied to /srv/docker/compose/webapp, which the container bind-mounts at /app. Frontend files are live immediately; backend changes need the restart that follows."),
            ("e-rpirunner-docker", "compose pull + up -d, then restart webapp",
             "Images are refreshed and the stack reconciled, then the webapp container restarts to re-exec the Node process."),
        ],
    },
    {
        "id": "flow-dns",
        "name": "Resolving a name on the LAN",
        "summary": "Why the rpi is the most load-bearing host despite being the weakest.",
        "steps": [
            ("e-others-dns", "A device gets its lease from Pi-hole",
             "Pi-hole — not the router — is the DHCP server for 192.168.1.0/24, scope .2–.250, with six MAC-pinned reservations for the servers."),
            ("e-clients-dns", "Every lookup goes to 192.168.1.10:53",
             "Ad-blocking plus the 15 local A records (webapp.rpi.lan, jellyfin.lan, comics.lan, opti.lan…) that make the homelab addressable by name."),
            ("e-pihole-gw", "Unknown names go upstream to the router",
             "192.168.1.1 is the primary upstream."),
            ("e-pihole-cf", "Cloudflare is the fallback",
             "1.1.1.1 covers the case where the router's resolver is unhappy."),
        ],
        "risk": "Both DNS and DHCP live in one container on an SD card. If the gateway's own DHCP is ever switched back on it races Pi-hole and hands out leases with the wrong DNS — which presents as 'all the servers are down'.",
    },
    {
        "id": "flow-agents",
        "name": "How this page knows what is up",
        "summary": "The agent loop that produces the live overlay on the Map tab.",
        "steps": [
            ("e-timers-agents", "A timer on opti starts an agent run",
             "homelab-doctor, plus the hardware, software and network reporters."),
            ("e-agents-rpi", "Each agent SSHes out to every host",
             "It collects containers, disks, packages and pool state first-hand."),
            ("e-agents-logs", "Results are written as JSON onto the pool",
             "homelab-doctor-latest.json and friends land in /srv/red/fs/ptm/agent-logs/."),
            ("e-webapp-mount", "The webapp reads them read-only",
             "The pool is mounted at /agent-logs inside the container."),
            ("e-nginx-webapp", "Sync fetches /api/architecture/live",
             "The route reshapes the newest doctor/hardware/software reports per host — no fresh SSH round trip, so the button is cheap."),
        ],
    },
    {
        "id": "flow-vpn-heal",
        "name": "The VPN port-forward watchdog",
        "summary": "A silent failure that needed a watchdog rather than a fix.",
        "steps": [
            ("e-heal-gluetun", "Every 2 minutes, check the forwarded port",
             "Gluetun's NAT-PMP lease dies without logging an error, so nothing surfaces the failure on its own."),
            ("e-heal-qbt", "Push the port back into qBittorrent",
             "If qBittorrent's listen port has drifted from the forwarded port, seeding silently stops. The healer re-syncs them."),
            ("e-gluetun-exit", "Confirm the tunnel still egresses in NL",
             "Public IP and port are recorded to /var/lib/vpn-stack-heal/status.json — check there first when torrents stall."),
        ],
    },
    {
        "id": "flow-vpn-access",
        "name": "Reaching the homelab from the phone",
        "summary": "The WireGuard path in from anywhere — terminating on the router, not on any homelab host.",
        "steps": [
            ("e-phone-wan", "The phone brings up its tunnel",
             "AllowedIPs = 0.0.0.0/0, so while connected everything the phone does routes through home."),
            ("e-wan-wg", "The Archer answers on UDP :51820",
             "The router itself is the WireGuard server — no homelab host runs wg. Tunnel traffic "
             "(10.213.87.0/24) is routed into the LAN without NAT, so hosts see the raw tunnel IP."),
            ("e-wg-pihole", "DNS rides the tunnel to Pi-hole",
             "Two prerequisites: the client config's DNS line hand-edited to 192.168.1.10, and "
             "Pi-hole's listening mode set to ALL — the LOCAL default refused non-LAN sources. "
             "This is what makes webapp.rpi resolve remotely."),
            ("e-wg-nginx", "The dashboard works exactly as on wifi",
             "Same origin, same homelab-CA cert — the phone's trust store doesn't care which "
             "network the request rode in on."),
            ("e-wg-samba", "opti's share is reachable too",
             "ufw on opti and noblenumbat needed explicit allow rules for 10.213.87.0/24 — "
             "without them VPN packets were silently dropped: the classic 5-second timeout."),
        ],
        "risk": "Tunnel clients keep their 10.213.87.x source address, so any new LAN-only firewall "
                "rule will work on wifi and time out on VPN. And a profile re-exported from the "
                "Archer reverts DNS to 10.213.87.1, silently losing every LAN name.",
    },
    {
        "id": "flow-vault",
        "name": "Opening the password vault",
        "summary": "The shortest path in the homelab, and the one with the most valuable data behind it.",
        "steps": [
            ("e-browser-vault", "HTTPS to bitwarden.rpi.lan",
             "nginx terminates TLS on :443 with a local cert."),
            ("e-vaultnginx-vault", "Proxied to Vaultwarden",
             "Vaultwarden itself is never published to the host — only nginx can reach it, over the internal docker bridge."),
            ("e-vault-db", "Secrets are read from MariaDB",
             "This dataset is the most backup-critical thing on the rpi."),
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Reference panels — facts that are tabular rather than graph-shaped.
# ─────────────────────────────────────────────────────────────────────────────
NETWORK = {
    "subnet": "192.168.1.0/24",
    "gateway": "192.168.1.1",
    "dns": {
        "server": "192.168.1.10:53 (Pi-hole FTL v6.7)",
        "upstreams": ["192.168.1.1 (router)", "1.1.1.1 (Cloudflare)"],
    },
    "dhcp": {
        "server": "Pi-hole (the router's DHCP must stay disabled)",
        "scope": "192.168.1.2 – 192.168.1.250",
        "router": "192.168.1.1",
        "ipv6": False,
    },
    "records": [
        {"name": "rpi.lan / rpi", "ip": "192.168.1.10"},
        {"name": "webapp.rpi.lan / webapp.rpi", "ip": "192.168.1.10"},
        {"name": "bitwarden.rpi.lan / bitwarden.rpi", "ip": "192.168.1.10"},
        {"name": "vpn.rpi.lan", "ip": "192.168.1.10", "note": "orphaned — WireGuard is decommissioned"},
        {"name": "opti.lan / opti", "ip": "192.168.1.11"},
        {"name": "noblenumbat.lan / noblenumbat", "ip": "192.168.1.6"},
        {"name": "jellyfin.lan / jellyfin", "ip": "192.168.1.6"},
        {"name": "comics.lan / comics", "ip": "192.168.1.6"},
        {"name": "tux.lan / ptm.lan", "ip": "192.168.1.3"},
        {"name": "twah.lan", "ip": "192.168.1.4"},
        {"name": "ptmshc.lan", "ip": "192.168.1.5"},
        {"name": "android / android.lan", "ip": "192.168.1.54"},
    ],
    "reservations": [
        {"host": "ptm / tux", "ip": "192.168.1.3", "mac": "d8:5e:d3:0c:13:f2"},
        {"host": "twah", "ip": "192.168.1.4", "mac": "98:25:4a:2f:49:3c"},
        {"host": "ptmshc", "ip": "192.168.1.5", "mac": "ac:1a:3d:7e:bc:a5"},
        {"host": "noblenumbat", "ip": "192.168.1.6", "mac": "14:f6:d8:ea:e3:22"},
        {"host": "rpi", "ip": "192.168.1.10", "mac": "e4:5f:01:89:b6:4d"},
        {"host": "opti", "ip": "192.168.1.11", "mac": "34:17:eb:d1:eb:f8"},
    ],
    "notes": [
        "There is no inbound path into this LAN. WireGuard and its peer-manager UI were "
        "decommissioned; no wg0 interface and nothing on UDP 51820. Orphaned peer configs "
        "still sit on the rpi's disk.",
        "Remote access is LAN-only: SSH everywhere, RDP on opti (xrdp) and noblenumbat "
        "(gnome-remote-desktop).",
    ],
}

STORAGE = {
    "summary": "One ZFS pool on opti backs essentially everything. Every other host is a CIFS "
               "client of it. Migrated from mergerfs 2026-07-25; the old disks survive as a "
               "weekly cold copy ('attic').",
    "pool": {
        "name": "zpool red → /srv/red (share root: red/fs → /srv/red/fs)",
        "size": "3.6 TB",
        "used": "602 GB (16%)",
        "free": "2.92 TB",
        "branches": [
            {"dev": "/dev/sdc (WD40EFZZ, 4 TB WD Red Plus)", "size": "3.6 TB", "fs": "ZFS",
             "note": "single vdev — no redundancy; scrub clean 2026-07-25"},
            {"dev": "attic: sda1 (ext4) + sdb2 (NTFS)", "size": "~1 TB", "fs": "mixed",
             "note": "retired mergerfs pair · noauto cold copy, refreshed Sun 04:00"},
        ],
    },
    "layout": [
        {"path": "ptm/Media/Movies", "purpose": "Jellyfin movie library → noblenumbat /mnt/opti-library"},
        {"path": "ptm/Media/Shows", "purpose": "Jellyfin TV library → noblenumbat /mnt/opti-shows"},
        {"path": "ptm/Media-Import", "purpose": "Drop inbox, swept every 2 min → /mnt/opti-media"},
        {"path": "ptm/agent-logs", "purpose": "Agent JSON reports → rpi webapp /agent-logs"},
        {"path": "ptm/security-reports", "purpose": "Security agent output → rpi webapp /reports"},
        {"path": "ptm/certs", "purpose": "TLS certs for webapp.rpi.lan"},
        {"path": "ptm/repo/ptm4", "purpose": "The repo itself — edited from tux, read by the webapp"},
        {"path": "ptm/logging", "purpose": "Deploy logs written by the rpi runner"},
    ],
    "consumers": [
        {"host": "rpi", "mount": "/mnt/opti-fs", "proto": "CIFS 3.0", "what": "agent logs, reports, certs, repo"},
        {"host": "noblenumbat", "mount": "/mnt/opti-library", "proto": "CIFS 3.1.1", "what": "movies"},
        {"host": "noblenumbat", "mount": "/mnt/opti-shows", "proto": "CIFS 3.1.1", "what": "TV"},
        {"host": "noblenumbat", "mount": "/mnt/opti-media", "proto": "CIFS 3.1.1", "what": "import inbox"},
        {"host": "tux", "mount": "~/opti", "proto": "CIFS 3.1.1", "what": "the whole share, for editing"},
    ],
    "notes": [
        "The live share [red] is configured in /etc/homelab/samba-red.conf, hand-managed. "
        "OMV no longer owns it — its smb.conf is not where the share lives.",
        "The pool is a single vdev: ZFS checksums detect corruption but cannot self-heal it "
        "without a mirror. The attic cold copy (weekly, rsync --delete with an empty-source "
        "interlock) is the recovery path, so worst-case loss is up to a week of changes.",
    ],
}

AUTOMATION = [
    {"host": "opti", "unit": "homelab-docs.timer", "when": "daily ~05:16", "what": "Regenerates homelab docs"},
    {"host": "opti", "unit": "opti-health-digest.timer", "when": "daily 06:30", "what": "Feeds the Discord health bot"},
    {"host": "opti", "unit": "hl-agent-dispatcher.service", "when": "always on", "what": "Agent control API on :9099"},
    {"host": "opti", "unit": "homelab-coldcopy.timer", "when": "Sun 04:00", "what": "Refreshes the cold copy (ZFS red → old mergerfs pair)"},
    {"host": "opti", "unit": "zfs-scrub-monthly@red.timer", "when": "monthly", "what": "ZFS scrub of the red pool"},
    {"host": "noblenumbat", "unit": "vpn-stack-heal.timer", "when": "every 2 min", "what": "Repairs Gluetun's forwarded port"},
    {"host": "noblenumbat", "unit": "media-import.timer", "when": "every 2 min", "what": "Sweeps the import inbox"},
    {"host": "noblenumbat", "unit": "bb-kavita-sync.timer", "when": "hourly", "what": "Kavita library sync"},
    {"host": "all", "unit": "homelab-autoupdate.timer", "when": "daily ~02:00", "what": "Unattended package updates"},
    {"host": "all", "unit": "homelab-autoreboot.timer", "when": "daily 03:00", "what": "Coordinated reboot window"},
]

AGENTS = [
    {"id": "homelab-doctor", "what": "Cross-host service + container health. Feeds this page's live overlay."},
    {"id": "hardware-report", "what": "CPU, RAM, disks, temperatures per host."},
    {"id": "software-inventory", "what": "Installed packages and pending updates."},
    {"id": "network-report", "what": "Interfaces, listening ports, reachability."},
    {"id": "docs-generator", "what": "Regenerates the technical documentation."},
    {"id": "journald-hunter", "what": "Scans journals for anomalies."},
    {"id": "persistence-auditor", "what": "Audits units, timers and cron for unexpected persistence."},
]

# Things worth knowing that the graph alone doesn't say.
OBSERVATIONS = [
    {
        "severity": "warning",
        "title": "DNS and DHCP are a single point of failure on an SD card",
        "detail": "Pi-hole on the rpi is the only DNS and DHCP server for the LAN, and the rpi "
                  "boots from a 117 GB SD card. Losing that card takes name resolution and "
                  "lease renewal down with it.",
    },
    {
        "severity": "warning",
        "title": "opti is the storage single point of failure",
        "detail": "The rpi, noblenumbat and tux all mount //opti/red. Jellyfin's libraries, the "
                  "webapp's data tabs, the TLS certs and the repo all live there. opti going "
                  "down degrades all three other hosts at once.",
    },
    {
        "severity": "good",
        "title": "No inbound attack surface",
        "detail": "WireGuard is decommissioned and nothing is port-forwarded. Both CI runners "
                  "reach GitHub outbound-only, so deploys work without exposing anything.",
    },
    {
        "severity": "good",
        "title": "The VPN kill-switch is real",
        "detail": "Five containers share Gluetun's network namespace rather than merely routing "
                  "through it, so they cannot leak to the WAN if the tunnel drops.",
    },
    {
        "severity": "warning",
        "title": "The live pool has no redundancy",
        "detail": "Pool red is a single 4 TB vdev. ZFS checksums catch corruption, but with no "
                  "mirror nothing self-heals — the weekly attic cold copy is the only second "
                  "copy, so a disk failure can cost up to a week of changes. A mirror disk is "
                  "the structural fix (see the opti-drive-onboard skill).",
    },
    {
        "severity": "info",
        "title": "Leftovers worth cleaning up",
        "detail": "A vpn.rpi.lan DNS record and WireGuard peer configs survive a decommissioned "
                  "service, and a stale pre-ZFS copy of the repo sits on opti's old NTFS disk "
                  "(dev-disk-by-uuid…/fs/ptm/repo/ptm4) — one commit behind and no longer "
                  "referenced by any unit.",
    },
    {
        "severity": "info",
        "title": "noblenumbat's real risk is thermal, not software",
        "detail": "A whole-host outage on 2026-07-16 turned out to be a cooling problem on the "
                  "laptop chassis, not a Jellyfin or container fault.",
    },
]

ZONES = [
    {"id": "wan", "label": "Off-LAN", "description": "Outside the perimeter."},
    {"id": "edge", "label": "Edge", "description": "The gateway between the LAN and the WAN."},
    {"id": "servers", "label": "Servers", "description": "The three always-on hosts."},
    {"id": "clients", "label": "Clients", "description": "What consumes the homelab."},
]

# Visual grouping of nodes inside a host rack.
GROUPS = [
    {"id": "wan", "label": "Off-LAN services"},
    {"id": "edge", "label": "Gateway"},
    {"id": "net", "label": "Network & DNS"},
    {"id": "apps", "label": "Web apps"},
    {"id": "bots", "label": "Discord bots"},
    {"id": "platform", "label": "Platform"},
    {"id": "disks", "label": "Disks & share"},
    {"id": "control", "label": "Agent control plane"},
    {"id": "vpn", "label": "VPN"},
    {"id": "serve", "label": "Media servers"},
    {"id": "arr", "label": "Automation (*arr)"},
    {"id": "dl", "label": "Download clients"},
    {"id": "nn-platform", "label": "Platform & storage"},
    {"id": "clients", "label": "Clients"},
]


def validate(doc) -> list[str]:
    """Referential integrity. An edge pointing at a missing node draws nothing and
    fails silently in the browser, so catch it here instead."""
    errors = []
    node_ids = {n["id"] for n in doc["nodes"]}
    host_ids = {h["id"] for h in doc["hosts"]}
    cat_keys = {c["key"] for c in doc["categories"]}
    kind_keys = {k["key"] for k in doc["edgeKinds"]}
    group_ids = {g["id"] for g in doc["groups"]}
    zone_ids = {z["id"] for z in doc["zones"]}
    edge_ids = {e["id"] for e in doc["edges"]}

    if len(node_ids) != len(doc["nodes"]):
        errors.append("duplicate node ids")
    if len(edge_ids) != len(doc["edges"]):
        errors.append("duplicate edge ids")

    for n in doc["nodes"]:
        if n["host"] not in host_ids:
            errors.append(f"node {n['id']}: unknown host {n['host']!r}")
        if n["category"] not in cat_keys:
            errors.append(f"node {n['id']}: unknown category {n['category']!r}")
        if n["group"] not in group_ids:
            errors.append(f"node {n['id']}: unknown group {n['group']!r}")

    for h in doc["hosts"]:
        if h["zone"] not in zone_ids:
            errors.append(f"host {h['id']}: unknown zone {h['zone']!r}")

    for e in doc["edges"]:
        if e["from"] not in node_ids:
            errors.append(f"edge {e['id']}: unknown from {e['from']!r}")
        if e["to"] not in node_ids:
            errors.append(f"edge {e['id']}: unknown to {e['to']!r}")
        if e["kind"] not in kind_keys:
            errors.append(f"edge {e['id']}: unknown kind {e['kind']!r}")

    for f in doc["flows"]:
        for step in f["steps"]:
            if step["edge"] not in edge_ids:
                errors.append(f"flow {f['id']}: unknown edge {step['edge']!r}")

    connected = {e["from"] for e in doc["edges"]} | {e["to"] for e in doc["edges"]}
    for orphan in sorted(node_ids - connected):
        errors.append(f"node {orphan}: no edges (would float unexplained on the map)")

    return errors


def build():
    flows = [
        {
            "id": f["id"],
            "name": f["name"],
            "summary": f["summary"],
            **({"risk": f["risk"]} if "risk" in f else {}),
            "steps": [{"edge": e, "title": t, "detail": d} for e, t, d in f["steps"]],
        }
        for f in FLOWS
    ]

    return {
        "meta": {
            "title": "Homelab architecture",
            "subtitle": "Four hosts, 25 containers, one storage pool — and how they actually depend on each other.",
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "probedAt": PROBED_AT,
            "generator": "homelab/tools/architecture/build-arch-data.py",
            "liveEndpoint": "/api/architecture/live",
            "note": "Structure is curated and versioned here; live health is overlaid at "
                    "runtime from the newest homelab-doctor report.",
        },
        "zones": ZONES,
        "groups": GROUPS,
        "categories": CATEGORIES,
        "edgeKinds": EDGE_KINDS,
        "hosts": HOSTS,
        "nodes": NODES,
        "edges": EDGES,
        "flows": flows,
        "network": NETWORK,
        "storage": STORAGE,
        "automation": AUTOMATION,
        "agents": AGENTS,
        "observations": OBSERVATIONS,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="validate only, don't write")
    args = ap.parse_args()

    doc = build()
    errors = validate(doc)
    if errors:
        print(f"FAILED — {len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  · {e}", file=sys.stderr)
        return 1

    counts = (f"{len(doc['hosts'])} hosts · {len(doc['nodes'])} nodes · "
              f"{len(doc['edges'])} edges · {len(doc['flows'])} flows")
    if args.check:
        print(f"OK — {counts} (not written)")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    size = args.out.stat().st_size
    print(f"OK — {counts}\nwrote {args.out} ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
