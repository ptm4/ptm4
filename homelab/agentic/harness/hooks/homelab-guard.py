#!/usr/bin/env python3
"""
PreToolUse hook — layer 3 of the harness (the only layer that actually enforces).

Wired by `probe.py --wire claude` for Bash|Edit|Write|NotebookEdit.

CLAUDE.md and .claude/rules/ are *context*: the model reads them and usually complies.
"Usually" is not a guarantee, and the mistakes this file guards against are the expensive,
hard-to-undo kind. Anthropic's docs are explicit — to block an action regardless of what the
model decides, you need a PreToolUse hook. This is that hook.

Two verdicts, chosen deliberately per rule:

  deny — the action is always wrong and a correct alternative exists. Blocked outright,
         with a reason that names the alternative.
  ask  — the action is sometimes legitimate but the usual reasoning about it is unsafe, so
         a human must consciously confirm. `rm -rf` of a repo copy is the canonical case:
         a clean `git status` says "safe" while gitignored local-only content is about to
         be destroyed. That exact reasoning error happened on 2026-07-22.

It also *injects* (never blocks) short reminders for a few easy-to-get-wrong targets, so
that detail costs tokens only when a command actually touches them.

PERFORMANCE / SAFETY POSTURE
This runs before every Bash, Edit and Write. It does pure string matching — no network, no
filesystem, no CIFS reads — and any internal error falls through to "allow" rather than
blocking legitimate work. A guard that breaks the session is worse than no guard.

Contract: stdin = PreToolUse JSON; stdout = hookSpecificOutput with permissionDecision;
exit 0 always (the decision travels in JSON, not the exit code).
"""

import json
import re
import sys

# ── helpers ────────────────────────────────────────────────────────────────────
def _writes_to(cmd, target):
    """True if `cmd` looks like it modifies `target` in place, as opposed to reading it or
    copying *onto* it with a sanctioned deploy tool."""
    if target not in cmd:
        return False
    editors = (
        r"\bsed\s+-[a-zA-Z]*i", r"\btee\b", r"\bnano\b", r"\bvi\b", r"\bvim\b",
        r"\btruncate\b", r"\bdd\b", r"\bchmod\b", r"\bchown\b",
        r">\s*" + re.escape(target), r">>\s*" + re.escape(target),
        r"\bmv\b[^|;]*" + re.escape(target),
    )
    return any(re.search(p, cmd) for p in editors)


# ── rules ──────────────────────────────────────────────────────────────────────
# Each rule: (id, verdict, predicate(tool, cmd, path) -> bool, reason)

def _rm_repo_copy(tool, cmd, path):
    if tool != "Bash":
        return False
    if not re.search(r"\brm\b[^|;&]*\s-[a-zA-Z]*[rR]", cmd):
        return False
    # Only the repo itself, not scratch dirs that merely mention it.
    return bool(re.search(r"(^|[\s'\"=:])[~/\w./-]*ptm4(/|\b)", cmd))


def _samba_or_omv(tool, cmd, path):
    targets = ("/etc/samba", "smb.conf", "/etc/openmediavault")
    if tool in ("Edit", "Write", "NotebookEdit"):
        return any(t in path for t in targets)
    return tool == "Bash" and any(_writes_to(cmd, t) for t in targets)


def _discord_on_rpi(tool, cmd, path):
    # The bot dirs as they exist *on the rpi* (the deploy target), not in the repo.
    marker = "/srv/docker/compose/discord-"
    if tool in ("Edit", "Write", "NotebookEdit"):
        return marker in path
    return tool == "Bash" and marker in cmd and _writes_to(cmd, marker)


def _webapp_deploy_dir(tool, cmd, path):
    # rsync/cp *into* this dir is the documented fast-iteration deploy, so it stays allowed.
    # Hand-editing files here treats a deploy artifact as source — the next CI run reverts it.
    marker = "/srv/docker/compose/webapp"
    if tool in ("Edit", "Write", "NotebookEdit"):
        return marker in path
    return tool == "Bash" and _writes_to(cmd, marker)


def _git_write(tool, cmd, path):
    if tool != "Bash":
        return False
    return bool(re.search(r"\bgit\b[^|;&]*\s(commit|push)\b", cmd)
                or re.search(r"\bgit\b[^|;&]*\bcommit\b[^|;&]*--amend", cmd)
                or re.search(r"\bgit\s+reset\b[^|;&]*--hard", cmd))


RULES = [
    (
        "rm-repo-copy", "ask", _rm_repo_copy,
        "Deleting a ptm4 working copy. A clean `git status` does NOT mean this is safe — it "
        "hides both ignored and uncommitted files. That reasoning error destroyed the "
        "add-to-rpi-webapp skill and the repo's own delete-safety rule on 2026-07-22, when "
        "homelab/agentic/ was still gitignored. It is tracked now, but uncommitted rules/hooks "
        "and everything under .claude/ still are not. Run `git status --ignored --porcelain` "
        "and `git clean -ndx` first, preserve anything they list, then confirm.",
    ),
    (
        "samba-omv-config", "deny", _samba_or_omv,
        "OpenMediaVault owns the Samba config on opti and regenerates it — a hand edit is "
        "silently discarded, so this change would appear to work and then vanish. Make the "
        "change through the OMV web UI on opti:80 instead.",
    ),
    (
        "discord-files-on-rpi", "deny", _discord_on_rpi,
        "The Discord bots are managed through the webapp, not by editing files on the rpi. "
        "Their control APIs are only reachable from the webapp container. Edit "
        "homelab/RPI-srv/discord-*/ in the repo, or use the webapp's bot tab.",
    ),
    (
        "webapp-deploy-dir", "deny", _webapp_deploy_dir,
        "/srv/docker/compose/webapp on the rpi is a deploy target, not source — the next CI "
        "run overwrites it. Edit homelab/RPI-srv/webapp/ in the repo instead, then rsync it "
        "over (copying into this dir is fine; editing in place is the trap).",
    ),
    (
        "git-write", "deny", _git_write,
        "Peter commits his own work — never run git commit/amend/push/reset --hard. Make the "
        "change, then say what needs committing.",
    ),
]

# ── conditional injections (never block) ───────────────────────────────────────
HINTS = [
    (
        lambda cmd: re.search(r"\bssh\s+android\b|192\.168\.1\.54|:8022", cmd),
        "android is port 8022, user u0_a204, and is frequently offline — treat failure as "
        "expected and degrade gracefully. It is unrooted, so privileged commands need adb "
        "over localhost.",
    ),
    (
        lambda cmd: re.search(r"\bgluetun\b|\bqbittorrent\b|forwarded_port", cmd),
        "Gluetun's NAT-PMP forwarded port dies silently and qBittorrent's listen port must "
        "track it. Check /var/lib/vpn-stack-heal/status.json on noblenumbat before assuming "
        "a torrent/VPN fault. Five containers share gluetun's netns, so stopping it takes "
        "them all offline by design.",
    ),
    (
        lambda cmd: re.search(r"\bpihole\b|\bdnsmasq\b|\bdhcp\b", cmd, re.I),
        "Pi-hole on the rpi is the LAN's only DNS *and* DHCP server. The Verizon router's "
        "DHCP must stay disabled — two DHCP servers race and present as 'all the servers are "
        "down'. Whitelist with `pihole allow <domain>`.",
    ),
]


def evaluate(tool, cmd, path):
    for rule_id, verdict, predicate, reason in RULES:
        try:
            if predicate(tool, cmd, path):
                return rule_id, verdict, reason
        except Exception:  # noqa: BLE001 — a broken rule must not block work
            continue
    return None, None, None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0  # unparseable input -> stay out of the way

    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    cmd = ti.get("command") or ""
    path = ti.get("file_path") or ti.get("notebook_path") or ""

    out = {"hookEventName": "PreToolUse"}
    rule_id, verdict, reason = evaluate(tool, cmd, path)

    if verdict:
        out["permissionDecision"] = verdict
        out["permissionDecisionReason"] = f"[{rule_id}] {reason}"
    else:
        hints = [text for match, text in HINTS if cmd and match(cmd)]
        if hints:
            out["additionalContext"] = "\n".join(f"Note: {h}" for h in hints)

    if len(out) > 1:
        json.dump({"hookSpecificOutput": out}, sys.stdout)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
