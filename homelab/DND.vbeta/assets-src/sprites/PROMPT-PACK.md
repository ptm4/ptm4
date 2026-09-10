# Sprite prompt pack v0.1 (Plan 05) — for Peter to run in Codex / ChatGPT

Attach to every request: `TEMPLATE_M_guide.png` (or `_L_guide` for Large) and
`../palettes/swatches.png`. Save results exactly where §4 says. Then run the cleanup.

**Run one creature end to end first** (recommended: `goblin`), check the output in Unity,
and only then batch the rest. The cleanup tool fixes palette and alpha; it cannot fix a
character that changed shape between frames. Consistency is the thing to test.

## 1. Style preamble (paste at the top of every prompt)

```
You are producing pixel-art sprite frames for an HD-2D fantasy RPG (Octopath Traveler /
Sea of Stars fidelity, Rain World grit). Rules that are not negotiable:
- Pixel art, hard pixels, no anti-aliasing, no gradients, no blur, no drop shadows, no glow.
- Transparent background. Nothing else in the image: no floor, no props, no text, no frame.
- Colors ONLY from the attached 54-color palette. Outline every shape in the darkest ink
  (#0b0a12), 1 pixel wide at final scale.
- Draw at 4x scale: each frame is 256 x 384 pixels for a Medium creature (the final frame is
  64 x 96). Keep the character's feet exactly 16 px above the bottom edge (4 px at 1x) and
  horizontally centered. The character occupies roughly the middle 160 x 288 (the "body box").
- 3-step shading per material (base, shadow, highlight) lit from the upper-left-front.
- Silhouette first: the creature must be recognizable filled in solid black.
- The same character must be pixel-consistent across every frame and facing: same height,
  same proportions, same colors, same gear.
```

## 2. Per-creature identity block (one per creature; the SAME block on every prompt for it)

Fill from the list in §3. Shape:

```
CREATURE: <name>   SIZE: Medium (64x96 final)
SILHOUETTE: <one sentence: the shape that identifies it at 64 px>
TWO COLORS: <primary ramp> + <secondary ramp>  (from the palette names)
GEAR: <2-3 items max, all readable at 64 px>
SKIN/HIDE: <ramp>   FACE: <one cue: hood, tusks, bare skull, none>
DO NOT: <one thing generations of this creature tend to get wrong>
```

## 3. First batch (4 pregens + 10 monsters)

| id | Identity block essentials |
|---|---|
| `fighter_human` | Broad shoulders, rectangular; metal + earth_wood; longsword + kite shield, banded mail; skin_2; face: open helm. DO NOT add a cape. |
| `wizard_elf` | Tall thin triangle, staff taller than head; night_purple + sand_warmstone; robe, staff with `emissive_magenta_1` gem, satchel; skin_3; face: long hair, no hat. DO NOT give a pointed hat. |
| `rogue_halfling` | Short, crouched, wide stance; earth_wood + neutral; two daggers, hooded leather; skin_2; face: hood up. DO NOT make it child-proportioned; it is a compact adult. |
| `cleric_dwarf` | Squat wide block, beard is a shape; metal + emissive_orange (holy symbol only); warhammer, scale mail, round shield with sun symbol; skin_2; face: braided beard. DO NOT glow the whole figure. |
| `goblin` | Small hunched, big head, big ears; acid_green (skin) + earth_wood; scimitar, ragged loincloth, small shield; face: overbite. DO NOT make it cute. |
| `skeleton` | Thin, angular, gaps between bones; neutral (bone `neutral_6`) + metal; rusted shortsword, broken shield; face: bare skull. DO NOT add flesh or eyes-glow unless told. |
| `zombie` | Slouched, one arm lower, torn outline; skin_1 desaturated toward `neutral_4` + earth_wood; no weapon, torn tunic; face: slack jaw. DO NOT add blood pools. |
| `wolf` | Long horizontal body, low head; neutral_3/4 + neutral_1; no gear; hide neutral; face: pointed muzzle. DO NOT make it a dog. |
| `giant_rat` | Low oval, long tail is half the silhouette; earth_wood_1/2 + skin_2 (tail, ears); no gear. DO NOT give it a collar. |
| `bandit` | Human, lean, scarf over face; earth_wood + danger_red (scarf only); scimitar, leather; skin_2; face: masked. DO NOT armor it heavily. |
| `cultist` | Human, hooded robe to the floor, no visible legs; night_purple + neutral_0; dagger; skin_2 hands only; face: hood shadow. DO NOT show a face. |
| `ghoul` | Hunched, long arms, claws; acid_green_0/1 (skin) + neutral; no gear, rags; face: lipless grin. DO NOT confuse with zombie: ghoul is fast and sharp, zombie is soft and slow. |
| `giant_spider` (Large, use TEMPLATE_L) | Wide flat, 8 legs read as spikes; neutral_1/2 + danger_red (eyes only); no gear. DO NOT symmetric-mirror legs in the E facing. |
| `ogre` (Large, use TEMPLATE_L) | Massive pear, tiny head; skin_1 + earth_wood; greatclub, loincloth; face: underbite. DO NOT armor. |

## 4. The three requests per creature (in this order)

**A. Turnaround (approve before anything else)**
```
[preamble] [identity block]
Produce ONE image, 768 x 384, transparent: three views of the character in a neutral idle
stance side by side, each in its own 256 x 384 slot: S (facing the viewer), N (back view),
E (right side view, facing right). Same height and proportions in all three.
```
Save as `inbox/<id>/turnaround.png`. Look at it. If the shape is wrong, fix the identity
block and regenerate. Do not proceed until it is right.

**B. Animation strips (one prompt per facing x animation, 15 prompts per creature)**
```
[preamble] [identity block]
Using the attached turnaround as the exact reference for this character, produce ONE
image, <N*256> x 384, transparent: the <FACING> view performing "<ANIM>" as <N> frames left
to right, each frame in its own 256 x 384 slot, feet on the same ground line in every frame.
<ANIM NOTES>
```
Facings and frame counts: idle 4, walk 6, attack 4, hit 2, death 4. Anim notes:
- idle: breathing/weight shift only; frame 1 = the turnaround pose.
- walk: full cycle, contact-down-pass-up, no sliding; frame 1 = left foot forward.
- attack: wind-up, strike (frame 3 is the hit frame, weapon at full extension), recover.
  Keep the full extension within 1.5x the body width; the cell is only 64 px wide.
- every strip: the character must be the SAME height as in this facing's idle strip
  (attach the idle strip as the size reference for walk/attack/hit/death).
- hit: recoil, then a half-return.
- death: stagger, fall, on the ground, settled (last frame is held in game).
Save each strip as `inbox/<id>/strip_<FACING>_<ANIM>.png` (e.g. `strip_S_walk.png`).

**C. Portrait**
```
[preamble] [identity block]
Produce ONE image, 512 x 512, transparent: a bust portrait of the character, head and
shoulders, three-quarter view facing left, same colors and gear as the turnaround.
```
Save as `inbox/<id>/portrait.png`.

## 5. After generating: slice strips into frames and clean

The cleanup tool expects single frames named `<FACING>_<anim>_<n>.png`. Slice each strip:
```
python tools/slice_strips.py <id>
python tools/sprite_clean.py build <id> --stature M   # S for goblin/giant_rat; L (+ --size L) for giant_spider/ogre
```
`build` writes `out/<id>.png`, `out/<id>_portrait.png`, updates `manifest.json`, and prints
`OK` or `NEEDS REGEN` with the reason. Regenerate the failing strip; do not hand-edit.

## 6. Known limits of the image tool (learned on the first goblin, 2026-09-09)
- **No alpha channel, ever.** Codex's image tool paints the checkerboard into the pixels and
  returns RGB. The cleanup keys the two dominant border colors (checkerboard greys or flat
  white) by flood fill from the edges, then trims anti-aliased fringe. Ask for a **flat
  white background**; it keys cleanest. Never a colored or textured background.
- **Fixed output size (~1774x887).** Irrelevant: the cleanup crops each slot to its content
  and scales to the cell. Only the layout matters: N equal slots, one pose each, common
  baseline, same character height across slots.
- The model changes proportions between prompts. Mitigation: always attach the turnaround
  and repeat the identity block verbatim. If it still drifts, generate whole facings in one
  prompt (all 20 frames of S as 20 slots) and accept fewer retries.
- Off-palette colors are normal and fixed by the quantizer; muddy results mean the source
  had gradients: ask for "flat shading, 3 tones per material".
- A turnaround alone already yields a Unity-usable placeholder sheet (`build` with no strips
  fills every frame from the pose). Animation strips upgrade it later.
- From the fighter run: **hit** poses tend to come back larger (ask for "10 % smaller than
  the idle reference"); **death** strips need "whole silhouette centered in each slot, limbs
  curled inward"; **attack** extensions cross slot cuts unless you ask for "a downward cut
  with a bent elbow, blade inside the slot".
- Stature: `rogue_halfling`, `goblin`, `giant_rat` build with `--stature S`; `giant_spider`
  and `ogre` with `--size L --stature L`; everything else `--stature M`.
