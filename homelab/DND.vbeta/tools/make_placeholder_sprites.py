"""Placeholder sprite sheets for the POC (Plan 02) until real generations land.

Simple palette-colored silhouettes per creature, template-exact, so the whole import and
billboard path is exercised before any art exists. Output goes through sprite_clean's
quantize/outline so it passes `sprite_clean.py check`.

Run: python tools/make_placeholder_sprites.py [--copy-to <Unity Sprites folder>]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import sprite_clean as sc

OUT = sc.SPRITES / "placeholder"

# id: (body ramp color, head/accent color, height px, width px, shape)
CREATURES = {
    "fighter_human": ("#7a8397", "#d9a37c", 70, 34, "block"),
    "wizard_elf": ("#3d1d63", "#f2cfa6", 72, 22, "tri"),
    "rogue_halfling": ("#4d3021", "#d9a37c", 50, 26, "block"),
    "cleric_dwarf": ("#c9d1de", "#a06a48", 56, 36, "block"),
    "goblin": ("#5cb32a", "#c4f24a", 48, 26, "hunch"),
}


def frame(color: str, accent: str, h: int, w: int, shape: str, phase: float) -> Image.Image:
    cw, ch = sc.SIZES["M"]
    im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # Shapes end one pixel above the ground line so the 1-px outline lands exactly on it.
    gy = ch - 2 - sc.GROUND_INSET
    bob = int(round(2 * np.sin(phase)))  # tiny idle bob so frames differ
    x0 = (cw - w) // 2
    top = gy - h + bob
    rgb = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    acc = tuple(int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    if shape == "tri":
        d.polygon([(cw // 2, top), (x0, gy), (x0 + w, gy)], fill=rgb + (255,))
        d.ellipse([cw // 2 - 7, top + 6, cw // 2 + 7, top + 20], fill=acc + (255,))
    elif shape == "hunch":
        d.rounded_rectangle([x0, top + 10, x0 + w, gy], radius=8, fill=rgb + (255,))
        d.ellipse([x0 + 2, top, x0 + w - 2, top + 22], fill=acc + (255,))
    else:
        d.rounded_rectangle([x0, top + 14, x0 + w, gy], radius=5, fill=rgb + (255,))
        d.ellipse([cw // 2 - 8, top, cw // 2 + 8, top + 16], fill=acc + (255,))
    return im


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-to", type=Path)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    pal, ink = sc.load_palette()
    cw, ch = sc.SIZES["M"]
    cols = sum(n for _, n in sc.ANIMS)
    for cid, (color, accent, h, w, shape) in CREATURES.items():
        sheet = np.zeros((ch * 3, cw * cols, 4), np.uint8)
        for r in range(3):
            c = 0
            for _, n in sc.ANIMS:
                for i in range(n):
                    f = frame(color, accent, h, w, shape, i / max(1, n - 1) * np.pi)
                    arr = sc.outline(sc.quantize(np.array(f), pal), ink)
                    sheet[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = arr
                    c += 1
        p = OUT / f"{cid}.png"
        Image.fromarray(sheet, "RGBA").save(p)
        ok = sc.check(p, "M", quiet=True)
        print(f"{cid}: {'PASS' if ok else 'FAIL'} {p.relative_to(sc.ROOT)}")
        if a.copy_to:
            a.copy_to.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, a.copy_to / p.name)
    if a.copy_to:
        print(f"copied to {a.copy_to}")


if __name__ == "__main__":
    main()
