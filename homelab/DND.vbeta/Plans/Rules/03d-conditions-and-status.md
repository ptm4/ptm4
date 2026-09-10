---
plan: 03d
title: Conditions and status
stage: 2
model: sonnet
mode: execute
depends_on: [03b]
inputs: [condition data from 03a, effect primitives from 03c if drafted]
outputs: [all SRD conditions implemented as rule modifiers, exhaustion (2024 model), tests per condition]
done_when: [every SRD 5.2 condition alters checks/attacks/movement/actions exactly per text, stacking and removal rules tested, exhaustion levels tested]
status: stub
---

# 03d: Conditions and status

## Goal
Blinded, Charmed, Deafened, Exhaustion, Frightened, Grappled, Incapacitated, Invisible,
Paralyzed, Petrified, Poisoned, Prone, Restrained, Stunned, Unconscious, implemented as
modifiers the core pipeline consults. Mechanical: the SRD text is the spec.

## Open questions
- 2024 exhaustion (flat -2 per level) vs 2014 table: default 2024, keep 2014 behind the
  ruleset toggle.
