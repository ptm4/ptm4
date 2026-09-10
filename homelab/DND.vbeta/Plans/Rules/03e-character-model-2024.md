---
plan: 03e
title: 2024 character model
stage: 2
model: fable
mode: decide
depends_on: [03a, 03b]
inputs: [species/background/class data from 03a, effect primitives from 03c]
outputs: [Character model, level-up pipeline 1-20, class features 1-5 fully, equipment/inventory/attunement, homebrew format spec, 4 pregens as JSON for Plan 02/13]
done_when: [a character can be built from species+background+class per 2024 rules and leveled 1-5 with all features applied, sheet totals match hand calculation in tests, homebrew class round-trips through the format]
status: stub
---

# 03e: 2024 character model

## Goal
The player-facing half of the rules: building and leveling a character under the 2024
rules, with the 2014 fallback per entry, and a homebrew format for Peter's own content (D15).

## Scope for v1
All SRD 5.2 species and backgrounds; all classes to level 5 fully (subclass choice at the
2024 level), higher levels data-present but feature coverage tracked in `coverage.md`;
weapon mastery; equipment, inventory, attunement, encumbrance choice.

## Open questions
- Multiclassing in v1: recommend no.
- Feats: origin feats yes (2024 backgrounds grant them); general feats behind coverage.
- Homebrew format: JSON with the same schema as ingested content plus `source: homebrew`.
