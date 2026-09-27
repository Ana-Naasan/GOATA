"""CPU integration with real source validators and simulated media/model boundaries."""
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import fast
from lifecycle import Counters


def sidecar(count=60):
    return dict(schema_version='1.0', take_id=str(uuid4()),
                adapter=dict(name='test', version='1'),
                image=dict(width_px=1920, height_px=1080, rotation_degrees=0, mirrored=False),
                camera=dict(id='test', calibration_status='calibrated', distortion_model='none',
                            distortion_coefficients=[], intrinsics=dict(fx=1321., fy=1321., cx=960., cy=540.)),
                clock=dict(id='test', unit='nanoseconds', origin_pts_ns='1000000000000'),
                capture=dict(view='other', condition='exercise', side='not_applicable', interrupted=False),
                frames=[dict(frame_id=100+i, pts_ns=str(10**12+round(Fraction(i*10**9,30))), image_valid=True)
                        for i in range(count)])


class FakeFrame:
    def __init__(self, pts, width=1920, height=1080):
        self.pts, self.width, self.height = pts, width, height
        self.time_base = Fraction(1,30)
        self.side_data = []
    def to_ndarray(self, format):
        return self.pts


class FakeContainer:
    def __init__(self, frames):
        self.frames = frames
        self.streams = SimpleNamespace(video=[SimpleNamespace(metadata={}, average_rate=30)])
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def decode(self, *args, **kwargs):
        return iter(self.frames)


class PipelineTests(unittest.TestCase):
    def test_preparation_two_inputs_no_prediction_reuse(self):
        from processing.reconstruction.runtime import write_json
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            root = Path(name)
            video = root/'source.mp4'
            video.write_bytes(b'simulated media')
            doc = sidecar()
            write_json(root/'source.json', doc)
            videos = {str(video): [FakeFrame(i) for i in range(60)]}
            def writer(path, width, height, **kwargs):
                path.write_bytes(b'simulated encoded media')
                videos[str(path)] = []
                return path, (width, height)
            def encode(path, shape, image, pts, base):
                self.assertEqual(base, Fraction(1,30))
                videos[str(path)].append(FakeFrame(pts, *shape))
            fake_av = SimpleNamespace(open=lambda path: FakeContainer(videos[str(path)]))
            fake_cv = SimpleNamespace(resize=lambda image, size, interpolation: image, INTER_AREA=1)
            calls = []
            def infer(video, plan, output, worker):
                calls.append(plan)
                self.assertEqual((plan['width'], plan['height']), (960,540))
                self.assertEqual(plan['K'], [[660.5,0,480.],[0,660.5,270.],[0,0,1]])
                self.assertEqual(plan['vo_source_indices'], list(range(60)))
                self.assertEqual(len(plan['sampling']['observation_indices']), 30)
                self.assertEqual(plan['source_frames'], doc['frames'])
                for i, row in enumerate(plan['frame_mapping']):
                    self.assertEqual(row['source_frame_id'], doc['frames'][plan['selected_indices'][i]]['frame_id'])
                return {'counters': {'detection_frames': 30}}
            worker = SimpleNamespace(metrics=SimpleNamespace(emit=Mock()), store=SimpleNamespace(residency='resident'))
            with patch.dict(sys.modules, {'av': fake_av, 'cv2': fake_cv}), \
                 patch('buffered.writer', writer), patch('buffered.encode', encode), \
                 patch('buffered.close_writer'), patch('adapter.infer_native', side_effect=infer):
                first_result = fast.run(video, root/'source.json', root/'one', 10**12, '960-15', worker)
                self.assertEqual(first_result['residency_mode'], 'resident')
                self.assertIn('GPU-resident', first_result['model_cache'])
                first = calls[0]['take_id']
                doc['take_id'] = str(uuid4())
                write_json(root/'source.json', doc)
                worker.store.residency = 'cpu-offload'
                second_result = fast.run(video, root/'source.json', root/'two', 10**12, '960-15', worker)
                self.assertEqual(second_result['residency_mode'], 'cpu-offload')
                self.assertIn('CPU-retained', second_result['model_cache'])
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(first, calls[1]['take_id'])
            self.assertIsNot(calls[0], calls[1])
            self.assertEqual(len(videos[str(root/'one'/'observations.mp4')]), 30)
            self.assertEqual(len(videos[str(root/'two'/'inference.mp4')]), 60)

    def test_four_segment_split_preserves_original_ids_pts_and_take_origins(self):
        from buffered import split
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            video, calibration = root/'source.mp4', root/'calib.txt'
            video.write_bytes(b'simulated original')
            calibration.write_text('1321 1321 960 540')
            output = root/'split'
            output.mkdir()
            videos = {str(video): [FakeFrame(i) for i in range(241)]}
            def writer(path, width, height, *args):
                path.write_bytes(b'encoded')
                videos[str(path)] = []
                return path, (width,height)
            def encode(path, shape, image, pts, base):
                videos[str(path)].append(FakeFrame(pts,*shape))
            fake_av = SimpleNamespace(open=lambda path: FakeContainer(videos[str(path)]))
            with patch.dict(sys.modules, {'av':fake_av}), patch('buffered.writer',writer), \
                 patch('buffered.encode',encode), patch('buffered.close_writer'):
                rows = split(SimpleNamespace(video=video, calibration=calibration, output=output,
                                             segment_s=2, segments=4))
            self.assertEqual(len(rows),4)
            self.assertEqual(len({row['take_id'] for row in rows}),4)
            for i, row in enumerate(rows):
                doc = json.loads((output/row['directory']/'sidecar.json').read_text())
                self.assertEqual([f['frame_id'] for f in doc['frames']], list(range(i*60,(i+1)*60)))
                self.assertEqual(doc['clock']['origin_pts_ns'], str(i*2*10**9))
                self.assertEqual(doc['original_origin_seconds'],'0')
                self.assertEqual(doc['frames'][-1]['pts_ns'], str(round(Fraction(((i+1)*60-1)*10**9,30))))
                self.assertEqual(row['source_end_s'],(i+1)*2)

    def test_source_pts_binding_strict_identity_and_calibration(self):
        from processing.reconstruction.runtime import plan_input, bind_pts, select_track
        doc = sidecar()
        plan = plan_input(doc)
        self.assertEqual(len(plan['selected_indices']), 60)
        bind_pts(doc['frames'], [(i,Fraction(i,30)) for i in range(60)], 10**12)
        with self.assertRaises(ValueError):
            bind_pts(doc['frames'], [(i,Fraction(i+1,30)) for i in range(60)], 10**12)
        person = {'id': 1, 'bbx_xyxy': [0,0,10,10]}
        for history in ([[]], [[person,person]], [[person],[dict(person,id=2)]]):
            with self.assertRaises(ValueError):
                select_track(history)
        doc['camera']['intrinsics']['fx'] = 0
        with self.assertRaises(ValueError):
            plan_input(doc)

    def test_irregular_mapping_never_uses_future_sample(self):
        times = [0, 20, 73, 94, 134, 167, 199, 241, 267, 300]
        frames = [dict(frame_id=50+i, pts_ns=str(t*10**6), image_valid=True) for i,t in enumerate(times)]
        sample = fast.sampling(frames,15,10)
        for i, selected in enumerate(sample['grid_to_observation']):
            self.assertLessEqual(int(sample['observations'][selected]['pts_ns']), round(Fraction(i*10**9,30)))
        frames[4]['image_valid'] = False
        with self.assertRaises(ValueError):
            fast.sampling(frames,15,10)

    def test_pose_feature_and_export_counters_reject_mismatch(self):
        for key, count in [('pose_frames',29),('feature_frames',31),('export_frames',59),('scatter_frames',61)]:
            counts = Counters()
            counts.add('detection_frames',30)
            counts.add(key,count)
            with self.assertRaises(ValueError):
                counts.finish(30,60)

    def test_watchdog_failure_timeout_and_output_bounds(self):
        import buffered
        import subprocess
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            root = Path(name)
            with self.assertRaises(subprocess.CalledProcessError):
                buffered.supervise([sys.executable,'-c','raise SystemExit(3)'],root,2)
            with self.assertRaises(TimeoutError):
                buffered.supervise([sys.executable,'-c','import time; time.sleep(10)'],root,.1)
            (root/'oversized').write_bytes(b'12345')
            with patch.object(buffered,'MAX_FILE_BYTES',4):
                with self.assertRaises(ValueError):
                    buffered.check_output(root)
            with patch.object(buffered,'MAX_OUTPUT_BYTES',4):
                with self.assertRaises(ValueError):
                    buffered.check_output(root)


if __name__ == '__main__':
    unittest.main()
