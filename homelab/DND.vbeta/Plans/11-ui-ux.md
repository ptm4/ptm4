---
plan: 11
title: UI / UX
stage: 3
model: fable then sonnet
mode: decide
depends_on: [03e, 04]
inputs: [character model, style bible, Unity UI Toolkit skill from the Unity plugin]
outputs: [UI design doc with wireframes, UI Toolkit theme matching the bible, character sheet (2024), character creator, combat HUD + initiative tracker, dialogue panel with checks, inventory, DM overlay, main menu/host/join]
done_when: [a new player can create a character, join, and fight a round without instructions, every rules outcome is visible (rolls, modifiers, why a rejection happened), readable at 1080p over the HD-2D scene]
status: stub
---

# 11: UI / UX

## Goal
Make the rules engine legible. Every roll shows its math; every rejected intent says why.
Fable designs (wireframes, information architecture), Sonnet builds in UI Toolkit.

## Screens
Main menu, host/join by code, character creator (species/background/class per 2024),
character sheet, combat HUD (actions, bonus, reaction, movement budget, conditions),
initiative tracker, dialogue panel with gated choices and check results, inventory and
equipment (paper-doll preview), journal/quests, DM overlay (see all, move anything, edit
flags, take a monster), settings (LLM layer toggle, accessibility).

## Open questions
- Controller support in v1: no.
- Icon style: generated per the bible (Plan 05 pipeline) or a CC0 icon set.
