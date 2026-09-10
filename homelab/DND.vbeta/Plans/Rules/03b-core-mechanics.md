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
