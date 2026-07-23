#!/usr/bin/env python3
"""
propose.py — capture a candidate skill or rule that emerged from recurring work, park it in
`homelab/agentic/proposed/`, and (once you approve it) promote it into the real
`skills/` or `rules/` folders.

The idea: when a session notices the same task/pattern coming up repeatedly, it drops a
*proposal* here instead of silently reimplementing it. Proposals surface on the rpi webapp's
Agentic Workspace page, where you Promote (accept) or Dismiss them. Promotion is deliberate —
nothing auto-writes a skill without your click.

Proposal files: proposed/<kind>-<slug>.md  (kind = skill | rule), with YAML frontmatter
(kind, name, description, rationale, status, created, created_by) and a Markdown body that
becomes the SKILL.md procedure / rule text on promotion.

Commands:
  create --kind skill --name <slug> --desc "..." [--rationale "..."] [--body-file F | --body-stdin]
  list [--json]
  promote <id>          # id = filename without .md, e.g. rule-check-ignored-before-delete
  dismiss <id>
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PROPOSED = os.path.join(HERE, "proposed")
SKILLS = os.path.join(HERE, "skills")
RULES = os.path.join(HERE, "rules")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ID_RE = re.compile(r"^(skill|rule)-[a-z0-9][a-z0-9-]*$")   # what the dispatcher will accept


def die(msg, code=2):
    print(msg, file=sys.stderr); sys.exit(code)


def parse_frontmatter(text):
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                m = re.match(r"^([a-z_]+):\s*(.*)$", line.strip())
                if m:
                    meta[m.group(1)] = m.group(2).strip()
            body = text[end + 4:].lstrip("\n")
    return meta, body


def read_proposal(pid):
    if not ID_RE.match(pid):
        die(f"invalid proposal id: {pid}")
    path = os.path.join(PROPOSED, pid + ".md")
    if not os.path.isfile(path):
        die(f"no such proposal: {pid}")
    meta, body = parse_frontmatter(open(path, encoding="utf-8").read())
    return path, meta, body


def cmd_create(a):
    if not SLUG_RE.match(a.name):
        die("--name must be a lowercase slug (a-z0-9-)")
    if a.kind not in ("skill", "rule"):
        die("--kind must be skill or rule")
    body = ""
    if a.body_file:
        body = open(a.body_file, encoding="utf-8").read()
    elif a.body_stdin:
        body = sys.stdin.read()
    os.makedirs(PROPOSED, exist_ok=True)
    pid = f"{a.kind}-{a.name}"
    path = os.path.join(PROPOSED, pid + ".md")
    fm = (
        "---\n"
        f"kind: {a.kind}\n"
        f"name: {a.name}\n"
        f"description: {a.desc}\n"
        f"rationale: {a.rationale or ''}\n"
        "status: proposed\n"
        f"created: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        f"created_by: {a.by or os.environ.get('HL_AGENT', 'session')}\n"
        "---\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + (body or f"# {a.name}\n\n_Draft — fill in the {a.kind}._\n"))
    print(f"created {path} (id: {pid})")


def cmd_list(a):
    items = []
    for fn in sorted(os.listdir(PROPOSED)) if os.path.isdir(PROPOSED) else []:
        if fn.endswith(".md"):
            meta, _ = parse_frontmatter(open(os.path.join(PROPOSED, fn), encoding="utf-8").read())
            items.append({"id": fn[:-3], **meta})
    if a.json:
        import json
        print(json.dumps(items, indent=2))
    else:
        for it in items:
            print(f"  {it['id']:40} {it.get('kind',''):5} — {it.get('description','')}")
        if not items:
            print("  (no proposals)")


def cmd_promote(a):
    path, meta, body = read_proposal(a.id)
    kind, name = meta.get("kind"), meta.get("name")
    if not name or not SLUG_RE.match(name):
        die("proposal missing a valid name")
    if kind == "skill":
        dest_dir = os.path.join(SKILLS, name)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, "SKILL.md")
        if os.path.exists(dest):
            die(f"skill already exists: skills/{name}/SKILL.md")
        fm = f"---\nname: {name}\ndescription: {meta.get('description','')}\n---\n\n"
        # Drop a leading "# name" from the body if present; frontmatter carries identity.
        open(dest, "w", encoding="utf-8").write(fm + body.strip() + "\n")
        made = f"skills/{name}/SKILL.md"
    elif kind == "rule":
        os.makedirs(RULES, exist_ok=True)
        dest = os.path.join(RULES, f"{name}.md")
        if os.path.exists(dest):
            die(f"rule already exists: rules/{name}.md")
        open(dest, "w", encoding="utf-8").write(body.strip() + "\n")
        made = f"rules/{name}.md"
    else:
        die(f"unknown kind in proposal: {kind}")
    os.remove(path)
    print(f"promoted {a.id} -> homelab/agentic/{made}")


def cmd_dismiss(a):
    path, _, _ = read_proposal(a.id)
    os.remove(path)
    print(f"dismissed {a.id}")


def main():
    p = argparse.ArgumentParser(description="capture/promote agentic skill & rule proposals")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create"); c.set_defaults(fn=cmd_create)
    c.add_argument("--kind", required=True); c.add_argument("--name", required=True)
    c.add_argument("--desc", required=True); c.add_argument("--rationale", default="")
    c.add_argument("--by", default=""); c.add_argument("--body-file", dest="body_file")
    c.add_argument("--body-stdin", dest="body_stdin", action="store_true")

    l = sub.add_parser("list"); l.set_defaults(fn=cmd_list); l.add_argument("--json", action="store_true")
    pr = sub.add_parser("promote"); pr.set_defaults(fn=cmd_promote); pr.add_argument("id")
    d = sub.add_parser("dismiss"); d.set_defaults(fn=cmd_dismiss); d.add_argument("id")

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
