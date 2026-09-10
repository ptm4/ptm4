---
plan: 03
title: Rules engine (headless)
stage: 2
model: fable
mode: decide
depends_on: [01]
inputs: [SOURCES.md rows confirmed, DECISIONS D3 D10 D12 D14 D15, engine/ solution from 01]
outputs: [engine/DND.Engine domain model + rules pipeline, xUnit suite as the executable spec, docs/engine-architecture.md]
done_when: [dotnet test green for a level 1-5 party across 03a-03e, deterministic replay of a recorded combat yields identical state, no UnityEngine reference anywhere in engine/]
status: stub
---

# 03: Rules engine (headless)

## Goal
The long pole of the project. A pure C# 5e engine that adjudicates everything a DM would,
with no human judgement required (D12), 2024 rules first with per-entry 2014 fallback
(D14), and no Unity dependency so it is testable in seconds.

## Design constraints (decide within these)
- **Deterministic**: seeded RNG; every state change is an `Event` in an append-only log.
  Replaying the log reproduces the state. This is also what Plan 10 replicates.
- **Intent in, events out**: the Unity layer sends `Intent` objects (move, attack, cast,
  end turn); the engine validates against rules and emits events or a rejection with reason.
- **Data-driven**: creatures, spells, items, conditions come from `content/rules/*.json`
  (Plan 03a), tagged `ruleset: 2024 | 2014`. Engine code implements *mechanics*, not lists.
- **Grid**: 5-ft squares, 3D positions (elevation matters for voxel maps), line of sight,
  cover (half/three-quarters/full), difficult terrain, diagonal rule chosen and recorded.
- **Turn structure**: initiative, action / bonus action / reaction / free interaction,
  movement budget, opportunity attacks, concentration, death saves.

## Sub-plans
[03a data ingest](Rules/03a-data-ingest.md) → [03b core mechanics](Rules/03b-core-mechanics.md)
→ [03c spells and effects](Rules/03c-spells-and-effects.md), [03d conditions](Rules/03d-conditions-and-status.md),
[03e 2024 character model](Rules/03e-character-model-2024.md).

## Open questions
- Effect system shape: composable effect primitives (damage, heal, condition, move, summon,
  modify roll) vs scripted per-spell code. Recommendation to evaluate first: primitives with
  a small escape hatch for the ~5% of spells that need code.
- How far to model 2024-only features in v1 (weapon mastery, new species traits)?
- Which 2014 entries are needed as fallback at level 1-5? Produce the list during 03a.
