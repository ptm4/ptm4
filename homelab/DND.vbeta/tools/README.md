# tools/

Scripts (Python 3.12, needs `pillow` + `numpy`; run from `homelab/DND.vbeta/`).

| Script | Plan | What it does |
|---|---|---|
| `palette.py` | 04 | Source of truth for the Dungine-54 palette. Writes `assets-src/palettes/{master.png,master.hex,master.json,swatches.png}`. Edit the ramps here, never the PNGs. |
| `make_sprite_template.py` | 04 | Writes `assets-src/sprites/TEMPLATE_{M,L}{,_guide}.png` (sheet geometry, body box, ground line). |
| `slice_strips.py <id>` | 05 | Cuts generated `strip_<FACING>_<anim>.png` images into single frames in the inbox. |
| `sprite_clean.py build <id>` | 05 | Inbox frames → template-exact, palette-exact `out/<id>.png` + portrait + `manifest.json`. `check <sheet>` validates; `build-all` batches. |

Planned: `ingest_srd.py` (03a), `vox_export.ps1` (06), `campaign_validate.py` (07), `build.ps1` (14).
