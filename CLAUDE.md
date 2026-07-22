<!-- agentic-workspace -->
# Agentic workspace

This repo's agent operating material lives under `homelab/agentic/` and is the
authoritative source for skills, rules, and runbooks:

- **Skills** — `homelab/agentic/skills/<name>/SKILL.md`. When a task matches a
  skill, follow that SKILL.md. Discovery copies are materialized into
  `.claude/skills/` by `homelab/agentic/probe.py --wire claude`.
- **Rules** — `homelab/agentic/rules/*.md` are standing behavioral rules; honor them.
- **Runbooks** — `homelab/agentic/runbooks/*.md` are per-host/subsystem reference.

See `homelab/agentic/workspace.json` for the machine-readable manifest.
