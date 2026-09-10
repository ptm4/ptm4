"""Dungine master palette: the single source of truth for every generated asset.

Run:  python tools/palette.py
Writes assets-src/palettes/master.png (256x1, MagicaVoxel-importable), master.hex (one hex per
line, Aseprite/Lospec style), master.json (named ramps), and swatches.png (human-readable sheet).

Edit colors HERE, re-run, re-quantize. Never hand-edit the PNGs.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets-src" / "palettes"

# Ramps run dark -> light. Names are stable identifiers used by prompt packs and the cleanup
# tool; hex values are what get tuned.
RAMPS: dict[str, list[str]] = {
    # Neutrals: outline ink, stone, bone, white. N0 is THE outline color for everything.
    "neutral": ["#0b0a12", "#1d1a2b", "#33304a", "#57546f", "#86849a", "#b8b6c4", "#e3e0dc", "#f7f4ea"],
    # Night mode base (gothic ref, Cloudpunk shadows)
    "night_purple": ["#120a1f", "#24123d", "#3d1d63", "#5c2f8c", "#8352b8"],
    # Emissives: one hot hue per scene. Magenta = arcane/moon, cyan = ice/ghost/tech, orange = fire/torch.
    "emissive_magenta": ["#8a1a6a", "#d42a9e", "#ff6fd0"],
    "emissive_cyan": ["#146b7a", "#23c4d6", "#a2f6ff"],
    "emissive_orange": ["#7a2a0c", "#d9561b", "#ffa23a", "#ffe08a"],
    # Accent hues reserved for meaning: red = danger/blood/loot-rare, acid = poison/undead/grass-at-night
    "danger_red": ["#6b0f1e", "#c81e35", "#ff5a63"],
    "acid_green": ["#1f5a1a", "#5cb32a", "#c4f24a"],
    # Day mode (Octopath / Sea of Stars)
    "foliage": ["#1c3b25", "#2f6b36", "#5da043", "#a8d95a"],
    "earth_wood": ["#2b1a12", "#4d3021", "#7a4d2e", "#a8723f", "#d9a566"],
    "sand_warmstone": ["#8c7a5c", "#c4ad84", "#eddcb4"],
    "sky": ["#2b4f8c", "#4d8fd6", "#a9d8ff"],
    "water": ["#0f4a6e", "#1e8fb5", "#6fdbe8"],
    "skin": ["#5a3323", "#a06a48", "#d9a37c", "#f2cfa6"],
    "metal": ["#3a3f4d", "#7a8397", "#c9d1de"],
    # Approved leather-armored goblin skin; append to preserve existing voxel indices.
    "goblin_olive": ["#303c28", "#626c43", "#90966b"],
}


def flat() -> list[tuple[str, str]]:
    out = []
    for ramp, colors in RAMPS.items():
        for i, c in enumerate(colors):
            out.append((f"{ramp}_{i}", c.lower()))
    return out


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    colors = flat()
    assert len(colors) <= 255, "MagicaVoxel palettes hold 255 usable colors"

    # 256x1 strip: index 0 is transparent/unused by MagicaVoxel convention -> put ink at 1.
    strip = Image.new("RGBA", (256, 1), (0, 0, 0, 0))
    for i, (_, c) in enumerate(colors, start=1):
        strip.putpixel((i, 0), (*hex_to_rgb(c), 255))
    strip.save(OUT / "master.png")

    (OUT / "master.hex").write_text("\n".join(c.lstrip("#") for _, c in colors) + "\n")
    (OUT / "master.json").write_text(json.dumps(
        {"name": "Dungine-%d" % len(colors), "outline": RAMPS["neutral"][0], "ramps": RAMPS}, indent=2))

    # Swatch sheet for humans and for the style bible.
    cell, pad, label_h = 48, 6, 14
    width = pad + max(len(v) for v in RAMPS.values()) * (cell + pad) + 160
    height = pad + len(RAMPS) * (cell + pad + label_h)
    sheet = Image.new("RGB", (width, height), hex_to_rgb("#1d1a2b"))
    d = ImageDraw.Draw(sheet)
    y = pad
    for ramp, cs in RAMPS.items():
        d.text((pad, y), ramp, fill=(230, 224, 220))
        x = pad + 150
        for c in cs:
            d.rectangle([x, y, x + cell, y + cell], fill=hex_to_rgb(c))
            d.text((x + 2, y + cell + 1), c, fill=(184, 182, 196))
            x += cell + pad
        y += cell + pad + label_h
    sheet.save(OUT / "swatches.png")
    print(f"wrote {len(colors)} colors -> {OUT}")


if __name__ == "__main__":
    main()
