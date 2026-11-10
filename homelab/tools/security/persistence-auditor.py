#!/usr/bin/env python3
"""
persistence-auditor.py — Linux persistence / autostart integrity auditor.

Enumerates the common places Linux persistence hides — cron, systemd timers &
enabled units, desktop autostart, and shell rc / profile files — and on first run
saves a baseline. On later runs it diffs against the baseline and flags new, changed,
or removed entries (the Linux analogue of the Windows registry-persist + scheduled-task
auditors).

Two things keep the output to what actually needs a human (audit A-1, 2026-11-09 —
before this, 434 of 806 warnings in a month were units CI itself had installed):

  * CI-deployed units are accepted automatically. opti-deploy.yml writes
    /etc/homelab/deployed-units.sha256 (root-owned) with the sha256 of every unit file
    it installed, taken from the git checkout. A `systemd-unitfile` entry is accepted
    only when its path AND full hash match; an enabled unit / timer only when its unit
    file (or its `name@.timer` template) matches. A unit hand-edited after a deploy,
    any unit not in the manifest, and every cron / rc / autostart entry are flagged
    exactly as before. A manifest anyone but root can write is ignored.
  * The summary leads with what changed since the PREVIOUS run. Unaccepted drift is
    critical (with the false positives gone, it pages once, per rules/alerting.md) and
    stays listed, with an unchanged message and the date it was first seen, until it is
    accepted with --save-baseline: a delta-only report would page once and then let
    ingest send "resolved" the next day, which is how a real implant would disappear.
    "Removed" entries are reported once, in the run where they vanished.

State (baseline + last run) lives in $HL_PERSISTENCE_STATE_DIR, default
/srv/red/opsdb/hl-agents-state/persistence — on the pool but NOT under the Samba-exported
/srv/red/fs. A baseline still at the legacy $HL_DATA_DIR path is read (never silently
replaced by a fresh one) until it is moved.

Writes <reports>/persistence-audit-latest.json. Reports dir from $HL_REPORTS_DIR.

Usage:
  python3 persistence-auditor.py [--save-baseline]
  python3 persistence-auditor.py --check        # self-test, no system access
"""

import argparse
import glob
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.environ.get(
    "HL_REPORTS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "security-reports")
)
DATA_DIR = os.environ.get("HL_DATA_DIR", os.path.join(BASE_DIR, "..", "data"))
DEFAULT_STATE_DIR = "/srv/red/opsdb/hl-agents-state/persistence"
STATE_DIR = os.environ.get("HL_PERSISTENCE_STATE_DIR") or (
    DEFAULT_STATE_DIR if os.path.isdir(DEFAULT_STATE_DIR) else DATA_DIR)
REPORT_PATH = os.path.join(REPORTS_DIR, "persistence-audit-latest.json")
BASELINE_PATH = os.path.join(STATE_DIR, "persistence-baseline.json")
LEGACY_BASELINE_PATH = os.path.join(DATA_DIR, "persistence-baseline.json")
LAST_RUN_PATH = os.path.join(STATE_DIR, "persistence-last-run.json")
MANIFEST_PATH = os.environ.get("HL_DEPLOY_MANIFEST", "/etc/homelab/deployed-units.sha256")
UNIT_DIR = "/etc/systemd/system"

HOME = os.path.expanduser("~")

ACTION = ("If you made this change, accept it: persistence-auditor.py --save-baseline. "
          "If not, investigate the entry before anything else.")


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return out.stdout if out.returncode == 0 else ""
    except Exception:
        return ""


def _full_sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return None


def _file_sig(path):
    """A stable signature for a file: sha256 of its contents (or a marker)."""
    full = _full_sha(path)
    return "sha256:" + full[:16] if full else "unreadable"


def collect():
    """Return {item_key: signature} across all persistence surfaces."""
    items = {}

    # ── cron ──────────────────────────────────────────────────────────────
    cron_paths = ["/etc/crontab"]
    for pat in ("/etc/cron.d/*", "/etc/cron.hourly/*", "/etc/cron.daily/*",
                "/etc/cron.weekly/*", "/etc/cron.monthly/*", "/var/spool/cron/*",
                "/var/spool/cron/crontabs/*"):
        cron_paths.extend(glob.glob(pat))
    for p in cron_paths:
        if os.path.isfile(p):
            items[f"cron:{p}"] = _file_sig(p)
    user_cron = _run(["crontab", "-l"])
    if user_cron.strip():
        items[f"cron:user:{os.environ.get('USER', 'me')}"] = \
            "sha256:" + hashlib.sha256(user_cron.encode()).hexdigest()[:16]

    # ── systemd: enabled units + timers + custom unit files ───────────────
    for line in _run(["systemctl", "list-unit-files", "--state=enabled",
                       "--no-legend", "--no-pager"]).splitlines():
        unit = line.split()[0] if line.split() else ""
        if unit:
            items[f"systemd-enabled:{unit}"] = "enabled"
    for line in _run(["systemctl", "list-timers", "--all", "--no-legend",
                      "--no-pager"]).splitlines():
        parts = line.split()
        # timer unit name is the column ending in .timer
        timer = next((c for c in parts if c.endswith(".timer")), "")
        if timer:
            items[f"systemd-timer:{timer}"] = "present"
    for p in glob.glob(f"{UNIT_DIR}/*.service") + glob.glob(f"{UNIT_DIR}/*.timer"):
        items[f"systemd-unitfile:{p}"] = _file_sig(p)

    # ── desktop autostart ─────────────────────────────────────────────────
    for pat in (os.path.join(HOME, ".config/autostart/*.desktop"),
                "/etc/xdg/autostart/*.desktop"):
        for p in glob.glob(pat):
            items[f"autostart:{p}"] = _file_sig(p)

    # ── shell rc / profile / rc.local ─────────────────────────────────────
    rc_files = ["/etc/rc.local", "/etc/profile",
                os.path.join(HOME, ".bashrc"), os.path.join(HOME, ".bash_profile"),
                os.path.join(HOME, ".profile"), os.path.join(HOME, ".zshrc"),
                os.path.join(HOME, ".zprofile")]
    rc_files.extend(glob.glob("/etc/profile.d/*.sh"))
    for p in rc_files:
        if os.path.isfile(p):
            items[f"rc:{p}"] = _file_sig(p)

    return items


# ── CI deploy manifest ──────────────────────────────────────────────────────────

def _trusted(st):
    """Root-owned and writable by nobody else. Anything weaker could be forged by the
    very thing the auditor is looking for."""
    return st.st_uid == 0 and not (st.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def parse_manifest(text):
    """`<sha256>  <absolute path>` per line; `#` comments. Returns {path: sha256}."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64 and parts[1].startswith("/"):
            out[parts[1].strip()] = parts[0].lower()
    return out


def load_manifest(path=MANIFEST_PATH, stat_fn=os.stat):
    """Returns (manifest, problem). problem is None, 'missing' or a reason it was ignored."""
    try:
        st = stat_fn(path)
        dst = stat_fn(os.path.dirname(path))
    except FileNotFoundError:
        return {}, "missing"
    except OSError as exc:
        return {}, f"unreadable ({exc.__class__.__name__})"
    if not (_trusted(st) and _trusted(dst)):
        return {}, "not root-owned or writable by non-root, so ignored"
    try:
        with open(path, encoding="utf-8") as f:
            return parse_manifest(f.read()), None
    except OSError as exc:
        return {}, f"unreadable ({exc.__class__.__name__})"


def _template_of(unit):
    """hl-collector-daily@hardware-report.timer -> hl-collector-daily@.timer"""
    if "@" not in unit or "." not in unit:
        return None
    name, _, rest = unit.partition("@")
    suffix = rest.rsplit(".", 1)[-1]
    return f"{name}@.{suffix}"


def ci_deployed(key, manifest, unit_hash):
    """True only when the entry is provably what the last CI deploy installed."""
    if not manifest:
        return False
    kind, _, ident = key.partition(":")

    def matches(path):
        want = manifest.get(path)
        return bool(want) and unit_hash(path) == want

    if kind == "systemd-unitfile":
        return matches(ident)
    if kind in ("systemd-enabled", "systemd-timer"):
        if matches(f"{UNIT_DIR}/{ident}"):
            return True
        tmpl = _template_of(ident)
        return bool(tmpl) and matches(f"{UNIT_DIR}/{tmpl}")
    return False   # cron, rc, autostart: never auto-accepted


# ── evaluation (pure: no system access, so --check can exercise it) ─────────────

def evaluate(current, baseline, last, manifest, unit_hash, today):
    """Diff current against the baseline, accept CI-deployed entries, and work out what
    changed since the previous run. `last` is the previous run's state or None.
    Returns (findings, summary, status, state_to_save, accepted)."""
    last_items = (last or {}).get("items")
    first_seen = dict((last or {}).get("first_seen") or {})

    new = {k for k in current if k not in baseline}
    changed = {k for k in current if k in baseline and baseline[k] != current[k]}
    removed = {k for k in baseline if k not in current}

    accepted = sorted(k for k in new | changed if ci_deployed(k, manifest, unit_hash))
    drift_new = sorted(new - set(accepted))
    drift_changed = sorted(changed - set(accepted))

    # Delta since the previous run (all entries, accepted or not).
    if last_items is None:
        d_new = d_changed = d_removed = None
    else:
        d_new = [k for k in current if k not in last_items]
        d_changed = [k for k in current if k in last_items and last_items[k] != current[k]]
        d_removed = [k for k in last_items if k not in current]

    findings = []
    for label, keys in (("NEW persistence entry", drift_new), ("CHANGED", drift_changed)):
        for k in keys:
            # A changed signature since the last run restarts the clock.
            if k not in first_seen or (last_items is not None and last_items.get(k) != current[k]):
                first_seen[k] = today
            findings.append({
                "severity": "critical",     # rules/alerting.md: unexpected persistence pages
                "message": f"{label}: {k}",          # unchanged text: a stable alert key
                "key": f"persistence:{k}",
                "since": first_seen[k],
                "new_since_last_run": last_items is None or k not in last_items
                                      or last_items.get(k) != current[k],
                "action": ACTION,
            })
    # Removed entries: once, in the run where they vanished (or on the first run of this
    # version, which has no previous run to compare with).
    gone = removed if last_items is None else (removed & set(last_items))
    for k in sorted(gone):
        findings.append({"severity": "info", "message": f"removed since baseline: {k}"})
    if accepted:
        findings.append({"severity": "info",
                         "message": f"{len(accepted)} entries match the CI deploy manifest (accepted)"})

    outstanding = {f["message"].split(": ", 1)[1] for f in findings if f["severity"] == "critical"}
    first_seen = {k: v for k, v in first_seen.items() if k in outstanding}

    if d_new is None:
        delta = "no previous run to compare"
    else:
        delta = (f"since last run: {len(d_new)} new, {len(d_changed)} changed, "
                 f"{len(d_removed)} removed")
    summary = (f"{delta}; {len(outstanding)} unaccepted vs baseline, "
               f"{len(accepted)} CI-deployed accepted, {len(current)} tracked")
    status = "critical" if outstanding else "ok"
    state = {"run_at": today, "items": current, "first_seen": first_seen}
    return findings, summary, status, state, accepted


# ── state I/O ───────────────────────────────────────────────────────────────────

def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_baseline():
    """Returns (baseline, where). where is 'state', 'legacy' or None."""
    b = _load_json(BASELINE_PATH)
    if b is not None:
        return b, "state"
    if os.path.abspath(LEGACY_BASELINE_PATH) != os.path.abspath(BASELINE_PATH):
        b = _load_json(LEGACY_BASELINE_PATH)
        if b is not None:
            return b, "legacy"
    return None, None


def main():
    ap = argparse.ArgumentParser(description="Linux persistence / autostart auditor")
    ap.add_argument("--save-baseline", action="store_true",
                    help="Force re-save the baseline (overwrites existing)")
    ap.add_argument("--check", action="store_true", help="Run the self-test and exit")
    args = ap.parse_args()
    if args.check:
        sys.exit(self_check())

    os.makedirs(REPORTS_DIR, exist_ok=True)
    current = collect()
    baseline, where = load_baseline()
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    findings, accepted = [], []
    if baseline is None or args.save_baseline:
        _save_json(BASELINE_PATH, current)
        _save_json(LAST_RUN_PATH, {"run_at": today, "items": current, "first_seen": {}})
        status = "ok"
        summary = f"{len(current)} persistence entries baselined ({'reset' if baseline else 'first run'})"
    else:
        manifest, problem = load_manifest()
        last = _load_json(LAST_RUN_PATH)
        findings, summary, status, state, accepted = evaluate(
            current, baseline, last, manifest, _full_sha, today)
        if problem:
            sev = "info" if problem == "missing" else "warn"
            findings.append({"severity": sev,
                             "message": f"deploy manifest {MANIFEST_PATH} {problem}; "
                                        "CI-installed units are not auto-accepted"})
        if where == "legacy":
            findings.append({"severity": "info",
                             "message": f"baseline still read from {LEGACY_BASELINE_PATH} "
                                        f"(Samba-exported); move it to {BASELINE_PATH}"})
        _save_json(LAST_RUN_PATH, state)

    report = {
        "tool": "persistence-auditor",
        "run_at": now.isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "tracked_count": len(current),
        "ci_accepted": accepted,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} (status={status}, {len(findings)} findings)")


# ── self-test ───────────────────────────────────────────────────────────────────

def self_check():
    problems = []

    def expect(cond, what):
        if not cond:
            problems.append(what)

    H = {f"{UNIT_DIR}/hl-collector@.service": "a" * 64,
         f"{UNIT_DIR}/hl-collector-daily@.timer": "b" * 64,
         f"{UNIT_DIR}/homelab-db-ingest.service": "c" * 64}
    on_disk = dict(H)
    on_disk[f"{UNIT_DIR}/evil.service"] = "d" * 64
    on_disk[f"{UNIT_DIR}/homelab-db-ingest.service"] = "e" * 64   # hand-edited after deploy
    unit_hash = on_disk.get
    manifest = parse_manifest("# header\n" + "\n".join(f"{h}  {p}" for p, h in H.items())
                              + "\nnot a line\n")
    expect(len(manifest) == 3, f"manifest parse: {len(manifest)} entries")

    expect(ci_deployed(f"systemd-unitfile:{UNIT_DIR}/hl-collector@.service", manifest, unit_hash),
           "matching unit file not accepted")
    expect(not ci_deployed(f"systemd-unitfile:{UNIT_DIR}/homelab-db-ingest.service", manifest, unit_hash),
           "hand-edited unit file was accepted")
    expect(not ci_deployed(f"systemd-unitfile:{UNIT_DIR}/evil.service", manifest, unit_hash),
           "unit not in manifest was accepted")
    expect(ci_deployed("systemd-timer:hl-collector-daily@hardware-report.timer", manifest, unit_hash),
           "template timer instance not accepted")
    expect(not ci_deployed("systemd-timer:evil@x.timer", manifest, unit_hash),
           "instance of unknown template accepted")
    expect(not ci_deployed("cron:/etc/cron.d/hl", manifest, unit_hash), "cron entry accepted")
    expect(not ci_deployed(f"systemd-unitfile:{UNIT_DIR}/hl-collector@.service", {}, unit_hash),
           "accepted with no manifest")

    class St:
        def __init__(self, uid, mode):
            self.st_uid, self.st_mode = uid, mode
    with tempfile.TemporaryDirectory() as d:
        mp = os.path.join(d, "m.sha256")
        with open(mp, "w") as f:
            f.write("\n".join(f"{h}  {p}" for p, h in H.items()))
        m, prob = load_manifest(mp, stat_fn=lambda p: St(0, 0o100644))
        expect(prob is None and len(m) == 3, f"trusted manifest rejected: {prob}")
        m, prob = load_manifest(mp, stat_fn=lambda p: St(1000, 0o100644))
        expect(not m and prob, "manifest owned by non-root was trusted")
        m, prob = load_manifest(mp, stat_fn=lambda p: St(0, 0o100666))
        expect(not m and prob, "world-writable manifest was trusted")
        m, prob = load_manifest(os.path.join(d, "nope"))
        expect(not m and prob == "missing", "missing manifest not reported as missing")

    baseline = {"cron:/etc/crontab": "sha256:1", f"systemd-unitfile:{UNIT_DIR}/old.service": "sha256:2"}
    current = {"cron:/etc/crontab": "sha256:1",
               f"systemd-unitfile:{UNIT_DIR}/hl-collector@.service": "sha256:a",
               "systemd-timer:hl-collector-daily@hardware-report.timer": "present",
               f"systemd-unitfile:{UNIT_DIR}/evil.service": "sha256:d"}
    f1, s1, st1, state1, acc1 = evaluate(current, baseline, None, manifest, unit_hash, "2026-11-10")
    warns = [f for f in f1 if f["severity"] == "critical"]
    expect(len(acc1) == 2, f"accepted {acc1}")
    expect([w["message"] for w in warns] == [f"NEW persistence entry: systemd-unitfile:{UNIT_DIR}/evil.service"],
           f"warns {[w['message'] for w in warns]}")
    expect(st1 == "critical", "status should be critical with unaccepted drift")
    expect(any(f["message"].startswith("removed since baseline") for f in f1), "removed not reported on first run")

    # Next day, nothing changed: the unaccepted entry is STILL listed with the same text
    # and its first-seen date; the removal is not repeated.
    f2, s2, st2, state2, _ = evaluate(current, baseline, state1, manifest, unit_hash, "2026-11-11")
    warns2 = [f for f in f2 if f["severity"] == "critical"]
    expect(len(warns2) == 1 and warns2[0]["message"] == warns[0]["message"], "unaccepted entry vanished on day 2")
    expect(warns2 and warns2[0]["since"] == "2026-11-10" and not warns2[0]["new_since_last_run"],
           "first-seen date / delta flag wrong on day 2")
    expect(not any(f["message"].startswith("removed") for f in f2), "removal repeated on day 2")
    expect(s2.startswith("since last run: 0 new, 0 changed, 0 removed"), f"summary {s2!r}")

    # Nothing unaccepted -> ok, and the summary says so.
    clean = {k: v for k, v in current.items() if "evil" not in k}
    f3, s3, st3, _, _ = evaluate(clean, baseline, state2, manifest, unit_hash, "2026-11-12")
    expect(st3 == "ok" and not [f for f in f3 if f["severity"] == "critical"], "clean run not ok")

    for p in problems:
        print(f"[check] FAIL {p}", file=sys.stderr)
    if not problems:
        print("[check] ok — manifest trust, CI acceptance, drift, run-to-run delta")
    return 1 if problems else 0


if __name__ == "__main__":
    main()
