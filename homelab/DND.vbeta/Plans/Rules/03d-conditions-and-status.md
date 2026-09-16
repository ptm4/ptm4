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

## Done in batch 02 (Plan 17, B4)
All 15 conditions modeled (`Runtime/Model/Conditions.cs`: `Condition`, `ConditionDuration`,
`ActiveCondition`), applied/removed via `Encounter.ApplyCondition`/`RemoveCondition` (host/DM/
spells call these directly; they are not intents). Every condition with a mechanical effect is
wired into the attack/move/check pipeline: Blinded, Charmed, Frightened, Grappled,
Incapacitated (+ implied by Paralyzed/Petrified/Stunned/Unconscious), Invisible, Paralyzed,
Petrified (damage-immune), Poisoned (attacks and Force/PickLock checks), Prone (`StandUpIntent`
ends it), Restrained, Stunned, Unconscious (auto-applied whenever a creature is Down and not
dead, per 03b's death-and-dying state), and Exhaustion (2024: flat -2 per level on every d20
roll, -5 ft speed per level, level 6 kills). Durations expire at the end of a turn
(`UntilRemoved`/`EndOfSourceNextTurn`/`EndOfTargetNextTurn`/`Rounds`); Grappled also
auto-clears when its source dies or is no longer adjacent. Deafened is recorded with no
mechanical effect (no hearing-based rules yet). Tests: `engine/DND.Engine.Tests/ConditionTests.cs`.

## Remaining for batch 03
The 2014 exhaustion table (currently 2024-only), stacking rules for a creature under more
than one adv/dis-granting condition beyond the two-source cancel-to-Normal case
(`Encounter.ResolveMode`), and reaction economy in the auto-DM (03c/08) when a spell needs
to apply a condition mid-combat.
