#!/usr/bin/env python3
"""
gen-workspace.py — generate workspace.json, the portable, tool-agnostic manifest of
this agentic workspace.

The point: everything an *agent* needs to pick up this workspace — where the repo lives,
where skills / rules / runbooks / harness notes are, and how a given tool discovers them —
described once, in plain JSON, so it survives a swap from Claude Code to Codex, Cursor, or
anything else. The canonical home is this folder: `homelab/agentic/` in the ptm4 repo.

Deterministic and stdlib-only (same convention as tools/collectors/docs-generator.py):
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
    "canonical_host": "ptm",
    "note": (
        "The working copy is E:\\REPO\\ptm4 on ptm (the Windows side of the workstation, "
        "local NTFS) since 2026-09-08; GitHub is the central copy. Edit there. opti holds "
        "only a .git-less deploy snapshot of homelab/ that opti-deploy.yml rsyncs on every "
        "push — never edit it. homelab/agentic/ is tracked in git except generated/ "
        "(written nightly on opti, pulled locally by probe.py --wire claude) and .claude/ "
        "(copies made by probe.py --wire claude), so nothing unique lives in either. "
        "Commit new rules/skills/hooks; uncommitted files exist only on disk."
    ),
    "access_paths": {
        "ptm_working_copy": "E:\\REPO\\ptm4",
        "opti_deploy_snapshot": "/srv/red/fs/ptm/repo/ptm4/homelab (rsync target, not git; read-only by convention)",
        "webapp_workspace_mount": "/workspace in the webapp container = /srv/red/fs/ptm/repo/ptm4 on opti, read-only",
    },
}

# LAN-only facts. No secrets — SSH keys/tokens are referenced by location elsewhere.
HOSTS = [
    {"alias": "ptm / tux", "ip": "192.168.1.3",
     "role": "The workstation, dual-booted: ptm = Windows 11 (holds the working copy, E:\\REPO\\ptm4; "
             "read-only asset server :8767), tux = CachyOS"},
    {"alias": "opti", "ip": "192.168.1.11",
     "role": "Storage (ZFS pool red -> Samba \\\\opti\\red; OMV UI-only; no second copy since the cold copy was retired 2026-09-24), "
             "control plane (agent dispatcher :9099, homelab-db :9100), x86 CI runner, and since 2026-09-10 the app tier "
             "(dashboard webapp.lan, Vaultwarden, notes, Dozzle, Discord bots, hltv-api)"},
    {"alias": "rpi", "ip": "192.168.1.10",
     "role": "DNS only: Pi-hole (DHCP is the router's since Sept 2026), Dozzle agent, ARM64 CI runner"},
    {"alias": "noblenumbat", "ip": "192.168.1.6",
     "role": "Media (Jellyfin, Kavita, *arr stack behind Gluetun), Uptime Kuma :3001, ntfy :2586"},
    {"alias": "android", "ip": "192.168.1.54",
     "role": "Galaxy S10 (Termux); local LLM (llama.cpp llama-server) on :8080, llama-ctl :8081; often offline"},
]

CURRENT_AGENT = {
    "tool": "Claude Code",
    "native_skill_discovery": ".claude/skills/<name>/SKILL.md",
    "discovery_link_design": (
        "Real skill and rule content lives in agentic/skills/<name>/ and agentic/rules/; "
        "Claude Code only discovers them under .claude/, so `probe.py --wire claude` COPIES "
        "them there (no symlinks: they need admin or Developer Mode on NTFS) and prunes "
        "copies whose source was removed. It also rewrites the CLAUDE.md pointer block, "
        "merges the harness hooks into .claude/settings.json, and pulls opti's "
        "agentic/generated/*.md. Edit the agentic/ sources, then re-wire."
    ),
    "config_files": ["CLAUDE.md", ".claude/settings.json", ".claude/settings.local.json", ".mcp.json"],
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
        "claude_code": "probe.py --wire claude copies agentic/skills -> .claude/skills and agentic/rules -> .claude/rules (auto-loaded); CLAUDE.md points here",
        "codex": "AGENTS.md points Codex at homelab/agentic; .codex/rules and .codex/skills hold copies (no automated wire in probe.py yet)",
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
        # "/" on every OS, so a run on Windows doesn't rewrite every path with "\\"
        files = sorted(
            os.path.relpath(os.path.join(r, fn), d).replace(os.sep, "/")
            for r, _, fns in os.walk(d) for fn in fns
            if "__pycache__" not in r
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


def scan_proposed():
    out = []
    base = os.path.join(HERE, "proposed")
    if not os.path.isdir(base):
        return out
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".md") or fn == "README.md":
            continue
        meta, _ = read_frontmatter(os.path.join(base, fn))
        out.append({
            "id": fn[:-3],
            "kind": meta.get("kind", ""),
            "name": meta.get("name", ""),
            "description": meta.get("description", ""),
            "rationale": meta.get("rationale", ""),
            "status": meta.get("status", "proposed"),
            "created": meta.get("created", ""),
            "created_by": meta.get("created_by", ""),
            "path": f"homelab/agentic/proposed/{fn}",
        })
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
            "runbooks. Displayed at webapp.lan and referenceable by agents."
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
        "proposed": scan_proposed(),
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
