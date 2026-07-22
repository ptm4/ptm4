# Where agentic files live

All homelab-operations material for agents — skills, standing rules, reference `.md`
docs, and harness config (permissions/hooks/settings notes) — lives under
`homelab/agentic/`, one respective subfolder each:

- `homelab/agentic/skills/` — Claude Code skills (each its own folder with `SKILL.md`).
  Since Claude Code only discovers skills under `.claude/skills/`, each skill here has a
  matching symlink at `.claude/skills/<name>` pointing back into this folder. The skill
  content lives here; `.claude/skills/` just holds the discovery pointer.
- `homelab/agentic/rules/` — standing behavioral rules for agents working this repo
  (this file is one).
- `homelab/agentic/runbooks/` — per-host / per-subsystem operational reference (hosts,
  network, VPN, local LLM, etc.).
- `homelab/agentic/harness/` — notes on the Claude Code harness itself: permission
  allowlists, hooks, settings — anything about *how the agent runs*, as opposed to how
  the homelab runs.

If a file doesn't fit an existing subfolder, create the right one under
`homelab/agentic/` rather than dropping it elsewhere in the repo (`.claude/`, repo root,
scattered per-host dirs). This whole tree is gitignored (see `.gitignore`) — it's local
operational material, not part of the tracked repo content.

## Rule: use skills for host access

When a query names a homelab host (`opti`, `rpi`, `noblenumbat`, `android`) and the task
needs actual shell access to it, use the [`homelab-ssh`](../skills/homelab-ssh/SKILL.md)
skill rather than hand-rolling an `ssh` command — it points at the current alias/key
convention so commands don't go stale when keys or config change.
