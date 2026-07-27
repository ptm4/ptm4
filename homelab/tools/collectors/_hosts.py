#!/usr/bin/env python3
"""
_hosts.py — multi-host SSH fan-out for the homelab collectors.

The collectors (hardware/software/network/doctor) gather *intrinsic* per-box data
(lscpu, df, ss, smartctl, dpkg, docker, /proc, /sys). Those commands must run ON the
box they describe, so this module runs every host's commands over SSH — including the
orchestrator's own host (localhost goes through SSH too, for one uniform code path and
so reachability/DNS/port checks reflect each host's real vantage point).

opti is the scheduled orchestrator (GitHub Actions runner + dispatcher), but nothing
here is opti-specific: point HL_HOSTS/HL_SSH_KEY at any boxes and run it from anywhere
(e.g. a workstation) and it behaves identically.

Config (env, set once in /etc/hl-agents.env):
  HL_HOSTS    comma list of name=target, e.g.
              "opti=127.0.0.1,rpi=192.168.1.10,noblenumbat=192.168.1.6"
              (target may be host, user@host, or host:port). Defaults to the three
              known homelab boxes if unset.
  HL_SSH_KEY  path to the private key authorized on every target (and on the
              orchestrator itself, since localhost goes through SSH). Default
              ~/.ssh/hl_agents.
  HL_SSH_USER default login user when a target omits "user@" (default: current user).

Fail-loud contract: if the key file is missing we raise MissingKeyError *once* so the
collector can turn it into a single clear finding instead of every host silently
failing. Per-host SSH failures (host down, key not authorized there) are returned as
unreachable hosts, not exceptions — one bad box never sinks the whole report.
"""

import os
import shlex
import subprocess

# Known homelab boxes — used when HL_HOSTS is unset. opti is the orchestrator; it still
# goes through SSH to itself so every host takes the same path.
DEFAULT_HOSTS = "opti=127.0.0.1,rpi=192.168.1.10,noblenumbat=192.168.1.6"
DEFAULT_KEY = os.path.expanduser("~/.ssh/hl_agents")

# Non-interactive SSH: never prompt, fail fast, don't pollute known_hosts on a LAN of
# boxes that get reimaged. BatchMode makes a missing/!authorized key fail instead of hang.
_SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
]


class MissingKeyError(Exception):
    """Raised once when HL_SSH_KEY does not exist, so the collector can report it."""


class Host:
    """One target. `name` is the friendly label shown in reports; `target` is the SSH
    destination (host / user@host / host:port)."""

    def __init__(self, name, target):
        self.name = name
        user, hostport = (target.split("@", 1) if "@" in target else (None, target))
        host, port = (hostport.rsplit(":", 1) if ":" in hostport else (hostport, None))
        self.host = host
        self.port = port if (port and port.isdigit()) else None
        self.user = user or os.environ.get("HL_SSH_USER") or os.environ.get("USER")

    @property
    def destination(self):
        return f"{self.user}@{self.host}" if self.user else self.host

    def __repr__(self):
        return f"<Host {self.name}={self.destination}>"


def hosts():
    """Parse HL_HOSTS into a list of Host. Order is preserved (report order)."""
    spec = os.environ.get("HL_HOSTS", DEFAULT_HOSTS)
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, target = part.partition("=")
        name, target = name.strip(), target.strip()
        if not target:  # bare "rpi" → name doubles as target
            target = name
        out.append(Host(name, target))
    return out


def key_path():
    return os.environ.get("HL_SSH_KEY", DEFAULT_KEY)


def ensure_key():
    """Raise MissingKeyError if the configured key is absent. Call once per run."""
    kp = key_path()
    if not os.path.isfile(kp):
        raise MissingKeyError(
            f"SSH key not found at {kp} — set HL_SSH_KEY or create the key and "
            f"authorize it on every host in HL_HOSTS (and on this host, since "
            f"localhost is reached over SSH)."
        )


def run_on(host, argv, timeout=30, input_text=None):
    """Run a command on `host` over SSH. Returns (stdout, returncode).

    `argv` is the command as a list (like subprocess); it is shell-quoted and run on the
    remote. On any SSH/transport failure returns ("", non-zero) — never raises — so a
    single unreachable host degrades to empty output rather than killing the report.
    """
    remote_cmd = " ".join(shlex.quote(a) for a in argv)
    cmd = ["ssh", "-i", key_path(), *_SSH_OPTS]
    if host.port:
        cmd += ["-p", host.port]
    cmd += [host.destination, remote_cmd]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            input=input_text if input_text is not None else None,
        )
        return out.stdout, out.returncode
    except Exception:
        return "", 1


def probe(host, timeout=8):
    """Cheap reachability check: can we SSH in and run `true`? Returns (ok, detail)."""
    _, rc = run_on(host, ["true"], timeout=timeout)
    return (rc == 0, "ok" if rc == 0 else "ssh failed (host down or key not authorized)")
