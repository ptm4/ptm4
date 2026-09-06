<!-- agentic-workspace -->
# Agentic workspace

This repo's agent operating material lives under `homelab/agentic/` and is the
authoritative source for skills, rules, and runbooks. All of it is materialized
into `.Codex/` by `homelab/agentic/probe.py --wire Codex`.

- **Rules** — `homelab/agentic/rules/*.md`, copied to `.Codex/rules/` and
  therefore **auto-loaded every session**. Start with `01-homelab-context.md`:
  it already carries the host table, both SSH key regimes, and where the repo
  lives, so you should not need to grep for any of that.
- **Skills** — `homelab/agentic/skills/<name>/SKILL.md`. When a task matches a
  skill, follow that SKILL.md. Discovery copies land in `.Codex/skills/`.
- **Runbooks** — `homelab/agentic/runbooks/*.md` are per-host/subsystem reference,
  read on demand when the always-on context isn't enough.
- **Generated** — `homelab/agentic/generated/*.md` is refreshed nightly by the
  architecture agent. Prefer it over re-probing a host.
- **Harness** — `homelab/agentic/harness/README.md` explains the hooks that inject
  that context and enforce the standing rules.

See `homelab/agentic/workspace.json` for the machine-readable manifest.
<!-- /agentic-workspace -->
