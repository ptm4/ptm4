---
plan: 08
title: Auto-DM engine
stage: 2
model: fable
mode: decide
depends_on: [03, 07]
inputs: [engine + effect system, campaign schema, monster data with tactics fields]
outputs: [storybook runtime state machine, tactical monster AI, procedural generators (encounters by CR/terrain, loot tables, rumor/quest templates), headless simulation harness that plays a campaign with scripted players]
done_when: [sample campaign runs start to finish with no human input, monster AI wins fights it should and loses fights it should across 100 seeded simulations, procedural encounter difficulty matches the 2024 encounter-building guidance in tests]
status: stub
---

# 08: Auto-DM engine

## Goal
Everything the human DM does at the table, done by code (D4, D12): advance the story, run
the monsters, adjudicate rules, and improvise side content from templates. Zero tokens.

## Components
- **Storybook runtime**: executes Plan 07 files; scene/trigger/flag state machine; pacing.
- **Tactical AI**: target selection, ability/spell choice, positioning with cover and
  opportunity attacks, focus-fire and retreat behaviors, stat-block tactics hints, monster
  morale. Utility-based scoring over engine-simulated candidate actions.
- **Adjudication**: hooks into 03 so every rule resolves automatically; DM override
  channel for when a human is present.
- **Procedural**: random encounters by CR and terrain, loot by rarity tables, rumor and
  side-quest templates with slot-filling from campaign facts.

## Open questions
- Difficulty knob semantics.
- How the human DM overrides or nudges the auto-DM mid-session (pause, edit flags, take
  control of a monster).
