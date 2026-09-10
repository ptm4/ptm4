---
plan: 12
title: DM tools and map editor
stage: 3
model: sonnet
mode: execute
depends_on: [06, 07]
inputs: [voxel kit prefabs with metadata, campaign schema]
outputs: [in-game map editor (place/rotate/erase voxel tiles and props on the grid, elevation), sprite placement, fog paint, scene/encounter editor that writes Plan 07 files, save/load]
done_when: [Peter builds a 3-room dungeon with an encounter and a dialogue trigger inside the game in under 30 minutes and it plays in auto-DM mode without editing files by hand]
status: stub
---

# 12: DM tools and map editor

## Goal
The "sandbox" half of the pitch: a DM picks from environments and sprites and assembles a
map and scene inside the game, producing the same data files the auto-DM executes.

## Scope
Grid placement with snap and elevation, palette of the biome's tiles/props, creature
placement from the compendium, fog/vision paint, triggers and flags, encounter setup with
tactics hints, export to `content/campaigns/<name>/`, import of existing campaigns.

## Open questions
- Live editing during a session (DM changes the map while players play): later.
- Undo depth and autosave cadence.
