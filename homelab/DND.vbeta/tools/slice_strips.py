"""Slice generated animation strips into the single frames sprite_clean.py expects.

Usage:  python tools/slice_strips.py <creature>

Reads  assets-src/sprites/inbox/<creature>/strip_<FACING>_<anim>.png  (N slots side by side, any size)
Writes assets-src/sprites/inbox/<creature>/<FACING>_<anim>_<i>.png

Slots are assumed equal width (width / N). Exact pixel sizes do not matter: sprite_clean
crops each slot to its content and scales it to the cell. Backgrounds may be real alpha or a
painted checkerboard/white (keyed later).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "assets-src" / "sprites" / "inbox"
ANIMS = [("idle", 4), ("walk", 6), ("attack", 4), ("hit", 2), ("death", 4)]
FACINGS = ["S", "N", "E"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("creature")
    a = ap.parse_args()
    src = INBOX / a.creature
    done = missing = 0
    for f in FACINGS:
        for anim, n in ANIMS:
            p = src / f"strip_{f}_{anim}.png"
            if not p.exists():
                missing += 1
                continue
            img = Image.open(p).convert("RGBA")
            slot = img.width / n
            for i in range(n):
                img.crop((int(i * slot), 0, int((i + 1) * slot), img.height)).save(src / f"{f}_{anim}_{i}.png")
                done += 1
    print(f"{a.creature}: {done} frames written from strips, {missing} strips missing")


if __name__ == "__main__":
    main()
