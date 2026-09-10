"""Generate the sprite-sheet templates every generated creature must match (style bible §3).

Run:  python tools/make_sprite_template.py
Writes assets-src/sprites/TEMPLATE_M.png (bare, exact delivery size) and TEMPLATE_M_guide.png
(labelled, for humans and for attaching to image-gen prompts). Also the Large variant.

Sheet layout (Medium/Small): 3 facing rows x 20 animation columns, 64x96 px cells:
  row 0 = S (facing camera), row 1 = N (back), row 2 = E (side; W is mirrored at runtime)
  cols  = idle x4 | walk x6 | attack x4 | hit x2 | death x4
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets-src" / "sprites"

ANIMS = [("idle", 4), ("walk", 6), ("attack", 4), ("hit", 2), ("death", 4)]
FACINGS = ["S", "N", "E"]
SIZES = {  # name: (cell_w, cell_h, body_w, body_h)  body box = where the creature's mass should sit
    "M": (64, 96, 40, 72),   # Medium and Small creatures (Small ~48 px tall inside the same cell)
    "L": (128, 128, 96, 104),  # Large creatures, 2x2 tiles
}
GROUND_INSET = 4  # px above the cell bottom where the feet sit (engine draws the shadow blob)

GRID = (87, 84, 111, 255)
GRID_STRONG = (184, 182, 196, 255)
BODY = (212, 42, 158, 120)
GROUND = (255, 162, 58, 255)
TEXT = (247, 244, 234, 255)


def build(size_key: str) -> None:
    cw, ch, bw, bh = SIZES[size_key]
    cols = sum(n for _, n in ANIMS)
    rows = len(FACINGS)
    w, h = cw * cols, ch * rows

    bare = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(bare)
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * cw, r * ch
            d.rectangle([x0, y0, x0 + cw - 1, y0 + ch - 1], outline=GRID)
            gy = y0 + ch - 1 - GROUND_INSET
            d.line([x0, gy, x0 + cw - 1, gy], fill=GROUND)
            bx0 = x0 + (cw - bw) // 2
            by0 = gy - bh
            d.rectangle([bx0, by0, bx0 + bw - 1, gy], outline=BODY)
    # Strong lines between animation groups
    x = 0
    for _, n in ANIMS:
        x += n * cw
        if x < w:
            d.line([x, 0, x, h - 1], fill=GRID_STRONG)
    bare.save(OUT / f"TEMPLATE_{size_key}.png")

    gutter_l, header = 28, 18
    guide = Image.new("RGBA", (w + gutter_l, h + header), (29, 26, 43, 255))
    guide.paste(bare, (gutter_l, header), bare)
    g = ImageDraw.Draw(guide)
    x = gutter_l
    for name, n in ANIMS:
        g.text((x + 3, 3), f"{name} x{n}", fill=TEXT)
        x += n * cw
    for r, f in enumerate(FACINGS):
        g.text((6, header + r * ch + ch // 2 - 5), f, fill=TEXT)
    guide.save(OUT / f"TEMPLATE_{size_key}_guide.png")
    print(f"{size_key}: sheet {w}x{h}, cell {cw}x{ch}, body box {bw}x{bh}, ground inset {GROUND_INSET}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for k in SIZES:
        build(k)


if __name__ == "__main__":
    main()
