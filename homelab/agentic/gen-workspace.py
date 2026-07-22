#!/usr/bin/env python3
"""
gen-workspace.py — generate workspace.json, the portable, tool-agnostic manifest of
this agentic workspace.

The point: everything an *agent* needs to pick up this workspace — where the repo lives,
where skills / rules / runbooks / harness notes are, and how a given tool discovers them —
described once, in plain JSON, so it survives a swap from Claude Code to Codex, Cursor, or
anything else. The canonical home is this folder: `homelab/agentic/` in the ptm4 repo.

Deterministic and stdlib-only (same convention as Tools/homelab/docs-generator.py):
  - The *inventory* (skills/rules/runbooks/harness) is scanned from the filesystem so it
    never drifts from reality.
  - The *facts* (workspace paths, hosts, portability guidance) are embedded below; edit
    them here when the setup changes, then re-run.

Usage:  python3 homelab/agentic/gen-workspace.py [--print]
Writes: homelab/agentic/workspace.json  (next to this script)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "workspace.json")

# ── embedded facts (edit here, then re-run) ─────────────────────────────────────

WORKSPACE = {
    "repo": "ptm4",
    "git_remote": "https://github.com/ptm4/ptm4.git",
    "agentic_root": "homelab/agentic",
    "canonical_host": "opti",
    "note": (
        "Canonical working copy lives on opti's fs share. Edit there (directly on opti "
        "or via a CIFS mount). homelab/agentic/ is gitignored — it is local-only content, "
        "NOT on GitHub, so keep it here and back it up out-of-band."
    ),
    "access_paths": {
        "opti_native": "/srv/dev-disk-by-uuid-C682C2DE82C2D1DB/fs/ptm/repo/ptm4",
        "tux_cifs_mount": "/home/ptm/opti/ptm/repo/ptm4",
        "rpi_cifs_mount": "/mnt/opti-fs/ptm/repo/ptm4",
    },
}

# LAN-only facts. No secrets — SSH keys/tokens are referenced by location elsewhere.
HOSTS = [
    {"alias": "opti", "ip": "192.168.1.11",
     "role": "Storage/NAS (OpenMediaVault, mergerfs pool /srv/pool, Samba), CI runner, control plane / agent dispatcher"},
    {"alias": "rpi", "ip": "192.168.1.10",
     "role": "DNS (Pi-hole v6), homelab dashboard webapp (webapp.rpi.lan), Vaultwarden"},
    {"alias": "noblenumbat", "ip": "192.168.1.6",
     "role": "Media server (Jellyfin, Radarr/Sonarr). Was a code server 2026-07-20; reverted 2026-07-22"},
    {"alias": "android", "ip": "192.168.1.54",
     "role": "Low-power node; local LLM (llama.cpp llama-server, Qwen2.5-3B) on :8080, LAN-only"},
]

CURRENT_AGENT = {
    "tool": "Claude Code",
    "native_skill_discovery": ".claude/skills/<name>/SKILL.md",
    "discovery_link_design": (
        "Real skill content lives in agentic/skills/<name>/; Claude Code only discovers "
        "skills under .claude/skills/, so each is meant to be exposed via a symlink "
        ".claude/skills/<name> -> ../../homelab/agentic/skills/<name>. NOTE: symlinks are "
        "not supported on the tux CIFS mount (create them on opti natively, or fall back "
        "to real copies)."
    ),
    "config_files": [".claude/settings.local.json", ".claude/ONBOARDING.md"],
}

PORTABILITY = {
    "summary": (
        "This workspace is described tool-agnostically. Skills are folders with a SKILL.md "
        "(YAML frontmatter: name + description, then a Markdown procedure). Rules are "
        "standing behavioral Markdown files. Runbooks are per-host/subsystem operational "
        "Markdown. Any agent can read these directly; only the *discovery* wiring differs "
        "per tool."
    ),
    "for_a_new_tool": [
        "Point the tool at homelab/agentic/ as the source of truth.",
        "Load agentic/rules/*.md as always-on system rules.",
        "Register each agentic/skills/<name> per the tool's skill/command mechanism.",
        "Treat agentic/runbooks/*.md as retrievable reference docs.",
    ],
    "tool_adapters": {
        "claude_code": ".claude/skills/<name> symlink -> agentic/skills/<name>; rules via CLAUDE.md / settings",
        "codex": "TODO: copy/symlink agentic/skills into the Codex skills dir; surface rules via AGENTS.md",
        "cursor": "TODO: reference agentic/rules from .cursor/rules; skills as callable commands",
    },
}

# ── filesystem inventory (scanned; never hand-edited) ───────────────────────────

def read_frontmatter(path):
    """Return (meta_dict, first_heading) from a Markdown file with optional YAML frontmatter."""
    meta, heading = {}, None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return meta, heading
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line.strip())
                if m:
                    meta[m.group(1)] = m.group(2).strip()
            text = text[end + 4:]
    for line in text.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            break
    return meta, heading


def rel(path):
    return os.path.relpath(path, os.path.dirname(os.path.dirname(HERE)))  # repo-relative-ish (from homelab/..)


def scan_skills():
    out = []
    base = os.path.join(HERE, "skills")
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if not os.path.isdir(d):
            continue
        skillmd = os.path.join(d, "SKILL.md")
        meta, _ = read_frontmatter(skillmd) if os.path.exists(skillmd) else ({}, None)
        files = sorted(
            os.path.relpath(os.path.join(r, fn), d)
            for r, _, fns in os.walk(d) for fn in fns
        )
        entry = {
            "name": meta.get("name", name),
            "description": meta.get("description", ""),
            "path": f"homelab/agentic/skills/{name}",
            "files": files,
        }
        if not os.path.exists(skillmd):
            entry["status"] = "missing SKILL.md"
        elif "RECOVERY STUB" in open(skillmd, encoding="utf-8", errors="ignore").read():
            entry["status"] = "recovery-stub (re-author)"
        out.append(entry)
    return out


def scan_md_dir(sub):
    out = []
    base = os.path.join(HERE, sub)
    if not os.path.isdir(base):
        return out
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(base, fn)
        _, heading = read_frontmatter(p)
        entry = {"file": fn, "path": f"homelab/agentic/{sub}/{fn}", "title": heading or fn}
        if "RECOVERY STUB" in open(p, encoding="utf-8", errors="ignore").read():
            entry["status"] = "recovery-stub (re-author)"
        out.append(entry)
    return out


def build():
    return {
        "schema_version": "1.0",
        "kind": "agentic-workspace-manifest",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "homelab/agentic/gen-workspace.py",
        "purpose": (
            "Portable, tool-agnostic description of this workspace so any coding agent "
            "(Claude Code, Codex, Cursor, ...) can pick up the same skills, rules, and "
            "runbooks. Displayed at webapp.rpi.lan and referenceable by agents."
        ),
        "workspace": WORKSPACE,
        "current_agent": CURRENT_AGENT,
        "portability": PORTABILITY,
        "hosts": HOSTS,
        "inventory": {
            "skills": scan_skills(),
            "rules": scan_md_dir("rules"),
            "runbooks": scan_md_dir("runbooks"),
            "harness": scan_md_dir("harness"),
        },
    }


def main():
    data = build()
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if "--print" in sys.argv:
        sys.stdout.write(text)
        return
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    inv = data["inventory"]
    print(f"wrote {OUT}")
    print(f"  skills={len(inv['skills'])} rules={len(inv['rules'])} "
          f"runbooks={len(inv['runbooks'])} harness={len(inv['harness'])}")


if __name__ == "__main__":
    main()
