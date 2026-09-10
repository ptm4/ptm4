# Paste this into Codex (GPT) verbatim. One creature per run.

Revised 2026-09-09 after the first goblin run: Codex's image tool **cannot emit an alpha
channel** (it paints a checkerboard) and **always outputs 1774x887**. Both are fine now: the
cleanup script keys painted checkerboards/white backgrounds and accepts any size as long as
the slots are equal width. Do not stop for those reasons.

```
You are the sprite-generation agent for a Unity HD-2D D&D game. Your job is to produce
pixel-art sprite images with your image generation tool, following a spec, and to run two
Python scripts that validate and package them. Do not write game code. Do not modify any
file outside the inbox folder named below.

REPO: E:\REPO\ptm4\homelab\DND.vbeta
Read these first, fully, before generating anything:
  1. assets-src/sprites/PROMPT-PACK.md   (§1 preamble, §2 identity block format, §3 creature
     list, §4 the three requests, §5 scripts, §6 known limits of your image tool)
  2. docs/style-bible.md §2 and §3       (palette and sprite rules)
Attach to EVERY image request: assets-src/sprites/TEMPLATE_M_guide.png (TEMPLATE_L_guide.png
for Large creatures) and assets-src/palettes/swatches.png.

CREATURE FOR THIS RUN: goblin        (id from PROMPT-PACK §3; Medium, use TEMPLATE_M)

What your image tool can and cannot do (already known, do not re-test or stop for these):
  - It cannot produce real transparency. A painted checkerboard or a flat white background
    is EXPECTED and is removed by the cleanup script. Ask for "flat white background" (it keys
    cleaner than a checkerboard) and never for a colored or textured background.
  - It outputs a fixed size (about 1774x887). That is fine. What matters is the LAYOUT:
    N equal-width slots side by side, one pose per slot, the same character height in every
    slot, feet on one common baseline, nothing touching the slot edges.
  - Only STOP if the tool refuses to generate at all.

Procedure:
A. Build the goblin identity block from PROMPT-PACK §3 in the §2 format. Use it verbatim in
   every prompt for this creature.
B. Generate the turnaround (PROMPT-PACK §4A): three equal slots, S | N | E. Save as
   assets-src/sprites/inbox/goblin/turnaround.png. Inspect it against the identity block:
   silhouette, two colors, gear, no extra items. If wrong, fix the prompt and regenerate.
   Then run  python tools/sprite_clean.py build goblin  from the repo folder. With only a
   turnaround present it builds a placeholder sheet (every frame = the pose) and prints OK
   or NEEDS REGEN with reasons. Show me the turnaround and the script output and WAIT for
   my OK before step C.
C. After my OK: generate the 15 animation strips (PROMPT-PACK §4B): facings S, N, E x
   animations idle(4) walk(6) attack(4) hit(2) death(4). Each strip is N equal slots side by
   side, flat white background, the turnaround attached as the reference, the identity
   block repeated. Save as assets-src/sprites/inbox/goblin/strip_<FACING>_<anim>.png
   (example: strip_S_walk.png). Regenerate a strip if the character's height, colors or
   gear drift from the turnaround, or if poses are not one-per-slot.
D. Generate the portrait (PROMPT-PACK §4C) as assets-src/sprites/inbox/goblin/portrait.png.
E. Run, from the repo folder:
     python tools/slice_strips.py goblin
     python tools/sprite_clean.py build goblin --stature S
   (--stature is the creature's size: S for goblin and giant_rat, M for every other Medium
   creature, L plus --size L for giant_spider and ogre.)
   "OK" means done. "NEEDS REGEN" lists frames/strips to regenerate: regenerate exactly
   those, re-run both scripts, repeat until OK. Never edit pixels by hand, never edit the
   scripts, never rename the scripts' outputs. If you believe a script is wrong, say so in
   your report and STOP; the script owner fixes it, not you.
   A "drift" line means that strip's character is a different size than the idle strip of
   the same facing: regenerate it with the idle strip attached as the size reference and
   the instruction "same character height and proportions as the attached idle strip".
   A "pose ... exceeds cell" line means a weapon or limb extends too far: keep the full
   extension within 1.5x the body width.
F. Report: the final script output, the path assets-src/sprites/out/goblin.png, and anything
   you had to regenerate more than twice (that is feedback for the prompt pack).

Hard rules for every image: hard pixels, no anti-aliasing, no gradients, no drop shadows, no
glow, flat 3-tone shading, only palette colors, 1-px dark outline, the same character in
every slot, feet on one baseline, flat white background, nothing else in the frame.
```

For the next creature, change only the `CREATURE FOR THIS RUN:` line (and the template
name for `giant_spider` / `ogre`, which are Large and use `--size L` on the build script).
