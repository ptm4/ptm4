# Dungine roadmap — the one page to check "where are we"

Updated 2026-09-12 by Fable. Detail lives in `Plans/` (index in `Plans/README.md`, decisions
in `Plans/DECISIONS.md`, dated snapshots in `Plans/STATUS-*.md`). This file is the shape of
the whole thing and the current marker.

## The idea (Peter, 2026-09-12)

Dungine is a generic D&D 5e game master: it loads a module we wrote, runs the world, combat
and rules for everyone at the table, and we (Peter, Fable, Astra) make the modules and assets.
Roleplay happens on Discord with the people; the engine handles everything a rulebook would.
Each chapter or session is a DM session in the app. First module: *Descent into Avernus*,
chapter 1, adapted privately (D48).

## Phases and where we are

```
 A. Dungine core  ────────►  B. Module & campaign  ────────►  C. Assets at scale  ──►  D. Beta & ship
 engine + app that runs      format, NPCs, chapter 1,       DiA-specific art batches,     friends test over
 modules; DM tools; the      auto-DM runs it, we test        biomes, sprites, portraits    Relay, builds, ship
 POC grows into this         and keep adding
      ▲ YOU ARE HERE (early A)
```

| Phase | What "done" means | Status 2026-09-12 |
|---|---|---|
| **A. Dungine core** | The POC scene runs on the engine (`Encounter` + `Compendium`), not on hand-written combat code; full core rules (movement, attacks, conditions, spells, rests, death); DM setup + placement of units and props; a module loads from a file; per-player camera; Discord-side roleplay needs nothing from the app. | ~30 %. POC proven and kept (D49). Engine: objects/Interact done, batch 02 (loader, core mechanics, conditions) ready for Sonnet, spells next. Rules data ingested. DM setup prototype in the POC. |
| **B. Module & campaign** | Storybook format (Plan 07) with scenes, encounters, dialogue, checks, flags, hex-crawl overworld; chapter 1 authored by Peter in the private folder; NPC/creature stat blocks; the auto-DM (Plan 08) runs it solo; we play it and fix what's wrong. | 5 %. Module chosen. Schema not designed yet (needs A's loader first). |
| **C. Assets at scale** | Every location, creature and NPC chapter 1 needs, in our style: city/sewer biome, cult props, cultist/devil sprites, original NPC portraits; then the infernal biome for later chapters. | Foundations done: 24 creatures, dungeon 42 + cave 18 tiles, pipelines and Codex skills proven. Chapter-1 lists not written yet. |
| **D. Beta & ship** | Relay/Lobby multiplayer, builds for Win/mac/Linux with the CC-BY credits, friends test, feedback loop, ship criteria. | 0 %. |

Phases overlap on purpose: C runs on Astra while A and B run on Fable + Sonnet, and B's
authoring is Peter's while the engine catches up.

## Who does what

- **Fable**: designs (engine architecture, spell/effect model, storybook schema, auto-DM,
  UI), reviews every Sonnet and Astra deliverable, writes Sonnet batches, runs the bridge.
- **Sonnet**: executes written batches, zero decisions (`Plans/16-*.md` shows the format).
- **Astra (Codex)**: assets (voxel kits, sprites, portraits) and Unity-side tasks, via the
  bridge or interactively with bridge hand-offs.
- **Peter**: direction, look reviews, commits, authoring chapter 1, running sessions.

## Next five steps (in order)

1. Sonnet batch 02 (`Plans/17-sonnet-batch-02.md`): engine JSON reader + compendium loader,
   core mechanics half 1, conditions.  ← paste to a Sonnet tab now
2. Sonnet batch 02b (`Plans/18-sonnet-batch-02b.md`): ingest the remaining SRD kinds
   (levels, features, subclasses, feats, magic items, …).  ← parallel-safe with 1
3. Fable: spells/effects design (03c) → Sonnet batch 03.
4. Fable + Astra: wire the POC to the engine (D49): TurnManager becomes a presenter over
   `Encounter`; units come from the compendium; DM setup gains prop placement.
5. Fable: Plan 07 storybook schema against DiA chapter 1; then Astra's chapter-1 asset lists.

## Standing rules
No non-SRD text in the repo or a build; module content lives in gitignored `content/private/`.
No commits by agents. Every visual has Inspector knobs. Never edit the repos while a bridge
run is active.
