#!/usr/bin/env python3
"""
probe.py — detect which coding-agent tooling is installed on THIS host and whether the
workspace is correctly wired to the agentic folder, then write the result to
`homelab/agentic/status/<hostname>.json` so the rpi webapp can display it.

Why per-host: the webapp runs on rpi and the workspace lives on opti, but a coding agent
(Claude Code, Codex, Cursor, ...) runs on whatever workstation you're at (e.g. tux). Only
that host can see its own installed tooling, so each host drops its own status file. The
files live under the (mounted) agentic folder, so the webapp reads them without reaching
back across machines.

Tool detection is a **modular registry** (DETECTORS below): add a dict to support a new
tool. Wiring checks are file-based against the repo root, so they're accurate on any host
that can see the workspace.

Usage:
  python3 homelab/agentic/probe.py                 # detect + write status/<host>.json
  python3 homelab/agentic/probe.py --print         # print, don't write
  python3 homelab/agentic/probe.py --wire claude   # create the Claude wiring, then re-probe
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))   # homelab/agentic -> repo root
STATUS_DIR = os.path.join(HERE, "status")
AGENTIC_REL = "homelab/agentic"

CANONICAL_BASENAMES = ("ptm4",)
EXPECTED_REMOTE = "github.com/ptm4/ptm4"


# ── helpers ─────────────────────────────────────────────────────────────────────

def sh(*args):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=8)
        return (out.returncode, (out.stdout or out.stderr).strip())
    except Exception as e:
        return (127, str(e))


def which(cmd):
    return shutil.which(cmd)


def skill_names():
    d = os.path.join(REPO_ROOT, AGENTIC_REL, "skills")
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)))


def rule_names():
    """Standing rules, as bare filenames. These become .claude/rules/<name>, which
    Claude Code auto-loads every session (a rule without `paths:` frontmatter loads
    unconditionally), so this is the always-on context layer of the harness."""
    d = os.path.join(REPO_ROOT, AGENTIC_REL, "rules")
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d) if n.endswith(".md"))


def hook_specs():
    """The harness hooks we wire into .claude/settings.json.

    Kept here (rather than only in settings.json) so `--wire claude` can rebuild the
    harness from scratch — settings.json and the whole .claude/ tree are gitignored and
    have been lost once already.
    """
    hooks_rel = f"{AGENTIC_REL}/harness/hooks"
    return {
        # Layer 2 — deterministic context injection. Cannot block; just guarantees the
        # homelab facts are present without the agent spending calls to discover them.
        "SessionStart": [{
            "hooks": [{
                "type": "command",
                "command": f'python3 "$CLAUDE_PROJECT_DIR/{hooks_rel}/session-context.py"',
            }],
        }],
        # Layer 3 — real enforcement. Returns permissionDecision:"deny" for the
        # known-wrong actions, and injects a runbook pointer when a host is named.
        "PreToolUse": [{
            "matcher": "Bash|Edit|Write|NotebookEdit",
            "hooks": [{
                "type": "command",
                "command": f'python3 "$CLAUDE_PROJECT_DIR/{hooks_rel}/homelab-guard.py"',
            }],
        }],
    }


def check(_id, label, ok, detail=""):
    return {"id": _id, "label": label, "status": "pass" if ok else "fail", "detail": detail}


# ── modular tool detectors ──────────────────────────────────────────────────────
# Each detector: detect() -> {installed, version, path, extra}; wire_checks() -> [check,...]
# wire() -> (changed:bool, msg) is optional (only implemented where wiring is supported).

def _claude_detect():
    p = which("claude")
    ver = None
    if p:
        rc, out = sh("claude", "--version")
        if rc == 0:
            m = re.search(r"[\d.]+", out)
            ver = m.group(0) if m else out
    return {"installed": bool(p), "version": ver, "path": p, "extra": {}}


def _claude_wire_checks():
    checks = []
    # 1. CLAUDE.md pointing at agentic
    claude_md = os.path.join(REPO_ROOT, "CLAUDE.md")
    has_md = os.path.exists(claude_md)
    refs = has_md and (AGENTIC_REL in open(claude_md, encoding="utf-8", errors="ignore").read())
    checks.append(check("claude_md", "CLAUDE.md directs Claude to homelab/agentic",
                        refs, "present & references agentic" if refs else
                        ("CLAUDE.md exists but no agentic reference" if has_md else "no CLAUDE.md")))
    # 2. .claude/skills discovery entries for each agentic skill
    names = skill_names()
    skills_dir = os.path.join(REPO_ROOT, ".claude", "skills")
    present = [n for n in names if os.path.exists(os.path.join(skills_dir, n, "SKILL.md"))]
    ok = names and len(present) == len(names)
    checks.append(check("claude_skills", ".claude/skills registers all agentic skills",
                        ok, f"{len(present)}/{len(names)} discoverable" +
                        ("" if ok else f" (missing: {sorted(set(names)-set(present))})")))
    # 3. .claude/rules copies — the always-on context layer
    rnames = rule_names()
    rules_dir = os.path.join(REPO_ROOT, ".claude", "rules")
    rpresent = [n for n in rnames if os.path.exists(os.path.join(rules_dir, n))]
    rok = bool(rnames) and len(rpresent) == len(rnames)
    checks.append(check("claude_rules", ".claude/rules registers all agentic rules",
                        rok, f"{len(rpresent)}/{len(rnames)} auto-loaded" +
                        ("" if rok else f" (missing: {sorted(set(rnames)-set(rpresent))})")))
    # 4. settings present
    sl = os.path.join(REPO_ROOT, ".claude", "settings.local.json")
    checks.append(check("claude_settings", ".claude settings present", os.path.exists(sl),
                        "settings.local.json found" if os.path.exists(sl) else "none"))
    # 5. harness hooks actually wired — the only layer that can *enforce* anything, so
    #    drift here silently downgrades the harness to advice.
    settings = os.path.join(REPO_ROOT, ".claude", "settings.json")
    wired_events = []
    try:
        with open(settings, encoding="utf-8") as f:
            conf = json.load(f)
        for event in hook_specs():
            entries = conf.get("hooks", {}).get(event) or []
            joined = json.dumps(entries)
            if "harness/hooks" in joined:
                wired_events.append(event)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    want = list(hook_specs())
    hok = len(wired_events) == len(want)
    checks.append(check("claude_hooks", "harness hooks wired in .claude/settings.json", hok,
                        f"{len(wired_events)}/{len(want)} events wired" +
                        ("" if hok else f" (missing: {sorted(set(want)-set(wired_events))})")))
    # 6. the hook scripts exist and are syntactically valid — a hook that crashes is a
    #    hook that silently stops enforcing.
    missing_scripts = []
    hooks_dir = os.path.join(REPO_ROOT, AGENTIC_REL, "harness", "hooks")
    for script in ("session-context.py", "homelab-guard.py"):
        p = os.path.join(hooks_dir, script)
        if not os.path.exists(p):
            missing_scripts.append(script)
            continue
        rc, _ = sh(sys.executable, "-m", "py_compile", p)
        if rc != 0:
            missing_scripts.append(f"{script} (syntax error)")
    checks.append(check("claude_hook_scripts", "harness hook scripts present & valid",
                        not missing_scripts,
                        "ok" if not missing_scripts else f"problem: {missing_scripts}"))
    return checks


def _claude_wire():
    """Create the wiring so Claude actually uses the agentic folder. Idempotent."""
    changed = []
    # ── CLAUDE.md pointer ──────────────────────────────────────────────────────
    # Delimited by start+end markers and rewritten in place, so the block can be
    # *updated*. The previous version only appended when the marker was absent, which
    # meant a stale block could never be corrected.
    claude_md = os.path.join(REPO_ROOT, "CLAUDE.md")
    marker, end_marker = "<!-- agentic-workspace -->", "<!-- /agentic-workspace -->"
    block = (
        f"{marker}\n"
        "# Agentic workspace\n\n"
        "This repo's agent operating material lives under `homelab/agentic/` and is the\n"
        "authoritative source for skills, rules, and runbooks. All of it is materialized\n"
        "into `.claude/` by `homelab/agentic/probe.py --wire claude`.\n\n"
        "- **Rules** — `homelab/agentic/rules/*.md`, copied to `.claude/rules/` and\n"
        "  therefore **auto-loaded every session**. Start with `01-homelab-context.md`:\n"
        "  it already carries the host table, both SSH key regimes, and where the repo\n"
        "  lives, so you should not need to grep for any of that.\n"
        "- **Skills** — `homelab/agentic/skills/<name>/SKILL.md`. When a task matches a\n"
        "  skill, follow that SKILL.md. Discovery copies land in `.claude/skills/`.\n"
        "- **Runbooks** — `homelab/agentic/runbooks/*.md` are per-host/subsystem reference,\n"
        "  read on demand when the always-on context isn't enough.\n"
        "- **Generated** — `homelab/agentic/generated/*.md` is refreshed nightly by the\n"
        "  architecture agent. Prefer it over re-probing a host.\n"
        "- **Harness** — `homelab/agentic/harness/README.md` explains the hooks that inject\n"
        "  that context and enforce the standing rules.\n\n"
        "See `homelab/agentic/workspace.json` for the machine-readable manifest.\n"
        f"{end_marker}\n"
    )
    existing = open(claude_md, encoding="utf-8").read() if os.path.exists(claude_md) else ""
    if marker in existing and end_marker in existing:
        head, _, rest = existing.partition(marker)
        _, _, tail = rest.partition(end_marker)
        updated = head + block.rstrip("\n") + tail
    elif marker in existing:
        # Legacy un-delimited block: replace from the marker to the end of file.
        updated = existing.partition(marker)[0] + block
    else:
        updated = (existing + ("\n" if existing and not existing.endswith("\n") else "")
                   + ("\n" if existing else "") + block)
    if updated != existing:
        with open(claude_md, "w", encoding="utf-8") as f:
            f.write(updated)
        changed.append("CLAUDE.md")

    # ── .claude/skills + .claude/rules (copies — symlinks fail on the CIFS mount) ──
    src = os.path.join(REPO_ROOT, AGENTIC_REL, "skills")
    dst = os.path.join(REPO_ROOT, ".claude", "skills")
    os.makedirs(dst, exist_ok=True)
    for name in skill_names():
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.exists(d):
            shutil.rmtree(d)
        shutil.copytree(s, d)
        changed.append(f".claude/skills/{name}")

    rsrc = os.path.join(REPO_ROOT, AGENTIC_REL, "rules")
    rdst = os.path.join(REPO_ROOT, ".claude", "rules")
    if rule_names():
        os.makedirs(rdst, exist_ok=True)
    for name in rule_names():
        shutil.copyfile(os.path.join(rsrc, name), os.path.join(rdst, name))
        changed.append(f".claude/rules/{name}")

    # ── hooks into .claude/settings.json ──────────────────────────────────────────
    # Merge, never replace: only our harness entries are managed here, so any hook or
    # setting added by hand survives. Identified by the "harness/hooks" path.
    settings_path = os.path.join(REPO_ROOT, ".claude", "settings.json")
    try:
        with open(settings_path, encoding="utf-8") as f:
            conf = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        conf = {}
    before = json.dumps(conf, sort_keys=True)
    conf.setdefault("hooks", {})
    for event, entries in hook_specs().items():
        others = [e for e in (conf["hooks"].get(event) or [])
                  if "harness/hooks" not in json.dumps(e)]
        conf["hooks"][event] = others + entries
    if json.dumps(conf, sort_keys=True) != before:
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        tmp = settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(conf, f, indent=2)
            f.write("\n")
        os.replace(tmp, settings_path)
        changed.append(".claude/settings.json (hooks)")

    return (bool(changed), "wired: " + ", ".join(changed) if changed else "already wired")


def _codex_detect():
    p = which("codex")
    ver = None
    if p:
        rc, out = sh("codex", "--version")
        ver = re.search(r"[\d.]+", out).group(0) if (rc == 0 and re.search(r"[\d.]+", out)) else None
    return {"installed": bool(p), "version": ver, "path": p, "extra": {}}


def _codex_wire_checks():
    agents_md = os.path.join(REPO_ROOT, "AGENTS.md")
    refs = os.path.exists(agents_md) and (AGENTIC_REL in open(agents_md, encoding="utf-8", errors="ignore").read())
    return [check("codex_agents_md", "AGENTS.md directs Codex to homelab/agentic", refs,
                  "present & references agentic" if refs else "not wired (Phase 2)")]


def _cursor_detect():
    p = which("cursor") or which("cursor-agent")
    return {"installed": bool(p), "version": None, "path": p, "extra": {}}


def _cursor_wire_checks():
    rules_dir = os.path.join(REPO_ROOT, ".cursor", "rules")
    ok = os.path.isdir(rules_dir) and any(
        AGENTIC_REL in open(os.path.join(rules_dir, f), encoding="utf-8", errors="ignore").read()
        for f in os.listdir(rules_dir)
    ) if os.path.isdir(rules_dir) else False
    return [check("cursor_rules", ".cursor/rules reference homelab/agentic", ok,
                  "wired" if ok else "not wired (Phase 2)")]


DETECTORS = {
    "claude": {"label": "Claude Code", "detect": _claude_detect,
               "wire_checks": _claude_wire_checks, "wire": _claude_wire},
    "codex":  {"label": "Codex", "detect": _codex_detect,
               "wire_checks": _codex_wire_checks, "wire": None},
    "cursor": {"label": "Cursor", "detect": _cursor_detect,
               "wire_checks": _cursor_wire_checks, "wire": None},
}


# ── workspace check ─────────────────────────────────────────────────────────────

def workspace_status():
    root_real = os.path.realpath(REPO_ROOT)
    rc, remote = sh("git", "-C", REPO_ROOT, "remote", "get-url", "origin")
    remote_ok = rc == 0 and EXPECTED_REMOTE in remote
    return {
        "repo_root": REPO_ROOT,
        "repo_root_realpath": root_real,
        "basename_ok": os.path.basename(root_real.rstrip("/")) in CANONICAL_BASENAMES,
        "git_remote": remote if rc == 0 else None,
        "git_remote_ok": remote_ok,
        "agentic_dir_present": os.path.isdir(os.path.join(REPO_ROOT, AGENTIC_REL)),
    }


# ── build + write ───────────────────────────────────────────────────────────────

def build():
    tools = []
    for key, d in DETECTORS.items():
        info = d["detect"]()
        checks = d["wire_checks"]() if info["installed"] else []
        wired = bool(checks) and all(c["status"] == "pass" for c in checks)
        tools.append({
            "key": key, "name": d["label"], **info,
            "wireable": d.get("wire") is not None,
            "wiring": checks, "wired": wired if info["installed"] else None,
        })
    return {
        "host": socket.gethostname(),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "homelab/agentic/probe.py",
        "workspace": workspace_status(),
        "tools": tools,
    }


def main():
    argv = sys.argv[1:]
    if "--wire" in argv:
        i = argv.index("--wire")
        tool = argv[i + 1] if i + 1 < len(argv) else ""
        d = DETECTORS.get(tool)
        if not d or not d.get("wire"):
            print(f"no wiring available for tool '{tool}'"); sys.exit(2)
        changed, msg = d["wire"]()
        print(msg)
    data = build()
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if "--print" in argv:
        sys.stdout.write(text); return
    os.makedirs(STATUS_DIR, exist_ok=True)
    out = os.path.join(STATUS_DIR, f"{data['host']}.json")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    inst = [t["name"] for t in data["tools"] if t["installed"]]
    print(f"wrote {out}")
    print(f"  host={data['host']} workspace_ok={data['workspace']['git_remote_ok']} installed={inst}")


if __name__ == "__main__":
    main()
