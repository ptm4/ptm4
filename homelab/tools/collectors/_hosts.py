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
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Known homelab boxes — used when HL_HOSTS is unset. opti is the orchestrator; it still
# goes through SSH to itself so every host takes the same path.
DEFAULT_HOSTS = "opti=127.0.0.1,rpi=192.168.1.10,noblenumbat=192.168.1.6"

# Hosts whose absence is expected rather than a fault.
#
# android is a Termux phone: Doze parks its radio and it drops off the LAN for hours
# at a time, by design. Treating that as a finding produced three standing incidents
# that were true, useless, and permanent — and an alert you are trained to scroll past
# is worse than no alert, because it teaches you to scroll past the ones that matter.
#
# The host is still PROBED and still appears in every report with an honest
# "unreachable" summary. What is suppressed is only the FINDING, i.e. the claim that
# something is wrong. Peter's call, 2026-09-10: "ignore it, it's unreliable and a
# project for another day."
INTERMITTENT_HOSTS = {"android"}

DEFAULT_KEY = os.path.expanduser("~/.ssh/hl_agents")

# Non-interactive SSH: never prompt, fail fast, don't pollute known_hosts on a LAN of
# boxes that get reimaged. BatchMode makes a missing/!authorized key fail instead of hang.
# ServerAliveInterval/CountMax bound how long a call can hang on a host that went dark
# mid-session (network drop, host power-cycled) — 3 missed 5s keepalives (~15s) kills
# the connection instead of sitting on it for the full command timeout, which matters
# most for a multiplexed ControlMaster session that several calls share.
_SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=3",
]

# rc 255 + one of these substrings in stderr is a transient connect failure worth one
# retry with backoff — as opposed to an auth failure or "command not found", which
# retrying would only repeat.
_TRANSIENT_PATTERNS = ("connection timed out", "connection refused", "kex_exchange")
_RETRY_BACKOFF_S = 1.5

_CONTROL_DIR = None  # cached after first successful mkdir; None means "mux unavailable"


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


def _control_dir():
    """Private per-user dir to hold ControlMaster sockets. Cached after the first
    successful mkdir (or the first failure — we don't retry mkdir every call).

    Preference order: $XDG_RUNTIME_DIR (tmpfs, already 0700, cleaned on logout),
    /run/user/<uid> (same thing when the env var isn't exported, e.g. non-login
    systemd units — which is exactly how these collectors run), then a 0700 dir
    under the system temp dir as a last resort. Any of these staying reachable
    keeps multiplexing working; if all three fail we just run unmultiplexed.
    """
    global _CONTROL_DIR
    if _CONTROL_DIR is not None:
        return _CONTROL_DIR
    uid = os.getuid() if hasattr(os, "getuid") else None
    candidates = []
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        candidates.append(os.path.join(xdg, "hl-collectors-ssh"))
    if uid is not None:
        candidates.append(f"/run/user/{uid}/hl-collectors-ssh")
    candidates.append(os.path.join(tempfile.gettempdir(),
                                    f"hl-collectors-ssh-{uid if uid is not None else 'u'}"))
    for d in candidates:
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
            os.chmod(d, 0o700)  # exist_ok mkdir doesn't fix perms on a dir left by someone else
            _CONTROL_DIR = d
            return d
        except OSError:
            continue
    _CONTROL_DIR = False  # tried and failed — don't keep retrying mkdir every call
    return None


def _mux_opts():
    """ControlMaster options, or [] if no usable control dir (multiplexing just doesn't
    kick in — every call still works, one connection per call, same as before).

    ControlPath uses %C (ssh's own hash of host+port+user+the local user), not the
    hostname, specifically to stay short: AF_UNIX socket paths are capped around 108
    bytes, and a path built from a long user@host string is an easy way to blow that
    silently (ssh just refuses to multiplex, no loud error).
    """
    d = _control_dir()
    if not d:
        return []
    return [
        "-o", "ControlMaster=auto",
        "-o", "ControlPersist=60s",
        "-o", f"ControlPath={d}/cm-%C",
    ]


def _is_transient(stderr):
    s = (stderr or "").lower()
    return any(p in s for p in _TRANSIENT_PATTERNS)


def _ssh_cmd(host, use_mux):
    cmd = ["ssh", "-i", key_path(), *_SSH_OPTS]
    cmd += _mux_opts() if use_mux else ["-o", "ControlMaster=no", "-o", "ControlPath=none"]
    if host.port:
        cmd += ["-p", host.port]
    return cmd


def run_on(host, argv, timeout=30, input_text=None):
    """Run a command on `host` over SSH. Returns (stdout, returncode).

    `argv` is the command as a list (like subprocess); it is shell-quoted and run on the
    remote. On any SSH/transport failure returns ("", non-zero) — never raises — so a
    single unreachable host degrades to empty output rather than killing the report.

    Connections are multiplexed (ControlMaster=auto, see _mux_opts) so the many calls a
    collector makes against one host reuse a single TCP+auth handshake. Two safety nets
    on top of that:
      - rc 255 gets one immediate retry with the master bypassed entirely
        (ControlMaster=no/ControlPath=none), so a stale or broken control socket can
        never wedge every subsequent call to that host — worst case we fall back to
        one connection per call, same as before multiplexing existed.
      - if THAT retry also comes back rc 255 with a stderr that looks like a transient
        connect failure (timeout/refused/kex — as opposed to e.g. an auth failure),
        one more retry follows after a short backoff. A command that timed out
        (subprocess.TimeoutExpired) is never retried here — retrying a slow command
        could double its side effects and its wall-clock cost.
    """
    remote_cmd = " ".join(shlex.quote(a) for a in argv)

    def attempt(use_mux):
        cmd = _ssh_cmd(host, use_mux) + [host.destination, remote_cmd]
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            input=input_text if input_text is not None else None,
        )

    try:
        out = attempt(use_mux=True)
    except Exception:
        return "", 1
    if out.returncode != 255:
        return out.stdout, out.returncode

    try:
        out2 = attempt(use_mux=False)
    except Exception:
        return "", 1
    if out2.returncode == 255 and _is_transient(out2.stderr):
        time.sleep(_RETRY_BACKOFF_S)
        try:
            out3 = attempt(use_mux=False)
        except Exception:
            return "", 1
        return out3.stdout, out3.returncode
    return out2.stdout, out2.returncode


def probe(host, timeout=8):
    """Cheap reachability check: can we SSH in and run `true`? Returns (ok, detail)."""
    _, rc = run_on(host, ["true"], timeout=timeout)
    return (rc == 0, "ok" if rc == 0 else "ssh failed (host down or key not authorized)")


def collect_parallel(host_list, worker, max_workers=8):
    """Run `worker(host)` for every host in `host_list` concurrently, bounded by
    `max_workers`. Returns a list of (host, result, error) triples in the SAME ORDER
    as `host_list` — report order must stay deterministic no matter which host's SSH
    session happens to finish first.

    `error` is the exception `worker` raised, or None. A host's worker blowing up
    (bad parsing, an unexpected None, whatever) is isolated to that host's triple —
    it can never lose or reorder any other host's result, which a bare
    `ThreadPoolExecutor.map` (or a thread that re-raises) would not guarantee.

    This is purely a fan-out helper: it does not know about probing, findings, or
    report shape. Each collector's own per-host worker still returns whatever tuple
    that collector's main() expects (see homelab-doctor.py / hardware-report.py /
    network-report.py / software-inventory.py for the pattern).
    """
    n = len(host_list)
    results = [None] * n
    if n == 0:
        return results
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, n))) as ex:
        future_to_idx = {ex.submit(worker, h): i for i, h in enumerate(host_list)}
        for fut in as_completed(future_to_idx):
            i = future_to_idx[fut]
            try:
                results[i] = (host_list[i], fut.result(), None)
            except Exception as e:  # noqa: BLE001 - isolate one host's blow-up from the rest
                results[i] = (host_list[i], None, e)
    return results
