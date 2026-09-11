"""Deterministic Plan 06 dungeon kit. Run: python tools/vox_write.py --all.

Arrays are uint8[x east, y north, z up]; zero is empty. Box bounds are
half-open. All carving and decoration is confined to the declared model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'assets-src/voxels'
PALETTES = ROOT / 'assets-src/palettes'


def master_palette():
    palette = np.array(Image.open(PALETTES / 'master.png').convert('RGBA'))
    if palette.shape != (1, 256, 4):
        raise ValueError('Expected a 256x1 master palette')
    return palette[0]


def named_colors():
    ramps = json.loads((PALETTES / 'master.json').read_text())['ramps']
    master = master_palette()
    result, index = {}, 1
    for ramp, colors in ramps.items():
        for step, hex_color in enumerate(colors):
            rgb = tuple(int(hex_color.lstrip('#')[k:k + 2], 16) for k in (0, 2, 4))
            if tuple(master[index, :3]) != rgb:
                raise ValueError(f'Master JSON/PNG mismatch at index {index}')
            result[f'{ramp}_{step}'] = index
            index += 1
    return result


def rng(tile_id):
    seed = int.from_bytes(hashlib.sha256(str(tile_id).encode('utf8')).digest()[:8], 'little')
    return np.random.Generator(np.random.PCG64(seed))


def box(a, lo, hi, color):
    """Fill a half-open box; reject accidental footprint overflow."""
    if len(lo) != 3 or len(hi) != 3:
        raise ValueError('Expected three coordinates per corner')
    if any(l < 0 or h > s or h < l for l, h, s in zip(lo, hi, a.shape)):
        raise ValueError(f'Box {lo}:{hi} outside {a.shape}')
    if not 0 <= int(color) <= 255:
        raise ValueError('Palette index outside uint8')
    a[tuple(slice(l, h) for l, h in zip(lo, hi))] = color


def fill_layer(a, z, color):
    box(a, (0, 0, z), (a.shape[0], a.shape[1], z + 1), color)


def noise_patch(a, seed, colors, count=12, eligible=None):
    """Seeded grit on occupied surface voxels, restricted to one material."""
    mask = a != 0 if eligible is None else np.isin(a, eligible)
    solid = a != 0
    surrounded = np.ones(a.shape, dtype=bool)
    padded = np.pad(solid, 1)
    for axis in range(3):
        for delta in (-1, 1):
            slices = [slice(1, s + 1) for s in a.shape]
            slices[axis] = slice(1 + delta, a.shape[axis] + 1 + delta)
            surrounded &= padded[tuple(slices)]
    points = np.argwhere(mask & ~surrounded)
    generator = rng(seed)
    if len(points):
        for i in generator.choice(len(points), min(count, len(points)), replace=False):
            a[tuple(points[i])] = generator.choice(colors)


def mortar_lines(a):
    """One-voxel recessed exterior joints, four-voxel courses; preserve footing."""
    w, d, h = a.shape
    for z in range(4, h, 4):
        a[:, 0, z] = a[:, d - 1, z] = 0
        a[0, :, z] = a[w - 1, :, z] = 0
    for z in range(1, h):
        offset = 2 if (z // 4) % 2 else 0
        for x in range(4 + offset, w - 1, 8):
            a[x, 0, z] = a[x, d - 1, z] = 0
        for y in range(4 + offset, d - 1, 8):
            a[0, y, z] = a[w - 1, y, z] = 0


def chunk(tag, body=b'', children=b''):
    return tag + struct.pack('<II', len(body), len(children)) + body + children


def save_vox(path, a):
    if a.dtype != np.uint8 or a.ndim != 3 or any(s < 1 or s > 256 for s in a.shape):
        raise ValueError('Expected uint8[x,y,z], dimensions 1..256')
    master = master_palette()
    used = np.unique(a[a != 0])
    if not len(used) or any(master[int(i), 3] == 0 for i in used):
        raise ValueError('Empty model or unused master index')
    positions = np.argwhere(a != 0)
    records = np.column_stack((positions, a[tuple(positions.T)])).astype(np.uint8)
    # VOX RGBA row zero corresponds to voxel index ONE, not zero.
    rgba = np.concatenate((master[1:], master[:1])).tobytes()
    children = chunk(b'SIZE', struct.pack('<iii', *a.shape))
    children += chunk(b'XYZI', struct.pack('<I', len(records)) + records.tobytes())
    children += chunk(b'RGBA', rgba)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'VOX ' + struct.pack('<I', 150) + chunk(b'MAIN', children=children))


def tile_specs():
    groups = {
        'floor': ['floor_stone', 'floor_stone_worn_a', 'floor_stone_worn_b',
                  'floor_stone_worn_c', 'floor_stone_drain', 'floor_dirt', 'floor_water_shallow'],
        'wall': ['wall_block', 'wall_block_cracked', 'wall_block_mossy', 'wall_arrowslit', 'wall_sconce'],
        'door': ['door_frame_open', 'door_closed', 'archway'],
        'stairs': ['stairs_half_up'], 'platform': ['platform_half', 'ledge_edge'],
        'pillar': ['pillar_round', 'pillar_broken'],
        'prop': ['table', 'chair', 'barrel', 'crate', 'chest_closed', 'chest_open',
                 'bookshelf', 'altar', 'sarcophagus', 'bones_pile', 'rubble', 'statue_knight'],
        'light': ['brazier', 'torch_standing', 'candle_cluster'],
    }
    heights = {'table': 12, 'chair': 20, 'barrel': 15, 'crate': 14,
               'chest_closed': 12, 'chest_open': 22, 'bookshelf': 32, 'altar': 16,
               'sarcophagus': 16, 'bones_pile': 4, 'rubble': 7, 'statue_knight': 36,
               'brazier': 19, 'torch_standing': 28, 'candle_cluster': 12}
    result = {}
    for category, ids in groups.items():
        for tid in ids:
            h = heights.get(tid, {'floor': 3, 'wall': 32, 'door': 32,
                                  'stairs': 8, 'platform': 8, 'pillar': 40}.get(category))
            footprint = [2, 1] if tid in ('table', 'sarcophagus') else [1, 1]
            closed = tid == 'door_closed'
            blocking = category in ('wall', 'pillar', 'prop') or closed
            sight = category == 'wall' or closed or (category == 'prop' and h >= 32)
            cover = 3 if category == 'wall' or closed else 2 if category == 'pillar' or tid in ('bookshelf', 'sarcophagus', 'statue_knight') else 1 if category == 'prop' else 0
            variant = 'floor_stone' if tid.startswith('floor_stone_worn') else 'wall_block' if tid in ('wall_block_cracked', 'wall_block_mossy') else 'pillar_round' if tid == 'pillar_broken' else None
            result[tid] = dict(file=f'dungeon/{tid}.vox', category=category, footprint=footprint,
                               height_tiles=max(1, h / 16), blocks_move=blocking, blocks_sight=sight,
                               cover=cover, elevation_half=int(category in ('stairs', 'platform')),
                               difficult=tid == 'floor_water_shallow', emissive=[], biome='dungeon',
                               mode='both', variant_of=variant)
    return result


def build_tile(tid, meta):
    c = named_colors()
    stone, shadow, light = (c[n] for n in ('neutral_2', 'night_purple_1', 'neutral_3'))
    wood, wood_dark, wood_light = (c[f'earth_wood_{i}'] for i in (2, 1, 3))
    metal, metal_dark, metal_light = (c[f'metal_{i}'] for i in (1, 0, 2))
    orange = [c[f'emissive_orange_{i}'] for i in (1, 2, 3)]
    w, d = (v * 16 for v in meta['footprint'])
    category = meta['category']
    h = 3 if category == 'floor' else int(meta['height_tiles'] * 16)
    a = np.zeros((w, d, h), dtype=np.uint8)

    def b(lo, hi, color=stone):
        box(a, lo, hi, color)

    def cylinder(cx, cy, radius, z0, z1, color):
        x, y = np.ogrid[:w, :d]
        mask = (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2
        for z in range(z0, z1):
            a[:, :, z][mask] = color

    def flame(cx, cy, z, height=5):
        for k in range(height):
            radius = 2 if k < height // 2 else 1 if k < height - 1 else 0
            cylinder(cx + (1 if k == height - 1 else 0), cy, radius, z + k, z + k + 1, orange[min(2, k * 3 // height)])
        meta['emissive'] = sorted(set(int(v) for v in a.flatten() if v in orange))

    if category == 'floor':
        b((0, 0, 0), (w, d, 2))
        fill_layer(a, 2, light)
        a[::8, :, 2] = shadow
        a[:, ::8, 2] = shadow
        if tid.endswith('worn_a'):
            b((0, 0, 2), (4, 3, 3), 0)
            b((13, 13, 2), (16, 16, 3), 0)
        elif tid.endswith('worn_b'):
            for y in range(2, 15):
                a[5 + y // 4, y, 2] = shadow
                if y % 3 == 0: a[6 + y // 4, y, 2] = 0
        elif tid.endswith('worn_c'):
            b((10, 1, 2), (15, 5, 3), c['foliage_0'])
            a[12:15, 2:4, 2] = c['foliage_1']
            a[15, 0:3, 2] = 0
        elif tid == 'floor_stone_drain':
            b((4, 4, 2), (12, 12, 3), metal_dark)
            for x in (5, 7, 9, 11): b((x, 4, 2), (x + 1, 12, 3), metal)
        elif tid == 'floor_dirt':
            a[:] = wood_dark
            fill_layer(a, 2, wood)
            a[2:5, 9:12, 2] = wood_light
        elif tid == 'floor_water_shallow':
            a[:] = c['water_0']
            fill_layer(a, 2, c['water_1'])
            a[3:9, 5, 2] = c['water_2']
            a[10:14, 11, 2] = c['water_0']
    elif category == 'wall':
        a[:] = stone
        a[:, :, 0] = shadow
        a[:, :, -1] = light
        mortar_lines(a)
        if tid == 'wall_block_cracked':
            for z in range(7, 30):
                x = 7 + (z // 5) % 3
                b((x, 0, z), (x + 2, 3, z + 1), 0)
            b((13, 0, 29), (16, 3, 32), 0)
        elif tid == 'wall_block_mossy':
            b((3, 0, 1), (10, 1, 6), c['foliage_0'])
            b((4, 0, 2), (8, 1, 5), c['foliage_1'])
        elif tid == 'wall_arrowslit':
            b((7, 0, 12), (9, 16, 24), 0)
        elif tid == 'wall_sconce':
            b((5, 0, 14), (11, 3, 27), 0)
            b((7, 1, 14), (9, 3, 22), metal_dark)
            b((5, 0, 20), (11, 3, 22), metal)
            flame(8, 1, 22, 5)
    elif category == 'door':
        # One-voxel threshold is part of the frame, not an invisible blocking slab.
        fill_layer(a, 0, stone)
        b((0, 5, 1), (3, 11, 32))
        b((13, 5, 1), (16, 11, 32))
        b((0, 5, 28), (16, 11, 32), light)
        if tid == 'archway':
            for z, inset in ((24, 2), (25, 3), (26, 4), (27, 5)):
                b((3, 5, z), (3 + inset, 11, z + 1))
                b((13 - inset, 5, z), (13, 11, z + 1))
        if tid == 'door_closed':
            b((3, 7, 1), (13, 9, 28), wood)
            for x in (5, 8, 11): b((x, 7, 1), (x + 1, 8, 28), wood_dark)
            for z in (6, 22): b((3, 6, z), (13, 7, z + 2), metal_dark)
            b((10, 5, 13), (12, 7, 15), metal)
        a[1, 5, 17:20] = shadow
    elif category in ('stairs', 'platform'):
        for y in range(d):
            height = 1 + y // 2 if category == 'stairs' else 8
            b((0, y, 0), (w, y + 1, height))
            b((0, y, height - 1), (w, y + 1, height), light)
        if tid == 'ledge_edge':
            b((0, 0, 7), (16, 2, 8), shadow)
            b((2, 0, 6), (5, 1, 8), 0)
        a[7, 6, int(np.max(np.nonzero(a[7, 6])[0]))] = shadow
    elif category == 'pillar':
        b((0, 0, 0), (16, 16, 2))
        b((1, 1, 2), (15, 15, 4), light)
        cylinder(7.5, 7.5, 5.5, 4, 37, stone)
        b((1, 1, 37), (15, 15, 40), light)
        if tid == 'pillar_broken':
            b((0, 0, 24), (16, 16, 40), 0)
            for x in range(3, 13):
                b((x, 3, 20 + x % 4), (x + 1, 13, 24), 0)
        a[2:4, 0:2, 1] = 0
    elif tid in ('table', 'chair'):
        top = 10 if tid == 'table' else 7
        for x in (2, w - 4):
            for y in (2, 12): b((x, y, 0), (x + 2, y + 2, top), wood_dark)
        b((1, 1, top), (w - 1, 15, top + 2), wood)
        for x in range(4, w - 2, 5): b((x, 1, top + 1), (x + 1, 15, top + 2), wood_dark)
        if tid == 'chair':
            b((2, 12, 8), (14, 14, 20), wood)
            b((5, 12, 11), (11, 14, 16), 0)
    elif tid == 'barrel':
        for z in range(15):
            cylinder(7.5, 7.5, 5 if z in (0, 14) else 6.5, z, z + 1, metal_dark if z in (2, 11) else wood)
        a[7, 2:14, 14] = wood_dark
    elif tid == 'crate':
        b((1, 1, 0), (15, 15, 14), wood)
        for x in (2, 7, 12): b((x, 0, 0), (x + 1, 1, 14), wood_dark)
        for z in range(14):
            b((max(1, z), 0, z), (min(15, z + 3), 1, z + 1), wood_light)
        for z in (1, 11): b((1, 0, z), (15, 1, z + 2), wood_dark)
        for y in (4, 8, 12): b((1, y, 13), (15, y + 1, 14), wood_dark)
    elif tid in ('chest_closed', 'chest_open'):
        b((1, 3, 0), (15, 13, 9), wood)
        b((3, 5, 2), (13, 11, 9), 0)
        if tid == 'chest_closed':
            b((1, 3, 9), (15, 13, 12), wood_light)
        else:
            b((1, 11, 9), (15, 13, 22), wood_light)
            b((3, 11, 11), (13, 12, 20), wood_dark)
        b((7, 2, 6), (9, 3, 10), metal)
    elif tid == 'bookshelf':
        b((1, 12, 0), (15, 15, 32), wood_dark)
        for x in (1, 13): b((x, 3, 0), (x + 2, 15, 32), wood)
        for z in (0, 10, 20, 30):
            b((1, 3, z), (15, 15, z + 2), wood)
        for shelf in (2, 12, 22):
            for x in (3, 5, 8, 10, 12):
                b((x, 5, shelf), (x + 1, 12, shelf + 5 + x % 3), c['sand_warmstone_1'])
    elif tid in ('altar', 'sarcophagus'):
        b((2, 2, 0), (w - 2, 14, 3))
        b((4, 4, 3), (w - 4, 12, 13), shadow)
        b((1, 1, 13), (w - 1, 15, 16), light)
        if tid == 'sarcophagus':
            b((6, 6, 15), (25, 10, 16), stone)
            b((23, 5, 15), (27, 11, 16), stone)
        else:
            a[5:11, 5:11, 15] = shadow
    elif tid == 'bones_pile':
        for x, y in ((3, 3), (7, 9), (2, 12)):
            b((x, y, 0), (x + 6, y + 2, 2), c['neutral_5'])
            b((x, y, 0), (x + 2, y + 2, 3), c['neutral_4'])
        b((9, 3, 0), (13, 7, 4), c['neutral_5'])
        a[10, 3, 2] = a[12, 3, 2] = c['neutral_3']
    elif tid == 'rubble':
        for x, y, size in ((1, 1, 4), (7, 2, 6), (3, 9, 5), (11, 11, 3)):
            b((x, y, 0), (x + size, y + size, size))
            b((x, y, size - 1), (x + size, y + size, size), light)
    elif tid == 'statue_knight':
        b((1, 1, 0), (15, 15, 4))
        for x in (4, 9): b((x, 6, 4), (x + 3, 10, 16), shadow)
        b((4, 5, 16), (12, 11, 27))
        b((5, 6, 27), (11, 11, 34), light)
        b((5, 5, 30), (11, 6, 31), shadow)
        b((1, 4, 16), (4, 10, 25), light)
        b((12, 7, 6), (14, 9, 24), shadow)
        b((11, 6, 19), (15, 10, 21))
    elif tid == 'brazier':
        for x, y in ((4, 4), (10, 4), (7, 11)): b((x, y, 0), (x + 2, y + 2, 10), metal_dark)
        cylinder(8, 8, 5, 9, 12, metal)
        cylinder(8, 8, 3, 11, 12, metal_dark)
        flame(8, 8, 12, 7)
    elif tid == 'torch_standing':
        b((4, 4, 0), (12, 12, 2), metal_dark)
        b((7, 7, 2), (9, 9, 21), wood)
        b((6, 6, 19), (10, 10, 22), metal)
        flame(8, 8, 22, 6)
    elif tid == 'candle_cluster':
        b((3, 3, 0), (13, 13, 1), metal_dark)
        for x, y, top in ((5, 5, 5), (10, 6, 8), (7, 10, 7)):
            b((x, y, 1), (x + 2, y + 2, top), c['sand_warmstone_1'])
            b((x, y, 1), (x + 1, y + 1, 2), c['sand_warmstone_0'])
            b((x + 1, y + 1, top - 2), (x + 2, y + 2, top), c['sand_warmstone_2'])
            flame(x, y, top, 3)
        meta['emissive'] = sorted(set(int(v) for v in a.flatten() if v in orange))
    else:
        raise ValueError(tid)

    # Material-restricted weathering; never overwrites fire or introduces extra tones.
    if tid != 'bones_pile':
        noise_patch(a, tid + ':stone', [shadow, light], 16, [stone, shadow, light])
    noise_patch(a, tid + ':wood', [wood_dark, wood_light], 12, [wood, wood_dark, wood_light])
    noise_patch(a, tid + ':metal', [metal_dark, metal_light], 5, [metal, metal_dark, metal_light])
    return a


def generate_all():
    specs = tile_specs()
    for tid, meta in specs.items():
        a = build_tile(tid, meta)
        save_vox(DEST / meta['file'], a)
        print(f'{tid}: {np.count_nonzero(a)} voxels, SIZE {a.shape}')
    kit = dict(version=1, biome='dungeon', voxels_per_tile=16, tiles=specs)
    (DEST / 'kit.json').write_text(json.dumps(kit, indent=2) + '\n', encoding='utf8')
    return kit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', required=True)
    parser.parse_args()
    generate_all()
