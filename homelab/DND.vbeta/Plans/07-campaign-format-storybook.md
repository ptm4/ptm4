---
plan: 07
title: Campaign format (storybook schema)
stage: 2
model: fable
mode: decide
depends_on: [03]
inputs: [engine intent/event model from 03, character model from 03e]
outputs: [docs/campaign-schema.md + JSON schema, tools/campaign_validate.py, authoring guide for writing campaigns with Claude, a 3-scene sample campaign in content/campaigns/sample/]
done_when: [sample campaign validates and plays end to end in the engine's headless runner (no Unity), authoring guide lets a fresh Claude session produce a valid scene from a prose description]
status: stub
---

# 07: Campaign format (storybook schema)

## Goal
The data format the auto-DM executes (D2, D3, D5): the whole campaign as files, authored
with Claude at authoring time, needing no LLM to run. This is what makes the game
self-sufficient.

## Must cover
Scenes (map ref, entry points, lighting/weather), encounters (creatures, placement,
tactics hints, triggers), dialogue trees (nodes, choices gated by species/class/stat/flag,
skill checks with DCs, outcomes), quest flags and state machine, loot and XP awards,
triggers (enter area, flag set, turn count, HP threshold), travel between maps, rests,
narrated text blocks, and an `optional_llm` hook per NPC for Plan 09.

## Open questions
- YAML for authoring with JSON compiled output, or JSON only.
- How much of a published module's structure can be represented (private use, D5) without
  copying text: the schema should make adaptation easy, but the repo never holds the text.
- Versioning and migration of campaign files as the schema evolves.
