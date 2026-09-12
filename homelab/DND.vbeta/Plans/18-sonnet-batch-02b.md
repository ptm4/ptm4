---
plan: 18
title: Sonnet execution batch 02b (ingest the remaining SRD kinds)
stage: 2
model: sonnet
mode: execute
depends_on: [03a]
inputs: [this file, tools/ingest_srd.py, tools/validate_rules.py, content/rules/ as it is now, Plans/Rules/03a-data-ingest.md]
outputs: [content/rules/{2024,2014}/<new kinds>.json, updated manifest/coverage/LICENSES, tools updated]
done_when: [validate_rules.py OK; --twice IDEMPOTENT; coverage.md lists every kind; nothing outside tools/ingest_srd.py, tools/validate_rules.py, content/rules/ and the two plan files changed]
status: approved
---

# 18: Sonnet batch 02b — the rest of the SRD data

Follow Plan 16's "How Sonnet must work" section literally. **This batch runs in parallel with
Plan 17 in another session: you must not touch anything under `engine/`.** Your files are
exactly: `tools/ingest_srd.py`, `tools/validate_rules.py`, `content/rules/**`,
`Plans/Rules/03a-data-ingest.md`, `Plans/README.md`. Python 3.12, stdlib only.

## Why
Plan 03a ingested nine kinds. Class levels, features, subclasses, feats, magic items and the
small lookup tables are needed for the 2024 character model (03e), spells (03c) and the
DM tools. Same envelope, same sources, same idempotence rules as 03a; this is a widening, not
a redesign. Read `tools/ingest_srd.py` fully before editing it: reuse `fetch_json`,
`envelope`, `attribution_for`, the write path, the manifest/coverage/LICENSES writers.

## C1. Kinds to add

Add these to `KINDS`, `SINGULAR`, and `FILE_FOR_KIND` (5e-database file stem after `5e-SRD-`).
A kind whose file does not exist for a ruleset is skipped for that ruleset with the existing
"no <ruleset> 5e-database file" log line and a row in coverage.md (no Open5e fallback for any
of these; Open5e stays spells-only).

| kind (file name) | singular | 5e-database stem | rulesets |
|---|---|---|---|
| `levels` | `level` | `Levels` | both |
| `features` | `feature` | `Features` | both |
| `subclasses` | `subclass` | `Subclasses` | both |
| `feats` | `feat` | `Feats` | both |
| `magic-items` | `magic-item` | `Magic-Items` | both |
| `magic-schools` | `magic-school` | `Magic-Schools` | both |
| `weapon-properties` | `weapon-property` | `Weapon-Properties` | both |
| `weapon-mastery-properties` | `weapon-mastery-property` | `Weapon-Mastery-Properties` | 2024 only |
| `proficiencies` | `proficiency` | `Proficiencies` | both |
| `languages` | `language` | `Languages` | both |
| `alignments` | `alignment` | `Alignments` | both |
| `ability-scores` | `ability-score` | `Ability-Scores` | both |
| `equipment-categories` | `equipment-category` | `Equipment-Categories` | both |
| `traits` | `trait` | `Traits` | both |
| `subspecies` | `subspecies` | `Subspecies` (2024) / `Subraces` (2014, mapped like species/races) | both |
| `poisons` | `poison` | `Poisons` | 2024 only |

Still skipped (prose, 2014-only): `rules`, `rule-sections`. Keep them in `SKIPPED_KINDS`.

## C2. Normalization rule (zero decisions)

For every new kind, `data` is built by **one generic rule** plus the per-kind fields below:

- **Generic**: copy every top-level source field whose value is a string, number, or bool
  into `data` unchanged (same key). `desc` becomes `description` (joined with `join_desc`).
  Objects and arrays are NOT copied by the generic rule (they stay in `raw`), except as
  listed per kind. Never invent a value; missing = absent.
- **levels**: `class` = `class.index`; `subclass` = `subclass.index` or null; `level`;
  `ability_score_bonuses`; `prof_bonus` → `proficiency_bonus`; `features` = list of
  `features[].index`; `spellcasting` = the source object as-is if present (it is flat ints:
  `cantrips_known`, `spell_slots_level_1..9`, `spells_known`); `class_specific` = source
  object as-is if present. Record `id` = source `index` (already unique like `barbarian-1`).
- **features**: `class` = `class.index`; `subclass` = `subclass.index` or null; `level`;
  `prerequisites` = source list as-is; `description`.
- **subclasses**: `class` = `class.index`; `subclass_flavor`; `description`; `spells` = list
  of `{level, spell}` with `level` = `prerequisites[0].level` if present else null and
  `spell` = `spell.index`; `subclass_levels` = the source URL string as-is.
- **feats**: `prerequisites` = list of `{ability, minimum_score}` from `prerequisites[]`
  (`ability_score.index`, `minimum_score`); `description`.
- **magic-items**: `category` = `equipment_category.index`; `rarity` = `rarity.name`;
  `variant` (bool); `variants` = list of `variants[].index`; `description`.
- **proficiencies**: `type`; `classes` = list of `classes[].index`; `species` = list of
  `races[].index` (2014) or `species[].index` (2024); `reference` = `reference.index`.
- **traits**: `species` = list of `races[].index` (2014) or `species[].index` (2024);
  `subspecies` likewise from `subraces`/`subspecies`; `proficiencies` = list of indexes;
  `description`.
- **subspecies**: `species` = `race.index` (2014) or `species.index` (2024);
  `ability_bonuses` as in species; `racial_traits`/`traits` = list of indexes under key
  `traits`; `description` = `desc`.
- **magic-schools, weapon-properties, weapon-mastery-properties, languages, alignments,
  ability-scores, equipment-categories, poisons**: generic rule only, plus for
  `ability-scores`: `skills` = list of `skills[].index`; for `equipment-categories`:
  `equipment` = list of `equipment[].index`; for `languages`: `typical_speakers` list as-is.

If a source record lacks `index`, `id = slugify(name)`; if it lacks both, skip it and add a
parse warning `"<kind>/<ruleset>: record <i> has no index or name"`.

## C3. Tool changes

- `ingest_srd.py`: `VERSION = "1.1.0"`. Extend the tables in C1. The per-kind normalizers go
  in `NORMALIZERS` like the existing ones; the generic rule is one helper `generic_data(rec)`.
  `discover_5edb` must handle the `subspecies` file-name split exactly like `species`.
  `_write_coverage`: the per-kind table covers every kind in `KINDS`; add a third list after
  spells: **class levels 1–5** (`id | 2024 | 2014`) from `levels` where `data.level <= 5`.
- `validate_rules.py`: no kind list is hardcoded today; keep it that way. Add: for kind
  `level`, `data.level` is an int 1..20 and `data.class` is non-empty.
- `.gitignore` already has the cache. Do not change `attribution_for` or LICENSES text.

## C4. Verify and paste
`python tools/ingest_srd.py` (full), then `python tools/validate_rules.py`
(`OK <n files> <m records>`), then `python tools/ingest_srd.py --twice` (`IDEMPOTENT`), then
the per-kind table from `coverage.md`. `content/rules/` must stay under 40 MB; if the new
kinds push it over, stop and ask Peter (the likely culprit is `raw` on `levels`/`features`).

Update `Plans/Rules/03a-data-ingest.md` with a short "Batch 02b" paragraph (kinds added,
counts, warnings) and the README row for 03a with "+ 16 kinds (02b)". Final message: the
four verification outputs and the commit list.
