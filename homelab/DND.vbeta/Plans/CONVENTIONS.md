# Plan conventions

Every plan in this folder is a hand-off document for an agent (or for Peter). It must be
executable without the conversation that produced it. The frontmatter is what routes it.

## Frontmatter (required on every plan)

```yaml
---
plan: 03                      # number; sub-plans use 03a, 03b ...
title: Rules engine (headless)
stage: 2                      # 1 POC · 2 engine · 3 local beta · 4 friends test · 5 ship
model: fable                  # fable | sonnet | codex-image | peter
mode: decide                  # decide | execute
depends_on: [01]              # plans that must be `done` first
inputs: []                    # files/facts the agent needs
outputs: []                   # what exists when this plan is done
done_when: []                 # observable checks, not feelings
status: stub                  # stub | drafted | approved | in-progress | done
---
```

## Model / mode routing

| model | mode | Use for |
|---|---|---|
| `fable` | `decide` | Anything with design judgement: schemas, architecture, art direction, the auto-DM. The agent makes calls along the way and records them in `DECISIONS.md`. |
| `sonnet` | `execute` | Mechanical work with a spec: scaffolding, ingest scripts, cleanup pipelines, netcode wiring, builds. Follow the plan literally; stop and ask if the spec is wrong. |
| `codex-image` | `execute` | Asset generation batches driven through Codex CLI / ChatGPT with its image tool. The plan ships prompt packs + templates; the agent produces files into `assets-src/**/inbox/`. |
| `peter` | n/a | Decisions and tests only Peter can do: source confirmations, Editor GUI clicks, Unity sign-in, friend sessions. |

Standing preference: do **not** run mechanical verify/scrape work on Fable. If a
`fable/decide` plan spawns mechanical sub-work, it hands that to Sonnet.

## Lifecycle

`stub` (one page: goal, inputs, outputs, open questions, done_when) → `drafted` (full plan,
written in a session with Peter) → `approved` (Peter said go) → `in-progress` → `done`
(done_when verified, outputs exist). Update `status` in the file **and** in `README.md`.

## How to start a plan session

1. Open Claude Code in `E:\REPO\ptm4` (plans, engine, content) or `E:\Unity\Projects\Dungine`
   (anything that touches the Editor via the Unity MCP bridge).
2. Pick the model named in the frontmatter.
3. Prompt: `Execute homelab/DND.vbeta/Plans/<file>.md per its frontmatter.` For `decide`
   plans, add the open questions you want settled first.
4. The agent updates `status`, appends to `DECISIONS.md`, and ends by listing paths to commit.

## Standing rules that apply to every plan

- Never `git commit`/push. Peter commits. End each session by listing paths to commit.
- Only SRD (CC-BY-4.0) and SRD-derived data may enter `content/` or a build. Anything else
  goes to gitignored `content/private/`. See `SOURCES.md`.
- Rules logic lives in `engine/`, never in the Unity project.
- Runtime must work with zero LLM calls. Any LLM feature is optional and off by default.
- Manifest everything generated (file, sha256, source, date), the same habit as `Modding.md`.
- One variable per test cycle; capture logs before fiddling.
