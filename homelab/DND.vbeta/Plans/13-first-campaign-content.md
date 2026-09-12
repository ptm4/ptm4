---
plan: 13
title: First campaign content
stage: 3
model: fable + peter
mode: decide
depends_on: [07, 08]
inputs: [campaign schema + authoring guide, Peter's choice of original vs adaptation, sprite/voxel kits]
outputs: [content/campaigns/<name>/ (or content/private/<name>/ if adapted), 4 pregens, all needed sprites and tiles generated via 05/06, playtest notes]
done_when: [campaign plays start to finish solo in auto-DM mode, then with Peter as DM, with no schema changes needed]
status: stub (module chosen 2026-09-12: Descent into Avernus, chapter 1 first; see DECISIONS D48)
---

# 13: First campaign content

## Goal
The content the local beta and the friends test will run. Written with Claude at authoring
time (D3), executed by the auto-DM.

## Decision to make first
Original short campaign (ships with the game, SRD-only monsters) versus a private
adaptation of a published module for the home table (lives in `content/private/`, never
shipped, D5). Recommendation: an original 3-4 session arc for levels 1-3 first, since it
can ship and doubles as the tutorial; adaptations later.

## Open questions
- Tone and setting (feeds sprite/voxel biome priorities).
- How much branching for v1.


## Module chosen (D48, 2026-09-12)

*Baldur's Gate: Descent into Avernus*, chapter 1 first. Private adaptation only
(`content/private/avernus/`, gitignored, never in a build). Asset needs for chapter 1, all
original work and therefore shippable: Baldur's Gate street/sewer biome (voxel kit), the
Dead Three dungeon (dungeon kit reuse + cult props), sprites for cultists/cult fanatics/bandits/
guards (SRD stat blocks) and the chapter's devils (imp, lemure, bearded and barbed devils are
SRD), portraits for the named NPCs (our own designs, not the book's art). Non-SRD creatures
and NPC stat blocks are homebrew entries Peter writes into the private folder.

## Reference material (reference only, never ingested; SOURCES.md)

- r/DescentintoAvernus master post: the index of guides, remixes and map packs. Use for
  structure and pacing decisions, especially the Alexandrian Remix's restructuring of the
  Avernus chapters into a hex-crawl, which is the shape Plan 07's overworld should support.
- The book itself (Peter's copy) and its 5e.tools page: Peter's reading only. Scene lists,
  NPC rosters and encounter tables are authored by Peter into `content/private/avernus/`.
