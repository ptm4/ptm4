---
kind: rule
name: check-ignored-before-delete
description: Before rm -rf of any repo copy, check git-ignored files (status --ignored / clean -ndx) and preserve agentic/.claude local-only content
rationale: Learned from the 2026-07-22 noblenumbat deletion that wiped the only copy of agentic/{skills,rules,harness}
status: proposed
created: 2026-07-22
created_by: jarvis-session
---

# Check for gitignored content before deleting a repo copy

Before `rm -rf`-ing any working copy of a repo (teardown, migration cleanup, freeing space),
do **not** rely on `git status` / "clean & in sync" to conclude it's safe. `git status`
ignores gitignored files, and in this repo `homelab/agentic/` and `.claude/` are gitignored
local-only content that exists **nowhere else** (not on GitHub).

**Always run first:**

```
git -C <copy> status --ignored --porcelain   # shows ignored files too
git -C <copy> clean -ndx                      # dry-run: what a clean would remove
```

If either lists anything under `homelab/agentic/`, `.claude/`, or other ignored paths,
**preserve it** (rsync/tar it out) before deleting. Only proceed once you've confirmed the
ignored content is either backed up or genuinely duplicated elsewhere.

**Why:** on 2026-07-22 the noblenumbat `~/code/ptm4` copy was deleted after a clean
`git status` check — which silently removed the only copy of `agentic/{skills,rules,harness}`.
Recovery from transcripts + git history was partial. This rule exists so that never repeats.
