---
plan: 03c
title: Spells and effects
stage: 2
model: fable
mode: decide
depends_on: [03b]
inputs: [effect-system decision from 03, spell data from 03a]
outputs: [effect primitive library, spell definitions expressed as primitives, escape-hatch mechanism for scripted spells, tests for every level 0-3 spell]
done_when: [every SRD cantrip and level 1-3 spell resolves in tests, concentration + area templates + saving throws work on the 3D grid, scripted-spell escape hatch used by fewer than 10 percent of spells]
status: stub
---

# 03c: Spells and effects

## Goal
A composable effect system that expresses most spells and class features as data, with a
code escape hatch for the odd ones. This is judgement-heavy: the primitive set decides how
painful the other 300 spells are.

## Candidate primitives
damage, heal, apply condition, remove condition, move/teleport, summon, modify roll (bonus,
advantage), grant/deny action, area (sphere/cube/cone/line/cylinder on the voxel grid),
duration (instant/rounds/minutes/concentration), trigger (on hit, on save fail, on turn
start/end), targeting (self, creature, point, area, count).

## Open questions
- Concentration break checks and their interaction with the event log.
- Upcasting representation.
- Spell slots vs pact magic vs innate casting in the same model.
