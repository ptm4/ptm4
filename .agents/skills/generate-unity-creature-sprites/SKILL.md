---
name: generate-unity-creature-sprites
description: Generate or repair a creature's pixel-art turnaround, animation strips, and portrait through a project's CODEX-PROMPT.md and slice_strips.py / sprite_clean.py pipeline. Use for Dungine-style Unity sprite production with design approval, fixed slots, palette cleanup, and stature checks; not for general Unity coding or unrelated illustration.
---

# Generate Unity creature sprites

Turn an approved character into consistent source strips and a validated sheet. Preserve the approved design and use the project's existing cleanup tools; a numerical PASS alone does not establish visual quality.

This workflow was exercised on Dungine goblin, fighter, and wizard runs. Read [the Dungine profile](references/dungine-profile.md) when using that project. For another project, establish its equivalent contract first; do not impose Dungine dimensions, palette, filenames, or approval rules without support.

## Establish the run once

- Locate the project from the user's path or workspace. Read its `CODEX-PROMPT.md`, `PROMPT-PACK.md`, style-bible palette/sprite sections, and the creature's existing brief, approval, and generation logs. Confirm the current scripts' options and source precedence without editing them.
- Merge explicit user appearance choices over conflicting defaults. Carry forward non-conflicting plan details. Put the resolved identity block, references, size/stature, approval status, and pending deliverables in the creature inbox Markdown. Reuse that same identity block in every prompt.
- Respect current scope: a new creature, an approved continuation, and a request to replace five named strips are different jobs. On a targeted repair, leave other source strips and the portrait alone. Existing approval and routine build authorization remain valid across turns.
- Ask only for a material unresolved design choice or a necessary scope change. Do not ask the user to reapprove an already approved design. Never invent approval or missing character traits.

## Generate and approve the turnaround

Use the built-in image generation tool; the installed `imagegen` skill describes its current interface. CLI/API generation requires explicit user authorization, including after a tool failure or usage limit.

Attach the current template guide and palette swatches to **every** request, including edits and portrait. Inspect local references before using them, and label each reference's role in the prompt.

Generate S/front, N/back, E/right profile in three equal slots. Inspect silhouette, proportions, face cues, equipment, and colors against the resolved identity. Save the selected original as `turnaround.png` in the authorized inbox and run the project's placeholder build with the correct stature. Show the actual turnaround and build output, then wait for design approval before animation. Skip this checkpoint when that exact design is already approved.

## Establish source scale before multiplying strips

Make a facing's idle strip before its walk/attack/hit/death strips. Set the initial source character size so the complete silhouette can fit the **six-slot walk**, the narrowest layout, on the actual generated canvas. Do not let a four-slot idle fill the canvas height by default.

Keep these separate:

- Source pixel height/proportions: must remain stable between a facing's strips.
- Delivery cell size and stature: set by the existing cleanup flags, not by enlarging every source pose.

Use one shared baseline and explicit whole-silhouette centers/gutters. Measure actual output dimensions; requested dimensions may be ignored. If idle needs a uniform source-size correction, settle that first. Carry the established scale into other facings and verify each; their own idle becomes the scale authority. After animation production starts, do not change idle merely to disguise drift in another strip.

## Produce the approved animations and portrait

For each non-idle animation, attach in clearly stated roles:

1. That facing's idle strip: **SIZE REFERENCE**.
2. Approved turnaround: identity reference.
3. Template guide: final geometry reference.
4. Swatches: palette reference.

Repeat: **"same character height and proportions as the attached idle strip, flat white background, N equal slots, feet on one baseline"**, replacing N with the required count. State that character size does not change with slot count.

For idle generation use the turnaround and, when available, the already established idle from another facing. For an idle correction attach that same facing's current idle as the size reference; do not create a circular requirement before the first idle exists.

Use the project's frame counts and naming. In the Dungine profile: S/N/E each have idle(4), walk(6), attack(4), hit(2), death(4), yielding 15 strips / 60 frames.

Keep the difficult poses specific:

- **Hit:** two full-body recoil/half-return poses. Full head, feet, and gear in both slots; no close-up or dramatic camera zoom.
- **Attack:** wind-up, strike with frame 3 at full extension, recovery. Prefer a short downward cut with bent elbow when applicable to the approved weapon. Keep weapon extension within 1.5x body width and inside its slot.
- **Death:** stagger, fall, grounded, settled. Center the entire silhouette, including weapon, hat, tail, or cloak. Curl limbs inward and pose long gear compactly; do not center only the head or torso. Preserve anatomy and equipment.
- **Walk:** distinct cycle phases and full-body proportions, no sliding or arbitrary enlargement.
- **Idle:** subtle breathing/weight shift; first pose matches the turnaround.

Use hard pixels, flat three-tone material shading, the approved palette and outline, and a flat white background for this project's keying workflow. No text, grid, floor, cast shadow, blur, or glow. White-background handling is a project convention, not a claim about every image tool's current alpha capability.

Generate the portrait from the same approved identity and gear using the plan's framing. Copy selected outputs into the inbox with exact expected filenames. Keep source originals at their returned locations.

## Check before accepting, then retry narrowly

Inspect each source immediately for correct count/facing/identity, stable size, a common baseline, and clear gutters at the **actual slicer's integer cut positions**. This catches fragments before they are split into adjacent frames. A dark-pixel boundary scan is only a diagnostic: visually confirm faint details and the full silhouette too.

Run the existing slicer, build with explicit stature, and checker. After replacing a strip, run the slicer again before the build; otherwise the build can use stale single frames. Inspect the final sheet and portrait at delivery scale.

Treat these as separate evidence:

- Slicer completeness and expected frame count.
- Build drift/missing-frame result and **all reported clipping notes**.
- Format/palette/alpha/ground-line checker.
- Visual source cuts, anatomy, equipment, pose readability, and animation consistency.

If output looks wrong despite OK, use the existing cleanup functions read-only to inspect unprinted fit/clipping notes; the Dungine build truncates its note list. Do not edit scripts, thresholds, palette, or pixels to turn a failure into a pass. If the script itself is wrong, preserve the concrete failing evidence and hand it to the owner.

Change one diagnosed problem per retry:

- Wrong scale: use the facing idle and a measured, uniform size correction on an unchanged canvas.
- Boundary overlap: preserve size, compact the pose, and recenter the whole silhouette.
- Identity/gear drift: return to approved references and repeat invariants.
- Repeated edit preserves the same layout defect: regenerate from approved turnaround + idle instead of repeatedly feeding the faulty strip back.
- After two unsuccessful retries for the same reason, remeasure scale and cuts before spending another generation. Do not keep appending contradictory size/position constraints.

Do not use anisotropic squashing/stretching as a routine fix; it can trade a cut failure for wrong anatomy. Do not shrink every animation to satisfy a single wide pose. Continue targeted correction until the requested scope passes; report residual problems outside a targeted-only repair without changing those sources.

If generation is refused or usage-limited, save status and exact error and report the block. Do not silently change backend or start scheduled work.

## Leave a resumable record

After each generation, persist prompt text, reference roles/paths, returned original path, selected inbox filename, retry number/reason, and acceptance status. Store compact metadata; never dump image base64 into logs or tool text.

At handoff, record the final exact command output, final sheet/portrait paths, script version and stature, approved design, and pending work. Explicitly list any strip regenerated **more than twice**. If final inspection finds a limitation, report it even when the script says OK. Claim Unity runtime validation only if it actually occurred. Do not regenerate completed good assets just because a conversation resumed.
