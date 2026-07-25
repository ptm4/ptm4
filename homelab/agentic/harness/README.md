# The harness

How the *agent* is configured, as opposed to `runbooks/` (how the homelab runs) or
`rules/`/`skills/` (what the agent should do).

"Harness" = the machinery outside the model that decides what context it receives and what
actions it is permitted to take. The model can ignore instructions; it cannot ignore the
harness.

---

## The core idea

The instinct is to write a good doc and tell the agent "read this first". That does not work
reliably, for a reason worth internalising:

> **Reading is a choice the model makes. Injection is not.**

Anthropic's own docs are blunt about it:

> Claude treats them as context, not enforced configuration. To block an action regardless of
> what Claude decides, use a PreToolUse hook instead.
> — *docs/en/memory*

So "make every agent check this file before doing anything" is the wrong shape for the goal.
The right shape is: **make the facts already present, and make the dangerous paths
impossible.** Three layers, weakest to strongest:

| # | Layer | Mechanism | Guarantee | Token cost |
|---|---|---|---|---|
| 1 | **Declarative** | `.claude/rules/*.md`, `CLAUDE.md` | Always in context. **Advisory** — high compliance, not certainty | Every session |
| 2 | **Injected** | `SessionStart` / `PreToolUse` → `additionalContext` | Text is *placed* in context. Can be **generated**, so it can carry live state | Session, or only when triggered |
| 3 | **Enforced** | `PreToolUse` → `permissionDecision`, `permissions.deny` | **Blocks regardless of model judgment** | ~0 |

Layer 3 is the only actual enforcement. Layers 1–2 are how you stop the agent *wanting* to do
the wrong thing; layer 3 is how you stop it *succeeding*.

### What this bought us here

The token win is layer 1+2 replacing exploration. Previously an agent asking "which key
reaches rpi?" would grep the repo, read a runbook, maybe SSH to check — several tool calls
and a lot of output. Now the host table and both key regimes are already in context before
the first turn, at a fixed cost of one short file.

The subtle part: **don't inject the same thing twice.** `rules/01-homelab-context.md` holds
the *static* facts (hosts, keys, repo location) because those belong in an always-loaded file.
The `SessionStart` hook deliberately does **not** repeat them — it contributes only what a
static file cannot: the newest per-host status and how stale that reading is. Duplicating
static facts in a hook is paying twice for the same tokens.

---

## What's wired here

`probe.py --wire claude` owns all of this. It writes `.claude/settings.json` by **merging**,
so hand-added hooks and settings survive.

### `hooks/session-context.py` — `SessionStart` (layer 2)

Injects live homelab state: per-host status from the newest `homelab-doctor-latest.json`,
which containers are not up, and a staleness warning past 6 hours.

The report sits on a CIFS mount of opti, so a down opti could make that read hang and delay
*every* session start. The read therefore happens in a daemon thread with a 2 s timeout, and
every failure path degrades to a one-line "live state unavailable" and exits 0.

### `hooks/homelab-guard.py` — `PreToolUse` on `Bash|Edit|Write|NotebookEdit` (layer 3)

| Rule | Verdict | Why |
|---|---|---|
| `rm -rf` of a ptm4 working copy | `ask` | A clean `git status` says "safe" while gitignored local-only content is destroyed. This exact reasoning error happened 2026-07-22. |
| Edit `/etc/samba/*`, `/etc/openmediavault/*` | `deny` | OMV regenerates them; the edit silently vanishes. |
| Edit `discord-*` files on the rpi | `deny` | Bots are managed through the webapp. |
| Hand-edit `/srv/docker/compose/webapp/` | `deny` | Deploy target, not source — the next CI run reverts it. |
| `git commit` / `--amend` / `push` / `reset --hard` | `deny` | Peter commits his own work. |

**`deny` vs `ask` is a real decision, not a severity dial.** Use `deny` when a correct
alternative exists and the action is simply wrong — the reason string should name the
alternative. Use `ask` when the action is legitimate but the *usual reasoning about it* is
unsafe, so a human has to look. `rm -rf` of a repo copy is the textbook `ask`.

The same hook also **injects** short reminders (never blocks) for a few easy-to-get-wrong
targets: android's non-standard port and flakiness, Gluetun's silent port-forward death,
Pi-hole owning DHCP. Conditional injection means that detail costs tokens only when a command
actually touches those things.

### Non-negotiable: allow-path regressions matter more than blocks

A guard that blocks legitimate work gets switched off, and then you have no guard. So the
test suite asserts the **allow** cases as hard as the deny cases — `rsync` *into* the deploy
dir is the documented deploy and must stay allowed, `rm -rf` of a scratch dir must stay
allowed, `git status` must stay allowed.

---

## Hook event reference

Condensed from `code.claude.com/docs/en/hooks`. The two columns that matter when choosing an
event: can it **block**, and can it **inject**.

| Event | Fires | Block? | Inject? |
|---|---|---|---|
| `SessionStart` | session begins/resumes (`startup`/`resume`/`clear`/`compact`/`fork`) | ✗ | ✓ |
| `UserPromptSubmit` | before a prompt is processed | ✓ | ✓ |
| `PreToolUse` | before a tool call | ✓ (`permissionDecision`) | ✓ |
| `PostToolUse` | after a tool succeeds | ✓ | ✓ (also `updatedToolOutput`) |
| `PostToolUseFailure` | after a tool fails | ✓ | ✓ |
| `PostToolBatch` | after a parallel batch, before next model call | ✓ | ✓ |
| `PermissionRequest` | permission dialog appears | ✓ (auto-allow/deny) | — |
| `Stop` / `SubagentStop` | turn / subagent finishing | ✓ (forces continue) | ✓ |
| `SubagentStart` | subagent spawned | ✗ | ✓ |
| `PreCompact` / `PostCompact` | around compaction | ✓ / ✗ | ✗ |
| `InstructionsLoaded` | CLAUDE.md or `.claude/rules/*.md` loads | ✗ | ✗ |
| `ConfigChange` | settings change mid-session | ✓ | ✗ |
| `SessionEnd`, `Notification`, `FileChanged`, `CwdChanged` | as named | ✗ | ✗ |

### Output contract

Decisions travel in JSON on stdout, not in the exit code:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",              // deny | allow | ask | defer
    "permissionDecisionReason": "why, and what to do instead",
    "additionalContext": "text injected into context"
  }
}
```

Exit codes: **0** = success, parse stdout. **1** = non-blocking error, *ignored* — this is the
trap: a hook that fails with exit 1 silently stops enforcing. **2** = blocking, stderr becomes
the reason. Prefer explicit JSON over exit 2; it lets you attach a useful message.

### Design rules for hooks in this repo

1. **Never break the session.** Wrap everything; on any internal error, fall through to
   allow/no-context. A crashed guard is indistinguishable from no guard — except you think
   you're protected.
2. **`PreToolUse` runs on every matching call.** Pure string matching only — no network, no
   filesystem, no CIFS. Latency here is paid on every tool use.
3. **Reasons must be actionable.** "Denied" teaches nothing; "Denied — OMV regenerates this,
   use the web UI on opti:80" resolves the situation in one turn.
4. **Stdlib Python only**, matching the rest of `homelab/Tools/`.

---

## Working on the harness

```bash
# after editing any rule, skill, or hook
python3 homelab/agentic/probe.py --wire claude

# report drift without changing anything
python3 homelab/agentic/probe.py
```

`probe.py` checks `claude_md`, `claude_skills`, `claude_rules`, `claude_settings`,
`claude_hooks` and `claude_hook_scripts` — the last two exist because a hook that is
unwired or syntactically broken degrades the harness to advice **without any visible signal**.

### Test a hook directly

Hooks are just stdin→stdout programs, so they're testable without a session:

```bash
echo '{"session_id":"t","source":"startup","hook_event_name":"SessionStart"}' \
  | python3 homelab/agentic/harness/hooks/session-context.py

echo '{"tool_name":"Bash","tool_input":{"command":"git push"},"hook_event_name":"PreToolUse"}' \
  | python3 homelab/agentic/harness/hooks/homelab-guard.py
```

### Verify it's actually live

Unit tests prove the logic; they do **not** prove the hook is wired. Confirm in-session:

- `/context` → the **Memory files** list should show `.claude/rules/01-homelab-context.md`.
- Trigger a rule and watch it block. `git push --dry-run` is the safe canary — it is denied
  before it can contact anything. If it *runs*, the hooks aren't loaded.
- Add an `InstructionsLoaded` hook temporarily to log exactly which instruction files loaded,
  when, and why — useful for debugging `paths:`-scoped rules.

Settings changes are picked up for new sessions; a running session may not see a newly added
hook until it restarts.

### Adding a rule

**Static fact an agent shouldn't have to look up?** → `rules/01-homelab-context.md`, and keep
it short; it's in every session.

**Only relevant to certain files?** → a new file in `rules/` with `paths:` frontmatter, so it
loads only when those files are touched:

```markdown
---
paths:
  - "homelab/RPI-srv/webapp/**"
---
```

**Multi-step procedure?** → a skill, not a rule. Skills load on demand; rules are always-on
weight.

**Must not be possible?** → a rule in `homelab-guard.py` *plus* a line in the context rule, so
the agent both knows and is prevented. Add both deny and allow test cases.

---

## Durability (checked 2026-07-25)

Good news, and a correction to what several docs here used to claim: **`homelab/agentic/` is
tracked in git.** Only `.claude` is ignored (`.gitignore:54`). So the source of the harness —
rules, skills, hooks, `probe.py` — is on the remote once committed.

That is what makes the copy-based materialization design safe rather than fragile: everything
under `.claude/` is *derived*, so losing the whole directory costs exactly one
`probe.py --wire claude`. Never put anything unique in `.claude/`.

The remaining exposure is ordinary and unglamorous: a **new, uncommitted** rule or hook exists
only on disk. Commit them. The 2026-07-22 loss happened when this tree really was ignored;
tracking it was the structural fix.

## Cross-tool

`workspace.json` describes this workspace tool-agnostically, and `probe.py` has detectors for
Codex and Cursor (wiring unimplemented — "Phase 2"). Rules and skills live here as the single
source; each tool's discovery layer is materialized from it. Hooks are Claude Code-specific,
so layer 3 currently only exists for Claude Code — another tool gets layers 1–2 only.
