# Paste this into Codex verbatim. Plan 06 voxel kit, dungeon biome.

```
Project: E:\REPO\ptm4\homelab\DND.vbeta. Read Plans/06-voxel-world-kit.md fully, then
docs/style-bible.md §2 and §4, then tools/vox_check.py (the validator you must pass; do not
edit it). No image generation in this job: you WRITE voxel files with code.

DELIVERABLES (all under the repo; commit nothing):
1. tools/vox_write.py — a small library: build a numpy uint8 array (x, y, z) of master
   palette indices (0 = empty) and save it as a MagicaVoxel .vox (VOX version 150, chunks
   MAIN > SIZE + XYZI + RGBA). The RGBA chunk must be the master palette in order:
   load assets-src/palettes/master.png (256x1; pixel i = palette index i; index 0 unused)
   and write it so that MagicaVoxel index i == master index i. Include helpers: box(),
   fill_layer(), noise_patch(seed) for grit, mortar_lines(), and a deterministic RNG
   (seed per tile id) so re-running produces identical files.
2. assets-src/voxels/dungeon/<tile>.vox for EVERY tile id in the plan's "Dungeon tile list
   v1" table, at 16 voxels per tile, MagicaVoxel Z-up (x = east, y = north, z = up), the
   model origin at the tile's floor corner, floors 3 voxels thick (2 base + 1 detail).
3. assets-src/voxels/kit.json following the plan's schema exactly, one entry per tile,
   with honest metadata (a closed door blocks sight; a barrel does not; the sconce lists
   its emissive_orange indices).
4. tools/vox_to_obj.py — convert every .vox to assets-src/voxels/obj/<tile>.obj + .mtl:
   one quad per exposed voxel face (greedy meshing optional), 1 voxel = 1/16 unit, convert
   to Y-up (Unity), origin at the tile's floor CENTER (so a 1x1 tile spans -0.5..0.5 in x/z).
   Colors via UVs into assets-src/voxels/obj/palette_atlas.png, a 16x16-cell atlas where
   cell i (row-major) is master color i; UVs point at the cell center. Faces whose voxel
   index is in the tile's kit.json "emissive" list go to a second OBJ group/material named
   "emissive". Write a generate-all entry point: python tools/vox_to_obj.py --all.
5. Run python tools/vox_check.py kit until every tile PASSES. Then run vox_to_obj --all.

STYLE RULES (style bible §4, enforced by eye later; the checker only enforces the contract):
- Only master palette indices. Stone = neutral_2/3 with night_purple_1/2 shadow voxels;
  wood = earth_wood ramp; metal = metal ramp; glow only from emissive ramps.
- 3 tones per material, no gradients. Every tile gets one grit detail. Walls get 1-voxel
  mortar relief every 4 voxels so flat faces catch light. Worn variants differ visibly
  (chips, moss, cracks), not just by noise.
- Nothing hangs outside the footprint. Props sit on the floor plane (z = 0 is the floor
  top for props; floors themselves start at z = 0).

REPORT: the vox_check output, the list of .vox and .obj files, tile count, and anything in
the plan that was ambiguous. Log per-tile notes in assets-src/voxels/inbox/STATUS.md. If
vox_check.py itself seems wrong, write the evidence in E:\REPO\ptm4\AgentComms.md and stop.
```
