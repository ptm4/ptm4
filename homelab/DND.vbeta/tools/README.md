# tools/

Scripts (Python 3.12, needs `pillow` + `numpy`; run from `homelab/DND.vbeta/`).

| Script | Plan | What it does |
|---|---|---|
| `palette.py` | 04 | Source of truth for the Dungine-54 palette. Writes `assets-src/palettes/{master.png,master.hex,master.json,swatches.png}`. Edit the ramps here, never the PNGs. |
| `make_sprite_template.py` | 04 | Writes `assets-src/sprites/TEMPLATE_{M,L}{,_guide}.png` (sheet geometry, body box, ground line). |
| `slice_strips.py <id>` | 05 | Cuts generated `strip_<FACING>_<anim>.png` images into single frames in the inbox. |
| `vox_check.py kit` | 06 | Validates every `.vox` in `assets-src/voxels/kit.json` against the kit contract (size, master palette indices, grounding, emissive ramps, schema). Codex must pass it. |
| `sprite_clean.py build <id>` | 05 | Inbox frames → template-exact, palette-exact `out/<id>.png` + portrait + `manifest.json`. `check <sheet>` validates; `build-all` batches. |

Codex-written (Plan 06): `vox_write.py`, `vox_to_obj.py`. Planned: `ingest_srd.py` (03a), `campaign_validate.py` (07), `build.ps1` (14).
