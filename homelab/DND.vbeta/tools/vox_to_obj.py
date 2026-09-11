"""VOX 150 to exposed-face OBJ. Run: python tools/vox_to_obj.py --all.

VOX east/north/up becomes Unity X/Z/Y. The axis swap reverses handedness,
so face winding is reversed after transformation. Origin: footprint center
at z=0 (VOX), never the occupied bounding-box center. One voxel=1/16 unit.
Atlas rows follow PNG top-to-bottom; OBJ v coordinates run bottom-to-top.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from vox_write import DEST, master_palette

# Outward CCW corners in right-handed VOX coordinates; reversed for Y-up export.
FACES = [
    ((-1, 0, 0), ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
    ((1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))),
    ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
    ((0, 1, 0), ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0))),
    ((0, 0, -1), ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))),
    ((0, 0, 1), ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
]


def read_vox(path):
    data = Path(path).read_bytes()
    if len(data) < 20 or data[:4] != b'VOX ' or struct.unpack_from('<I', data, 4)[0] != 150:
        raise ValueError('Expected VOX version 150')
    chunks = []

    def walk(start, end):
        pos = start
        while pos < end:
            if pos + 12 > end:
                raise ValueError('Truncated chunk header')
            tag = data[pos:pos + 4]
            n, children = struct.unpack_from('<II', data, pos + 4)
            body_start = pos + 12
            body_end, chunk_end = body_start + n, body_start + n + children
            if chunk_end > end:
                raise ValueError('Chunk exceeds parent')
            chunks.append((tag, data[body_start:body_end]))
            if children:
                walk(body_end, chunk_end)
            pos = chunk_end

    walk(8, len(data))
    if chunks[0][0] != b'MAIN' or chunks[0][1]:
        raise ValueError('Expected empty MAIN container')
    if any(sum(tag == t for tag, _ in chunks) != 1 for t in (b'SIZE', b'XYZI', b'RGBA')):
        raise ValueError('Expected one model with SIZE, XYZI and RGBA')
    bodies = dict(chunks)
    if len(bodies[b'SIZE']) != 12 or len(bodies[b'RGBA']) != 1024:
        raise ValueError('Invalid SIZE or palette length')
    shape = struct.unpack('<III', bodies[b'SIZE'])
    if any(s < 1 or s > 256 for s in shape):
        raise ValueError('Invalid dimensions')
    xyzi = bodies[b'XYZI']
    count = struct.unpack_from('<I', xyzi)[0]
    if len(xyzi) != 4 + count * 4:
        raise ValueError('Invalid XYZI count')
    records = np.frombuffer(xyzi, np.uint8, offset=4).reshape(count, 4)
    if not count or np.any(records[:, :3] >= np.array(shape)) or np.any(records[:, 3] == 0):
        raise ValueError('Empty model, invalid coordinate or color zero')
    if len(np.unique(records[:, :3], axis=0)) != count:
        raise ValueError('Duplicate voxel coordinates')
    palette = np.frombuffer(bodies[b'RGBA'], np.uint8).reshape(256, 4)
    master = master_palette()
    if not np.array_equal(palette, np.concatenate((master[1:], master[:1]))):
        raise ValueError('Palette does not preserve all master indices')
    if np.any(master[records[:, 3], 3] == 0):
        raise ValueError('Unused master color')
    a = np.zeros(shape, np.uint8)
    a[tuple(records[:, :3].T)] = records[:, 3]
    return a


def exposed_faces(a):
    shape = np.array(a.shape)
    for xyz in np.argwhere(a != 0):
        color = int(a[tuple(xyz)])
        for normal, corners in FACES:
            neighbor = xyz + normal
            if np.all(neighbor >= 0) and np.all(neighbor < shape) and a[tuple(neighbor)] != 0:
                continue
            yield color, normal, [tuple(xyz + c) for c in reversed(corners)]


def unity_vertex(xyz, shape):
    x, y, z = xyz
    return ((x - shape[0] / 2) / 16, z / 16, (y - shape[1] / 2) / 16)


def palette_uv(index):
    return ((index % 16 + 0.5) / 16, 1 - (index // 16 + 0.5) / 16)


def write_atlas(directory):
    # Eight texels per color cell; center UVs stay away from neighboring colors.
    colors = master_palette().reshape(16, 16, 4)
    atlas = np.repeat(np.repeat(colors, 8, axis=0), 8, axis=1)
    Image.fromarray(atlas).save(directory / 'palette_atlas.png')


def convert(tid, meta, directory):
    a = read_vox(DEST / meta['file'])
    if tuple(a.shape[:2]) != tuple(v * 16 for v in meta['footprint']):
        raise ValueError('Model footprint and metadata disagree')
    vertices, lookup = [], {}
    groups = {'palette': [], 'emissive': []}
    emissive = set(meta['emissive'])
    normals = [(n[0], n[2], n[1]) for n, _ in FACES]
    normal_ids = {n: i + 1 for i, (n, _) in enumerate(FACES)}
    for color, normal, corners in exposed_faces(a):
        indices = []
        for corner in corners:
            if corner not in lookup:
                lookup[corner] = len(vertices) + 1
                vertices.append(unity_vertex(corner, a.shape))
            indices.append(lookup[corner])
        groups['emissive' if color in emissive else 'palette'].append((indices, color + 1, normal_ids[normal]))
    lines = [f'# Dungine {tid}; 1 voxel = 1/16 unit; Y-up floor-center origin',
             f'mtllib {tid}.mtl', f'o {tid}', 's off']
    lines += ['v ' + ' '.join(f'{v:.6f}' for v in xyz) for xyz in vertices]
    lines += ['vt %.8f %.8f' % palette_uv(i) for i in range(256)]
    lines += ['vn %d %d %d' % n for n in normals]
    for group, faces in groups.items():
        if not faces:
            continue
        lines += [f'g {group}', f'usemtl {group}']
        for indices, uv, normal in faces:
            lines.append('f ' + ' '.join(f'{v}/{uv}/{normal}' for v in indices))
    (directory / f'{tid}.obj').write_text('\n'.join(lines) + '\n', encoding='utf8')
    material = '# Import textures with Point filtering; no mipmaps or compression.\n'
    material += 'newmtl palette\nKa 0 0 0\nKd 1 1 1\nKs 0 0 0\nd 1\nillum 1\nmap_Kd palette_atlas.png\n'
    if groups['emissive']:
        material += '\nnewmtl emissive\nKa 0 0 0\nKd 1 1 1\nKe 1 1 1\nd 1\nillum 1\nmap_Kd palette_atlas.png\nmap_Ke palette_atlas.png\n'
    (directory / f'{tid}.mtl').write_text(material, encoding='utf8')
    return {key: len(faces) for key, faces in groups.items()}


def generate_all():
    kit = json.loads((DEST / 'kit.json').read_text())
    directory = DEST / 'obj'
    directory.mkdir(parents=True, exist_ok=True)
    write_atlas(directory)
    for tid, meta in kit['tiles'].items():
        counts = convert(tid, meta, directory)
        print(f'{tid}: {sum(counts.values())} exposed quads ({counts["emissive"]} emissive)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', required=True)
    parser.parse_args()
    generate_all()
