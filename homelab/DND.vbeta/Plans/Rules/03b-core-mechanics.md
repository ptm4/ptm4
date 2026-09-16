---
plan: 03b
title: Core mechanics
stage: 2
model: sonnet
mode: execute
depends_on: [03, 03a]
inputs: [03 architecture doc, content/rules from 03a]
outputs: [engine code for checks, attacks, damage, movement, turn structure; tests per rule with the SRD paragraph cited in the test name]
done_when: [tests cover ability checks, saves, attack rolls (advantage/disadvantage, crits), damage types/resistance, movement + difficult terrain + opportunity attacks, action economy, death saves, resting; deterministic replay test passes]
status: stub
---

# 03b: Core mechanics

## Goal
The rules every fight uses. Implement literally from the 2024 SRD text with each test
naming the rule it proves. Mechanical work: follow the spec, ask when the text is ambiguous.

## Scope
d20 tests (checks, saves, attacks), advantage/disadvantage, proficiency, modifiers, critical
hits, damage rolls and types, resistance/vulnerability/immunity, temporary HP, initiative,
turn structure (action, bonus action, reaction, movement, free interaction), opportunity
attacks, cover, line of sight on a 3D grid, difficult terrain, jumping/climbing, dying and
death saves, short/long rest.

## Open questions
- Diagonal movement rule: 5-5-5 (default) vs 5-10-5 variant. Record in DECISIONS.md.
- Flanking optional rule: off by default.

## Done in batch 02 (Plan 17, B3)
Difficult terrain (double move cost), opportunity attacks (one reaction, melee reach,
Disengage prevents them), ranged attacks (long range rejects, beyond-normal-range and
adjacent-hostile disadvantage), cover (`IBattlefield.CoverBonus` added to target AC), line of
sight on the X/Z plane (`Rules/LineOfSight.cs`, cell-center walk with the diagonal-corner
rule), advantage/disadvantage stacking (`Encounter.ResolveMode`), Dash/Disengage/Dodge
intents, and death saves (nat 1 = 2 failures, nat 20 = revive at 1 HP, 3 successes = stable,
3 failures or massive damage = dead; a Down party creature auto-rolls at the start of its
turn). Tests: `engine/DND.Engine.Tests/CoreMechanicsTests.cs`.

## Remaining for batch 03
Multi-step move intents with pathing (v0.1/v0.2 send one cell per intent), short/long rests,
initiative ties broken by player choice (currently Dex score then insertion order), mounted
and flying movement, and the "can see" nuance for Dodge/opportunity attacks against an
Invisible creature (03d's Invisible only changes attack advantage/disadvantage so far).
