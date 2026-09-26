"""CPU-only synthetic parameter fixtures, not inference results."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from processing.reconstruction.native import prepare, load_json, main, MAX_JSON_BYTES, MAX_FRAMES


def fixture():
    params = {key: [[i + 0.25] * width for i in range(3)]
              for key, width in [('body_pose', 63), ('betas', 10),
                                 ('global_orient', 3), ('transl', 3)]}
    return {
        'take_id': 'synthetic-take',
        'frames': [{'frame_id': 8, 'pts_ns': '90071992547409930', 'image_valid': False},
                   {'frame_id': 12, 'pts_ns': '90071992567409930', 'image_valid': True},
                   {'frame_id': 20, 'pts_ns': '90071992637409930', 'image_valid': True}],
        'selected_indices': [1, 1, 2],
        'prediction': {'smpl_params_global': params,
                       'smpl_params_incam': deepcopy(params),
                       'K_fullimg': [[[500, 0, 320], [0, 500, 240], [0, 0, 1]] for _ in range(3)]}}


class NativeTests(unittest.TestCase):
    def test_preserves_parameters_and_source_provenance(self):
        data = fixture()
        original = deepcopy(data)
        result = prepare(data)
        self.assertEqual(result['parameters'], data['prediction'])
        self.assertEqual([r['source_frame_id'] for r in result['frame_mapping']], [12, 12, 20])
        self.assertEqual(result['frame_mapping'][0]['source_time_s'], 0.02)
        self.assertEqual(result['source_frames'], data['frames'])
        self.assertEqual(result['take_id'], data['take_id'])
        self.assertEqual(data, original)
        result['parameters']['smpl_params_global']['transl'][0][0] = 99
        self.assertEqual(data, original)
        self.assertFalse(result['geometry_available'])

    def test_rejects_bad_parameters(self):
        for space in ('smpl_params_global', 'smpl_params_incam'):
            for field in ('body_pose', 'betas', 'global_orient', 'transl'):
                for value in (None, [], [[0]], [[[0]]], [[0] * 72] * 3):
                    data = fixture()
                    data['prediction'][space][field] = value
                    with self.subTest(space=space, field=field, value=value):
                        with self.assertRaises(ValueError):
                            prepare(data)
                for value in (True, '1', None, float('nan'), float('inf'), 10**400):
                    data = fixture()
                    data['prediction'][space][field][0][0] = value
                    with self.assertRaises(ValueError):
                        prepare(data)
                data = fixture()
                del data['prediction'][space][field]
                with self.assertRaises(ValueError):
                    prepare(data)

    def test_invalid_metadata_intrinsics_and_counts(self):
        for key, value in [('take_id', ''), ('take_id', None), ('frames', []),
                           ('selected_indices', [0, 1, 2]), ('selected_indices', [1, 2]),
                           ('prediction', {}), ('prediction', None)]:
            data = fixture()
            data[key] = value
            with self.assertRaises(ValueError):
                prepare(data)
        for matrix in ([], [[0]*3]*3, [[500, 0, 0], [0, -1, 0], [0, 0, 1]],
                       [[500, 0, 0], [0, 500, 0], [0, 1, 1]]):
            data = fixture()
            data['prediction']['K_fullimg'][0] = matrix
            with self.assertRaises(ValueError):
                prepare(data)
        for data in (None, [], dict(fixture(), unknown=1)):
            with self.assertRaises(ValueError):
                prepare(data)

    def test_native_camera_structure(self):
        matrices = [
            [[500, 500, 320], [500, 500, 240], [0, 0, 1]],
            [[500, 1, 320], [0, 500, 240], [0, 0, 1]],
            [[500, 0, 320], [1, 500, 240], [0, 0, 1]],
            [[500, 0, 320], [0, 501, 240], [0, 0, 1]],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            for matrix in matrices:
                data = fixture()
                data['prediction']['K_fullimg'][0] = matrix
                with self.subTest(matrix=matrix):
                    with self.assertRaises(ValueError):
                        prepare(data)
                    path.write_text(json.dumps(data))
                    run = subprocess.run(
                        [sys.executable, '-B', '-m', 'processing.reconstruction.native', str(path)],
                        capture_output=True, text=True)
                    self.assertEqual(run.returncode, 1)
                    self.assertEqual(run.stdout, '')
                    self.assertNotIn('Traceback', run.stderr)

    def test_rejects_extra_frame_metadata_in_python_api(self):
        for index in (0, 1):  # Rejected and selected source frames.
            for value in ({'nested': [float('inf')]}, object(), {1, 2}, 'unknown'):
                data = fixture()
                data['frames'][index]['extra'] = value
                with self.subTest(index=index, value=value):
                    with self.assertRaises(ValueError):
                        prepare(data)

    def test_frame_count_ceilings(self):
        data = fixture()
        data['frames'] = [dict(frame_id=i, pts_ns=str(i), image_valid=True)
                          for i in range(MAX_FRAMES)]
        self.assertEqual(len(prepare(data)['source_frames']), MAX_FRAMES)
        data['frames'].append(dict(frame_id=MAX_FRAMES, pts_ns=str(MAX_FRAMES), image_valid=True))
        with self.assertRaises(ValueError):
            prepare(data)
        data = fixture()
        data['selected_indices'] = [1] * MAX_FRAMES
        for params in ('smpl_params_global', 'smpl_params_incam'):
            for key, rows in data['prediction'][params].items():
                data['prediction'][params][key] = [rows[0]] * MAX_FRAMES
        data['prediction']['K_fullimg'] = [data['prediction']['K_fullimg'][0]] * MAX_FRAMES
        self.assertEqual(len(prepare(data)['frame_mapping']), MAX_FRAMES)
        data['selected_indices'].append(1)
        with self.assertRaises(ValueError):
            prepare(data)

    def test_strict_output_roundtrip(self):
        data = fixture()
        data['frames'][0]['pts_ns'] = '090071992547409930'
        result = prepare(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'output.json'
            path.write_text(json.dumps(result, allow_nan=False))
            self.assertEqual(load_json(path), result)
        self.assertEqual(result['source_frames'], data['frames'])
        self.assertEqual(result['selected_indices'], [1, 1, 2])
        self.assertEqual([r['source_pts_ns'] for r in result['frame_mapping']],
                         [data['frames'][i]['pts_ns'] for i in [1, 1, 2]])
        self.assertEqual(result['parameters'], data['prediction'])

    def test_json_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'\x80pickle',
                        b'{"a":[{"nested":1,"nested":2}]}',
                        b'{"a":1e999}', b'{"a":[-1e999]}',
                        b'[' * 1100, b' ' * (MAX_JSON_BYTES + 1)):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    load_json(path)

    def test_main_success_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_text(json.dumps(fixture()))
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(main([str(path)]), 0)
            self.assertEqual(json.loads(output.getvalue())['take_id'], 'synthetic-take')
            path.unlink()
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(main([str(path)]), 1)
            self.assertEqual(output.getvalue(), '')
            self.assertIn('Preparation failed', errors.getvalue())

    def test_cli_runs_whole_slice_and_fails_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_text(json.dumps(fixture()))
            command = [sys.executable, '-m', 'processing.reconstruction.native', str(path)]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['parameters'], fixture()['prediction'])
            path.write_text('{}')
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(run.stdout, '')
            self.assertNotIn('Traceback', run.stderr)
