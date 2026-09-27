"""CPU-only lifecycle checks. No upstream imports, assets or CUDA needed."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lifecycle import RetainedModels, reset_detector, IdentityRecords, Counters, validate_segment
from fast import sampling, scatter


class LifecycleTests(unittest.TestCase):
    def test_predictor_reset_preserves_weights_and_callbacks(self):
        cap, writer, track = Mock(), Mock(), Mock()
        weights = object()
        baseline = {'on_predict_start': [object()]}
        detector = SimpleNamespace(model=weights, callbacks={'on_predict_start': [1, 2]},
            predictor=SimpleNamespace(dataset=SimpleNamespace(cap=cap), vid_writer={'x': writer}, trackers=[track]))
        reset_detector(detector, baseline)
        self.assertIs(detector.model, weights)
        self.assertIsNone(detector.predictor)
        cap.release.assert_called_once()
        writer.release.assert_called_once()
        track.reset.assert_called_once()
        self.assertEqual(detector.callbacks, baseline)
        detector.callbacks['on_predict_start'].append(3)
        reset_detector(detector, baseline)
        self.assertEqual(len(detector.callbacks['on_predict_start']), 1)
        self.assertEqual(len(baseline['on_predict_start']), 1)

    def test_retain_only_models_and_offload_each_use(self):
        moves = []
        model = object()
        factory = Mock(return_value=model)
        store = RetainedModels(lambda name, obj, device: moves.append((name, obj, device)), residency='cpu-offload')
        for _ in range(2):
            with store.use('pose', factory) as result:
                self.assertIs(result, model)
        factory.assert_called_once()
        self.assertEqual([x[2] for x in moves], ['cuda', 'cpu', 'cuda', 'cpu'])
        self.assertIsNone(store.active)
        self.assertEqual(store.constructors, {'pose': 1})
        self.assertEqual(store.uses, {'pose': 2})

    def test_failure_offloads_and_poison_prevents_reuse(self):
        moves = []
        store = RetainedModels(lambda n, o, d: moves.append(d), residency='cpu-offload')
        with self.assertRaisesRegex(ValueError, 'bad input'):
            with store.use('pose', object):
                raise ValueError('bad input')
        self.assertEqual(moves[-1], 'cpu')
        with self.assertRaises(RuntimeError):
            with store.use('pose', object):
                pass
        self.assertIsNone(store.active)

    def test_transfer_failures_poison_and_release_active_slot(self):
        for failed_device in ('cuda', 'cpu'):
            moves = []
            def move(name, obj, device):
                moves.append(device)
                if device == failed_device:
                    raise RuntimeError('transfer failed')
            store = RetainedModels(move, residency='cpu-offload')
            with self.assertRaises(RuntimeError):
                with store.use('pose', object):
                    pass
            self.assertTrue(store.failed)
            self.assertIsNone(store.active)
            self.assertEqual(moves,['cuda','cpu'])

    def test_offload_cleanup_cannot_replace_inference_or_activation_oom(self):
        for origin in ('stage', 'transfer'):
            with self.subTest(origin=origin):
                error = RuntimeError('CUDA out of memory')
                def move(name, obj, device):
                    if device == 'cpu':
                        raise ValueError('CPU cleanup failed')
                    if origin == 'transfer':
                        raise error
                store = RetainedModels(move, residency='cpu-offload')
                with self.assertRaises(RuntimeError) as raised:
                    with store.use('pose', object):
                        raise error
                self.assertIs(raised.exception, error)
                self.assertEqual(error.cleanup_errors, [dict(stage='transfer_cpu/pose',
                    error_type='ValueError', error='CPU cleanup failed')])
                self.assertTrue(store.failed)
                self.assertIsNone(store.active)
                with self.assertRaises(RuntimeError):
                    with store.use('pose', object):
                        pass

    def test_no_nested_stages_or_unbounded_models(self):
        store = RetainedModels(lambda *args: None, residency='cpu-offload')
        with store.use('pose', object):
            with self.assertRaises(RuntimeError):
                with store.use('features', object):
                    pass
        with self.assertRaises(ValueError):
            with store.use('arbitrary', object):
                pass

    def test_assets_hashed_once_and_no_prediction_cache(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            (root/'weights').write_bytes(b'weights')
            hash_file = Mock(return_value='digest')
            records = IdentityRecords(root, ('weights',), hash_file)
            self.assertEqual(records.get(), {'weights': 'digest'})
            self.assertEqual(records.get(), {'weights': 'digest'})
            hash_file.assert_called_once()
            records.get()['weights'] = 'mutated'
            self.assertEqual(records.get()['weights'], 'digest')
            self.assertEqual(records.hash_calls, 1)

    def test_missing_assets_fail(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            with self.assertRaises(ValueError):
                IdentityRecords(Path(folder), ('absent',), Mock()).get()

    def test_counts_do_not_leak_between_segments(self):
        counts = Counters()
        for key, value in dict(detection_frames=30, pose_frames=30, feature_frames=30,
                               scatter_frames=60, export_frames=60, pose_calls=15, feature_calls=15,
                               gvhmr_calls=1, vo_sample_frames=9).items():
            counts.add(key, value)
        self.assertEqual(counts.finish(30, 60)['detection_frames'], 30)
        with self.assertRaises(ValueError):
            counts.finish(30, 60)
        counts.add('detection_frames', 31)
        with self.assertRaises(ValueError):
            counts.finish(30, 60)

    def test_failed_constructor_is_not_retried(self):
        store = RetainedModels(lambda *args: None, residency='cpu-offload')
        factory = Mock(side_effect=ValueError('constructor'))
        with self.assertRaises(ValueError):
            with store.use('pose', factory):
                pass
        self.assertEqual(store.models, {})
        self.assertIsNone(store.active)
        with self.assertRaises(RuntimeError):
            with store.use('pose', factory):
                pass
        factory.assert_called_once()

    def test_worker_input_binding_rejects_duplicate_takes_and_escape(self):
        from worker import validate_rows
        row = {'index': 0, 'directory': 'segment-00', 'take_id': 'take', 'pts_offset_ns': 0}
        validate_rows([row])
        with self.assertRaises(ValueError):
            validate_rows([row, row])
        for directory in ('../outside', '/absolute', 'segment-00/x'):
            with self.assertRaises(ValueError):
                validate_rows([dict(row, directory=directory)])

    def test_metrics_capture_failure_and_host_rss(self):
        from metrics import Metrics
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            metrics = Metrics(Path(folder)/'events.jsonl')
            with self.assertRaises(ValueError):
                with metrics.measure('bad-stage'):
                    raise ValueError('bad')
            self.assertFalse(metrics.events[0]['ok'])
            self.assertGreater(metrics.events[0]['after']['peak_rss_bytes'], 0)

    def test_gpu_metrics_deltas_and_process_peaks_with_fake_cuda(self):
        from metrics import Metrics
        state = dict(allocated=100, reserved=200, peak_allocated=100, peak_reserved=200)
        def reset():
            state.update(peak_allocated=state['allocated'], peak_reserved=state['reserved'])
        cuda = SimpleNamespace(synchronize=Mock(), mem_get_info=lambda: (1000,2000),
                               reset_peak_memory_stats=reset,
                               memory_allocated=lambda: state['allocated'],
                               memory_reserved=lambda: state['reserved'],
                               max_memory_allocated=lambda: state['peak_allocated'],
                               max_memory_reserved=lambda: state['peak_reserved'])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            metrics = Metrics(Path(folder)/'metrics.jsonl', SimpleNamespace(cuda=cuda))
            with metrics.measure('constructor'):
                state.update(allocated=300,reserved=500,peak_allocated=400,peak_reserved=600)
            with metrics.measure('no-op'):
                pass
            self.assertEqual(metrics.events[0]['allocated_delta_bytes'],200)
            self.assertEqual(metrics.events[0]['reserved_delta_bytes'],300)
            self.assertEqual(metrics.events[1]['peak_allocated_bytes'],300)
            self.assertEqual(metrics.peaks,dict(allocated=400,reserved=600))

    def test_bounds(self):
        validate_segment({'width': 960, 'height': 540, 'selected_indices': list(range(60)),
                          'sampling': {'observation_indices': list(range(30))}})
        for n in (0, 1, 64, 601):
            with self.assertRaises(ValueError):
                validate_segment({'width': 960, 'height': 540, 'selected_indices': list(range(n)),
                                  'sampling': {'observation_indices': list(range(30))}})

    def test_causal_observation_scatter_preserves_ids_pts(self):
        frames = [{'frame_id': 100+i, 'pts_ns': str(10**12 + round(i*10**9/30)), 'image_valid': True}
                  for i in range(60)]
        result = sampling(frames, 15, 60)
        self.assertEqual(len(result['observation_indices']), 30)
        self.assertEqual(result['observations'], [frames[i] for i in result['observation_indices']])
        from fractions import Fraction
        for i, j in enumerate(result['grid_to_observation']):
            self.assertLessEqual(int(result['observations'][j]['pts_ns'])-10**12, Fraction(i*10**9,30)+1)
        self.assertEqual(len(scatter(result['observations'], result['grid_to_observation'])), 60)
        with self.assertRaises(ValueError):
            scatter([1], [-1])


if __name__ == '__main__':
    unittest.main()
