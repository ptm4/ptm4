#!/usr/bin/env python3
"""
hl-arch-agent.py — per-host architecture collector, installed and run ON each host
(opti, rpi, noblenumbat). Distinct from the homelab/tools/collectors/ runners: those
SSH out from opti to every host; this collects only its OWN host, locally, and pushes
the result — it never touches another machine.

WHY A DAEMON, NOT A ONESHOT + SEPARATE HTTP LISTENER
------------------------------------------------------
The obvious shape is "a systemd timer for the nightly run, plus something else that
answers Force Sync". But Force Sync has to reach a live process at any moment, not just
at 00:00 — so that second "something else" would need to run continuously anyway, and
would end up owning the collection logic to avoid duplicating it. Simpler to have one
long-running process (Type=simple) that both self-schedules the daily run and answers
/status and /sync on demand:

  - an internal loop sleeps until the next 00:00 (local time) and collects+pushes
  - a small stdlib HTTP server on HL_ARCH_AGENT_PORT (default 8787) exposes:
      GET  /status  -> last run time/result, next scheduled run, control capabilities
      GET  /apt-status -> homelab-autoupdate unit state + log tail + reboot-required
      POST /sync    -> collect + push right now, block and return the real result
                       (never a fire-and-forget "queued" with no feedback)
      POST /restart -> restart one named container (token always required)
      POST /update  -> pull the newest image for one compose service and recreate it
                       (token always required)
      POST /reboot  -> reboot this host (token always required; ZFS-DKMS guard on
                       pool hosts; responds FIRST, reboots ~2s later)
      POST /apt-upgrade     -> start homelab-autoupdate.service, return immediately;
                               progress is polled via GET /apt-status (token required)
      POST /service-restart -> restart one ALLOWED_UNITS systemd unit (token required)
      POST /wake    -> broadcast a WoL magic packet for a WAKE_MACS target (token
                       required; sent by this host on behalf of a powered-off one)
  - a state file records the last successful run date, so a host that was rebooted
    or the service restarted past 00:00 catches up on the next tick instead of
    silently waiting a full day (the manual equivalent of a timer's Persistent=true)

WHAT IT COLLECTS (all local, no SSH, no remote calls except the final push)
  os/cpu/mem/uptime, disks (df, real filesystems only), mounts (cifs/nfs/fuse only —
  the cross-host dependencies), network interfaces, listening ports (best-effort;
  needs root for process names), every `docker inspect`-able container (image, state,
  network_mode, published ports, mounts, compose labels), docker networks, and
  systemd timers. Collection itself is read-only; the only mutations this agent ever
  performs are the explicitly token-gated POSTs: /restart (v0.2.0) and /update
  (v0.3.0) on a single named container, and the host controls (v0.4.0) — /reboot,
  /apt-upgrade, /service-restart (allowlisted units only) and /wake — that back the
  dashboard's Cockpit tab.

WHAT IT DELIBERATELY DOES NOT COLLECT
  Human judgment: no "why it matters" text, no category/plane assignment, no flows.
  Those live in the curated overlay (homelab/tools/architecture/build-arch-data.py)
  and are merged server-side — see routes/architecture.js. This agent's fragment is
  facts only, so drift between "what's running" and "what's described" is visible
  as a diff, not silently overwritten.

PUSH TARGET
  POST <fragment JSON> to HL_ARCH_INGEST_URL (default the rpi webapp's ingest route)
  with an optional bearer token (HL_ARCH_AGENT_TOKEN), mirroring the existing
  agent-dispatcher's optional-token pattern. The webapp's cert is self-signed, so TLS
  verification is intentionally relaxed for this LAN-only call — see _post_fragment.

FAILURE POSTURE
  A collection error for one subsystem (docker not running, ss needing root, …) is
  recorded in the fragment's `errors` list and does not abort the run — partial data
  beats no data. A push failure is logged and retried on the next tick; it never
  crashes the daemon.

Install (systemd), per host:
    sudo cp hl-arch-agent.py /usr/local/bin/hl-arch-agent.py
    sudo chmod +x /usr/local/bin/hl-arch-agent.py
    sudo cp hl-arch-agent.service /etc/systemd/system/
    sudo cp hl-arch-agent.env.example /etc/hl-arch-agent.env   # then edit HOST + token
    sudo systemctl daemon-reload
    sudo systemctl enable --now hl-arch-agent

Env (set in /etc/hl-arch-agent.env, EnvironmentFile= in the unit):
  HL_ARCH_AGENT_HOST     this host's id as used in architecture data (opti|rpi|noblenumbat) — required
  HL_ARCH_INGEST_URL     default https://webapp.rpi.lan:8443/api/architecture/ingest
  HL_ARCH_AGENT_TOKEN    optional bearer token, must match the webapp's HL_ARCH_INGEST_TOKEN
  HL_ARCH_AGENT_PORT     default 8787
  HL_ARCH_AGENT_STATE    default /var/lib/hl-arch-agent/state.json
  HL_ARCH_RUN_HOUR       default 0 (local 00:00)

CLI:
  --dry-run   collect and print the fragment to stdout; do not push, do not serve HTTP.
              Run this FIRST on a new host and diff container names against `docker ps`
              before ever installing the service.
  --once      collect and push once, then exit (no HTTP server, no scheduling loop)
"""

import argparse
import glob
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_VERSION = "0.4.0"

HOST = os.environ.get("HL_ARCH_AGENT_HOST", "")
INGEST_URL = os.environ.get("HL_ARCH_INGEST_URL", "https://webapp.rpi.lan:8443/api/architecture/ingest")
TOKEN = os.environ.get("HL_ARCH_AGENT_TOKEN", "")
PORT = int(os.environ.get("HL_ARCH_AGENT_PORT", "8787"))
STATE_PATH = os.environ.get("HL_ARCH_AGENT_STATE", "/var/lib/hl-arch-agent/state.json")
RUN_HOUR = int(os.environ.get("HL_ARCH_RUN_HOUR", "0"))

# Only these carry cross-host meaning; a bind-mount of /proc or an overlay layer is noise.
_INTERESTING_FSTYPES = ("cifs", "nfs", "nfs4", "fuse", "fuse.")

# ── host-control config (v0.4.0) ───────────────────────────────────────────────
# Only these units may be restarted via POST /service-restart. Hardcoded rather than
# env-configured for the same reason routes/agents.js hardcodes AGENT_HOSTS: the
# topology is fixed and known, the list is versioned with the code, and it deploys
# atomically to all three hosts instead of drifting per-host in /etc.
ALLOWED_UNITS = {
    "opti": ["hl-agent-dispatcher.service", "hl-arch-agent.service",
             "smbd.service", "docker.service"],
    "rpi": ["hl-arch-agent.service"],
    # vpn-stack-heal is a oneshot: restarting it while inactive just runs it, so the
    # dashboard button doubles as "run the VPN heal check now".
    "noblenumbat": ["hl-arch-agent.service", "vpn-stack-heal.service"],
}

# POST /wake targets — hosts whose NIC has WoL armed (opti eno1: `Wake-on: g`,
# verified 2026-08-02). Any agent can broadcast for any target; the webapp asks an
# agent that is UP to wake one that is not. noblenumbat is absent deliberately:
# its USB NIC has no WoL support, which is also why there is no /shutdown endpoint.
WAKE_MACS = {"opti": "34:17:eb:d1:eb:f8"}


def _run(argv, timeout=10):
    """Run a local command. Never raises — returns ("", stderr) on any failure so one
    missing tool (e.g. no docker on a host) degrades that section, not the whole run."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return (p.stdout, "") if p.returncode == 0 else ("", p.stderr.strip() or f"exit {p.returncode}")
    except FileNotFoundError:
        return "", f"{argv[0]}: not installed"
    except Exception as exc:  # noqa: BLE001
        return "", str(exc)


def _section(fn, errors, key):
    """Run a collector function, catching everything so a single bad section can't
    abort the whole fragment. Failure is recorded under errors[key]."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        errors[key] = str(exc)
        return None


# ── collectors ─────────────────────────────────────────────────────────────────
def collect_os():
    info = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    info["pretty_name"] = line.split("=", 1)[1].strip().strip('"')
                    break
    except OSError:
        pass
    out, _ = _run(["uname", "-r"])
    info["kernel"] = out.strip()
    out, _ = _run(["uname", "-m"])
    info["arch"] = out.strip()
    return info


def collect_cpu():
    out, _ = _run(["lscpu"])
    model, cores = None, None
    for line in out.splitlines():
        if line.startswith("Model name:"):
            model = line.split(":", 1)[1].strip()
        elif line.startswith("CPU(s):") and cores is None:
            try:
                cores = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return {"model": model, "cores": cores}


def collect_mem():
    total = used = None
    try:
        with open("/proc/meminfo") as f:
            vals = {}
            for line in f:
                k, _, v = line.partition(":")
                vals[k.strip()] = int(v.strip().split()[0]) * 1024  # kB -> bytes
        total = vals.get("MemTotal")
        avail = vals.get("MemAvailable")
        if total is not None and avail is not None:
            used = total - avail
    except OSError:
        pass
    return {"total_bytes": total, "used_bytes": used}


def collect_uptime():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


# ── vitals (v0.2.0) ────────────────────────────────────────────────────────────
# Cheap sub-minute sample for the dashboard's live sparklines. Deliberately:
#   - /proc and /sys reads only, no subprocesses — this is polled every 30s per host,
#     so it must cost effectively nothing.
#   - CPU and network are exposed as RAW CUMULATIVE COUNTERS. The agent stays
#     stateless; the webapp diffs consecutive samples. That way a restarted agent
#     never emits a bogus spike, and two consumers can poll independently.
_NET_SKIP = ("lo", "veth", "docker", "br-", "virbr", "tun", "tap")


def _read_first_line(path):
    with open(path) as f:
        return f.readline().strip()


def collect_cpu_counters():
    """Aggregate jiffies from /proc/stat's first line: total and idle (idle+iowait)."""
    fields = _read_first_line("/proc/stat").split()
    if not fields or fields[0] != "cpu":
        return None
    vals = [int(x) for x in fields[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)   # idle + iowait
    return {"total": sum(vals), "idle": idle}


def collect_temp():
    """Highest plausible on-die reading. Sensor naming differs per host (rpi exposes
    thermal_zone0, opti acpitz/x86_pkg_temp via hwmon), so scan both trees and take the
    max in a sane range rather than guessing a path that won't exist elsewhere."""
    temps = []
    for pattern in ("/sys/class/thermal/thermal_zone*/temp",
                    "/sys/class/hwmon/hwmon*/temp*_input"):
        for path in glob.glob(pattern):
            try:
                milli = float(_read_first_line(path))
            except (OSError, ValueError):
                continue
            c = milli / 1000.0
            if 0 < c < 130:
                temps.append(c)
    return round(max(temps), 1) if temps else None


def collect_net_counters():
    """Per-interface cumulative rx/tx bytes, physical interfaces only."""
    out = {}
    try:
        with open("/proc/net/dev") as f:
            lines = f.readlines()[2:]
    except OSError:
        return out
    for line in lines:
        name, _, rest = line.partition(":")
        name = name.strip()
        if not name or name.startswith(_NET_SKIP):
            continue
        parts = rest.split()
        if len(parts) >= 9:
            out[name] = {"rx_bytes": int(parts[0]), "tx_bytes": int(parts[8])}
    return out


def collect_vitals():
    errors = {}
    loadavg = None
    try:
        loadavg = [float(x) for x in _read_first_line("/proc/loadavg").split()[:3]]
    except (OSError, ValueError, IndexError) as exc:
        errors["loadavg"] = str(exc)
    return {
        "host": HOST,
        "t": time.time(),
        "loadavg": loadavg,
        "cpu": _section(collect_cpu_counters, errors, "cpu"),
        "cores": (_section(collect_cpu_cores, errors, "cores") or None),
        "mem": _section(collect_mem, errors, "mem"),
        "temp_c": _section(collect_temp, errors, "temp"),
        "net": _section(collect_net_counters, errors, "net"),
        "uptime_s": collect_uptime(),
        "agent_version": AGENT_VERSION,
        "errors": errors,
    }


def collect_cpu_cores():
    """Core count without shelling out to lscpu (collect_cpu does that once a night;
    vitals runs every 30s)."""
    return os.cpu_count()


def collect_disks():
    out, _ = _run(["df", "-B1", "--output=source,fstype,size,used,avail,target"])
    disks = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 5)
        if len(parts) != 6:
            continue
        source, fstype, size, used, avail, target = parts
        if fstype in ("tmpfs", "devtmpfs", "overlay", "squashfs", "efivarfs"):
            continue
        disks.append({
            "source": source, "fstype": fstype, "mount": target,
            "size_bytes": int(size), "used_bytes": int(used), "avail_bytes": int(avail),
        })
    return disks


def collect_mounts():
    out, _ = _run(["findmnt", "-r", "-n", "-o", "SOURCE,TARGET,FSTYPE,OPTIONS"])
    mounts = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        source, target, fstype, options = parts
        if any(fstype.startswith(p) for p in _INTERESTING_FSTYPES):
            mounts.append({"source": source, "target": target, "fstype": fstype,
                           "options": options})
    return mounts


def collect_interfaces():
    out, _ = _run(["ip", "-o", "-4", "addr", "show"])
    ifaces = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] != "lo":
            ifaces.append({"name": parts[1], "addr": parts[3].split("/")[0]})
    return ifaces


def collect_listening():
    # -p (process names) needs root; the daemon runs as root via systemd, but degrade
    # to addr:port-only if it's ever run unprivileged (e.g. --dry-run as a normal user).
    out, err = _run(["ss", "-tulnp"])
    if not out:
        out, _ = _run(["ss", "-tuln"])
    listening = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        proto, local = parts[0], parts[4]
        if ":" not in local:
            continue
        addr, _, port = local.rpartition(":")
        proc = None
        if len(parts) > 6 and "users:" in parts[-1]:
            proc = parts[-1].split('"')[1] if '"' in parts[-1] else None
        try:
            port_i = int(port)
        except ValueError:
            continue
        listening.append({"proto": proto, "addr": addr, "port": port_i, "process": proc})
    # de-dupe (ss lists a listener once per address family sometimes)
    seen, out_list = set(), []
    for item in listening:
        key = (item["proto"], item["addr"], item["port"])
        if key in seen:
            continue
        seen.add(key)
        out_list.append(item)
    return sorted(out_list, key=lambda x: x["port"])


def collect_docker():
    ids_out, err = _run(["docker", "ps", "-aq"])
    if err and not ids_out:
        return None  # docker not installed / not running on this host — not an error
    ids = ids_out.split()
    containers = []
    if ids:
        inspect_out, ierr = _run(["docker", "inspect", *ids], timeout=20)
        if inspect_out:
            for c in json.loads(inspect_out):
                containers.append(_container_summary(c))
    nets_out, _ = _run(["docker", "network", "ls", "--format", "{{.Name}}\t{{.Driver}}"])
    networks = []
    for line in nets_out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            networks.append({"name": parts[0], "driver": parts[1]})
    return {"containers": containers, "networks": networks}


def _container_summary(c):
    name = (c.get("Name") or "").lstrip("/")
    state = c.get("State", {}) or {}
    hostcfg = c.get("HostConfig", {}) or {}
    netsettings = c.get("NetworkSettings", {}) or {}

    ports = []
    for cport, bindings in (netsettings.get("Ports") or {}).items():
        cport_num, _, proto = cport.partition("/")
        for b in (bindings or []):
            ports.append({
                "container_port": cport_num, "proto": proto or "tcp",
                "host_ip": b.get("HostIp"), "host_port": b.get("HostPort"),
            })

    mounts = [{"source": m.get("Source"), "destination": m.get("Destination"),
              "mode": m.get("Mode")} for m in (c.get("Mounts") or [])]

    labels = c.get("Config", {}).get("Labels") or {}
    compose_labels = {k: v for k, v in labels.items() if k.startswith("com.docker.compose.")}

    return {
        "name": name,
        "image": c.get("Config", {}).get("Image"),
        "state": state.get("Status"),
        "status_since": state.get("StartedAt"),
        "network_mode": hostcfg.get("NetworkMode"),
        "networks": sorted((netsettings.get("Networks") or {}).keys()),
        "ports": ports,
        "mounts": mounts,
        "compose_project": compose_labels.get("com.docker.compose.project"),
        "compose_service": compose_labels.get("com.docker.compose.service"),
    }


def collect_timers():
    out, _ = _run(["systemctl", "list-timers", "--all", "--no-legend", "--no-pager"])
    timers = []
    for line in out.splitlines():
        # Columns: NEXT LEFT LAST PASSED UNIT ACTIVATES — free-form spacing, so split on
        # the double-space gaps systemd pads with rather than assuming fixed columns.
        cols = [c for c in line.split("  ") if c.strip()]
        cols = [c.strip() for c in cols]
        if len(cols) < 3:
            continue
        unit = cols[-2] if len(cols) >= 2 else None
        timers.append({"raw": line.strip(), "unit": unit})
    return timers


def collect_fragment():
    errors = {}
    fragment = {
        "host": HOST,
        "hostname": socket.gethostname(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "agent_version": AGENT_VERSION,
        "os": _section(collect_os, errors, "os") or {},
        "cpu": _section(collect_cpu, errors, "cpu") or {},
        "mem": _section(collect_mem, errors, "mem") or {},
        "uptime_seconds": _section(collect_uptime, errors, "uptime"),
        "disks": _section(collect_disks, errors, "disks") or [],
        "mounts": _section(collect_mounts, errors, "mounts") or [],
        "interfaces": _section(collect_interfaces, errors, "interfaces") or [],
        "listening": _section(collect_listening, errors, "listening") or [],
        "docker": _section(collect_docker, errors, "docker"),
        "timers": _section(collect_timers, errors, "timers") or [],
        "errors": errors,
    }
    return fragment


# ── push ───────────────────────────────────────────────────────────────────────
def push_fragment(fragment, timeout=15):
    body = json.dumps(fragment).encode("utf-8")
    req = urllib.request.Request(INGEST_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    # The webapp's cert is self-signed and this call never leaves the LAN — verification
    # is intentionally relaxed here, the same trust boundary the rest of the homelab's
    # inter-host calls (dispatcher, `curl -k`) already operate under.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return True, resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return False, e.code, e.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)


# ── state ──────────────────────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


# ── run-once (shared by the scheduler tick and /sync) ───────────────────────────
_run_lock = threading.Lock()


def do_run():
    """Collect + push once. Serialized so a Force Sync landing mid-tick can't race the
    scheduled run — they'd both be doing the same work, so just wait your turn."""
    with _run_lock:
        fragment = collect_fragment()
        ok, status, detail = push_fragment(fragment)
        result = {
            "ran_at": fragment["collected_at"],
            "ok": ok,
            "http_status": status,
            "detail": detail[:500] if isinstance(detail, str) else detail,
            "containers": len((fragment.get("docker") or {}).get("containers") or []),
            "errors": fragment["errors"],
        }
        state = load_state()
        state["last_run"] = result
        if ok:
            state["last_success_date"] = datetime.now(timezone.utc).date().isoformat()
        save_state(state)
        return result


def next_run_at(now=None):
    now = now or datetime.now()
    target = now.replace(hour=RUN_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def scheduler_loop(stop_event):
    state = load_state()
    today = datetime.now().date().isoformat()
    # Persistent=true equivalent: if we haven't succeeded today and it's already past
    # the run hour (e.g. the service restarted after a reboot that missed 00:00),
    # catch up immediately instead of waiting for tomorrow's tick.
    if state.get("last_success_date") != today and datetime.now().hour >= RUN_HOUR:
        do_run()

    while not stop_event.is_set():
        target = next_run_at()
        wait_s = max(1.0, (target - datetime.now()).total_seconds())
        # Sleep in bounded slices so a stop request doesn't wait out the whole night.
        while wait_s > 0 and not stop_event.is_set():
            time.sleep(min(wait_s, 60))
            wait_s -= 60
        if not stop_event.is_set():
            do_run()


# ── container restart (v0.2.0) ─────────────────────────────────────────────────
def restart_container(name):
    """Restart one container by exact name. Returns (http_code, body).

    The name is validated by EXISTENCE — it must appear verbatim in `docker ps -a`
    output — and is then passed as its own argv element. It is never interpolated
    into a shell string, so there is no injection surface even if validation changed.
    Blocking, like /sync: the caller gets the real result, never "queued"."""
    if not isinstance(name, str) or not name.strip():
        return 400, {"ok": False, "error": "body.container is required"}
    name = name.strip()

    out, err = _run(["docker", "ps", "-a", "--format", "{{.Names}}"], timeout=15)
    if err:
        return 502, {"ok": False, "error": f"cannot list containers: {err}"}
    if name not in out.split():
        return 404, {"ok": False, "error": f"no container named {name!r} on {HOST}"}

    started = time.time()
    _, err = _run(["docker", "restart", name], timeout=45)
    took_ms = int((time.time() - started) * 1000)
    if err:
        return 502, {"ok": False, "container": name, "host": HOST,
                     "took_ms": took_ms, "error": err}
    return 200, {"ok": True, "container": name, "host": HOST, "took_ms": took_ms}


# ── container image update (v0.3.0) ────────────────────────────────────────────
# Pull the current tag for one compose-managed container and recreate ONLY that
# service. Same trust posture as restart_container: the name is validated by
# existence and every value is its own argv element, never a shell string.
#
# The compose invocation is reconstructed from the container's own labels rather
# than from any path this agent knows: that is what makes one code path work for
# rpi's single-file project at /srv/docker/compose and noblenumbat's two chained
# yams files, without either being hardcoded here.
_COMPOSE_LBL = "com.docker.compose."


def update_container(name):
    """Pull + recreate one container by exact name. Returns (http_code, body).

    Deliberately narrow: `up -d --no-deps <service>` touches the named service and
    nothing else, so recreating gluetun can never take its five netns dependents
    with it as collateral. Blocking, like /restart — the caller gets the real
    result, including `changed: false` when the pull found nothing new."""
    if not isinstance(name, str) or not name.strip():
        return 400, {"ok": False, "error": "body.container is required"}
    name = name.strip()

    out, err = _run(["docker", "ps", "-a", "--format", "{{.Names}}"], timeout=15)
    if err:
        return 502, {"ok": False, "error": f"cannot list containers: {err}"}
    if name not in out.split():
        return 404, {"ok": False, "error": f"no container named {name!r} on {HOST}"}

    out, err = _run(["docker", "inspect", name], timeout=15)
    if err or not out.strip():
        return 502, {"ok": False, "error": f"docker inspect failed: {err or 'empty output'}"}
    try:
        info = json.loads(out)[0]
    except (ValueError, IndexError) as exc:
        return 502, {"ok": False, "error": f"unreadable docker inspect output: {exc}"}

    labels = (info.get("Config") or {}).get("Labels") or {}
    workdir = labels.get(_COMPOSE_LBL + "project.working_dir")
    config_files = labels.get(_COMPOSE_LBL + "project.config_files") or ""
    service = labels.get(_COMPOSE_LBL + "service")
    image_ref = (info.get("Config") or {}).get("Image") or ""
    before_sha = info.get("Image") or ""

    if not (workdir and service):
        return 409, {"ok": False, "error": f"{name!r} is not compose-managed on {HOST} "
                     f"(no compose labels) — update it by hand"}

    compose = ["docker", "compose", "--project-directory", workdir]
    for f in [p for p in config_files.split(",") if p.strip()]:
        compose += ["-f", f.strip()]
    # .env in the project directory (COMPOSE_FILE chaining, VPN creds, RPI_IP) is
    # auto-loaded by compose from --project-directory, so it needs no handling here.

    # Services with a build: context (notes-api, the discord-* bots) are rebuilt by the
    # deploy workflow, never pulled — a `compose pull` on one silently no-ops, which
    # would report a successful "update" that updated nothing. Ask compose itself
    # rather than inferring from the image: locally built images DO carry a local
    # RepoDigest (compose-discord-weather@sha256:…), so digests can't tell them apart.
    out, err = _run([*compose, "config", "--format", "json"], timeout=30)
    if err:
        return 502, {"ok": False, "error": f"cannot read compose config for {name}: {err[:300]}"}
    try:
        svc_def = (json.loads(out).get("services") or {}).get(service) or {}
    except ValueError as exc:
        return 502, {"ok": False, "error": f"unreadable compose config: {exc}"}
    if svc_def.get("build"):
        return 409, {"ok": False, "error": f"{name!r} is a build: service — its image is "
                     f"built by the deploy workflow, so there is nothing to pull"}

    # Preflight every host-side bind source before touching anything. A stale CIFS
    # handle lets the RUNNING container coast but makes the recreate fail or hang
    # half-down — that is exactly the outage noblenumbat-deploy.yml's preflight was
    # added for, generalized to whatever this container actually mounts. `timeout`
    # bounds a D-state hang to a few seconds and a clean abort.
    bind_sources = sorted({m.get("Source") for m in (info.get("Mounts") or [])
                           if m.get("Type") == "bind" and m.get("Source")})
    for src in bind_sources:
        _, perr = _run(["timeout", "5", "ls", src], timeout=10)
        if perr:
            return 503, {"ok": False, "stage": "preflight", "container": name,
                         "host": HOST, "mount": src,
                         "error": f"bind source {src} is not traversable (stale or hung "
                         f"CIFS mount?) — container left untouched. On {HOST}: "
                         f"sudo umount {src} && ls {src} to re-trigger the automount"}

    started = time.time()
    _, err = _run([*compose, "pull", service], timeout=140)
    if err:
        return 502, {"ok": False, "stage": "pull", "container": name, "host": HOST,
                     "took_ms": int((time.time() - started) * 1000),
                     "error": f"image pull failed, container untouched: {err[:400]}"}

    _, err = _run([*compose, "up", "-d", "--no-deps", service], timeout=45)
    took_ms = int((time.time() - started) * 1000)
    if err:
        return 502, {"ok": False, "stage": "up", "container": name, "host": HOST,
                     "took_ms": took_ms,
                     "error": f"recreate failed after a successful pull — {name} may be "
                     f"down, check `docker ps` on {HOST}: {err[:400]}"}

    after_sha = ""
    out, err = _run(["docker", "inspect", name, "--format", "{{.Image}}"], timeout=15)
    if not err:
        after_sha = out.strip()
    return 200, {"ok": True, "container": name, "service": service, "host": HOST,
                 "image": image_ref, "took_ms": took_ms,
                 "changed": bool(after_sha) and after_sha != before_sha,
                 "before": before_sha[7:19], "after": (after_sha or "?")[7:19]}


# ── host controls (v0.4.0) ─────────────────────────────────────────────────────
# These back the dashboard's Cockpit tab. Same shape as the container mutators:
# fn(body) -> (http_code, dict), every command via _run argv (never a shell string),
# token always required. The one deliberate difference: actions that kill this very
# process (/reboot, self-restart) RESPOND FIRST and act ~2s later from a detached
# thread — a synchronous `systemctl reboot` would die mid-response and the caller
# could never tell "rebooting" from "crashed".
_APT_UNIT = "homelab-autoupdate.service"
_APT_LOG = "/var/log/homelab-autoupdate.log"


def _unit_prop(unit, prop):
    """One systemd property via `systemctl show` — unlike is-active, exit code is 0
    regardless of state, which matters because _run maps nonzero exits to ("", err)."""
    out, err = _run(["systemctl", "show", unit, "-p", prop, "--value"], timeout=15)
    return (out.strip(), err)


def _detached(action_argv, delay=2.0):
    """Run a command from a daemon thread after the response has gone out."""
    def _later():
        time.sleep(delay)
        subprocess.run(action_argv)
    threading.Thread(target=_later, daemon=True).start()


def _zfs_reboot_guard():
    """Refuse to reboot into a kernel the zfs DKMS module did not build for — the
    pool (and \\opti\\red for four hosts) would not come back. Ported from
    homelab-autoreboot.sh; presence-based, so hosts without zpool skip through.
    Returns None when safe, else the human-readable abort reason."""
    _, err = _run(["zpool", "list", "-H"], timeout=15)
    if err:
        return None  # no zfs on this host — nothing to guard
    try:
        kernels = os.listdir("/lib/modules")
    except OSError:
        return None
    if not kernels:
        return None
    # all-int sort key (a mixed str/int key can raise TypeError on uneven names)
    newest = max(kernels, key=lambda s: [int(x) for x in re.findall(r"\d+", s)])
    if os.path.exists(f"/lib/modules/{newest}/updates/dkms/zfs.ko"):
        return None
    _, merr = _run(["modinfo", "-k", newest, "zfs"], timeout=15)
    if not merr:
        return None
    return f"no zfs module for kernel {newest} — fix DKMS before rebooting {HOST}"


def do_reboot(body):
    """Reboot this host. The request must name the host it thinks it is rebooting —
    a cheap guard against a proxy/route mixup sending the reboot somewhere else."""
    want = body.get("host")
    if want != HOST:
        return 400, {"ok": False, "error": f"host mismatch: this agent is {HOST!r}, "
                     f"request said {want!r}"}
    guard = _zfs_reboot_guard()
    if guard:
        return 409, {"ok": False, "stage": "zfs-guard", "host": HOST, "error": guard}
    _detached(["systemctl", "reboot"])
    return 200, {
        "ok": True, "host": HOST,
        "rebooting_at": (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(),
        "uptime_s": collect_uptime(),
        "reboot_required": os.path.exists("/var/run/reboot-required"),
    }


def apt_upgrade(body):
    """Kick homelab-autoupdate.service and return immediately. Async on purpose:
    an apt upgrade can outlive every timeout in the nginx/backend/browser ladder,
    so the caller polls GET /apt-status instead of holding a request open. Reuses
    the nightly unit rather than running apt directly — same code path that already
    works unattended at 02:00 every day."""
    del body  # no parameters; signature matches the mutator shape
    loaded, err = _unit_prop(_APT_UNIT, "LoadState")
    if err or loaded != "loaded":
        return 404, {"ok": False, "error": f"{_APT_UNIT} not installed on {HOST}"}
    active, _ = _unit_prop(_APT_UNIT, "ActiveState")
    if active in ("active", "activating", "reloading"):
        return 200, {"ok": True, "host": HOST, "unit": _APT_UNIT, "already_running": True}
    _, err = _run(["systemctl", "start", "--no-block", _APT_UNIT], timeout=15)
    if err:
        return 502, {"ok": False, "stage": "start", "host": HOST, "unit": _APT_UNIT,
                     "error": err[:400]}
    return 202, {"ok": True, "host": HOST, "unit": _APT_UNIT,
                 "started_at": datetime.now(timezone.utc).isoformat()}


def apt_status():
    """Progress/result of the last (or current) homelab-autoupdate run. Read-only
    and unauthenticated like /status and /vitals — the same package facts are
    already published to the dashboard by software-inventory."""
    props = {}
    out, _ = _run(["systemctl", "show", _APT_UNIT,
                   "-p", "ActiveState,SubState,Result,ExecMainStartTimestamp,"
                   "ExecMainExitTimestamp,ExecMainStatus"], timeout=15)
    for line in out.splitlines():
        k, _, v = line.partition("=")
        props[k] = v.strip()
    active = props.get("ActiveState", "unknown")
    reboot_pkgs = ""
    try:
        with open("/var/run/reboot-required.pkgs") as f:
            reboot_pkgs = ", ".join(sorted(set(f.read().split())))
    except OSError:
        pass
    log_tail = []
    try:
        with open(_APT_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192))
            log_tail = f.read().decode("utf-8", "replace").splitlines()[-40:]
    except OSError:
        pass
    return 200, {
        "host": HOST, "unit": _APT_UNIT,
        "active": active, "sub": props.get("SubState"),
        "running": active in ("active", "activating"),
        "result": props.get("Result"),
        "exit_status": props.get("ExecMainStatus"),
        "started_at": props.get("ExecMainStartTimestamp") or None,
        "finished_at": props.get("ExecMainExitTimestamp") or None,
        "reboot_required": os.path.exists("/var/run/reboot-required"),
        "reboot_pkgs": reboot_pkgs,
        "log_tail": log_tail,
    }


def service_restart(body):
    """Restart one systemd unit — allowlist FIRST, so this endpoint never probes
    (or even acknowledges the existence of) arbitrary units."""
    unit = body.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        return 400, {"ok": False, "error": "body.unit is required"}
    unit = unit.strip()
    allowed = ALLOWED_UNITS.get(HOST, [])
    if unit not in allowed:
        return 403, {"ok": False, "error": f"unit {unit!r} is not in the allowlist "
                     f"for {HOST}", "allowed": allowed}
    loaded, err = _unit_prop(unit, "LoadState")
    if err or loaded != "loaded":
        return 404, {"ok": False, "error": f"unit {unit!r} not found on {HOST}"}
    before, _ = _unit_prop(unit, "ActiveState")

    if unit == "hl-arch-agent.service":
        _detached(["systemctl", "restart", unit])
        return 200, {"ok": True, "host": HOST, "unit": unit, "before": before,
                     "self_restart": True,
                     "note": "agent restarting itself in ~2s — poll /status for the "
                             "new process"}

    started = time.time()
    # 120s: docker.service on opti restarts every container it runs — the slowest
    # allowlisted case. The webapp proxy allows 160s, nginx 240s (ladder must nest).
    _, err = _run(["systemctl", "restart", unit], timeout=120)
    took_ms = int((time.time() - started) * 1000)
    if err:
        return 502, {"ok": False, "stage": "restart", "host": HOST, "unit": unit,
                     "before": before, "took_ms": took_ms, "error": err[:400]}
    after, _ = _unit_prop(unit, "ActiveState")
    # A oneshot (vpn-stack-heal) lands back on "inactive" after a successful run —
    # that IS success; the caller reads ok, not the after state, for the verdict.
    return 200, {"ok": True, "host": HOST, "unit": unit, "before": before,
                 "after": after, "took_ms": took_ms}


def wake_target(body):
    """Broadcast a WoL magic packet for a known target. Runs on a host that is UP
    (the target is off — its own agent obviously can't help)."""
    target = body.get("target")
    if not isinstance(target, str) or not target.strip():
        return 400, {"ok": False, "error": "body.target is required"}
    target = target.strip()
    mac = WAKE_MACS.get(target)
    if not mac:
        return 404, {"ok": False, "error": f"no wake target {target!r} on this agent",
                     "targets": sorted(WAKE_MACS)}
    try:
        mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
        if len(mac_bytes) != 6:
            raise ValueError(f"decodes to {len(mac_bytes)} bytes, want 6")
    except ValueError as exc:
        return 500, {"ok": False, "error": f"bad MAC configured for {target!r}: {exc}"}
    packet = b"\xff" * 6 + mac_bytes * 16
    sent = 0
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # Global + subnet-directed broadcast, 3x each — WoL is fire-and-forget
            # UDP with no ack, so redundancy is the only delivery guarantee there is.
            for addr in ("255.255.255.255", "192.168.1.255"):
                for _ in range(3):
                    s.sendto(packet, (addr, 9))
                    sent += 1
                    time.sleep(0.1)
    except OSError as exc:
        if not sent:
            return 502, {"ok": False, "error": f"could not send magic packet: {exc}"}
    return 200, {"ok": True, "host": HOST, "target": target, "mac": mac,
                 "packets": sent}


# ── local HTTP endpoint ──────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        if not TOKEN:
            return True
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "/status":
            state = load_state()
            self._json(200, {
                "host": HOST, "agent_version": AGENT_VERSION,
                "last_run": state.get("last_run"),
                "next_scheduled": next_run_at().isoformat(),
                # Control capabilities for the Cockpit tab — their presence is also
                # how the webapp detects a pre-0.4.0 agent (missing -> old).
                "allowed_units": ALLOWED_UNITS.get(HOST, []),
                "wake_targets": sorted(WAKE_MACS),
            })
            return
        if path == "/vitals":
            # Unauthenticated like /status: read-only counters, LAN-only listener.
            self._json(200, collect_vitals())
            return
        if path == "/apt-status":
            # Unauthenticated: read-only, and software-inventory already publishes
            # the same package facts to the dashboard.
            self._json(*apt_status())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.rstrip("/")
        if path == "/sync":
            if not self._authorized():
                self._json(401, {"error": "unauthorized"})
                return
            result = do_run()
            self._json(200 if result["ok"] else 502, result)
            return

        # Unlike /sync, these ALWAYS require a token — a tokenless agent must never
        # expose container or host mutation to anything that can reach port 8787.
        mutators = {
            "/restart": lambda b: restart_container(b.get("container")),
            "/update": lambda b: update_container(b.get("container")),
            "/reboot": do_reboot,
            "/apt-upgrade": apt_upgrade,
            "/service-restart": service_restart,
            "/wake": wake_target,
        }
        if path in mutators:
            if not TOKEN:
                self._json(403, {"error": f"{path.lstrip('/')} requires "
                                          "HL_ARCH_AGENT_TOKEN to be set"})
                return
            if not self._authorized():
                self._json(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or "{}")
            except (ValueError, OSError) as exc:
                self._json(400, {"error": f"bad request body: {exc}"})
                return
            if not isinstance(body, dict):
                self._json(400, {"error": "body must be a JSON object"})
                return
            self._json(*mutators[path](body))
            return

        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{datetime.now().isoformat(timespec='seconds')}] "
                         f"{self.address_string()} {fmt % args}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="collect and print the fragment; never push, never serve HTTP")
    ap.add_argument("--once", action="store_true",
                    help="collect and push once, then exit")
    args = ap.parse_args()

    if not HOST and not args.dry_run:
        print("HL_ARCH_AGENT_HOST is not set — refusing to push an unlabeled fragment. "
              "Set it in /etc/hl-arch-agent.env (opti|rpi|noblenumbat).", file=sys.stderr)
        return 1

    if args.dry_run:
        fragment = collect_fragment()
        json.dump(fragment, sys.stdout, indent=2)
        sys.stdout.write("\n")
        if fragment["errors"]:
            print(f"\n(non-fatal collection errors: {fragment['errors']})", file=sys.stderr)
        return 0

    if args.once:
        result = do_run()
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    stop_event = threading.Event()
    sched = threading.Thread(target=scheduler_loop, args=(stop_event,), daemon=True)
    sched.start()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"hl-arch-agent {AGENT_VERSION} for host={HOST!r} listening on :{PORT} "
         f"(next scheduled run {next_run_at().isoformat()})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
