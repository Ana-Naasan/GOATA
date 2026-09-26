import contextlib
from fractions import Fraction
import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from processing.reconstruction import runtime


def sidecar():
    return {
        'schema_version': '1.0', 'take_id': '01234567-89ab-cdef-0123-456789abcdef',
        'adapter': {'name': 'fixture', 'version': '1'},
        'image': {'width_px': 640, 'height_px': 480, 'rotation_degrees': 0, 'mirrored': False},
        'camera': {'id': 'test', 'calibration_status': 'calibrated',
                   'intrinsics': {'fx': 500, 'fy': 500, 'cx': 301, 'cy': 230},
                   'distortion_model': 'none', 'distortion_coefficients': []},
        'clock': {'id': 'test', 'unit': 'nanoseconds', 'origin_pts_ns': '1000000000'},
        'capture': {'view': 'front', 'condition': 'exercise', 'side': 'bilateral', 'interrupted': False},
        'frames': [{'frame_id': i * 2, 'pts_ns': str(1000000000 + round(Fraction(i, 30) * 10**9)),
                    'image_valid': True} for i in range(8)],
    }


class RuntimeTests(unittest.TestCase):
    def test_plan_preserves_irregular_source_and_repeats(self):
        doc = sidecar()
        doc['frames'][2]['pts_ns'] = '1070000000'
        plan = runtime.plan_input(doc)
        self.assertEqual(plan['selected_indices'], list(range(8)))
        self.assertEqual(plan['frame_mapping'][2]['source_pts_ns'], '1070000000')
        self.assertEqual(plan['K'][0][2], 301)
        doc['frames'] = doc['frames'][::2]
        plan = runtime.plan_input(doc)
        self.assertGreater(len(plan['selected_indices']), len(set(plan['selected_indices'])))

    def test_hash_works_on_python310_fallback(self):
        import hashlib
        self.assertEqual(runtime._hash(io.BytesIO(b'content')), hashlib.sha256(b'content').hexdigest())

    def test_other_input_limits(self):
        for section, key, value in [(None, 'schema_version', '2.0'), (None, 'take_id', 3),
                                    ('clock', 'unit', 'seconds'), ('clock', 'origin_pts_ns', 'NaN'),
                                    ('camera', 'distortion_model', 'fisheye')]:
            doc = sidecar()
            target = doc if section is None else doc[section]
            target[key] = value
            with self.assertRaises(ValueError):
                runtime.plan_input(doc)
        doc = sidecar()
        doc['camera']['intrinsics']['skew'] = 0
        with self.assertRaises(ValueError):
            runtime.plan_input(doc)
        doc = sidecar()
        doc['frames'] = [{'frame_id': i, 'pts_ns': str(i * 50_000_000), 'image_valid': True} for i in range(500)]
        with self.assertRaisesRegex(ValueError, '600'):
            runtime.plan_input(doc)

    def test_invalid_and_gaps_fail_instead_of_concatenating(self):
        for change in ('invalid', 'gap', 'interruption', 'explicit_gap'):
            doc = sidecar()
            if change == 'invalid':
                doc['frames'][3]['image_valid'] = False
            elif change == 'gap':
                for frame in doc['frames'][4:]:
                    frame['pts_ns'] = str(int(frame['pts_ns']) + 500000000)
            elif change == 'interruption':
                doc['capture']['interrupted'] = True
            else:
                doc['capture']['gaps'] = [{'start_s': 0, 'end_s': 1}]
            with self.subTest(change=change), self.assertRaises(ValueError):
                runtime.plan_input(doc)

    def test_malformed_sidecar_structure(self):
        for doc in ([], {}, {'schema_version': '1.0'}, dict(sidecar(), image=None),
                    dict(sidecar(), frames='bad'), dict(sidecar(), camera=[]),
                    dict(sidecar(), adapter={'name': '', 'version': '1'})):
            with self.subTest(doc=doc), self.assertRaises(ValueError):
                runtime.plan_input(doc)

    def test_supported_camera_subset_explicit(self):
        for field, value in [('fx', 0), ('fy', 501), ('fx', float('inf'))]:
            doc = sidecar()
            doc['camera']['intrinsics'][field] = value
            with self.assertRaises(ValueError):
                runtime.plan_input(doc)
        doc = sidecar()
        doc['camera']['calibration_status'] = 'unavailable'
        del doc['camera']['intrinsics']
        with self.assertRaises(ValueError):
            runtime.plan_input(doc)
        plan = runtime.plan_input(doc, allow_estimated_intrinsics=True)
        self.assertEqual(plan['intrinsics_status'], 'estimated')
        for key, value in [('mirrored', True), ('rotation_degrees', 90), ('width_px', 10000)]:
            doc = sidecar()
            doc['image'][key] = value
            with self.assertRaises(ValueError):
                runtime.plan_input(doc)

    def test_pts_binding_not_count_equality(self):
        frames = sidecar()['frames']
        decoded = [(i, Fraction(i, 30)) for i in range(8)]
        self.assertEqual(runtime.bind_pts(frames, decoded, 1000000000), list(range(8)))
        with self.assertRaises(ValueError):
            runtime.bind_pts(frames, decoded, 0)
        with self.assertRaises(ValueError):
            runtime.bind_pts(frames, decoded[:-1], 1000000000)
        with self.assertRaises(ValueError):
            runtime.bind_pts(frames, decoded + [(8, Fraction(7, 30))], 1000000000)

    def test_missing_tracks_are_not_zero_observations(self):
        good = [[{'id': 7, 'bbx_xyxy': [1, 2, 30, 40]}] for _ in range(8)]
        self.assertEqual(runtime.select_track(good), [[1, 2, 30, 40]] * 8)
        for bad in ([], [[{'id': 7, 'bbx_xyxy': [5, 2, 1, 4]}]],
                    good[:3] + [[]] + good[4:], good[:3] + [[{'id': 8, 'bbx_xyxy': [1, 2, 30, 40]}]] + good[4:]):
            with self.assertRaises(ValueError):
                runtime.select_track(bad)

    def test_geometry_metadata_and_malformed_arrays(self):
        metadata = runtime.geometry_metadata(['pelvis', 'left_hip'], [-1, 0], 3, 1)
        self.assertEqual(metadata['scale_status'], 'estimated')
        self.assertEqual(metadata['coordinate_system'], 'gvhmr_global_ay')
        self.assertFalse(metadata['unity_conversion_applied'])
        for parents in ([-1, 1], [-1], [0, 0]):
            with self.assertRaises(ValueError):
                runtime.geometry_metadata(['pelvis', 'left_hip'], parents, 3, 1)
        runtime.validate_rows([[1, 2, 3]], 1, 3)
        for rows in ([[1, 2]], [[1, float('nan'), 3]], [[True, 2, 3]]):
            with self.assertRaises(ValueError):
                runtime.validate_rows(rows, 1, 3)

    def test_cli_missing_files_and_failure_leave_no_success(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result'
            with contextlib.redirect_stderr(io.StringIO()):
                result = runtime.main(['--video', '/missing.mp4', '--sidecar', '/missing.json',
                                       '--output', str(output), '--pts-offset-ns', '0'])
            self.assertEqual(result, 1)
            self.assertFalse((output / 'handoff.json').exists())

    def test_camera_motion_failure_keeps_source_but_no_completion_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, metadata = root / 'clip.mp4', root / 'clip.json'
            video.write_bytes(b'fixture, not media')
            runtime.write_json(metadata, sidecar())
            output = root / 'result'
            stderr = io.StringIO()
            with patch.object(runtime, 'prepare_video'), \
                 patch.object(runtime, 'infer', side_effect=ValueError('Camera motion unavailable: no relative pose')), \
                 contextlib.redirect_stderr(stderr):
                result = runtime.main(['--video', str(video), '--sidecar', str(metadata),
                                       '--output', str(output), '--pts-offset-ns', '1000000000'])
            self.assertEqual(result, 1)
            self.assertIn('Camera motion unavailable', stderr.getvalue())
            self.assertTrue((output / 'source-sidecar.json').is_file())
            self.assertTrue((output / 'selection.json').is_file())
            self.assertFalse((output / 'handoff.json').exists())
            self.assertFalse((output / 'handoff.partial.json').exists())
            self.assertEqual(video.read_bytes(), b'fixture, not media')

    def test_mutated_source_fails_before_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, metadata = root / 'clip.mp4', root / 'clip.json'
            video.write_bytes(b'initial')
            runtime.write_json(metadata, sidecar())
            with patch.object(runtime, 'prepare_video', side_effect=lambda *args: video.write_bytes(b'changed')), \
                 patch.object(runtime, 'infer') as infer:
                with self.assertRaisesRegex(ValueError, 'changed'):
                    runtime.run(video, metadata, root / 'out', 0, False)
                infer.assert_not_called()
            self.assertFalse((root / 'out/handoff.json').exists())

    def test_orchestration_completion_marker_is_last(self):
        # Control-flow test only. No media decoding or model success is claimed.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, metadata = root / 'clip.mp4', root / 'clip.json'
            video.write_bytes(b'not media')
            runtime.write_json(metadata, sidecar())
            output = root / 'result'
            with patch.object(runtime, 'prepare_video'), patch.object(runtime, 'infer', return_value={}):
                runtime.run(video, metadata, output, 1000000000, False)
            handoff = runtime.load_json(output / 'handoff.json')
            self.assertEqual(handoff['take_id'], sidecar()['take_id'])
            self.assertEqual(handoff['source_video_sha256'], runtime.digest(video))
            self.assertEqual(handoff['validation_status'], 'research_demo_unvalidated')
            self.assertFalse((output / 'handoff.partial.json').exists())
            with patch.object(runtime, 'run'), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runtime.main(['--video', str(video), '--sidecar', str(metadata),
                                               '--output', str(output), '--pts-offset-ns', '0']), 0)

    def test_orchestration_passes_plan_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / 'test.mp4'
            video.write_bytes(b'fixture, not media')
            output = root / 'result'
            runtime.write_json(root / 'test.json', sidecar())
            with patch.object(runtime, 'load_json', return_value=sidecar()), \
                 patch.object(runtime, 'prepare_video') as prepare, \
                 patch.object(runtime, 'infer', side_effect=RuntimeError('GPU unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'GPU unavailable'):
                    runtime.run(video, root / 'test.json', output, 1000000000, False)
                self.assertTrue(prepare.called)
                self.assertTrue((output / 'selection.json').exists())
                self.assertFalse((output / 'handoff.json').exists())
                with self.assertRaises(FileExistsError):
                    runtime.run(video, root / 'test.json', output, 0, False)


if __name__ == '__main__':
    unittest.main()
