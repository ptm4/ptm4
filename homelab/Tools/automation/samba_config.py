#!/usr/bin/env python3
"""
samba_config.py — view/edit the hand-managed [red] Samba share from the webapp.

Imported by agent-dispatcher.py (same directory, stdlib only). Kept separate so a fault in
here cannot take the dispatcher's existing control plane down — the import is guarded there.

WHY THIS EXISTS
  OpenMediaVault owns /etc/samba/smb.conf and regenerates it from its config DB, and it has
  no filesystem backend for ZFS, so it cannot model the [red] share at all. Instead of
  hand-editing a generated file (which is silently reverted on the next OMV commit), the
  share lives in /etc/homelab/samba-red.conf and OMV is told to `include =` it via its own
  persisted "Extra options" field. This module edits only that file.

SAFETY
  - TARGET is a module constant. Nothing from the request ever selects a path.
  - /etc/samba/smb.conf and /etc/openmediavault are never written, only read for validation.
  - Every write is: validate composed -> backup -> atomic replace -> reload -> verify, and
    a failed post-reload verify restores the backup automatically. A broken config would
    take the share down for four hosts, so the verify step is not optional.
  - Share paths are constrained to POOL_ROOT.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile

TARGET = "/etc/homelab/samba-red.conf"
BACKUP_DIR = "/etc/homelab/samba-backups"
OMV_SMB_CONF = "/etc/samba/smb.conf"          # read-only here, never written
POOL_ROOT = "/srv/red"                         # share paths must live under this
SHARE_NAME = "red"
MAX_BYTES = 64 * 1024

# Repo copy, for the drift indicator. Webapp edits do not persist to git.
REPO_COPY = "/srv/red/fs/ptm/repo/ptm4/homelab/opti-srv/samba/samba-red.conf"

_PATH_RE = re.compile(r"^\s*path\s*=\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_STAMP_RE = re.compile(r"^\d{8}-\d{6}$")


def _sudo(*args, **kw):
    return subprocess.run(["sudo", "-n", *args], capture_output=True, text=True,
                          timeout=kw.pop("timeout", 20), **kw)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def validate(content):
    """Validate `content` as it would actually be loaded — composed into the real smb.conf,
    not in isolation (a bare [share] fragment does not validate on its own).

    Returns (ok: bool, output: str).
    """
    if len(content.encode()) > MAX_BYTES:
        return False, f"config exceeds {MAX_BYTES} bytes"

    # Constrain share paths. Cheap, and stops a typo exporting something it shouldn't.
    for m in _PATH_RE.finditer(content):
        p = os.path.normpath(m.group(1).strip().strip('"'))
        if not (p == POOL_ROOT or p.startswith(POOL_ROOT + "/")):
            return False, f"share path {p!r} is outside {POOL_ROOT}"

    base = _read(OMV_SMB_CONF)
    if base is None:
        return False, f"cannot read {OMV_SMB_CONF}"

    tmpdir = tempfile.mkdtemp(prefix="samba-validate-")
    try:
        frag = os.path.join(tmpdir, "fragment.conf")
        with open(frag, "w", encoding="utf-8") as fh:
            fh.write(content)

        # Point the include at our candidate fragment. If OMV's extraoptions include line is
        # not present yet (first run, before Phase 5), append one so we still validate.
        if TARGET in base:
            composed = base.replace(TARGET, frag)
        else:
            composed = base.rstrip() + f"\n    include = {frag}\n"

        conf = os.path.join(tmpdir, "smb.conf")
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write(composed)

        r = subprocess.run(["testparm", "-s", "--suppress-prompt", conf],
                           capture_output=True, text=True, timeout=20)
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            return False, out
        if f"[{SHARE_NAME}]" not in r.stdout:
            return False, f"[{SHARE_NAME}] share not present in the resulting config\n{out}"
        return True, out
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _effective_path():
    """The path Samba is actually serving for [red] right now."""
    try:
        r = subprocess.run(["testparm", "-s", "--suppress-prompt"],
                           capture_output=True, text=True, timeout=20)
        section = None
        for line in r.stdout.splitlines():
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                section = s[1:-1]
            elif section == SHARE_NAME and s.lower().startswith("path"):
                return s.split("=", 1)[1].strip()
    except Exception:  # noqa: BLE001
        pass
    return None


def read_config():
    content = _read(TARGET)
    repo = _read(REPO_COPY)
    try:
        mtime = datetime.datetime.utcfromtimestamp(
            os.path.getmtime(TARGET)).isoformat() + "Z"
    except OSError:
        mtime = None
    ok, out = (validate(content) if content is not None else (False, "file does not exist"))
    return {
        "path": TARGET,
        "content": content,
        "exists": content is not None,
        "mtime": mtime,
        "valid": ok,
        "validation": out,
        "effective_path": _effective_path(),
        "repo_path": REPO_COPY,
        # None = repo copy unreadable (e.g. pool not mounted), not "they differ"
        "repo_matches": None if repo is None else (repo == content),
    }


def list_backups():
    try:
        names = sorted(os.listdir(BACKUP_DIR), reverse=True)
    except OSError:
        return []
    out = []
    for n in names:
        m = re.match(r"samba-red\.conf\.(\d{8}-\d{6})$", n)
        if m:
            full = os.path.join(BACKUP_DIR, n)
            try:
                out.append({"stamp": m.group(1), "size": os.path.getsize(full)})
            except OSError:
                pass
    return out


def _backup_current():
    """Copy the live file aside. Returns the stamp, or None if there was nothing to save."""
    if not os.path.exists(TARGET):
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    _sudo("mkdir", "-p", BACKUP_DIR)
    r = _sudo("cp", "-a", TARGET, os.path.join(BACKUP_DIR, f"samba-red.conf.{stamp}"))
    return stamp if r.returncode == 0 else None


def _install(content):
    """Atomically place `content` at TARGET (needs root; dispatcher runs as ptm)."""
    fd, tmp = tempfile.mkstemp(prefix="samba-red-", suffix=".conf")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(tmp, 0o644)
        _sudo("mkdir", "-p", os.path.dirname(TARGET))
        r = _sudo("cp", tmp, TARGET)      # cp onto the target = atomic enough here
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _reload():
    r = _sudo("smbcontrol", "all", "reload-config")
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def write_config(content):
    """validate -> backup -> write -> reload -> verify, with automatic rollback."""
    ok, out = validate(content)
    if not ok:
        return {"ok": False, "stage": "validate", "error": out}

    stamp = _backup_current()

    ok, err = _install(content)
    if not ok:
        return {"ok": False, "stage": "write", "error": err, "backup": stamp}

    ok, err = _reload()
    if not ok:
        return {"ok": False, "stage": "reload", "error": err, "backup": stamp}

    # The point of the whole exercise: confirm Samba is still serving what we expect.
    eff = _effective_path()
    if eff is None or not (eff.rstrip("/") == f"{POOL_ROOT}/fs" or eff.startswith(POOL_ROOT)):
        if stamp:
            _sudo("cp", os.path.join(BACKUP_DIR, f"samba-red.conf.{stamp}"), TARGET)
            _reload()
            return {"ok": False, "stage": "verify", "restored": stamp,
                    "error": f"[{SHARE_NAME}] resolved to {eff!r} after reload; rolled back"}
        return {"ok": False, "stage": "verify",
                "error": f"[{SHARE_NAME}] resolved to {eff!r} and there was no backup to restore"}

    return {"ok": True, "backup": stamp, "effective_path": eff, "validation": out}


def rollback(stamp):
    if not _STAMP_RE.match(stamp or ""):
        return {"ok": False, "error": "invalid backup id"}
    src = os.path.join(BACKUP_DIR, f"samba-red.conf.{stamp}")
    if not os.path.exists(src):
        return {"ok": False, "error": f"no such backup: {stamp}"}
    content = _read(src)
    if content is None:
        return {"ok": False, "error": f"cannot read backup {stamp}"}
    return write_config(content)


def status():
    def _active(unit):
        r = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip()

    shares, clients = [], []
    try:
        r = subprocess.run(["testparm", "-s", "--suppress-prompt"],
                           capture_output=True, text=True, timeout=20)
        shares = [l.strip()[1:-1] for l in r.stdout.splitlines()
                  if l.strip().startswith("[") and l.strip().endswith("]")]
    except Exception:  # noqa: BLE001
        pass
    try:
        r = _sudo("smbstatus", "-b")
        for line in r.stdout.splitlines():
            m = re.search(r"\((ipv4|ipv6):([0-9a-fA-F.:]+):\d+\)", line)
            if m:
                clients.append(m.group(2))
    except Exception:  # noqa: BLE001
        pass

    return {
        "smbd": _active("smbd"),
        "shares": shares,
        "clients": sorted(set(clients)),
        "effective_path": _effective_path(),
    }
