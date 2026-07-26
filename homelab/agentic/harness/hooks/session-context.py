#!/usr/bin/env python3
"""
SessionStart hook — layer 2 of the harness (deterministic context injection).

Wired by `probe.py --wire claude` into .claude/settings.json.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not re-state the host table, SSH keys, or repo location. Those are static, and
static facts belong in `rules/01-homelab-context.md`, which Claude Code already auto-loads
into every session via `.claude/rules/`. Injecting them here too would just pay for the
same tokens twice.

What a static file *cannot* do is tell you the state of the homelab right now. So this hook
contributes only the perishable part:

  - per-host status from the newest homelab-doctor report, and how old that report is
  - which hosts are currently degraded or unreachable (android is routinely offline)
  - a warning when the report is stale enough that it shouldn't be trusted

That is the whole justification for using a hook instead of another markdown file.

FAILURE POSTURE
---------------
A hook that hangs delays every session start; a hook that crashes silently removes the
context it was supposed to guarantee. The report lives on a CIFS mount of opti, so if opti
is down that read can block. Everything here is therefore wrapped, and the read happens in
a daemon thread with a hard timeout — on any problem we emit a short "live state
unavailable" note and exit 0. Never fail the session.

Contract: stdin = SessionStart JSON; stdout = {"hookSpecificOutput": {...}}; exit 0.
"""

import json
import os
import sys
import threading
from datetime import datetime, timezone

# opti's pool, as seen from wherever Claude Code is running. Ordered by preference:
# the CIFS mount on tux, the container mount, then opti's own local path.
AGENT_LOG_DIRS = [
    "/home/ptm/opti/ptm/agent-logs",
    "/agent-logs",
    "/srv/red/fs/ptm/agent-logs",
]
READ_TIMEOUT_S = 2.0
# Past this, the report describes a homelab that may have moved on.
STALE_HOURS = 6


def _read_json(path, sink):
    try:
        with open(path, encoding="utf-8") as f:
            sink["data"] = json.load(f)
    except Exception as exc:  # noqa: BLE001 — any failure degrades identically
        sink["error"] = str(exc)


def read_with_timeout(path, timeout=READ_TIMEOUT_S):
    """Read JSON without ever blocking the session. A hung CIFS mount is the case that
    matters; the mount is `soft` so it should error out, but don't rely on that."""
    sink = {}
    t = threading.Thread(target=_read_json, args=(path, sink), daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, "timed out (opti unreachable?)"
    return sink.get("data"), sink.get("error")


def find_report():
    for d in AGENT_LOG_DIRS:
        path = os.path.join(d, "homelab-doctor-latest.json")
        try:
            if not os.path.exists(path):
                continue
        except OSError:
            continue
        data, err = read_with_timeout(path)
        if data:
            return data, None
        if err:
            return None, err
    return None, "no homelab-doctor report found"


def age_phrase(run_at):
    try:
        when = datetime.fromisoformat(str(run_at).replace("Z", "+00:00"))
        hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        return None, None
    if hours < 1:
        return f"{int(hours * 60)}m ago", hours
    if hours < 48:
        return f"{hours:.0f}h ago", hours
    return f"{hours / 24:.0f}d ago", hours


def build_context():
    report, err = find_report()
    if not report:
        return (f"**Homelab live state:** unavailable ({err}). "
                f"The static context in `.claude/rules/01-homelab-context.md` still applies; "
                f"treat per-host status as unknown and verify before relying on it.")

    lines = []
    age, hours = age_phrase(report.get("run_at"))
    summary = report.get("summary") or "no summary"
    header = f"**Homelab live state** — homelab-doctor: {summary}"
    if age:
        header += f" (report {age})"
    lines.append(header)

    degraded, fine = [], []
    for h in report.get("hosts") or []:
        name, status = h.get("host", "?"), (h.get("status") or "unknown")
        containers = h.get("metrics", {}).get("containers") or []
        down = [c.get("name") for c in containers
                if not str(c.get("status", "")).lower().startswith("up")]
        if status == "ok" and not down:
            fine.append(f"{name} ({len(containers)} containers up)" if containers else name)
        else:
            bit = f"**{name}: {status}**"
            if down:
                bit += f" — not up: {', '.join(n for n in down if n)}"
            degraded.append(bit)

    if fine:
        lines.append(f"- Healthy: {', '.join(fine)}")
    for d in degraded:
        lines.append(f"- {d}")

    if hours is not None and hours > STALE_HOURS:
        lines.append(f"- ⚠ This report last ran {age} — re-run the homelab-doctor runner "
                     f"(or check live) before trusting per-host detail.")

    lines.append("- Static facts (hosts, SSH keys, repo location) are already loaded from "
                 "`.claude/rules/01-homelab-context.md` — don't grep for them.")
    return "\n".join(lines)


def main():
    try:
        sys.stdin.read()  # drain the payload; nothing here needs to branch on it
    except Exception:  # noqa: BLE001
        pass

    try:
        context = build_context()
    except Exception as exc:  # noqa: BLE001 — never break session start
        context = f"**Homelab live state:** unavailable (hook error: {exc})."

    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
