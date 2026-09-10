# Bulk sprite run for Codex (GPT Pro). Paste the fenced block verbatim.

Written 2026-09-10 after goblin, fighter_human, wizard_elf, rogue_halfling all passed.
Codex's own skill `generate-unity-creature-sprites` (copied into this repo at
`.agents/skills/generate-unity-creature-sprites/`) encodes the lessons; this prompt only
sets scope, order, and the no-stall rules.

```
Use your generate-unity-creature-sprites skill. Project: E:\REPO\ptm4\homelab\DND.vbeta
(read assets-src/sprites/CODEX-PROMPT.md and PROMPT-PACK.md first; the skill's Dungine
profile applies). Do not edit any script, palette, or pixel by hand.

SCOPE: produce every creature in the list below, one after another, fully (turnaround,
15 strips, 60 frames, portrait, slice + build + check until OK). Then the second list.

BATCH 1 (finish the first roster):
  cleric_dwarf     --stature M
  skeleton         --stature M
  zombie           --stature M
  bandit           --stature M
  cultist          --stature M
  ghoul            --stature M
  wolf             --stature M   (quadruped: S = head toward viewer, N = tail toward viewer, E = side profile)
  giant_rat        --stature S   (quadruped, same facing rule)
  giant_spider     --size L --stature L   (use TEMPLATE_L_guide.png)
  ogre             --size L --stature L   (use TEMPLATE_L_guide.png)

BATCH 2 (PROMPT-PACK §3b, identity blocks are there):
  kobold           --stature S
  hobgoblin        --stature M
  orc              --stature M
  bugbear          --stature M
  thug             --stature M
  guard            --stature M
  acolyte          --stature M
  wererat          --stature M
  black_bear       --stature M   (quadruped)
  owlbear          --size L --stature L

APPROVAL: Peter pre-approves any turnaround that matches its identity block (silhouette,
two colors, gear, face cue, the DO NOT line). Inspect it yourself against the block and the
style bible; if it matches, save turnaround.png, run the placeholder build, and CONTINUE to
the animation strips without asking. Only stop for a turnaround you cannot make match after
three attempts; then save the best attempt, write why in the inbox status file, and move
on to the next creature.

PER CREATURE, run from the repo folder (E:\REPO\ptm4\homelab\DND.vbeta):
  python tools/slice_strips.py <id>
  python tools/sprite_clean.py build <id> --stature <S|M|L> [--size L for Large]
Repeat targeted regenerations until the output says OK with no "drift" lines. Clipping
notes of 3 px or less are acceptable; more than that, regenerate that strip.

RECORD KEEPING: keep the inbox markdown per creature as the skill describes. At the end of
each creature, append one line to assets-src/sprites/inbox/BATCH-LOG.md:
  <id> | OK or BLOCKED | strips regenerated more than twice | notable limitation
If you hit a usage limit, write "PAUSED at <id> <step>" to BATCH-LOG.md and stop; when
Peter says "continue", resume from that line without regenerating finished creatures.

FINAL REPORT: the BATCH-LOG.md contents, plus the list of assets-src/sprites/out/*.png
produced. No Unity work; the script owner installs sheets.
```

## What to expect
- ~21 minutes per creature at the current pace, so batch 1 is a few hours of Codex time and
  batch 2 the same. Usage limits will pause it; "continue" resumes from BATCH-LOG.md.
- When a batch lands, tell Claude "verify the batch": it rebuilds every sheet with the
  checker, makes contact sheets, installs them into Dungine, and reports.
