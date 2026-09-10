---
plan: 06
title: Voxel world kit
stage: 1
model: sonnet + codex-image
mode: execute
depends_on: [04]
inputs: [style bible voxel scale + palette, MagicaVoxel installed]
outputs: [tile taxonomy doc, assets-src/voxels/*.vox per tile/prop, tools/vox_export.ps1, Unity prefabs with grid-snap, one biome complete (dungeon), procedural room generator hook]
done_when: [a DM can assemble a room from prefabs on the 5-ft grid in the Editor, tiles light correctly under the HD-2D post recipe, export is one command, manifest complete]
status: stub
---

# 06: Voxel world kit

## Goal
The Lego set the DM builds maps from (D7): floors, walls, doors, stairs, pillars, props,
per biome, authored in MagicaVoxel at the bible's scale, exported to Unity prefabs that
snap to the grid and carry gameplay metadata (blocks movement, blocks sight, cover value,
elevation, difficult terrain).

## Biome order
Dungeon (v1, needed for POC and first campaign), then town, forest, cave, ruins.

## Open questions
- Export path: MagicaVoxel .obj vs a Unity voxel importer package; test both for draw calls.
- Whether to let codex-image produce palette/texture sheets or keep voxels flat-shaded.
- Procedural generation scope in v1: rooms and corridors only.
