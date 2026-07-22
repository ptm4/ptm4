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
    # 3. settings present
    sl = os.path.join(REPO_ROOT, ".claude", "settings.local.json")
    checks.append(check("claude_settings", ".claude settings present", os.path.exists(sl),
                        "settings.local.json found" if os.path.exists(sl) else "none"))
    return checks


def _claude_wire():
    """Create the wiring so Claude actually uses the agentic folder. Idempotent."""
    changed = []
    # CLAUDE.md pointer
    claude_md = os.path.join(REPO_ROOT, "CLAUDE.md")
    marker = "<!-- agentic-workspace -->"
    block = (
        f"{marker}\n"
        "# Agentic workspace\n\n"
        "This repo's agent operating material lives under `homelab/agentic/` and is the\n"
        "authoritative source for skills, rules, and runbooks:\n\n"
        "- **Skills** — `homelab/agentic/skills/<name>/SKILL.md`. When a task matches a\n"
        "  skill, follow that SKILL.md. Discovery copies are materialized into\n"
        "  `.claude/skills/` by `homelab/agentic/probe.py --wire claude`.\n"
        "- **Rules** — `homelab/agentic/rules/*.md` are standing behavioral rules; honor them.\n"
        "- **Runbooks** — `homelab/agentic/runbooks/*.md` are per-host/subsystem reference.\n\n"
        "See `homelab/agentic/workspace.json` for the machine-readable manifest.\n"
    )
    existing = open(claude_md, encoding="utf-8").read() if os.path.exists(claude_md) else ""
    if marker not in existing:
        with open(claude_md, "a" if existing else "w", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(("\n" if existing else "") + block)
        changed.append("CLAUDE.md")
    # Materialize .claude/skills copies (symlinks fail on CIFS)
    src = os.path.join(REPO_ROOT, AGENTIC_REL, "skills")
    dst = os.path.join(REPO_ROOT, ".claude", "skills")
    os.makedirs(dst, exist_ok=True)
    for name in skill_names():
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.exists(d):
            shutil.rmtree(d)
        shutil.copytree(s, d)
        changed.append(f".claude/skills/{name}")
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
