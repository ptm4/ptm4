"""Validate MagicaVoxel .vox tiles against the Dungine kit contract (Plan 06, style bible §4).

Usage
  python tools/vox_check.py kit                       # validate every tile listed in assets-src/voxels/kit.json
  python tools/vox_check.py file <tile.vox> [--footprint W D] [--height H]

Checks per tile:
  - parses as VOX 150 with SIZE/XYZI (first model only; multi-model files are rejected)
  - model dimensions == footprint * 16 wide/deep and <= height * 16 tall (16 voxels per tile)
  - every used palette index maps to a master-palette color (the file's RGBA chunk must equal
    assets-src/palettes/master.png order: index 1 = first master color)
  - floors/walls/pillars: >= 60 % of the bottom layer is filled (sits on the ground)
  - emissive indices (kit.json "emissive") are only from the emissive ramps
  - kit.json entry has every required field
Exit 0 = all PASS.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
VOXELS = ROOT / "assets-src" / "voxels"
KIT = VOXELS / "kit.json"
MASTER_PNG = ROOT / "assets-src" / "palettes" / "master.png"
MASTER_JSON = ROOT / "assets-src" / "palettes" / "master.json"
VPT = 16  # voxels per 5-ft tile
REQUIRED = ["file", "category", "footprint", "height_tiles", "blocks_move", "blocks_sight", "cover", "elevation_half", "difficult", "emissive", "biome", "mode"]
GROUNDED = {"floor", "wall", "pillar", "door", "stairs", "platform"}


def read_vox(path: Path):
    data = path.read_bytes()
    if data[:4] != b"VOX ":
        raise ValueError("not a VOX file")
    version = struct.unpack("<i", data[4:8])[0]
    pos = 8
    size = None; voxels = None; palette = None; models = 0
    while pos + 12 <= len(data):
        cid = data[pos:pos + 4]; n, m = struct.unpack("<ii", data[pos + 4:pos + 12]); pos += 12
        body = data[pos:pos + n]
        if cid == b"SIZE":
            models += 1
            if size is None:
                size = struct.unpack("<iii", body[:12])
        elif cid == b"XYZI" and voxels is None:
            cnt = struct.unpack("<i", body[:4])[0]
            voxels = np.frombuffer(body[4:4 + cnt * 4], dtype=np.uint8).reshape(-1, 4)
        elif cid == b"RGBA":
            palette = np.frombuffer(body[:1024], dtype=np.uint8).reshape(256, 4)
        pos += n if cid != b"MAIN" else 0
    if size is None or voxels is None:
        raise ValueError("missing SIZE/XYZI")
    return version, size, voxels, palette, models


def master_palette() -> np.ndarray:
    strip = np.array(Image.open(MASTER_PNG).convert("RGBA"))[0]  # 256 x RGBA, index 0 unused
    return strip


def check_tile(path: Path, footprint, height_tiles, category: str, emissive: list[int]) -> list[str]:
    errs: list[str] = []
    try:
        version, (sx, sy, sz), vox, pal, models = read_vox(path)
    except Exception as e:  # noqa: BLE001
        return [f"unreadable: {e}"]
    if models != 1:
        errs.append(f"{models} models in file; one model per tile")
    fw, fd = footprint
    if (sx, sy) != (fw * VPT, fd * VPT):
        errs.append(f"SIZE {sx}x{sy} (x,y) != footprint {fw * VPT}x{fd * VPT}")
    if sz > height_tiles * VPT:
        errs.append(f"height {sz} > {height_tiles * VPT}")
    if len(vox) == 0:
        errs.append("empty model")
        return errs
    # Palette: file RGBA must match master order for the indices in use (MagicaVoxel stores index i at row i-1).
    master = master_palette()
    used = np.unique(vox[:, 3])
    master_count = int((master[1:, 3] > 0).sum())
    if pal is None:
        errs.append("no RGBA chunk (save with the master palette loaded)")
    else:
        for i in used:
            if i == 0 or i > master_count:
                errs.append(f"palette index {i} outside master ({master_count} colors)")
                continue
            if not np.array_equal(pal[i - 1, :3], master[i, :3]):
                errs.append(f"palette index {i} is {tuple(pal[i - 1, :3])}, master has {tuple(master[i, :3])}")
    # Grounding.
    if category in GROUNDED:
        bottom = (vox[:, 2] == 0).sum()
        if bottom < 0.6 * sx * sy:
            errs.append(f"bottom layer {bottom}/{sx * sy} filled (< 60 %); tile would float")
    # Emissive indices must be from emissive ramps.
    ramps = json.loads(MASTER_JSON.read_text())["ramps"]
    order = [c for r, cs in ramps.items() for c in cs]
    names = [r for r, cs in ramps.items() for _ in cs]
    for i in emissive:
        if i < 1 or i > len(order) or not names[i - 1].startswith("emissive_"):
            errs.append(f"emissive index {i} is not in an emissive ramp ({names[i - 1] if 0 < i <= len(order) else 'n/a'})")
    return errs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("kit")
    f = sub.add_parser("file"); f.add_argument("path"); f.add_argument("--footprint", nargs=2, type=int, default=[1, 1]); f.add_argument("--height", type=int, default=2)
    a = ap.parse_args()
    failed = 0
    if a.cmd == "file":
        errs = check_tile(Path(a.path), a.footprint, a.height, "prop", [])
        print(f"{a.path}: {'PASS' if not errs else 'FAIL'}"); [print("   !", e) for e in errs]
        sys.exit(1 if errs else 0)
    kit = json.loads(KIT.read_text())
    for tid, t in sorted(kit["tiles"].items()):
        missing = [k for k in REQUIRED if k not in t]
        errs = [f"kit.json missing {m}" for m in missing]
        if not missing:
            p = VOXELS / t["file"]
            errs += check_tile(p, t["footprint"], t["height_tiles"], t["category"], t["emissive"]) if p.exists() else [f"file not found: {t['file']}"]
        print(f"{tid:28s} {'PASS' if not errs else 'FAIL'}"); [print("   !", e) for e in errs]
        failed += bool(errs)
    print(f"{len(kit['tiles']) - failed}/{len(kit['tiles'])} tiles pass")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
