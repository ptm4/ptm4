# Where agentic files live

All homelab-operations material for agents lives under `homelab/agentic/`, one subfolder
each. This tree is the **authoritative source**; everything Claude Code actually reads from
`.claude/` is a generated copy.

- `rules/` — standing behavioral rules (this file is one). Materialized into
  `.claude/rules/`, which Claude Code **auto-loads every session**. Keep each rule short and
  correct; a stale always-on rule costs tokens *and* misleads.
- `skills/` — one folder per skill, each with `SKILL.md`. Materialized into
  `.claude/skills/`, the only place Claude Code discovers skills.
- `runbooks/` — per-host / per-subsystem reference, read on demand.
- `generated/` — **machine-written, do not hand-edit.** Refreshed nightly by the architecture
  agent; anything you write here is overwritten.
- `harness/` — how the *agent* runs (hooks, permissions, settings), as opposed to how the
  homelab runs. See `harness/README.md`.
- `proposed/` — draft skills/rules awaiting promotion via `propose.py`.

## Materialization: copies, not symlinks

`probe.py --wire claude` **copies** each rule and skill into `.claude/`. It deliberately does
not symlink: the working copy is reached over a CIFS mount that does not support symlinks
(`ln -s` → "Operation not supported"). So:

```bash
python3 homelab/agentic/probe.py --wire claude   # after editing any rule or skill
python3 homelab/agentic/probe.py                 # report drift without changing anything
```

**Editing `.claude/rules/*.md` or `.claude/skills/*` directly is pointless** — the next wire
overwrites it. Edit here, then re-wire. `probe.py` reports the `claude_rules`,
`claude_skills`, `claude_hooks` and `claude_hook_scripts` checks so drift is visible.

## Tracking status (verified 2026-07-25)

- **`homelab/agentic/` IS tracked in git.** Only `.claude` is ignored (`.gitignore:54`). Earlier
  revisions of this file claimed the whole tree was gitignored and existed on no remote — that
  is no longer true, and it was the reason the 2026-07-22 loss was unrecoverable.
- **`.claude/` is ignored, and that's fine**: every file in it is a generated copy. Losing it
  costs one `probe.py --wire claude`. Nothing unique should ever live there.

Residual risk is the ordinary one: a *new, uncommitted* file here exists only on disk. So
before deleting any repo working copy, still run `git status --ignored --porcelain` and
`git clean -ndx` and preserve what they list — `git status` alone hides both ignored and
untracked content. The `PreToolUse` guard blocks that deletion path, but the same care applies
by hand.

If a file doesn't fit an existing subfolder, create the right one here rather than dropping
it in `.claude/`, the repo root, or a per-host directory.

## Rule: use skills for host access

When a task names a homelab host (`opti`, `rpi`, `noblenumbat`, `android`) and acting on it
needs real shell access, use the [`homelab-ssh`](../skills/homelab-ssh/SKILL.md) skill rather
than hand-rolling `ssh` — it points at the current alias/key convention, so commands don't go
stale when keys or config change. See also `homelab-ssh-autotrigger.md`.
