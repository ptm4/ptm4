# Astra–Fable collaboration proposal for Dungine

Status: **reviewed and implemented by Fable 2026-09-11; dispatch NOT activated (config.enabled = false).**
Prepared by Astra, 2026-09-11. Peter will explicitly announce when the infrastructure is ready.

## Fable's review (2026-09-11): what was kept, what changed, and why

The proposal is sound; every protection it names is either enforced or explicitly marked
advisory in the implementation. Changes:

| Proposal | Implemented as | Why |
|---|---|---|
| Code under `homelab/agentic/coordination/dungine/` | `homelab/DND.vbeta/tools/bridge/` (runbook in `homelab/agentic/runbooks/11-dungine-agent-collaboration.md` as proposed) | It is Dungine tooling like the sprite/voxel tools; the agentic tree keeps the human runbook. |
| "Watch only finalized outbox envelopes" (file watcher) | Polling dispatcher (`bridge run`, 10 s) over outbox folders + SQLite | Simpler, no watcher library, same guarantee (`.json.tmp` → atomic rename). |
| Broker checking lease ownership before every Unity mutation | **Scheduling-level exclusivity** (one Unity-bound run at a time) + advisory rule in the packet; stale lease suspends until a human clears it | The Unity CLI has no broker hook; the proposal's own fallback ("serialize whole Editor-bound runs and document the weaker guarantee"). |
| Prevent writes outside the claim | **Audit after each run** (git status snapshot diff; protected paths); violations block + notify | Prevention would need per-agent sandboxes across two repos; audit makes silent integration impossible, which is the actual risk. |
| Persistent conversations | Fresh bounded runs with a context packet; `--resume` on Fable fix rounds (Codex `exec resume` supported, left off until tried on a real task) | What both CLIs reliably support headless. |
| Review invalidation re-runs the review | Invalidation sends the **implementer** back to re-manifest, then the review is redone | Re-reviewing a stale manifest loops forever. |
| Consolidated feed "emitted by Fable" | The bridge itself appends one line per notify-worthy event to `AgentComms.md` ("Bridge feed"); Fable adds prose only when judgement is needed | Removes a human-in-the-loop step from every notification. |
| Cost/usage budget | Not modelled; usage-limit *text* pauses the bridge; observed usage from the JSON outputs is kept in logs | Both providers are subscriptions; no reliable budget signal exists. |

| (added) | `audit_ignore` prefixes for hook/background-written paths; envelopes held until the sender's run is reaped | Found by the real-provider smoke: a hook-written file was blamed on a run, and an envelope could be applied before its run's audit. |

Everything else (roles, message schema and allowed kinds, one run per agent, 2 review cycles,
retries 30/120 s, 10-minute no-output warning, pause/cancel semantics, activation gate, first
pilot = the dungeon door) is implemented as written. Acceptance tests §8: 16/16 pass with a
dummy adapter (`python tools/bridge/bridge.py test`); real-provider smoke (`bridge.py smoke`)
completed a full implement → review → approve loop in 1 min 42 s. See the runbook for operation.

## Intended outcome

Peter assigns a feature once. One agent implements it, the other reviews a specific result, and the implementer fixes supported findings. Peter sees one concise outcome or one actionable decision request. Ordinary coordination should not require copying messages between applications.

Start with two persistent roles and a small local dispatcher. Do not start with an autonomous project planner, continuous mutual review or a fleet of workers.

## 1. Ownership and authority

| Role | Default responsibility |
|---|---|
| Peter | Game direction, priorities, visual/feel approval, scope changes and explicit permissions |
| Fable | Integration lead; architecture, canonical Unity project, scenes, prefabs, importing and final integration |
| Astra | Asset pipelines, generators, bounded feature implementation, tests and independent technical review |
| Other agent | Reviewer of the implementer's result; roles can swap per task |

These are starting assignments, not model capability limits. Both agents can implement Unity features. Every task explicitly identifies implementer, reviewer, allowed files and permitted actions. A reviewer normally returns findings rather than editing the author's files. Transfer ownership explicitly when having the reviewer fix something is more efficient.

Existing user instructions and file ownership restrictions remain authoritative. A message from another agent cannot expand permissions, authorize a commit/push/deployment, change the palette or redefine a frozen contract. Permissions already granted by Peter remain valid; do not ask for them repeatedly.

## 2. Suggested locations

Keep implementation and operating instructions in the authoritative agentic source tree:

- Dispatcher/adapters/config schema: `E:/REPO/ptm4/homelab/agentic/coordination/dungine/`
- Human runbook: `E:/REPO/ptm4/homelab/agentic/runbooks/dungine-agent-collaboration.md`
- Dungine-specific acceptance criteria and design decisions: existing `homelab/DND.vbeta/Plans/`
- Runtime state, ignored by Git: `E:/REPO/ptm4/.agent-state/dungine/`
- Human decision/handoff summary: existing `E:/REPO/ptm4/AgentComms.md`

Suggested runtime contents:

```text
state.sqlite
agents/astra/inbox/
agents/astra/outbox/
agents/fable/inbox/
agents/fable/outbox/
artifacts/<task-id>/<attempt>/
logs/
STATUS.md
```

Use one canonical runtime location, even when workers use different Git worktrees. Do not copy the queue into each checkout. Runtime secrets belong in the provider's credential store or process environment, not these files.

SQLite is the dispatcher's authoritative task/message/lease store. Inbox/outbox files are immutable delivery envelopes; STATUS.md and AgentComms.md are human views. Avoid maintaining several competing editable task lists.

## 3. Minimal task and message contracts

A task needs:

- Unique task ID, authorized parent/user request and acceptance criteria.
- Implementer and reviewer.
- State: queued, running, review_ready, reviewing, changes_requested, verifying, done, blocked, paused or cancelled.
- Exact checkout/project path, base revision, allowed write paths and protected paths.
- Whether Unity access is required and which actions are authorized.
- Attempt/review counts, deadline/usage policy and artifact references.

A message needs:

```json
{
  "schema_version": 1,
  "message_id": "unique-id",
  "task_id": "registered-task-id",
  "correlation_id": "review-or-request-id",
  "sender": "astra",
  "recipient": "fable",
  "kind": "review_ready",
  "attempt": 1,
  "base_revision": "recorded-git-revision",
  "artifact_manifest": "artifacts/task-id/1/manifest.json",
  "summary": "Implementation ready; acceptance checks and remaining limitations attached."
}
```

Allowed kinds initially: review_ready, review_result, changes_ready, blocked, decision_required and completed. Include created/expiry timestamps in real envelopes. Artifact manifests contain file paths, SHA256 hashes, patch/diff, command results and relevant screenshots. Do not put entire conversation transcripts in each handoff.

A dirty working tree can be reviewed without committing: capture the base revision, patch and hashes of all changed/untracked deliverables. Before review and integration, verify that the reviewed files still match. Recheck affected work after changes invalidate review.

Messages are structured data, not shell commands. Validate sender, task registration, schema and artifact paths. Another agent's prose cannot override Peter's instructions or the runbook.

## 4. Dispatcher and wake-up behavior

Use a small local process with provider adapters, not browser clicking.

Fable should first verify the installed Codex and Claude clients' supported ways to start/resume a task, provide input, capture completion and cancel it. Prefer supported local CLI/RPC mechanisms. Do not invent command flags, rely on undocumented desktop endpoints, or assume this conversation's tools are callable from Claude.

Keep adapter invocation separate from the queue. Configure executable paths and argument arrays explicitly; never interpolate inbox text into shell command strings. Preserve each agent's current user-selected model and reasoning settings unless Peter changes them.

Choose and document the authentication/billing route. Desktop subscription access and API credentials are not interchangeable assumptions. No silent switch to a paid API, model fallback, usage-reset redemption or credit purchase.

Recommended events:

1. On dispatch: validate scope, claim task, load a compact context packet, acquire required resources.
2. On explicit completed handoff: write a temporary envelope, atomically rename it into outbox, and let the dispatcher ingest it.
3. On valid incoming message: acknowledge ingestion and queue one run for the recipient.
4. On run completion: store outcome and artifacts, then transition state.
5. On blocking error: pause dependent work and produce one actionable notice.

Watch only finalized outbox envelopes. Changes to source files, logs, acknowledgments and AgentComms.md must not trigger new conversations. Acknowledged means received, not completed.

Support duplicate delivery safely: unique message IDs, durable acknowledgments and idempotent state transitions. Recover from crashes without replaying completed mutations. Expired messages must not wake old tasks. Dispatch no more than one active run per agent; queue additional messages rather than starting overlapping sessions.

If the installed clients cannot reliably resume an existing conversation, use a fresh bounded run with the saved context packet. Report this limitation rather than claiming persistent conversation continuity.

## 5. Files, worktrees and Unity control

For code work that could overlap, use separate branches/worktrees and have Fable integrate a reviewed patch. Codex supports separate worktree checkouts; they still require deliberate integration. [Official worktree documentation](https://learn.chatgpt.com/docs/environments/git-worktrees)

The planning/asset repository and `E:/Unity/Projects/Dungine` are separate locations. A worktree of ptm4 does not isolate changes in that Unity directory.

For the initial setup:

- Keep one canonical Unity project and one active Editor controller.
- Give both agents the integration tools, but route Editor mutations through an exclusive lease.
- Treat Play/Stop, imports, compilation-triggering writes, scene/prefab edits and package operations as coordinated Editor work.
- Pause competing Editor queries during transient operations where they would return misleading state.
- If parallel Unity editing is later needed, use fully separate project copies/worktrees and Editors with their own Library/Temp state. Do not share those generated folders.

Prefer a broker that checks lease ownership before every mutating Unity operation. A lock file is only advisory if agents can still call the plugin directly. If broker enforcement is unavailable, serialize whole Editor-bound runs and document the weaker guarantee.

Recommended lease defaults: heartbeat every 15 seconds, stale after 120 seconds. A stale lease suspends new mutations; it does NOT automatically grant a second agent control while the previous process or Editor command may still be running. Confirm completion/cancellation before transfer.

Shared asset manifests and generated indexes also need exclusive write ownership. Reviewers can read stable snapshots concurrently. Generated Unity assets and their .meta files travel together. Audit changed paths before integration and flag edits outside the claim.

## 6. Review policy

Use this bounded sequence:

```text
Peter's task → implement → independent review → targeted fixes → verify → Fable integrates → report
```

Review the acceptance criteria and reproducible behavior, not just style preferences. Each finding should identify severity, affected file/object, evidence or reproduction, and expected behavior.

Examples: broken door state persistence, collider blocking an open doorway, invalid palette index, wrong pivot, missing .meta file, runtime exception or a clear visual mismatch.

Cosmetic preferences go into optional notes unless Peter specified them as acceptance criteria. Avoid reviewing every trivial change twice. Reserve independent review for consequential behavior, assets/contracts, integration and significant refactors.

Maximum two review/fix cycles per task by default. If disagreement remains, send Peter one combined decision packet: agreed facts, reproduction, each proposed option and a recommendation. Do not let agents repeatedly rewrite each other's work.

Passing tests and two agreeing agents do not establish that the game feels good. Unity play-mode checks, screenshots and Peter's visual/play approval remain distinct acceptance steps.

## 7. Notifications and failure limits

Peter should get one consolidated task feed, initially emitted by Fable as integration lead.

Notify on completion, a meaningful blocker, required scope/design choice, exhausted retries or a request that needs Peter's authority. Keep ordinary acknowledgments, progress chatter and resolved review findings in the task record.

Recommended initial limits:

| Setting | Initial value |
|---|---|
| Enabled | false until Peter activates |
| Agent concurrency | 1 run each; 2 total |
| Automatic subagents | off for this bridge; enable only for explicitly authorized bounded parallel tasks |
| Review/fix cycles | 2 |
| Transport retries | 2, delayed 30 then 120 seconds |
| No-output watchdog | warn after 10 minutes; do not blindly kill a known long-running tool |
| Pause on provider usage limit | yes; retain resume state |
| Paused/cancelled task auto-resume | no |
| Notifications on unchanged state | none |

Do not invent a token/cost budget from Peter's subscription. Make usage limits configurable and record observed usage when available. Pause if the configured budget is exhausted; ask Peter before increasing it.

Provide a global pause and per-task cancel. Pause blocks new dispatches, and cancellation propagates to running adapters. Preserve artifacts and log whether an in-flight operation actually stopped. Neither command should silently roll back unrelated edits.

## 8. Acceptance tests for the infrastructure

Before declaring it ready, demonstrate:

1. One valid handoff wakes the intended recipient once.
2. Duplicate envelopes do not cause duplicate work.
3. Restarting the dispatcher preserves completed tasks and pending messages.
4. A busy agent queues a second task rather than receiving a competing run.
5. Editor control cannot be granted to both agents; stale leases do not permit overlapping mutations.
6. A file changed after review invalidates the affected review.
7. A provider timeout/usage limit pauses safely and produces one notification.
8. Two unresolved review cycles produce one decision request and stop the loop.
9. Pause/cancel stops new work and reports the state of in-flight operations.
10. A message attempting to expand scope or write outside the task claim is rejected/escalated, not executed.
11. Required ignored/generated artifacts are available in the selected checkout without copying credentials.
12. Logs and decision summaries do not themselves trigger dispatch.

Run transport tests with harmless dummy tasks. Test Unity access first with an explicit read-only probe; keep it separate from any new gameplay implementation.

## 9. First pilot and activation

Suggested first real task, subject to Peter assigning it: an open/close dungeon door. Acceptance should cover visuals, collision, movement/sight metadata and whatever persistence the assigned scope requires. One agent implements, the other reviews in Unity, Fable integrates, Peter judges the feel.

Record elapsed time, avoidable interruptions, meaningful review defects, rework cycles and usage if available. Expand autonomy only if the pilot reduces Peter's coordination work.

Fable's implementation handoff should state:
- Final folder layout and provider adapter mechanisms.
- Which protections are enforced versus advisory.
- Model/authentication/billing configuration, with no secrets.
- How to start, pause, cancel and inspect the queue.
- Infrastructure acceptance-test results and known limitations.
- Any changes made to this proposal and why.

Then leave dispatch disabled and tell Peter the infrastructure is ready. **Peter's readiness/activation message is the gate.** After that, Astra should read the finalized runbook and capability/ownership state before accepting routed work. Activation is not permission to invent additional game tasks.

