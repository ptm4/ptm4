#!/usr/bin/env python3
"""
journald-hunter.py — Linux log threat & health hunter.

Combs ALL of journald (every unit/boot in the lookback window), not just auth, and
classifies what it finds into security signals + general-health flags. Falls back to
reading /var/log/{auth,sys}.log when journalctl is unavailable.

Categories:
  security  — failed/accepted SSH logins, sudo/su, new/changed users
  service   — failed systemd units, crashes, coredumps
  oom       — out-of-memory kills
  storage   — disk / filesystem / I-O / SMART errors
  kernel    — kernel BUGs, MCE/hardware errors, segfaults, call traces

Writes <reports>/journal-hunt-latest.json. Reports dir from $HL_REPORTS_DIR
(default: ../../../security-reports relative to this file).

Journal access: an unprivileged user outside the systemd-journal / adm group sees only
its own user journal (no kernel, no smartd). The hunter checks for that and reports a
warn finding rather than silently scanning a fraction of the log. On opti the collector
units grant it with SupplementaryGroups=systemd-journal.

Self-matching: the homelab's own collectors log through journald too. Lines that are
the hunter's/collectors' own output (ingest stats, cron/sudo PAM session lines) are
skipped, and sudo audit lines ("... ; COMMAND=...") are checked against the security
rules only — a command line naming smartctl is not a disk error. Tests:
  python -m unittest discover -s homelab/tools/security -v

Fleet mode (2026-11-10): with --hosts or $HL_JOURNAL_HOSTS (the opti collector units set
"opti,rpi,noblenumbat") the hunter reads every listed host's journal and runs the same rules
centrally. The local host is read directly; the others over SSH through
../collectors/_hosts.py (HL_HOSTS targets, HL_SSH_KEY), as the collectors' login user, at
nice 19 / idle IO. Nothing is installed on the other hosts. Each host is read from where its
last successful read ended (journal-hunt-state.json in the reports dir), at most
FLEET_MAX_DAYS back and FLEET_LINE_CAP lines, so a missed run catches up without an
unbounded read on the Pi. Every finding is then prefixed "[host]" (ingest's host column),
and the report carries one "hosts" block per host. Without --hosts / $HL_JOURNAL_HOSTS it
reads only the local journal, as before.

Usage:
  python3 journald-hunter.py [--hours 24] [--hosts opti,rpi,noblenumbat]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.environ.get(
    "HL_REPORTS_DIR", os.path.join(BASE_DIR, "..", "..", "..", "security-reports")
)
REPORT_PATH = os.path.join(REPORTS_DIR, "journal-hunt-latest.json")

# (category, severity, compiled-pattern, human label)
PATTERNS = [
    ("security", "warn",     re.compile(r"Failed password|authentication failure|Invalid user|Failed publickey"), "Failed SSH/auth attempt"),
    ("security", "info",     re.compile(r"Accepted (password|publickey|keyboard)"), "Successful SSH login"),
    ("security", "warn",     re.compile(r"\bsudo\b.*COMMAND="), "sudo command executed"),
    ("security", "warn",     re.compile(r"session opened for user root|su(\[|:).*session opened"), "Privilege escalation (su/root session)"),
    ("security", "critical", re.compile(r"\b(useradd|userdel|usermod|groupadd)\b"), "User/group account change"),
    ("service",  "warn",     re.compile(r"Failed with result|entered failed state|Failed to start|Main process exited.*status=[1-9]"), "systemd unit failure"),
    ("service",  "critical", re.compile(r"dumped core|systemd-coredump\[\d+\]|Process \d+ \(.+\) of user"), "Process core dump"),
    ("oom",      "critical", re.compile(r"Out of memory|oom[-_]kill|Killed process \d+|invoked oom-killer"), "Out-of-memory kill"),
    ("storage",  "critical", re.compile(r"I/O error|EXT4-fs error|XFS.*error|Buffer I/O error|critical medium error|failed command| ataX?.*error|^ata\d+(\.\d+)?:.*\berror", re.I), "Disk / filesystem error"),
    # smartd's own wording only. A bare "SMART" also matched ingest's "smart_flags" stats
    # line and sudo audit lines for smartctl; smartd's temperature/airflow/raw-read-rate
    # attribute chatter is deliberately not listed.
    ("storage",  "critical", re.compile(r"FAILED SMART self-check|Failed SMART (usage|prefailure) Attribute|self-assessment test result: FAILED", re.I), "SMART health failure"),
    ("storage",  "warn",     re.compile(
        r"Currently unreadable \(pending\) sectors|Offline uncorrectable sectors|ATA error count increased"
        r"|Self-Test Log error count increased"
        r"|SMART (Prefailure|Usage) Attribute: \d+ (Reallocated_Sector_Ct|Reallocated_Event_Count|Current_Pending_Sector|Offline_Uncorrectable|Reported_Uncorrect) changed"
        r"|reallocated sector|pending sector|offline uncorrectable", re.I), "SMART / disk-health warning"),
    # \bBUG: so sshd's "send DEBUG: Broken pipe" no longer reads as a kernel BUG.
    ("kernel",   "critical", re.compile(r"Hardware Error|Machine Check Exception|mce: \[Hardware Error\]|Uncorrected error|kernel BUG|\bBUG: |general protection fault|Call Trace"), "Kernel / hardware fault"),
    # The kernel prints "Oops:"; lowercase "oops" never matched a real one.
    ("kernel",   "warn",     re.compile(r"segfault|traps:|\bOops\b"), "Process crash (segfault/oops)"),
    # Raspberry Pi signals (rpi). SD-card controller errors are disk errors; rpi boots from
    # a USB SSD since its microSD died, so any mmc error means the card slot is in use again.
    ("storage",  "critical", re.compile(r"\bmmc\d+: (Timeout waiting|Card stuck|error -?\d+|.*\bCRC error)|\bmmcblk\d+\S*: error", re.I), "SD card error"),
    # A USB reset of the boot SSD (rpi) or the USB GbE adapter (noblenumbat) is the early
    # sign of a bad cable, port or supply; real I/O errors are caught above as critical.
    ("storage",  "warn",     re.compile(r"uas_eh_(abort|device_reset)_handler|\breset (SuperSpeed|high-speed|full-speed)\b.*USB device"), "USB device reset"),
    ("power",    "warn",     re.compile(r"Under-?voltage detected", re.I), "Undervoltage"),
]

# One-line "what to do" for each critical, carried in the finding so the page says it.
ACTIONS = {
    "User/group account change": "confirm you made it; if not, treat the host as compromised",
    "Process core dump": "run coredumpctl list on the host to see what crashed",
    "Out-of-memory kill": "check journalctl -k on the host for what was killed and what grew",
    "Disk / filesystem error": "run dmesg and smartctl -a on the host; back up anything unique",
    "SMART health failure": "back up that disk now and plan its replacement",
    "Kernel / hardware fault": "read journalctl -k around the trace on the host",
    "SD card error": "check what is in the Pi's SD slot; rpi should boot from its USB SSD",
}

# Lines that are the homelab's own bookkeeping, never a finding:
#  - ingest.py's per-cycle stats dict ("[ingest] {... smart_flags ...}")
#  - PAM session lines for cron jobs and sudo: every collector's sudo and every root
#    cron job opens one. sshd/su root sessions are still counted.
SKIP_LINE = re.compile(r"^\[ingest\] \{|pam_unix\((cron|sudo|sudo-i):session\)")

# sudo's audit line as journalctl -o cat prints it (no "sudo:" prefix):
#   "    ptm : PWD=/home/ptm ; USER=root ; COMMAND=/usr/sbin/smartctl -H -A /dev/sda"
# It records a command, not an event, so only the security rules apply to it.
SUDO_AUDIT = re.compile(r"^\s*\S+ : (TTY=\S+ ; )?PWD=.* ; USER=\S+ ; .*COMMAND=")

JOURNAL_GROUPS = ("systemd-journal", "adm", "wheel")

SEV_ORDER = {"critical": 0, "warn": 1, "info": 2}
STATUS_FROM_SEV = {"critical": "critical", "warn": "warn", "info": "ok"}


def have_journalctl():
    return shutil.which("journalctl") is not None


def journal_cmd(hours):
    """argv for reading the journal; a remote read can prefix it (e.g. ["ssh", host])."""
    return ["journalctl", "--no-pager", "--since", f"{hours} hours ago", "-o", "cat"]


def journal_access():
    """'full' if this process can read the system journal, else 'partial'.

    Root, or membership of systemd-journal / adm / wheel (the groups journald's ACLs
    grant), sees everything. Anyone else gets only their own user journal.
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:          # not a POSIX host; journald does not apply
        return "full"
    if geteuid() == 0:
        return "full"
    try:
        import grp
    except ImportError:
        return "full"
    gids = set(os.getgroups()) | {os.getegid()}
    for name in JOURNAL_GROUPS:
        try:
            if grp.getgrnam(name).gr_gid in gids:
                return "full"
        except KeyError:
            continue
    return "partial"


def journal_lines(hours, cmd=None):
    """Return message strings from journald over the lookback window."""
    try:
        out = subprocess.run(
            cmd or journal_cmd(hours),
            capture_output=True, text=True, timeout=120,
        )
        if out.returncode == 0:
            return out.stdout.splitlines()
    except Exception:
        pass
    return []


def file_lines(hours):
    """Fallback: read common text logs (whole file; time filtering is best-effort)."""
    lines = []
    for path in ("/var/log/auth.log", "/var/log/syslog", "/var/log/messages", "/var/log/secure"):
        try:
            with open(path, "r", errors="replace") as f:
                lines.extend(f.read().splitlines()[-20000:])
        except (FileNotFoundError, PermissionError):
            continue
    return lines


def read_lines(hours):
    """(lines, used_fallback): journald if it yields anything, else the text logs."""
    if have_journalctl():
        lines = journal_lines(hours)
        if lines:
            return lines, False
        # journalctl present but returned nothing (perms?) — try files
        lines = file_lines(hours)
        return lines, bool(lines)
    return file_lines(hours), True


def classify(line):
    """The (category, severity, pattern, label) rule a line counts under, or None."""
    if SKIP_LINE.search(line):
        return None
    audit = SUDO_AUDIT.match(line) is not None
    for rule in PATTERNS:
        if audit and rule[0] != "security":
            continue
        if rule[2].search(line):
            return rule  # first matching pattern wins
    return None


def hunt(lines):
    cat_counts = Counter()
    # keep a few representative examples per (category,label) so the report isn't huge
    examples = {}
    worst_sev = "info"
    for line in lines:
        rule = classify(line)
        if rule is None:
            continue
        category, severity, _pat, label = rule
        key = (category, severity, label)
        cat_counts[key] += 1
        if key not in examples:
            examples[key] = line.strip()[:300]
        if SEV_ORDER[severity] < SEV_ORDER[worst_sev]:
            worst_sev = severity
    return cat_counts, examples, worst_sev


PARTIAL_READ_FINDING = {
    "severity": "warn",
    "message": "[hunter] Partial journal read — this user is not in systemd-journal/adm, "
               "so kernel and smartd lines are not visible and disk errors cannot be seen",
}


def build_findings(cat_counts, examples, host=None):
    """One finding per rule hit. The text before the first " | " is the stable part ingest
    keys alerts on (digits collapse there, the rest is ignored), so a critical's action goes
    before it and the volatile example line after it. `host` (fleet mode) prefixes
    "[host] ", which ingest reads into its host column."""
    prefix = f"[{host}] " if host else ""
    findings = []
    for (category, severity, label), count in cat_counts.items():
        action = ACTIONS.get(label) if severity == "critical" else None
        message = f"{prefix}[{category}] {label} ×{count}"
        if action:
            message += f" — {action}"
        message += f" | e.g. {examples[(category, severity, label)]}"
        finding = {"severity": severity, "message": message}
        if action:
            finding["action"] = action
        findings.append(finding)
    findings.sort(key=lambda f: SEV_ORDER.get(f["severity"], 9))
    return findings


# ── fleet mode ──────────────────────────────────────────────────────────────────────

STATE_PATH = os.path.join(REPORTS_DIR, "journal-hunt-state.json")
FLEET_LINE_CAP = 100000   # per host per run; rpi writes ~27k lines/day, noblenumbat ~36k
FLEET_MAX_DAYS = 7        # catch-up limit after missed runs (rpi keeps ~2 weeks of journal)
FLEET_TIMEOUT_S = 180
INTERMITTENT = {"android"}  # Termux: no journald; never read even if listed


def fleet_cmd(since_epoch, remote):
    """Bounded journal read from a fixed point. Remote reads run at the lowest CPU and IO
    priority so the Pi's DNS service never competes with them."""
    cmd = ["journalctl", "--no-pager", "-q", "-o", "cat",
           "--since", f"@{int(since_epoch)}", "-n", str(FLEET_LINE_CAP)]
    return (["nice", "-n", "19", "ionice", "-c3"] + cmd) if remote else cmd


def load_state(path=None):
    try:
        with open(path or STATE_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state, path=None):
    path = path or STATE_PATH
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def since_for(host, state, now, hours):
    """Start of this run's window for `host`: where its last good read ended, else `hours`
    back, never more than FLEET_MAX_DAYS back."""
    floor = now - FLEET_MAX_DAYS * 86400
    last = (state.get(host) or {}).get("last_ok")
    start = last if isinstance(last, (int, float)) and last < now else now - hours * 3600
    return max(start, floor)


def _hosts_module():
    sys.path.insert(0, os.path.join(BASE_DIR, "..", "collectors"))
    import _hosts  # noqa: E402  (homelab/tools/collectors/_hosts.py)
    return _hosts


def _local_name():
    import socket
    return socket.gethostname().split(".")[0].lower()


def access_from_ids(uid_line, groups_line):
    """'full'/'partial' from a remote `id -u` / `id -nG`, by the same rule as journal_access."""
    if uid_line.strip() == "0":
        return "full"
    return "full" if set(groups_line.split()) & set(JOURNAL_GROUPS) else "partial"


def read_host(name, since_epoch, local, targets):
    """(lines, ok, access, detail) for one host. ok=False means the read failed and the
    host's cursor must not advance."""
    if local:
        try:
            out = subprocess.run(fleet_cmd(since_epoch, remote=False),
                                 capture_output=True, text=True, timeout=FLEET_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            return [], False, None, f"journalctl failed: {exc.__class__.__name__}"
        if out.returncode != 0:
            return [], False, None, f"journalctl exited {out.returncode}"
        return out.stdout.splitlines(), True, journal_access(), "local"

    target = targets.get(name)
    if target is None:
        return [], False, None, "not in HL_HOSTS"
    hl = _hosts_module()
    ids, rc = hl.run_on(target, ["sh", "-c", "id -u; id -nG"], timeout=20)
    if rc != 0:
        return [], False, None, "ssh failed (host down or key not authorized)"
    uid_line, _, groups_line = ids.partition("\n")
    access = access_from_ids(uid_line, groups_line)
    out, rc = hl.run_on(target, fleet_cmd(since_epoch, remote=True), timeout=FLEET_TIMEOUT_S)
    if rc != 0:
        return [], False, access, f"remote journalctl exited {rc}"
    return out.splitlines(), True, access, "ssh"


def hunt_fleet(names, hours, reader=None, state=None, now=None):
    """Run the rules over each host's journal. Returns (findings, host_blocks, by_cat,
    new_state, total_lines). `reader(name, since, local)` is injectable for tests."""
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    state = dict(state or {})
    local = _local_name()
    if reader is None:
        targets = {}
        try:
            hl = _hosts_module()
            hl.ensure_key()
            targets = {h.name: h for h in hl.hosts()}
        except Exception as exc:  # noqa: BLE001 - one clear finding per remote host below
            print(f"[journald-hunter] remote hosts unavailable: {exc}", file=sys.stderr)
        reader = lambda n, s, is_local: read_host(n, s, is_local, targets)  # noqa: E731

    findings, blocks, by_cat, total = [], [], Counter(), 0
    for name in names:
        since = since_for(name, state, now, hours)
        lines, ok, access, detail = reader(name, since, name == local)
        host_findings, host_cats = [], Counter()
        if not ok:
            host_findings.append({"severity": "warn",
                                  "message": f"[{name}] [hunter] Journal not read | {detail}"})
        else:
            counts, examples, _worst = hunt(lines)
            host_findings = build_findings(counts, examples, host=name)
            for (category, _s, _l), n in counts.items():
                host_cats[category] += n
            if access == "partial":
                f = dict(PARTIAL_READ_FINDING)
                f["message"] = f"[{name}] " + f["message"]
                host_findings.append(f)
            if len(lines) >= FLEET_LINE_CAP:
                host_findings.append({"severity": "warn",
                                      "message": f"[{name}] [hunter] Journal read capped | only the "
                                                 f"newest {FLEET_LINE_CAP} lines since the last run were scanned"})
            state[name] = {"last_ok": now, "lines": len(lines)}
            total += len(lines)
        worst = min((SEV_ORDER[f["severity"]] for f in host_findings), default=SEV_ORDER["info"])
        status = {0: "critical", 1: "warn"}.get(worst, "ok")
        window_h = round((now - since) / 3600, 1)
        if ok:
            parts = ", ".join(f"{n} {c}" for c, n in sorted(host_cats.items())) or "no errors or flags"
            summary = f"{len(lines)} lines over {window_h}h — {parts}"
        else:
            summary = f"journal not read — {detail}"
        blocks.append({"host": name, "status": status, "summary": summary,
                       "journal_access": access, "source": detail,
                       "metrics": {"lines_scanned": len(lines) if ok else 0,
                                   "window_hours": window_h,
                                   "critical": sum(f["severity"] == "critical" for f in host_findings),
                                   "warn": sum(f["severity"] == "warn" for f in host_findings)}})
        findings.extend(host_findings)
        by_cat.update(host_cats)
    findings.sort(key=lambda f: SEV_ORDER.get(f["severity"], 9))
    return findings, blocks, by_cat, state, total


def fleet_names(arg):
    spec = arg or os.environ.get("HL_JOURNAL_HOSTS", "")
    names = [n.strip().lower() for n in spec.split(",") if n.strip()]
    return [n for n in names if n not in INTERMITTENT]


def main_fleet(args, names):
    findings, blocks, by_cat, state, total = hunt_fleet(names, args.hours, state=load_state())
    worst = min((SEV_ORDER[f["severity"]] for f in findings), default=SEV_ORDER["info"])
    status = {0: "critical", 1: "warn"}.get(worst, "ok")
    per_host = "; ".join(f"{b['host']} {b['summary']}" for b in blocks)
    report = {
        "tool": "journald-hunter",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": f"{total} log lines from {len(blocks)} hosts — {per_host}",
        "findings": findings,
        "categories": dict(by_cat),
        "hosts": blocks,
        "source": "journald (fleet)",
        "journal_access": "partial" if any(b["journal_access"] == "partial" for b in blocks) else "full",
        "window_hours": args.hours,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    # Cursors advance only after the report that covers them is safely written.
    save_state(state)
    print(f"Report written: {REPORT_PATH} (status={status}, {len(findings)} finding types, "
          f"{len(blocks)} hosts)")


def main():
    ap = argparse.ArgumentParser(description="Linux log threat & health hunter")
    ap.add_argument("--hours", type=int, default=24, help="Lookback window in hours (first run)")
    ap.add_argument("--hosts", help="Comma list of hosts to read (fleet mode); "
                                    "default $HL_JOURNAL_HOSTS, else the local journal only")
    args = ap.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    names = fleet_names(args.hosts)
    if names:
        return main_fleet(args, names)

    lines, used_fallback = read_lines(args.hours)
    access = "files" if used_fallback else journal_access()

    cat_counts, examples, worst_sev = hunt(lines)
    findings = build_findings(cat_counts, examples)
    if access == "partial":
        findings.append(dict(PARTIAL_READ_FINDING))
        if SEV_ORDER["warn"] < SEV_ORDER[worst_sev]:
            worst_sev = "warn"
        findings.sort(key=lambda f: SEV_ORDER.get(f["severity"], 9))

    status = STATUS_FROM_SEV[worst_sev] if findings else "ok"
    by_cat = Counter()
    for (category, _sev, _label), count in cat_counts.items():
        by_cat[category] += count
    if findings:
        parts = ", ".join(f"{n} {c}" for c, n in sorted(by_cat.items()))
        summary = f"{len(lines)} log lines scanned over {args.hours}h — {parts}"
    else:
        summary = f"{len(lines)} log lines scanned over {args.hours}h — no errors or flags"
    if used_fallback:
        summary += " (text-log fallback)"
    elif access == "partial":
        summary += " (partial journal: own user journal only)"

    report = {
        "tool": "journald-hunter",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
        "findings": findings,
        "categories": dict(by_cat),
        "source": "auth/syslog files" if used_fallback else "journald",
        "journal_access": access,
        "window_hours": args.hours,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: {REPORT_PATH} (status={status}, {len(findings)} finding types)")


if __name__ == "__main__":
    main()
