---
plan: 05
title: Sprite pipeline
stage: 1
model: codex-image + sonnet
mode: execute
depends_on: [04]
inputs: [style bible, sprite TEMPLATE.png, master palette, creature list from 03a]
outputs: [assets-src/sprites/PROMPT-PACK.md (preamble, identity blocks, 3 requests per creature, first batch of 14), tools/slice_strips.py, tools/sprite_clean.py (build / build-all / check, manifest), Unity import postprocessor (Plan 01), assets-src/sprites/manifest.json, first batch: 4 pregens + 10 monsters]
done_when: [inbox to Unity-ready sheet is one command (done, smoke-tested), output sprites match template + palette exactly (check enforces), manifest has sha256 + sources + tool + date per creature (done), first batch approved by Peter in the POC scene (pending)]
status: drafted
---

# 05: Sprite pipeline

## Goal
Generate as much as possible (D8, D18): GPT image generation driven by a Codex/ChatGPT
agent produces raw images into `assets-src/sprites/inbox/`; a Sonnet-written cleanup
pipeline turns them into template-exact, palette-exact sheets with a manifest.

## Split of work
- **codex-image**: run prompt packs (one per creature family: humanoid, beast, undead,
  fiend...), one facing/animation at a time against the template, into `inbox/`.
- **sonnet**: `sprite_clean.py` (downscale to canvas, nearest-palette quantize, alpha
  threshold, stray-pixel removal, slice into frames), `sheet_assemble.py`, import presets,
  manifest writer, paper-doll layer compositor.

## Hand-off to Codex (Peter runs it, D25) — READY as of 2026-09-09
Claude never invokes Codex. Everything Peter needs is in `assets-src/sprites/`:

1. **`PROMPT-PACK.md`**: the preamble, the identity-block format, the first batch of 14
   creatures (4 pregens + 10 monsters), and the three requests per creature (turnaround →
   15 animation strips → portrait) with exact file names.
2. Attach **`TEMPLATE_M_guide.png`** (or `_L_`) and **`../palettes/swatches.png`** to each prompt.
3. Save results into `assets-src/sprites/inbox/<id>/` exactly as named.
4. Then run, per creature:
   ```
   python tools/slice_strips.py <id>
   python tools/sprite_clean.py build <id>        # --size L for giant_spider, ogre
   ```
   `OK` means `out/<id>.png` is template- and palette-exact and the manifest is updated.
   `NEEDS REGEN` lists which frames to regenerate. Never hand-fix in bulk.
5. Drop `out/<id>.png` into `E:\Unity\Projects\Dungine\Assets\Dungine\Sprites\` (the import
   postprocessor from Plan 01 makes it pixel-perfect on import).

**Start with `goblin` alone.** Consistency across frames is the known risk (see the pack's
§6); the tool cannot fix a character that changed shape between prompts.

### First run outcome (2026-09-09)
Codex stopped because its image tool cannot emit alpha (painted checkerboard, fixed
1774x887) and `CODEX-PROMPT.md` v1 told it to stop in that case. The art itself was good.
Fixes: `sprite_clean` 0.2.0 keys painted backgrounds and accepts any slot size; a turnaround
alone builds a placeholder sheet; `CODEX-PROMPT.md` v2 tells Codex those limits are expected
and to ask for a flat white background. Codex's second turnaround
(`inbox/goblin/turnaround-rejected-02.png`) was promoted to `turnaround.png`, built OK, and
is live in the POC scene. **Next Codex run starts at step C** (animation strips) once Peter
approves the turnaround; otherwise rerun from B with an adjusted identity block.

### Second run outcome (2026-09-09, later)
Peter approved a revised leather-armored olive goblin (D30). Codex generated all 15 strips,
60 frames and the portrait, and correctly reported that `sprite_clean` 0.2.0 fitted each
frame individually, so poses changed size. Fixed in **0.3.0 (D31)**: one scale per facing
from `<F>_idle_0`, slot-center anchoring, and a drift check. Result on Codex's frames:

| Facing | Good strips | Flagged (regenerate at the idle's scale) |
|---|---|---|
| S | idle, walk, attack, death | hit (+45 %) |
| N | idle, attack, hit?, death | walk (-24 %), hit (+43 %) |
| E | idle, hit, death | walk (-22 %), attack (-53 %) |

Also: `S_attack_2` and two idle frames overflow the 64 px cell width by up to 12 px (weapon
extension); sides clipped. Prompt-pack rule added: keep the full extension inside 1.5x the
body width.

### Third run (2026-09-10): goblin complete
Codex regenerated the five flagged strips with the idle strips as size references. Build:
**OK, no drift**, 60 frames + portrait, `manifest.json` marks it non-placeholder
(`sprite_clean 0.3.0`, sha256 `d85363c8...`). Installed in the POC and animating in play
mode (idle/walk/attack/hit/death via `SpriteAnimator`). Remaining cosmetic notes, not
blockers: three frames clip 1-12 px of weapon at the cell edge; `E_death_0/1` read as a
shrunken goblin instead of a stagger (regenerate that strip when convenient). **First
creature of 14 done; the pipeline is proven end to end.** Next creatures: run
`CODEX-PROMPT.md` per creature, `fighter_human` first so the party has a real sprite.

### fighter_human (2026-09-10): complete, 2/14
Codex: 15 strips, 60 frames, portrait, no drift, three walk frames 1-3 px over the top at the
old box-fill scale. That exposed the scale rule bug fixed in **0.4.0 (D32)**: scale to a
stature height (M 72 / S 52), not the body box. Rebuilt fighter at 72 px and goblin at 52 px;
both OK, both installed in the POC, zero runtime errors. Codex's own notes worth keeping for
the prompt pack: hit poses tend to grow (ask for a percentage size reduction), death poses
need "whole silhouette centered, limbs curled", horizontal attack extensions cross slot cuts
(ask for a downward cut with a bent elbow). Next: `wizard_elf`, `rogue_halfling` (Small),
`cleric_dwarf`, then monsters.

### wizard_elf + rogue_halfling (2026-09-10): complete, 4/14
Both OK at stature (72 / 52), no drift, no clipping, installed in the POC. Codex also
distilled its process into a skill, `generate-unity-creature-sprites`, copied into the repo
at `.agents/skills/` (D33). **Bulk mode from here:** `BATCH-RUN.md` gives Codex the
remaining 10 plus a second batch of 10 (PROMPT-PACK §3b) with turnaround approval delegated
against the identity blocks; it logs progress to `inbox/BATCH-LOG.md` and resumes after
usage limits. Claude verifies each batch on request ("verify the batch").

Inbox/out contract (also enforced by the tool): frames `<FACING>_<anim>_<i>.png` at any
integer scale of 64x96 (256x384 recommended), or `sheet.png` at an integer scale of
1280x288; `portrait.png` any square. Output `out/<id>.png` 1280x288 RGBA, alpha 0 or 255,
every opaque pixel in `master.hex`, feet on the ground line.

The Unity plugin also has a Codex variant (`codex plugin add unity@unity-agent-plugin`) if
Codex is ever pointed at the Editor.

## Open questions
- Whether Peter's Codex runs as the CLI or inside the ChatGPT app (affects only how files
  land in `inbox/`).
- Consistency strategy across frames: reference-image conditioning vs generate one sheet
  per prompt. Test both on one creature before batching.
- Alternative pixel-art-specific generators to trial if GPT output needs too much cleanup.
