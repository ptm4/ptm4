---
plan: 03a
title: SRD / Open5e data ingest
stage: 2
model: sonnet
mode: execute
depends_on: [03]
inputs: [SOURCES.md rows marked confirmed: yes, engine JSON schema from 03]
outputs: [tools/ingest_srd.py, tools/validate_rules.py, content/rules/{2024,2014}/*.json, content/rules/LICENSES.md with attribution text, content/rules/coverage.md listing 2014 fallbacks used, content/rules/manifest.json]
done_when: [ingest is re-runnable and idempotent, every record carries ruleset + source + license fields, schema validation passes, coverage.md lists every level 1-5 entity and whether it came from 2024 or 2014]
status: done
---

# 03a: SRD / Open5e data ingest

## Goal
Turn the confirmed sources into ruleset-tagged JSON the engine loads. 2024 (SRD 5.2) is
the primary; 2014 (SRD 5.1) fills gaps. No hand-typed rules data.

## How it ran (Sonnet, 2026-09-11, Plan 16 batch 01 S4)

**Source discovery.** 5e-database (`github.com/5e-bits/5e-database`, commit `0b171af2`) has a
full 2024 (SRD 5.2) set under `src/2024/en/5e-SRD-*.json` for every kind **except spells** — it
ships no `5e-SRD-Spells.json` for 2024 (confirmed by a 404 on that exact path). 2014 (SRD 5.1)
is complete for all nine kinds. Per the plan's fallback order, Open5e v2 (`api.open5e.com`,
document `srd-2024`) was checked next and does carry 2024 spell data (339 spells, verified with
`curl`) — but the ingest script could not reach it: Python's OpenSSL rejects Open5e's TLS
certificate chain (`certificate has expired`) even though every certificate in that chain is
independently valid through at least 2028 (checked with `openssl x509 -noout -dates` on each
link) and `curl` on the same machine, using Windows' own certificate store, connects fine. This
looks like a stale/incomplete local trust-store entry for Open5e's recently-rotated Let's
Encrypt intermediate ("YE1"/"Root YE"), not a problem with the data or the script.
**Resolved by Fable 2026-09-12:** `ingest_srd.py` now falls back to the system `curl` (which
verifies through the OS trust store) only when urllib raises `SSLCertVerificationError`;
verification is never disabled. 2024 spells landed: 339 records. Open5e's spell shape is
normalized to 5e-database's vocabulary (ability abbreviations, class slugs without the
`srd-2024_` prefix, the spell's own level included in `at_slot_level`).

**What was ingested.** All nine kinds (monsters, conditions, equipment, classes, species,
backgrounds, skills, damage-types) for both rulesets. `content/rules/` is
6.6 MB (1553 records across 18 files), well under the 40 MB stop-and-ask threshold. `species`
2014 reads `5e-SRD-Races.json` (2014 calls them "races"); 2024's own `5e-SRD-Species.json` is
used directly. Every skipped/blocked kind is recorded in `coverage.md`, not silently dropped.

**Verification.** `python tools/validate_rules.py` → `OK 18 files 1553 records`.
`python tools/ingest_srd.py --twice` → `IDEMPOTENT` (byte-identical per-kind data files across
two runs from cache; `manifest.json`/`coverage.md` are excluded from that check since they
carry a `generated` timestamp by design).

## Steps (as executed)
1. ~~Confirm each `SOURCES.md` row with Peter~~ — already confirmed 2026-09-09 (see `SOURCES.md`).
2. Pull SRD 5.2 (species, backgrounds, classes, monsters, equipment, conditions, skills,
   damage-types) from 5e-database; 2024 spells from Open5e v2 (`srd-2024`).
3. Pull SRD 5.1 (all nine kinds) from 5e-database.
4. Normalized into the envelope schema; every record tagged `ruleset`, `source`, `source_url`,
   `license`, `attribution`, plus `data` (normalized) and `raw` (untouched source record).
5. `coverage.md` emitted: per-kind counts, 2014-only ids, monsters CR≤5 and spells level≤3
   presence tables, skipped kinds (feats/magic-items/subclasses/rules-text — out of scope for
   this batch), parse warnings (one: `octopus`'s "Ink Cloud" action has no reach/range text to
   parse), and the Open5e blockage.
6. `LICENSES.md` generated with the CC-BY-4.0 attribution text for SRD 5.2 and SRD 5.1 verbatim
   (source-stated version strings: "SRD 5.2", not "5.2.1" — Open5e's own document record names
   it that way), a 5e-database MIT/SRD note, and an Open5e note. Must be surfaced in Plan 11's
   credits screen and Plan 14's `THIRD-PARTY.md`.

## Open questions
- ~~Is there a machine-readable SRD 5.2 yet~~ — yes, 5e-database's `src/2024/en/`, except spells.
- ~~Open5e document slugs for SRD-only filtering~~ — `document__key=srd-2024` / `srd-2014`.
- Feats, magic items, subclasses and rules-text prose are out of scope for this batch
  (`coverage.md` "Skipped kinds"); a future batch should size that work.

## Batch 02b (Sonnet, 2026-09-12, Plan 18)

Ingested the remaining 16 kinds, same envelope/sources/idempotence rules: `levels`, `features`,
`subclasses`, `feats`, `magic-items`, `magic-schools`, `weapon-properties`,
`weapon-mastery-properties` (2024 only), `proficiencies`, `languages`, `alignments`,
`ability-scores`, `equipment-categories`, `traits`, `subspecies` (2024 `Subspecies.json` /
2014 `Subraces.json`, mapped like species/races), `poisons` (2024 only). `SKIPPED_KINDS` is
now just the 2014-only prose kinds `rules`/`rule-sections` (feats/magic-items/subclasses moved
out of "skipped" into ingested). `content/rules/` is now 12 MB across 48 files, 3953 records —
well under the 40 MB stop-and-ask threshold.

**Two deviations from the plan text, both logged, neither a design decision:**
- **`feats` prerequisites shape.** Plan 18 C2 specifies `prerequisites` as a list of
  `{ability_score, minimum_score}` — true for 2014's one feat (`grappler`) but not for 2024's
  17 feats, whose `Feats.json` uses an unrelated schema (`prerequisites: {minimum_level,
  feature_named}` plus a separate `prerequisite_options` for ability-score choices). Normalizing
  that 2024 shape isn't specified anywhere, so `data.prerequisites` is left absent for those 13
  records that hit it (the plan's own "never invent a value; missing = absent") — the full
  structure is still in `raw`. Each instance is logged in `coverage.md` "Parse warnings"
  (`feats/2024: <id> has a non-list 'prerequisites' shape...`). Whoever designs the 2024 feat
  model (03e) should read `raw.prerequisites`/`raw.prerequisite_options` directly.
- **`levels` name for 2014.** 2014's `Levels.json` (unlike 2024's) has no `name` field at all,
  which would leave the required envelope `name` field empty for all 290 2014 level records.
  2024's own records already name themselves `"<Class> <level>"` (e.g. `"Barbarian 1"`) from
  exactly the `class`/`level` fields every record has; the same convention is applied only when
  the source omits `name`, so 2014 levels get e.g. `"Barbarian 1"` too. Not a new naming
  scheme — the one the source already uses elsewhere, applied where it's missing.
- Also fixed in passing (pre-existing, not batch-02b-specific): the Open5e-fallback path would
  have crashed (`SystemExit`) on any *other* kind missing its 2024 5e-database file, since the
  old code routed every 2024 gap through the (spells-only) Open5e fallback regardless of kind.
  Restricted the fallback trigger to `kind == "spells"`, matching "no Open5e fallback for any of
  these [16 kinds]" in Plan 18 C1.

**Verification.** `python tools/validate_rules.py` → `OK 48 files 3953 records`.
`python tools/ingest_srd.py --twice` → `IDEMPOTENT`.
