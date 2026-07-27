#!/usr/bin/env python3
"""
gen-agentic-docs.py — renders homelab/agentic/generated/*.md from the live merged
architecture data (curated facts ⊕ per-host agent fragments).

Distinct audience from docs-generator.py: that script writes
agent-logs/generated-docs/*.md for the phone's local LLM assistant. This one writes
homelab/agentic/generated/*.md — the inventory an AI *coding* agent (Claude Code etc.)
consults instead of re-probing the homelab, wired into every session via
rules/01-homelab-context.md. Different reader, different directory, so kept separate
rather than bolted onto the existing generator.

Source of data: the webapp's GET /api/architecture/data (routes/architecture.js),
fetched over HTTPS rather than read from disk. Two reasons:
  1. That endpoint already computes the curated+live merge — reimplementing the merge
     here in Python would be a second copy of the same logic to keep in sync.
  2. It's the one place all three hosts' facts have already landed, regardless of
     which host this script runs from.

Fully regenerated every run, no hand-edited content preserved — these are derived
navigation aids, not curated prose (that boundary is the whole design: see
routes/architecture.js's module docstring). A stale doc here is strictly worse than a
missing one, so every doc carries a generation timestamp and a "how current" line.

Usage:
    python3 gen-agentic-docs.py [--url URL] [--out DIR]

Env (same names the fetching side already uses, for consistency):
  HL_ARCH_DATA_URL   default https://webapp.rpi.lan:8443/api/architecture/data
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_URL = os.environ.get("HL_ARCH_DATA_URL", "https://webapp.rpi.lan:8443/api/architecture/data")
DEFAULT_OUT = os.path.join(REPO_ROOT, "homelab", "agentic", "generated")

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url, timeout=15):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE   # self-signed, LAN-only — same trust boundary as hl-arch-agent.py
    with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:
        return json.load(resp)


def banner(title, source):
    return (
        f"# {title}\n\n"
        f"> ⚙️ **AUTO-GENERATED — do not hand-edit.** Rewritten each run by "
        f"`homelab/tools/architecture/gen-agentic-docs.py` from `{source}`. Any manual "
        f"change here is overwritten on the next run.\n"
        f"> Generated: `{NOW}`\n\n"
    )


def table(headers, rows):
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) if c not in (None, "") else "—" for c in r) + " |")
    return "\n".join(out) + "\n"


def age_str(iso):
    if not iso:
        return "unknown"
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    if hours < 1:
        return f"{int(hours * 60)}m ago"
    if hours < 48:
        return f"{hours:.0f}h ago"
    return f"{hours / 24:.0f}d ago"


def doc_inventory(data):
    lm = data.get("live_merge") or {}
    ingested = lm.get("ingested") or {}
    out = [banner("Homelab Inventory (live)", "GET /api/architecture/data")]

    out.append("## Agent sync status\n")
    rows = [[h, i.get("agent_version"), f"{age_str(i.get('collected_at'))}",
            i.get("containers"), ", ".join(i.get("errors") or {}) or "none"]
           for h, i in sorted(ingested.items())]
    out.append(table(["Host", "Agent", "Last synced", "Containers", "Collection errors"], rows))

    out.append("\n## Nodes\n")
    out.append("Every node on the architecture map. `Live` columns come from the newest "
               "agent sync where available; blank means no agent has reported that host, "
               "not that the thing is down — check Agent sync status above.\n")
    by_host = {}
    for n in data.get("nodes", []):
        by_host.setdefault(n["host"], []).append(n)
    host_label = {h["id"]: h["label"] for h in data.get("hosts", [])}

    for host in sorted(by_host, key=lambda h: host_label.get(h, h)):
        out.append(f"\n### {host_label.get(host, host)}\n")
        rows = []
        for n in sorted(by_host[host], key=lambda n: n["label"]):
            live = n.get("_live") or {}
            rows.append([
                n["label"], n.get("category"), n.get("container") or "—",
                live.get("state", "—" if n.get("container") else "n/a"),
                live.get("image") or n.get("image") or "—",
                n.get("sublabel") or "",
            ])
        out.append(table(["Node", "Plane", "Container", "State", "Image", "Summary"], rows))

    return "\n".join(out)


def doc_drift(data):
    lm = data.get("live_merge") or {}
    drift = lm.get("drift") or {}
    undescribed, missing = drift.get("undescribed") or [], drift.get("missing") or []
    out = [banner("Homelab Drift", "GET /api/architecture/data")]

    out.append(
        "Where the architecture map and reality disagree, as of the last agent sync. "
        "This is a TODO list, not a health report: an empty section means nothing to do, "
        "not that everything is fine — cross-check `90-homelab-inventory.md`'s sync ages.\n"
    )

    out.append(f"\n## Running, not described on the map · {len(undescribed)}\n")
    out.append(
        "A container an agent found that has no matching node in the architecture data. "
        "Either add it to `homelab/tools/architecture/build-arch-data.py`'s NODES, or if "
        "it's expected to be transient/unmanaged, leave it — this list is informational, "
        "nothing acts on it automatically.\n"
    )
    out.append(table(["Host", "Container", "Image", "State"],
                     [[d["host"], d["container"], d.get("image"), d.get("state")] for d in undescribed]))

    out.append(f"\n## Described, not detected · {len(missing)}\n")
    out.append(
        "A node on the map with a `container` field that the matching host's agent did "
        "NOT find — likely renamed, removed, or recreated under a different container "
        "name. A compose recreate can also leave the old container behind under a "
        "`-old-<id>` suffix; that shows up as a *separate* entry in the section above, "
        "since it's a different container name.\n"
    )
    out.append(table(["Host", "Container", "Was described as"],
                     [[m["host"], m["container"], m.get("label")] for m in missing]))

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    try:
        data = fetch(args.url)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        print(f"[gen-agentic-docs] could not fetch {args.url}: {e}", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    docs = [
        ("90-homelab-inventory.md", doc_inventory(data)),
        ("91-homelab-drift.md", doc_drift(data)),
    ]
    for name, content in docs:
        path = os.path.join(args.out, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.rstrip() + "\n")
        print(f"[gen-agentic-docs] wrote {path} ({len(content)} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
