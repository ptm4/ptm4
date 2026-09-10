# Dungine style bible (v0.1, 2026-09-09)

The one document every generated asset obeys. Produced by Plan 04. References live in
`Plans/Digital-Influences/`; the analysis of each is in `Plans/04-art-style-bible.md`.
Numbers here are the source of truth for `tools/palette.py`, `tools/make_sprite_template.py`,
`PixelSpriteImportPostprocessor.PixelsPerUnit`, and `HD2DSetup`. Change here first.

## 1. Pillars

1. **HD-2D.** Pixel-art creatures standing in a real 3D-lit voxel world. Sprites are never
   lit by vertex color tricks; the world's lights, fog and post do the mood (Octopath).
2. **One light, one accent.** Every scene has one dominant emissive hue and one reserved
   accent hue for what the players should notice (gothic reference, Rain World).
3. **Readable first.** A creature is identifiable by silhouette and two outfit colors at
   gameplay zoom; the HUD stays legible over the brightest day tile (Sea of Stars, Octopath
   castle party).
4. **Grit over gloss.** Film grain, wet stone, worn wood, drifting fog. Nothing is clean
   (Cloudpunk, Rain World).

## 2. Master palette: `Dungine-57`

Source: `tools/palette.py`. Outputs in `assets-src/palettes/`: `master.png` (256x1 strip,
import into MagicaVoxel), `master.hex` (Aseprite/Lospec), `master.json` (named ramps),
`swatches.png` (look at this one).

| Ramp | Use | Colors (dark → light) |
|---|---|---|
| neutral (8) | **Outline ink = neutral_0 `#0b0a12` for everything.** Stone, bone, white. | `0b0a12 1d1a2b 33304a 57546f 86849a b8b6c4 e3e0dc f7f4ea` |
| night_purple (5) | Night-mode base: shadows, sky, distant silhouettes | `120a1f 24123d 3d1d63 5c2f8c 8352b8` |
| emissive_magenta (3) | Arcane, moon, portals | `8a1a6a d42a9e ff6fd0` |
| emissive_cyan (3) | Ice, ghosts, crystals, "tech" | `146b7a 23c4d6 a2f6ff` |
| emissive_orange (4) | Fire, torches, lava, windows | `7a2a0c d9561b ffa23a ffe08a` |
| danger_red (3) | Blood, traps, rare loot, hostile UI | `6b0f1e c81e35 ff5a63` |
| acid_green (3) | Poison, undead glow, grass at night | `1f5a1a 5cb32a c4f24a` |
| foliage (4) | Day plants | `1c3b25 2f6b36 5da043 a8d95a` |
| earth_wood (5) | Dirt, bark, planks, leather | `2b1a12 4d3021 7a4d2e a8723f d9a566` |
| sand_warmstone (3) | Paths, sandstone, parchment UI | `8c7a5c c4ad84 eddcb4` |
| sky (3) | Day sky, water highlights | `2b4f8c 4d8fd6 a9d8ff` |
| water (3) | Rivers, sea | `0f4a6e 1e8fb5 6fdbe8` |
| skin (4) | Humanoid skin tones (use ramps offset for species) | `5a3323 a06a48 d9a37c f2cfa6` |
| metal (3) | Armor, weapons, chains | `3a3f4d 7a8397 c9d1de` |
| goblin_olive (3) | Approved muted olive goblin skin; leather-armored design | `303c28 626c43 90966b` |

The approved goblin uses `goblin_olive` skin and `earth_wood` leather armor, with a scimitar
and small wooden shield. This replaces its earlier acid-green, bare-torso design. The three
new colors are appended so existing palette indices remain stable. Older Dungine-54 references
describe the original subset; cleanup now uses all 57 colors from the generated master palette.

Rules:
- Sprites use **only** these colors after cleanup (`tools/sprite_clean.py` quantizes to
  `master.hex`). Voxels import `master.png` as their MagicaVoxel palette.
- **Palette modes** are lighting, not different palettes: *Day* scenes light with warm white
  and let foliage/earth/sky ramps dominate; *Night/Dungeon* scenes sit on night_purple with
  one emissive ramp active. The same sprite must read on both (test on a `foliage_2` tile and
  a `night_purple_1` tile before approving any creature).
- Emissive ramps are for things that glow. A magenta cloak is wrong; a magenta rune is right.
- danger_red and acid_green are semantic. Do not use them for decoration.

## 3. Sprites

Source: `tools/make_sprite_template.py`. Templates in `assets-src/sprites/`:
`TEMPLATE_M.png` (exact delivery size), `TEMPLATE_M_guide.png` (labelled, attach to prompts),
and `TEMPLATE_L*.png` for Large creatures.

| Property | Value |
|---|---|
| Pixels per unit | **64**. One Unity unit = one 5-ft tile = 64 px of sprite. |
| Medium/Small cell | **64 x 96** px. Body box 40 x 72 centered; Medium ~64-72 px tall, Small ~44-52, Tiny ~28-36. |
| Large cell | 128 x 128 px, body box 96 x 104 (2x2 tiles). Huge+ deferred (multi-sprite later). |
| Pivot | Bottom-center. Feet on the ground line **4 px above the cell bottom** (engine draws the shadow blob). |
| Facings | **3 generated: S (faces camera), N (back), E (side). W = E mirrored at runtime.** Asymmetric gear (a shield, a one-sided pauldron) is accepted as swapping sides; do not generate W. |
| Animations (frames) | idle 4, walk 6, attack 4, hit 2, death 4 = **20 per facing, 60 per creature.** |
| Sheet | 3 rows (S, N, E) x 20 columns; Medium sheet is exactly **1280 x 288**. Column groups in template order. |
| Frame timing | idle 8 fps, walk 10 fps, attack 12 fps (hit frame = frame 3), hit 12 fps, death 8 fps then hold last frame. |
| Outline | 1 px, `neutral_0`, full outline. No outline breaks for "light against dark". |
| Shading | 3 steps per material (base, shadow, highlight) from one ramp; optional 1-px rim in the scene's emissive hue only for glowing creatures. Light from upper-left-front. |
| Anti-aliasing | None. No sub-pixel blending, no gradients, no dithering except 50 % checker on large flat areas (capes, water). |
| Portrait | 128 x 128, same palette and outline rule, bust framing, transparent background. |
| Paper-doll | Layers, bottom to top: body, legwear, footwear, torso armor, cloak-back (drawn behind body in S, in front in N), hands/weapon, headgear, cloak-front. Each layer is a full sheet with the same 60 frames, transparent elsewhere. Body is the only layer with skin. |

Generation workflow (Plan 05 packs this into prompts): generate at **4x** (256 x 384 per
frame) in the reference style, then `sprite_clean.py` keys any painted background,
downsamples nearest-neighbour by **one scale factor per creature** (derived from the S idle
pose, so poses keep their relative size), maps every pixel to the nearest master-palette
color, drops pixels with alpha < 50 %, re-outlines with `neutral_0`, anchors feet on the
ground line and the slot center on the cell center, and slices into the sheet. Anything the
cleanup cannot make template-exact is regenerated, never hand-fixed in bulk.

## 4. Voxel world

| Property | Value |
|---|---|
| Scale | **16 voxels per 5-ft tile** (1 unit). Voxel = 1/16 unit. |
| Wall height | 32 voxels (10 ft) standard; 48 for halls. Floors are 2 voxels thick with a 1-voxel top layer for wear/detail. |
| Character height check | A Medium sprite (~1.05-1.15 units) stands just over half a standard wall. |
| Palette | `master.png` loaded in MagicaVoxel. Emissive materials only on emissive ramps. |
| Kit unit | Every tile prefab snaps to 1 unit; props snap to 1/4 unit. Pivot at floor center. |
| Metadata per prefab | blocksMove, blocksSight, coverValue (0 / half / three-quarters / full), elevation, difficultTerrain, biome, mode (day / night / both). |
| Surfaces | Wet stone (smoothness 0.6-0.8) on dungeon floors; wood rough; metal 0.7. Grain and fog do the rest. |
| Grit pass | Every tile ships with a "worn" variant (chips, moss, cracks) at ≥ 1 in 4 placements in the DM kit. |

## 5. Camera and post-processing

| Property | Value |
|---|---|
| Camera | Perspective, **FOV 28°**, pitch **50°** down (POC: 38° hid the party behind 10-ft walls; D28), distance ~11 u to the subject, yaw 0. Walls between camera and party are cut away or dithered. Orthographic is not used; the DoF band needs depth. |
| Sprites | Billboard on Y only, tilted back 12° toward the camera so they sit on the ground instead of floating. Sorting by depth; never Z-fight with walls (offset 0.02 u). |
| Base profile | `Assets/Dungine/Rendering/HD2D_Base.asset`: Bloom 0.9 (threshold 1.1, scatter 0.65), Gaussian DoF 12→40 u (max radius 1.2), ACES, contrast +12, saturation +6, exposure +0.1, Vignette 0.28, FilmGrain Thin1 0.25. |
| Day profile (Plan 02 makes it) | Directional light 4500 K, intensity 1.6, angle 50° elevation, 30° azimuth; shadows soft; fog linear 30→90 u tinted `sky_2`; bloom threshold 1.3. |
| Night profile | Directional moon 9000 K intensity 0.25 tinted `night_purple_3`; ambient `night_purple_1`; fog 12→45 u tinted `night_purple_0`; bloom threshold 0.9 so emissives bloom; point lights per torch: `emissive_orange_2`, range 6 u, intensity 12, flicker ±10 %. |
| Weather | Rain: 2 layers of streak particles (near 1.5 u/s, far 0.7 u/s) + surface ripple decals; puddle smoothness 0.95. Fog motes: slow 0.1 u/s drift, 20 % opacity. Embers for fire scenes. |
| Light shafts | URP has no built-in volumetrics: use 3-4 additive quads per window/door with `emissive_orange_3` at 8-15 % alpha, animated 2 % sway. |
| Pixel discipline | Sprites are never filtered (Point) and never scaled non-integer in world space. The camera may be any height; the world is 3D so screen pixels do not need to align. |

## 6. UI

| Property | Value |
|---|---|
| Panels | `neutral_1` at 88 % alpha, 1-px border `neutral_5`, 2-px inner shadow `neutral_0`. Corners square. |
| Accent | Day: `emissive_orange_2`. Night: the scene's active emissive ramp, index 1. Hostile: `danger_red_1`. |
| Text | Primary `neutral_7`, secondary `neutral_5`, disabled `neutral_3`. |
| Fonts | Pixel font for the world layer and HUD numbers; a clean sans for dialogue and sheets (readability beats theme). Candidates (licenses to confirm in SOURCES.md): m6x11 / m5x7 (Daniel Linssen, free), Pixel Operator (SIL OFL). |
| Icons | 32 x 32, `neutral_7` glyph on transparent, 1-px `neutral_0` outline; one accent color max. Generated through the Plan 05 pipeline. |
| Rolls | Every roll shows `d20 + mods = total vs DC` inline; rejected intents show the rule name that refused them. |

## 7. Do / don't

- **Do** put the hot emissive on the thing that tells the story of the scene (the moon, the
  altar, the forge). **Don't** scatter glowing props everywhere; one per screen carries.
- **Do** design creatures as silhouettes first (shape, then two colors, then detail).
  **Don't** rely on face detail; at 64 px a face is six pixels.
- **Do** use `neutral_0` outlines on everything, including props drawn as sprites.
  **Don't** outline voxels.
- **Do** keep the ground darker than the creature's mid-tone so feet read. **Don't** put a
  Medium creature on a `neutral_7` tile.
- **Do** let post-processing do the mood. **Don't** paint bloom, fog or light shafts into
  sprites or voxel textures.
- **Do** regenerate an asset that fails the palette/template check. **Don't** hand-fix in
  bulk; fixes do not scale to 300 monsters.

## 8. Acceptance checks (per creature)

1. Sheet is exactly template size; every frame's feet touch the ground line; nothing
   crosses a cell border.
2. `sprite_clean.py --check` reports 0 off-palette pixels and 0 semi-transparent pixels.
3. Reads on `foliage_2` and `night_purple_1` tiles at 100 % and at 50 % zoom.
4. Silhouette test: filled `neutral_0` version is still identifiable among the party.
5. E facing mirrored to W does not break weapon-hand logic the engine cares about.

## 9. Open for Peter's review

- Palette hues (especially skin ramp offsets per species and the two greens).
- FOV/pitch: 28°/38° is a starting point; the POC (Plan 02) tunes it by eye.
- Whether Huge/Gargantuan get multi-sprite treatment or a single 192 px cell.
