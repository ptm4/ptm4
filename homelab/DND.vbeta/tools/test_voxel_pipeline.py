"""Independent geometry/format regressions: python -m unittest discover -s tools -p test_voxel_pipeline.py."""
from contextlib import contextmanager
import json
import struct
import unittest
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

import vox_write as writer
import vox_to_obj as exporter


@contextmanager
def scratch_directory():
    # TemporaryDirectory requests mode0700, which this Windows sandbox cannot reopen.
    base = (writer.DEST / 'inbox').resolve()
    path = base / ('test-' + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        assert path.resolve().parent == base
        for child in path.iterdir():
            child.unlink()
        path.rmdir()


class VoxelPipelineTests(unittest.TestCase):
    def test_master_index_shift_and_full_roundtrip(self):
        # Workspace-local temporary artifacts; source palette is never changed.
        with scratch_directory() as directory:
            a = np.zeros((16, 16, 3), np.uint8)
            a[0, 0, 0], a[15, 15, 2], a[3, 9, 1] = 1, 57, 16
            path = Path(directory) / 'fixture.vox'
            writer.save_vox(path, a)
            self.assertTrue(np.array_equal(exporter.read_vox(path), a))
            data = path.read_bytes()
            self.assertEqual(struct.unpack_from('<I', data, 4)[0], 150)
            palette = np.frombuffer(data[-1024:], np.uint8).reshape(256, 4)
            master = writer.master_palette()
            for i in range(1, 256):
                np.testing.assert_array_equal(palette[i - 1], master[i])
            np.testing.assert_array_equal(palette[255], master[0])

    def test_exposed_faces_and_normals(self):
        for shape, expected in [((1, 1, 1), 6), ((2, 1, 1), 10), ((2, 2, 2), 24)]:
            a = np.ones(shape, np.uint8)
            faces = list(exporter.exposed_faces(a))
            self.assertEqual(len(faces), expected)
            for _, normal, corners in faces:
                vertices = np.array([exporter.unity_vertex(c, shape) for c in corners])
                cross = np.cross(vertices[1] - vertices[0], vertices[2] - vertices[0])
                transformed = np.array([normal[0], normal[2], normal[1]])
                self.assertGreater(np.dot(cross, transformed), 0)

    def test_axis_scale_and_floor_center(self):
        self.assertEqual(exporter.unity_vertex((0, 0, 0), (32, 16, 32)), (-1, 0, -.5))
        self.assertEqual(exporter.unity_vertex((32, 16, 32), (32, 16, 32)), (1, 2, .5))
        self.assertEqual(exporter.unity_vertex((16, 8, 0), (32, 16, 32)), (0, 0, 0))

    def test_atlas_uv_orientation(self):
        with scratch_directory() as directory:
            exporter.write_atlas(Path(directory))
            atlas = np.array(Image.open(Path(directory) / 'palette_atlas.png'))
            for index, color in enumerate(writer.master_palette()):
                u, v = exporter.palette_uv(index)
                np.testing.assert_array_equal(atlas[int((1 - v) * 128), int(u * 128)], color)

    def test_tile_metadata_and_determinism(self):
        specs = writer.tile_specs()
        self.assertEqual(len(specs), 35)
        self.assertEqual(set(specs), set(json.loads((writer.DEST / 'kit.json').read_text())['tiles']))
        colors = writer.named_colors()
        for tid, meta in specs.items():
            first = writer.build_tile(tid, meta)
            again = writer.build_tile(tid, dict(meta))
            np.testing.assert_array_equal(first, again)
            self.assertGreater(np.count_nonzero(first[:, :, 0]), 0)
            self.assertEqual(set(meta['emissive']), set(np.unique(first)) & {colors[f'emissive_orange_{i}'] for i in range(4)})
        self.assertTrue(specs['door_closed']['blocks_sight'])
        self.assertFalse(specs['barrel']['blocks_sight'])
        self.assertFalse(specs['door_frame_open']['blocks_move'])
        self.assertTrue(specs['floor_water_shallow']['difficult'])
        self.assertEqual(specs['table']['footprint'], [2, 1])
        self.assertEqual(specs['sarcophagus']['footprint'], [2, 1])
        stairs = writer.build_tile('stairs_half_up', specs['stairs_half_up'])
        heights = [np.where(stairs[8, y])[0].max() + 1 for y in range(16)]
        self.assertEqual(heights, [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8])

    def test_written_obj_material_faces(self):
        kit = json.loads((writer.DEST / 'kit.json').read_text())
        for tid, meta in kit['tiles'].items():
            a = exporter.read_vox(writer.DEST / meta['file'])
            expected = {'palette': 0, 'emissive': 0}
            # Independently count occupied-to-empty transitions using padded slices.
            padded = np.pad(a, 1)
            for axis in range(3):
                for delta in (-1, 1):
                    slices = [slice(1, s + 1) for s in a.shape]
                    slices[axis] = slice(1 + delta, a.shape[axis] + 1 + delta)
                    exposed = (a != 0) & (padded[tuple(slices)] == 0)
                    glow = np.isin(a, meta['emissive'])
                    expected['emissive'] += np.count_nonzero(exposed & glow)
                    expected['palette'] += np.count_nonzero(exposed & ~glow)
            actual, group, vertex_count = {'palette': 0, 'emissive': 0}, None, 0
            for line in (writer.DEST / 'obj' / f'{tid}.obj').read_text().splitlines():
                if line.startswith('v '): vertex_count += 1
                if line.startswith('usemtl '): group = line.split()[1]
                if line.startswith('f '):
                    actual[group] += 1
                    corners = [list(map(int, term.split('/'))) for term in line.split()[1:]]
                    self.assertEqual(len(corners), 4)
                    for vertex, uv, normal in corners:
                        self.assertTrue(1 <= vertex <= vertex_count)
                        self.assertTrue(1 <= uv <= 256)
                        self.assertTrue(1 <= normal <= 6)
                    color = corners[0][1] - 1
                    self.assertEqual(group == 'emissive', color in meta['emissive'])
            self.assertEqual(actual, expected, tid)


if __name__ == '__main__':
    unittest.main()
