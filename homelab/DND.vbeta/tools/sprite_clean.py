"""Sprite pipeline: raw generations -> template-exact, palette-exact sheets (style bible §3).

Usage
  python tools/sprite_clean.py build  <creature> [--size M|L] [--stature T|S|M|L] [--no-outline] [--from-turnaround]
  python tools/sprite_clean.py check  <sheet.png> [--size M|L]
  python tools/sprite_clean.py build-all [--size M|L]

Inbox layout (what the image agent produces), per creature, any of:
  assets-src/sprites/inbox/<creature>/S_idle_0.png ... E_death_3.png   single frames, any scale
  assets-src/sprites/inbox/<creature>/sheet.png                        whole sheet, integer scale
  assets-src/sprites/inbox/<creature>/turnaround.png                   3 equal slots S | N | E
  optional: portrait.png (any square size)

Backgrounds: real alpha is best, but images with a PAINTED checkerboard or a flat white/grey
background (GPT image tools often cannot emit alpha) are keyed automatically: the two most
common border colors are treated as background and flood-filled from the edges.

Output:
  assets-src/sprites/out/<creature>.png          (Medium: 1280x288)
  assets-src/sprites/out/<creature>_portrait.png (128x128)
  assets-src/sprites/manifest.json               (sha256, source files, date, tool version)

Steps per frame: key background -> alpha threshold -> nearest-neighbour scale to the cell ->
map every pixel to the nearest Dungine-54 color -> re-outline with neutral_0 -> place on the
ground line. Anything that cannot be made exact is reported; regenerate rather than hand-fix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, deque
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

TOOL_VERSION = "0.4.0"
ROOT = Path(__file__).resolve().parents[1]
SPRITES = ROOT / "assets-src" / "sprites"
INBOX, OUT = SPRITES / "inbox", SPRITES / "out"
PALETTE_HEX = ROOT / "assets-src" / "palettes" / "master.hex"
PALETTE_JSON = ROOT / "assets-src" / "palettes" / "master.json"

ANIMS = [("idle", 4), ("walk", 6), ("attack", 4), ("hit", 2), ("death", 4)]
FACINGS = ["S", "N", "E"]
SIZES = {"M": (64, 96), "L": (128, 128)}
STATURE_HEIGHT = {"T": 36, "S": 52, "M": 72, "L": 104}  # target sprite height in px (bible §3)
GROUND_INSET = 4
ALPHA_CUTOFF = 128   # < 50 % alpha becomes transparent (bible: no semi-transparent pixels)
BG_TOLERANCE = 28    # per-channel distance to count as a background color when keying
EDGE_TOLERANCE = 90  # looser distance for anti-aliased fringe pixels next to keyed background
DRIFT_TOLERANCE = 0.12  # an animation whose mean height differs from idle by more than this fails


def load_palette() -> tuple[np.ndarray, tuple[int, int, int]]:
    hexes = [h.strip() for h in PALETTE_HEX.read_text().splitlines() if h.strip()]
    pal = np.array([[int(h[i:i + 2], 16) for i in (0, 2, 4)] for h in hexes], dtype=np.int32)
    outline_hex = json.loads(PALETTE_JSON.read_text())["outline"].lstrip("#")
    return pal, tuple(int(outline_hex[i:i + 2], 16) for i in (0, 2, 4))


def frame_names() -> list[tuple[str, str, int]]:
    return [(f, a, i) for f in FACINGS for a, n in ANIMS for i in range(n)]


def col_index(anim: str, i: int) -> int:
    names = [a for a, _ in ANIMS]
    return sum(n for _, n in ANIMS[:names.index(anim)]) + i


# ---- background keying -------------------------------------------------------------------

def key_background(rgba: np.ndarray) -> tuple[np.ndarray, str | None]:
    """If the image has no useful alpha, detect painted checkerboard / flat background from the
    border and flood-fill it transparent. Returns (image, note)."""
    a = rgba[..., 3]
    if a.min() < ALPHA_CUTOFF:
        return rgba, None  # real alpha present; trust it
    h, w = a.shape
    rgb = rgba[..., :3].astype(np.int32)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    # Quantize border colors coarsely to find the (up to) two dominant background colors.
    keys = Counter(map(tuple, (border // 16 * 16).tolist()))
    bg = [np.array(k) + 8 for k, _ in keys.most_common(2)]
    near = np.zeros((h, w), bool)
    for c in bg:
        near |= (np.abs(rgb - c) <= BG_TOLERANCE).all(axis=2)
    # Flood fill from the border through "near background" pixels.
    seen = np.zeros((h, w), bool)
    q: deque[tuple[int, int]] = deque()
    for y in range(h):
        for x in (0, w - 1):
            if near[y, x] and not seen[y, x]:
                seen[y, x] = True; q.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if near[y, x] and not seen[y, x]:
                seen[y, x] = True; q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < h and 0 <= nx < w and near[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True; q.append((ny, nx))
    out = rgba.copy()
    out[seen, 3] = 0
    # Fringe pass: opaque pixels touching the keyed region that are still close to a bg color.
    fringe_loose = np.zeros((h, w), bool)
    for c in bg:
        fringe_loose |= (np.abs(rgb - c) <= EDGE_TOLERANCE).all(axis=2)
    for _ in range(2):
        t = out[..., 3] == 0
        adj = np.zeros((h, w), bool)
        adj[1:] |= t[:-1]; adj[:-1] |= t[1:]; adj[:, 1:] |= t[:, :-1]; adj[:, :-1] |= t[:, 1:]
        kill = adj & ~t & fringe_loose
        out[kill, 3] = 0
    keyed = int(seen.sum())
    return out, f"keyed painted background ({keyed} px, colors {[tuple(int(v) for v in c) for c in bg]})"


# ---- per-frame processing ----------------------------------------------------------------

def quantize(rgba: np.ndarray, pal: np.ndarray) -> np.ndarray:
    """Map opaque pixels to the nearest palette color (weighted RGB distance)."""
    out = rgba.copy()
    mask = out[..., 3] >= ALPHA_CUTOFF
    out[~mask] = 0
    out[mask, 3] = 255
    px = out[mask][:, :3].astype(np.int32)
    if len(px):
        w = np.array([0.30, 0.59, 0.11]) * 3
        d = (((px[:, None, :] - pal[None, :, :]) ** 2) * w).sum(axis=2)
        out[mask, :3] = pal[d.argmin(axis=1)]
    return out


def outline(rgba: np.ndarray, ink: tuple[int, int, int]) -> np.ndarray:
    """Add a 1-px ink outline around every opaque region (4-connected)."""
    a = rgba[..., 3] > 0
    grown = a.copy()
    grown[1:, :] |= a[:-1, :]; grown[:-1, :] |= a[1:, :]; grown[:, 1:] |= a[:, :-1]; grown[:, :-1] |= a[:, 1:]
    ring = grown & ~a
    out = rgba.copy()
    out[ring] = (*ink, 255)
    return out


def keyed_content(img: Image.Image) -> tuple[np.ndarray, tuple[int, int, int, int] | None, list[str]]:
    """Key the background and return (rgba, content bbox (x0, y0, x1, y1) or None, notes)."""
    notes: list[str] = []
    arr = np.array(img.convert("RGBA"))
    arr, note = key_background(arr)
    if note:
        notes.append(note)
    a = arr[..., 3] >= ALPHA_CUTOFF
    if not a.any():
        return arr, None, notes
    ys, xs = np.where(a)
    return arr, (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1), notes


def reference_scale(img: Image.Image, cell: tuple[int, int], target_h: int) -> float:
    """Source-pixels-per-output-pixel so the reference pose's HEIGHT lands on the stature target
    (bible §3: Tiny 36, Small 52, Medium 72, Large 104). ONE value per facing: every frame of
    that facing is scaled by the same factor, so poses keep their relative size (a crouching
    death frame stays small, an extended weapon stays long). Width is never the driver: a wide
    stance must not shrink the creature (that made the goblin 62 px and the fighter 92 px)."""
    _, bbox, _ = keyed_content(img)
    if bbox is None:
        return 1.0
    x0, y0, x1, y1 = bbox
    return max((y1 - y0) / max(1, target_h - 2), 1e-6)  # -2: outline adds a pixel top and bottom


def fit_frame(img: Image.Image, cell: tuple[int, int], pal, ink, add_outline: bool, scale: float | None = None) -> tuple[np.ndarray, list[str]]:
    """Key, scale (by the creature's shared factor), quantize, outline a single frame, then
    anchor it: feet on the ground line, horizontally on the source slot's center so poses do
    not slide when a weapon extends. Falls back to per-frame fitting when `scale` is None."""
    cw, ch = cell
    arr, bbox, notes = keyed_content(img)
    if bbox is None:
        notes.append("frame is empty after keying/alpha cutoff")
        return np.zeros((ch, cw, 4), np.uint8), notes
    src_w, src_h = arr.shape[1], arr.shape[0]
    x0, y0, x1, y1 = bbox
    if scale is None:
        scale = max((y1 - y0) / (ch - GROUND_INSET - 2), (x1 - x0) / (cw - 2))
        notes.append("no reference; fitted per frame")
    # Scale the whole slot (not just the crop) so the slot center stays meaningful.
    sw, sh = max(1, int(round(src_w / scale))), max(1, int(round(src_h / scale)))
    small = np.array(Image.fromarray(arr, "RGBA").resize((sw, sh), Image.NEAREST))
    small = quantize(small, pal)
    if add_outline:
        small = outline(small, ink)
    a = small[..., 3] > 0
    if not a.any():
        notes.append("frame vanished after scaling")
        return np.zeros((ch, cw, 4), np.uint8), notes
    ys, xs = np.where(a)
    cy1 = int(ys.max()) + 1                       # feet
    cx0, cx1 = int(xs.min()), int(xs.max()) + 1   # content x-extent after scaling
    content_h = cy1 - int(ys.min())
    # Vertical: feet on the ground line; clip the top if the pose is taller than the cell.
    dst_bottom = ch - GROUND_INSET
    src_top = max(0, cy1 - dst_bottom)  # rows of the scaled image to drop from the top
    if content_h > dst_bottom:
        notes.append(f"pose {content_h} px tall exceeds cell; top clipped by {content_h - dst_bottom}")
    # Horizontal: slot center -> cell center, then nudge to keep content inside the cell.
    slot_cx = sw / 2.0
    shift = int(round(cw / 2.0 - slot_cx))
    if cx0 + shift < 0:
        shift = -cx0
    if cx1 + shift > cw:
        shift = cw - cx1
    if cx1 - cx0 > cw:
        notes.append(f"pose {cx1 - cx0} px wide exceeds cell {cw}; sides clipped")
        shift = int(round(cw / 2.0 - (cx0 + cx1) / 2.0))
    canvas = np.zeros((ch, cw, 4), np.uint8)
    for sy in range(src_top, cy1):
        dy = dst_bottom - (cy1 - sy)
        if dy < 0 or dy >= ch:
            continue
        row = small[sy]
        for sx in range(cx0, cx1):
            dx = sx + shift
            if 0 <= dx < cw and row[sx, 3] > 0:
                canvas[dy, dx] = row[sx]
    return canvas, notes


# ---- build / check -------------------------------------------------------------------------

def build(creature: str, size: str, add_outline: bool, from_turnaround: bool = False, stature: str | None = None) -> bool:
    pal, ink = load_palette()
    cw, ch = SIZES[size]
    stature = stature or ("L" if size == "L" else "M")
    target_h = STATURE_HEIGHT[stature]
    src = INBOX / creature
    if not src.is_dir():
        print(f"no inbox folder: {src}")
        return False
    cols = sum(n for _, n in ANIMS)
    sheet = np.zeros((ch * len(FACINGS), cw * cols, 4), np.uint8)
    problems: list[str] = []
    notes: list[str] = []
    sources: list[str] = []

    whole = src / "sheet.png"
    turn = src / "turnaround.png"
    frames_present = any((src / f"{f}_{a}_{i}.png").exists() for f, a, i in frame_names())

    if whole.exists():
        img = Image.open(whole).convert("RGBA")
        sx, sy = img.width / (cw * cols), img.height / (ch * len(FACINGS))
        sources.append("sheet.png")
        if abs(sx - sy) > 0.02:
            problems.append(f"sheet.png {img.width}x{img.height} is not a uniform scale of {cw * cols}x{ch * len(FACINGS)}")
        scale = reference_scale(img.crop((0, 0, int(cw * sx), int(ch * sy))), (cw, ch), target_h)
        notes.append(f"shared scale {scale:.3f} from sheet r0c0 (stature {stature}, {target_h} px)")
        for r in range(len(FACINGS)):
            for c in range(cols):
                box = (int(c * cw * sx), int(r * ch * sy), int((c + 1) * cw * sx), int((r + 1) * ch * sy))
                frame, n_ = fit_frame(img.crop(box), (cw, ch), pal, ink, add_outline, scale)
                notes += [f"r{r}c{c}: {x}" for x in n_ if "keyed" not in x]
                sheet[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = frame
    elif frames_present and not from_turnaround:
        # One scale per FACING, from that facing's idle_0 (strips of one facing are generated
        # together, so this is the consistency the generator can actually deliver). Drift between
        # animations of the same facing is measured and reported, not hidden.
        scales: dict[str, float | None] = {}
        for f in FACINGS:
            ref = src / f"{f}_idle_0.png"
            if ref.exists():
                scales[f] = reference_scale(Image.open(ref), (cw, ch), target_h)
                notes.append(f"{f}: scale {scales[f]:.3f} from {f}_idle_0 (stature {stature}, {target_h} px)")
            else:
                scales[f] = None
                problems.append(f"{f}_idle_0.png missing: {f} frames fitted individually")
        heights: dict[tuple[str, str], list[int]] = {}
        for f, a, i in frame_names():
            p = src / f"{f}_{a}_{i}.png"
            r, c = FACINGS.index(f), col_index(a, i)
            if not p.exists():
                problems.append(f"missing {p.name}")
                continue
            sources.append(p.name)
            frame, n_ = fit_frame(Image.open(p), (cw, ch), pal, ink, add_outline, scales[f])
            notes += [f"{p.name}: {x}" for x in n_ if "keyed" not in x]
            sheet[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = frame
            alpha = frame[..., 3] > 0
            if alpha.any():
                ys = np.where(alpha)[0]
                heights.setdefault((f, a), []).append(int(ys.max() - ys.min() + 1))
        # Drift check: each animation's mean height vs the facing's idle. Death legitimately shrinks.
        for f in FACINGS:
            idle = heights.get((f, "idle"))
            if not idle:
                continue
            idle_h = sum(idle) / len(idle)
            for a, _ in ANIMS:
                if a in ("idle", "death") or (f, a) not in heights:
                    continue
                mean_h = sum(heights[(f, a)]) / len(heights[(f, a)])
                drift = (mean_h - idle_h) / idle_h
                if abs(drift) > DRIFT_TOLERANCE:
                    problems.append(f"drift: {f} {a} averages {mean_h:.0f} px vs idle {idle_h:.0f} px ({drift:+.0%}); regenerate strip_{f}_{a}.png at the idle's scale")
    elif turn.exists():
        # Turnaround-only sheet: every frame of a facing = that facing's slot. Marks the sheet
        # as a placeholder in the manifest; animation strips replace it later.
        img = Image.open(turn).convert("RGBA")
        slot = img.width // 3
        sources.append("turnaround.png (placeholder: all frames from one pose)")
        scale = reference_scale(img.crop((0, 0, slot, img.height)), (cw, ch), target_h)
        notes.append(f"shared scale {scale:.3f} from turnaround S slot (stature {stature}, {target_h} px)")
        for r, f in enumerate(FACINGS):
            frame, n_ = fit_frame(img.crop((r * slot, 0, (r + 1) * slot, img.height)), (cw, ch), pal, ink, add_outline, scale)
            notes += [f"{f}: {x}" for x in n_]
            for c in range(cols):
                sheet[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = frame
    else:
        problems.append("no sheet.png, frames, or turnaround.png in inbox")

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{creature}.png"
    Image.fromarray(sheet, "RGBA").save(out_path)

    portrait = src / "portrait.png"
    if portrait.exists():
        parr = np.array(Image.open(portrait).convert("RGBA"))
        parr, _ = key_background(parr)
        pimg = Image.fromarray(parr, "RGBA").resize((128, 128), Image.NEAREST)
        parr = quantize(np.array(pimg), pal)
        if add_outline:
            parr = outline(parr, ink)
        Image.fromarray(parr, "RGBA").save(OUT / f"{creature}_portrait.png")
        sources.append("portrait.png")

    write_manifest(creature, out_path, sources, size, placeholder=("turnaround.png" in " ".join(sources)), stature=stature)
    ok = check(out_path, size, quiet=True) and not problems
    print(f"{creature}: {'OK' if ok else 'NEEDS REGEN'} -> {out_path.relative_to(ROOT)}")
    for p in problems:
        print(f"   ! {p}")
    shown = [n for n in notes if "keyed" in n][:3] + [n for n in notes if "keyed" not in n][:6]
    for n in shown:
        print(f"   - {n}")
    return ok


def check(sheet_path: Path, size: str, quiet: bool = False) -> bool:
    pal, _ = load_palette()
    cw, ch = SIZES[size]
    cols = sum(n for _, n in ANIMS)
    img = Image.open(sheet_path).convert("RGBA")
    arr = np.array(img)
    errs: list[str] = []
    if img.size != (cw * cols, ch * len(FACINGS)):
        errs.append(f"size {img.size}, expected {(cw * cols, ch * len(FACINGS))}")
    semi = int(((arr[..., 3] > 0) & (arr[..., 3] < 255)).sum())
    if semi:
        errs.append(f"{semi} semi-transparent pixels")
    opaque = arr[arr[..., 3] == 255][:, :3]
    if len(opaque):
        pal_set = {tuple(c) for c in pal.tolist()}
        off = sum(1 for c in map(tuple, opaque.tolist()) if c not in pal_set)
        if off:
            errs.append(f"{off} off-palette pixels")
    if not errs:
        gy = ch - 1 - GROUND_INSET
        for r in range(len(FACINGS)):
            for c in range(cols):
                cell = arr[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw, 3] > 0
                if not cell.any():
                    continue
                if not cell[gy].any():
                    errs.append(f"frame r{r} c{c}: nothing touches the ground line")
                if cell[gy + 1:].any():
                    errs.append(f"frame r{r} c{c}: pixels below the ground line")
    if not quiet:
        print(f"{sheet_path.name}: {'PASS' if not errs else 'FAIL'}")
        for e in errs[:12]:
            print(f"   ! {e}")
    return not errs


def write_manifest(creature: str, out_path: Path, sources: list[str], size: str, placeholder: bool, stature: str = "M") -> None:
    mpath = SPRITES / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    manifest[creature] = {
        "sheet": str(out_path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest(),
        "size": size,
        "stature": stature,
        "sources": sources,
        "placeholder": placeholder,
        "date": date.today().isoformat(),
        "tool": f"sprite_clean {TOOL_VERSION}",
    }
    mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("creature"); b.add_argument("--size", default="M", choices=SIZES)
    b.add_argument("--no-outline", action="store_true"); b.add_argument("--from-turnaround", action="store_true")
    b.add_argument("--stature", choices=STATURE_HEIGHT, help="T/S/M/L target height (default M, or L for --size L)")
    ba = sub.add_parser("build-all"); ba.add_argument("--size", default="M", choices=SIZES); ba.add_argument("--no-outline", action="store_true")
    c = sub.add_parser("check"); c.add_argument("sheet"); c.add_argument("--size", default="M", choices=SIZES)
    a = ap.parse_args()
    if a.cmd == "build":
        sys.exit(0 if build(a.creature, a.size, not a.no_outline, a.from_turnaround, a.stature) else 1)
    if a.cmd == "build-all":
        ok = all(build(p.name, a.size, not a.no_outline) for p in sorted(INBOX.iterdir()) if p.is_dir())
        sys.exit(0 if ok else 1)
    if a.cmd == "check":
        sys.exit(0 if check(Path(a.sheet), a.size) else 1)


if __name__ == "__main__":
    main()
