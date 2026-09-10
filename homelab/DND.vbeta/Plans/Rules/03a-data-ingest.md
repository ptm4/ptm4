---
plan: 03a
title: SRD / Open5e data ingest
stage: 2
model: sonnet
mode: execute
depends_on: [03]
inputs: [SOURCES.md rows marked confirmed: yes, engine JSON schema from 03]
outputs: [tools/ingest_srd.py, content/rules/{2024,2014}/*.json, content/rules/LICENSES.md with attribution text, content/rules/coverage.md listing 2014 fallbacks used]
done_when: [ingest is re-runnable and idempotent, every record carries ruleset + source + license fields, schema validation passes, coverage.md lists every level 1-5 entity and whether it came from 2024 or 2014]
status: stub
---

# 03a: SRD / Open5e data ingest

## Goal
Turn the confirmed sources into ruleset-tagged JSON the engine loads. 2024 (SRD 5.2) is
the primary; 2014 (SRD 5.1) fills gaps. No hand-typed rules data.

## Steps (draft)
1. Confirm each `SOURCES.md` row with Peter; record the exact license text and version.
2. Pull SRD 5.2 (species, backgrounds, classes, spells, monsters, items, conditions).
3. Pull SRD 5.1 via Open5e (SRD documents only) and/or 5e-database for the fallback set.
4. Normalize into the 03 schema; tag `ruleset`, `source`, `license`, `source_url`.
5. Emit `coverage.md`: what 2024 lacks, what 2014 supplied, what is still missing.
6. Generate the in-game attribution text required by CC-BY-4.0.

## Open questions
- Is there a machine-readable SRD 5.2 yet, or does 5.2 need PDF/markdown parsing?
- Open5e document slugs for SRD-only filtering (avoid third-party OGL/ORC content).
