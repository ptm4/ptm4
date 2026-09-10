# Dungine profile and observed failure lessons

Use this profile for the CODEX-PROMPT.md pipeline in DND.vbeta. Paths below are relative to the project root unless explicitly marked as an example. Read current project documents; this profile records observations from 2026-09-10 and does not freeze old implementation behavior.

Example local project root: `E:/REPO/ptm4/homelab/DND.vbeta`. The Unity Editor project is separate; a repo-side sprite build does not establish a Unity import or play-mode test.

## Source contract and writable scope

Read:

- `assets-src/sprites/CODEX-PROMPT.md`
- `assets-src/sprites/PROMPT-PACK.md`
- `docs/style-bible.md`, palette and sprite sections
- `assets-src/sprites/inbox/<id>/*.md` for the current approved identity, prior prompts, and completion state.

Inspect:

- `assets-src/sprites/TEMPLATE_M_guide.png`, or `TEMPLATE_L_guide.png`
- `assets-src/palettes/swatches.png`

The prompt limits manual asset/doc changes to the selected creature inbox. The explicitly requested slicer/build may write their normal generated outputs and manifest. It does not authorize game-code edits, script edits, changing palette sources, or Unity installation. An explicit user authorization can extend that scope.

Old prompt text has conflicting transparency, palette-count, wizard-hat, and stature defaults. Reconcile against the current user brief, current palette/style data, the later notes, and script behavior. For example, Dulandir's approved white beard, pointed hat, and blue/gold robes overrode the original no-hat/purple wizard entry. Goblin's approved olive skin and leather armor replaced neon green/bare torso. These are examples of user overrides, not defaults for future characters.

## Delivery and flags

| Creatures | Cell / guide | Stature | Build flags |
|---|---|---|---|
| rogue_halfling, goblin, giant_rat | 64x96 / M | Small, 52 px | `--stature S` |
| Other Medium-template creatures | 64x96 / M | Medium, 72 px | `--stature M` |
| giant_spider, ogre | 128x128 / L | Large, 104 px | `--size L --stature L` |

Confirm additions/changed creature classifications in the live plan. Small stature still uses the M cell/template. Version 0.4.0 derives one source scale per facing from its `<FACING>_idle_0.png` and the requested stature; the older fit-to-box behavior produced wrong relative heights. The current master palette is Dungine-57, including approved goblin olive tones.

Three generated facings: S/front, N/back, E/right. W mirrors E at runtime; do not add W files. Twenty columns per facing: idle 4, walk 6, attack 4, hit 2, death 4. Sheet: 1280x288 for M cell or 2560x384 for L; portrait 128x128; PPU 64; ground line 4 px above bottom.

Required source names:

- `turnaround.png`
- `strip_<FACING>_<anim>.png` (15 strips)
- `portrait.png`

The slicer writes `<FACING>_<anim>_<i>.png` for zero-based frame indices. Build writes `assets-src/sprites/out/<id>.png`, portrait output, and `assets-src/sprites/manifest.json`. Do not rename generated outputs.

## Commands and source precedence

Run from the project root, substituting the actual id:

```powershell
python tools/sprite_clean.py build rogue_halfling --stature S
```

For a new creature with only turnaround, this builds a placeholder for review. When continuing an existing inbox, inspect which sources the build will select: in version 0.4.0, `sheet.png` takes precedence over frames; otherwise existing single frames take precedence over turnaround. Do not silently delete or rename older assets to force a source switch. A new selected creature normally has no such collision; a collision needs a scoped resolution.

After all strips:

```powershell
python tools/slice_strips.py rogue_halfling
python tools/sprite_clean.py build rogue_halfling --stature S
python tools/sprite_clean.py check assets-src/sprites/out/rogue_halfling.png
```

For a Large creature use `--size L --stature L` on build and `--size L` on check. Expected slicer result for a full run: `60 frames written from strips, 0 strips missing`. Confirm the manifest represents the selected sources and has `placeholder: false` for completed animations.

The checker tests dimensions, binary alpha, palette, and ground line. It does not guarantee every cell is populated or visually correct; blank cells are skipped. Build measures drift for walk/attack/hit against that facing's idle, and excludes death because falling legitimately lowers the silhouette. Review death anatomy visually. Clipping notes do not necessarily make build fail, and only a subset of notes is printed.

## Slot and scale diagnosis

The observed generator usually returned 1774x887, but actual dimensions can differ: a rogue N_walk returned 2098x750 despite a 1774x887 prompt, and the tool preview was resized to 2048x732. Measure the saved source, not its displayed preview. Compute from the returned image rather than trusting prompt coordinates:

- Strip slot interval i: `[int(i * (W/N)), int((i+1) * (W/N)))`
- Interior cut j: `int(j * (W/N))`
- Suggested prompt center: `(i+0.5) * (W/N)`

At W=1774 and N=6, cuts are 295, 591, 887, 1182, 1478. A previous rounded-cut scan differed by 1 px. Scan a small band around the real cuts, and look at every source frame.

Read-only image inspection via Pillow/NumPy is allowed; source editing/resizing/repainting must use the authorized image generator, and final processing belongs to the existing tools. The completed wizard was audited by importing the current `sprite_clean.py` without running its main entrypoint, using:

- `key_background` for a source alpha mask and checking the exact cut bands;
- `reference_scale` using each facing's idle0 and the correct target stature;
- `fit_frame` on all 60 source frames and inspecting its full returned notes.

When reusing that diagnostic, read the functions' current signatures first. It writes no asset files. Do not make importing/executing a copied alternate cleanup implementation part of the workflow.

## What the previous retries taught

- **Goblin hit:** an otherwise correct recoil returned 26% too large. Attaching its idle as the size authority and explicitly reducing source size corrected drift. Turnaround was identity-only, not the size authority.
- **Fighter:** downward bent-elbow attacks reduced cross-slot blades. Full-body hit language prevented zoomed-in reactions. Final numerical PASS coexisted with clipping, exposed by read-only all-frame inspection; owner later corrected stature behavior.
- **Wizard:** reduce the initial idle size before other strips to make room for six-slot walk. S/E death needed curled limbs, a compact hat pose, and foreshortened staff along the body. E walk needed 9 retries: spacing edits changed height and size edits disturbed spacing. Do not repeat its sequence of horizontal compression and vertical stretching as a recipe; preserve proportions and diagnose one defect at a time.

Evidence within the example project: `inbox/goblin/V030-RESULT.md`, `inbox/fighter_human/FINAL-RESULT.md`, and `inbox/wizard_elf/{COMPLETION,ANIMATION-PROMPTS,FINAL-CORRECTIONS}.md`, all under `assets-src/sprites/`.

## Compact prompt scaffold

```text
[Resolved identity block, unchanged]
Reference 1: this facing's idle, authoritative SIZE REFERENCE.
Reference 2: approved turnaround, identity only.
Reference 3: template guide, geometry only.
Reference 4: palette swatches, colors only.
[Facing], [animation], exactly N equal-width slots, one full character per slot.
Same character height and proportions as the attached idle strip,
flat white background, N equal slots, feet on one baseline.
Center the whole silhouette including all gear. Clear white gutters at every cut.
Keep the source pixel size independent of N. Do not enlarge to fill the canvas.
[Specific pose sequence and only the diagnosed correction, if retrying.]
Hard pixels, flat 3-tone shading, dark 1 px outline at final scale;
no gradients, anti-aliasing, cast shadows, floor, glow, text, or grid.
```

Portrait uses the same identity/template/palette and turnaround, with the plan's bust framing; it has no animation idle-size requirement. Request an explicit square 1:1 source canvas as the plan specifies, then inspect the saved source aspect ratio and the final 128x128 portrait. In sprite_clean 0.4.0, the portrait exporter resizes the whole source canvas directly to 128x128 without first cropping its content. A rogue portrait drawn in square content on a 1774x887 landscape canvas was horizontally compressed by that export. Regenerating through the built-in tool with an explicit square 1:1 canvas returned 1254x1254 and resolved the distortion without script edits. Do not assume the generator is limited to landscape canvases, and do not treat square content inside a landscape image as a square source.
