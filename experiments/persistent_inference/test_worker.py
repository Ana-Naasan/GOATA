"""Run the real worker with CPU-only model and CUDA fakes, never import Torch."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lifecycle import MODEL_NAMES, RESIDENCY_MODES
from worker import run


class FakeOOM(RuntimeError):
    pass


class WorkerTests(unittest.TestCase):
    def check_worker(self, residency, fail_at=None, diagnostic_failure=False, skip_model=None, cleanup_failure=False):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder, ExitStack() as stack:
            root = Path(folder)
            inputs, output = root/'inputs', root/'output'
            inputs.mkdir()
            rows = [dict(index=i, directory=f'segment-{i:02d}', take_id=f'take-{i}', pts_offset_ns=i*10**9,
                         video={}, sidecar={}) for i in range(4)]
            (inputs/'provenance.json').write_text(json.dumps(dict(segments=rows)))
            for row in rows:
                take = inputs/row['directory']
                take.mkdir()
                (take/'sidecar.json').write_text(json.dumps(dict(take_id=row['take_id'])))
            factories = {name: Mock(return_value=object()) for name in MODEL_NAMES}
            error = FakeOOM('CUDA out of memory, activation does not fit')
            if fail_at == 'constructor':
                factories['pose'].side_effect = error
            body = Mock()
            body.cuda.return_value.eval.return_value = factories['body'].return_value
            make_body = Mock(return_value=body)
            cuda = SimpleNamespace(is_available=lambda: True, init=Mock(), synchronize=Mock(),
                                   manual_seed_all=Mock(), mem_get_info=lambda: (1000, 8000),
                                   memory_allocated=lambda: 5500, memory_reserved=lambda: 5600,
                                   max_memory_allocated=lambda: 6000, max_memory_reserved=lambda: 6100,
                                   reset_peak_memory_stats=Mock(), OutOfMemoryError=FakeOOM)
            torch = SimpleNamespace(cuda=cuda, manual_seed=Mock())
            modules = {
                'torch': torch, 'hmr4d': SimpleNamespace(PROJ_ROOT=root),
                'hmr4d.utils.preproc': SimpleNamespace(Tracker=Mock(), Extractor=factories['features'],
                                                      VitPoseExtractor=factories['pose'], SimpleVO=Mock()),
                'hmr4d.model.gvhmr.gvhmr_pl_demo': SimpleNamespace(DemoPL=Mock()),
                'hmr4d.utils.smplx_utils': SimpleNamespace(make_smplx=make_body),
            }
            stack.enter_context(patch.dict(sys.modules, modules))
            stack.enter_context(patch.dict(os.environ))
            stack.enter_context(patch('worker.dependency_identity', return_value={}))
            stack.enter_context(patch('lifecycle.IdentityRecords.get', return_value={}))
            stack.enter_context(patch('buffered.verify'))
            stack.enter_context(patch('models.Detector', factories['detector']))
            stack.enter_context(patch('adapter.load_demo_model', factories['gvhmr']))
            stack.enter_context(patch('models.WorkerModels.residency'))
            moves = stack.enter_context(patch('models.WorkerModels.move'))
            if fail_at == 'transfer' or cleanup_failure:
                def move(name, model, device):
                    if cleanup_failure and device == 'cpu' and (name == 'pose' or fail_at == 'shutdown'):
                        raise ValueError('CPU cleanup failed')
                    if name == 'pose' and fail_at == 'transfer':
                        raise error
                moves.side_effect = move
            if fail_at == 'shutdown':
                def close():
                    cuda.memory_allocated = lambda: 0
                    raise ValueError('shutdown failed')
                stack.enter_context(patch('models.WorkerModels.close', side_effect=close))
            stores = []
            def infer(video, sidecar, output, offset, variant, worker):
                stores.append(worker.store)
                self.assertEqual(variant, '960-15')
                if residency == 'resident':
                    self.assertEqual(worker.store.constructors, dict.fromkeys(MODEL_NAMES, 1))
                for name in ('detector', 'pose', 'features', 'gvhmr', 'body'):
                    if name == skip_model:
                        continue
                    factory = factories[name] if name != 'body' else lambda: make_body('supermotion').cuda().eval()
                    with worker.use(name, factory) as model:
                        self.assertIs(model, factories[name].return_value)
                        if fail_at in ('stage', 'shutdown') and name == 'pose':
                            with worker.metrics.measure('pose'):
                                if diagnostic_failure:
                                    cuda.mem_get_info = Mock(side_effect=RuntimeError('diagnostic unavailable'))
                                raise error
                return dict(counters={}, gpu={})
            inference = stack.enter_context(patch('fast.run', side_effect=infer))
            if skip_model:
                with self.assertRaisesRegex(RuntimeError, 'model use count mismatch'):
                    run(inputs, output, [0, 1, 2, 3], time.monotonic_ns(), residency=residency)
                self.assertFalse((output/'result.json').exists())
                return
            if fail_at:
                with self.assertRaises(FakeOOM) as raised:
                    run(inputs, output, [0, 1, 2, 3], time.monotonic_ns(), residency=residency)
                self.assertIs(raised.exception, error)
                failure = json.loads((output/'failure.json').read_text())
                self.assertFalse((output/'result.json').exists())
                self.assertEqual(failure['residency_mode'], residency)
                self.assertTrue(failure['cuda_oom'])
                self.assertFalse(failure['fallback_applied'])
                self.assertEqual(failure['completed_segments'], [])
                self.assertEqual(failure['failed_stage'], {'constructor': 'constructor_deserialization/pose',
                                                         'transfer': 'transfer_cuda/pose', 'stage': 'pose',
                                                         'shutdown': 'pose'}[fail_at])
                self.assertEqual(failure['error'], str(error))
                self.assertIn('process_gpu_peaks_bytes', failure)
                if diagnostic_failure:
                    self.assertIn('diagnostic unavailable', failure['memory']['diagnostic_error'])
                else:
                    self.assertEqual(failure['memory']['allocated_bytes'], 5500)
                    self.assertEqual(failure['memory']['device_free_bytes'], 1000)
                if residency == 'resident':
                    self.assertTrue(all(call.args[2] == 'cuda' for call in moves.call_args_list))
                if cleanup_failure:
                    self.assertEqual(failure['cleanup_errors'][0], dict(stage='transfer_cpu/pose',
                                     error_type='ValueError', error='CPU cleanup failed'))
                    self.assertEqual(failure['cleanup_errors'][1]['stage'], 'worker_close')
                    self.assertIn('cleanup failed', failure['cleanup_errors'][1]['error'])
                if fail_at == 'shutdown':
                    self.assertEqual(failure['cleanup_errors'], [dict(stage='worker_close',
                                     error_type='ValueError', error='shutdown failed')])
                self.assertTrue(all(factory.call_count <= 1 for factory in factories.values()))
                self.assertEqual(inference.call_count,
                                 1 if residency == 'cpu-offload' or fail_at in ('stage', 'shutdown') else 0)
                return
            report = run(inputs, output, [0, 1, 2, 3], time.monotonic_ns(), residency=residency)
            self.assertEqual(inference.call_count, 4)
            self.assertEqual(report['residency_mode'], residency)
            self.assertEqual(report['lifecycle'], RESIDENCY_MODES[residency])
            self.assertEqual(report['status'], 'complete')
            self.assertEqual(report['segments'][-1]['constructors'], dict.fromkeys(MODEL_NAMES, 1))
            self.assertEqual(report['segments'][-1]['model_uses'], dict.fromkeys(MODEL_NAMES, 4))
            self.assertTrue(all(store is stores[0] for store in stores))
            self.assertEqual(stores[0].models, {})
            for name, factory in factories.items():
                if name != 'body':
                    factory.assert_called_once()
            make_body.assert_called_once_with('supermotion')
            events = [json.loads(line) for line in (output/'metrics.jsonl').read_text().splitlines()]
            if residency == 'resident':
                self.assertEqual(moves.call_count, 5)
                self.assertTrue(all(call.args[2] == 'cuda' for call in moves.call_args_list))
                ready = next(event for event in events if event['event'] == 'resident_ready')
                self.assertIsNone(ready['segment'])
                self.assertEqual(set(ready['models']), MODEL_NAMES)
            else:
                self.assertEqual(sum(call.args[2] == 'cuda' for call in moves.call_args_list), 20)
                self.assertGreaterEqual(sum(call.args[2] == 'cpu' for call in moves.call_args_list), 20)
                self.assertNotIn('resident_ready', [event['event'] for event in events])

    def test_all_five_resident_before_first_segment_and_retained_for_four_takes(self):
        self.check_worker('resident')

    def test_cpu_offload_remains_separate_and_lazy(self):
        self.check_worker('cpu-offload')

    def test_resident_oom_is_diagnostic_and_stops_without_fallback(self):
        for stage in ('constructor', 'transfer', 'stage'):
            with self.subTest(stage=stage):
                self.check_worker('resident', fail_at=stage)

    def test_preload_does_not_hide_a_model_missing_from_stage_use_counts(self):
        self.check_worker('resident', skip_model='body')

    def test_cpu_offload_and_worker_cleanup_keep_primary_oom_and_stage(self):
        for origin in ('stage', 'transfer'):
            with self.subTest(origin=origin):
                self.check_worker('cpu-offload', fail_at=origin, cleanup_failure=True)

    def test_worker_shutdown_failure_cannot_replace_primary_oom(self):
        self.check_worker('cpu-offload', fail_at='shutdown')

    def test_diagnostic_failure_does_not_mask_original_oom(self):
        self.check_worker('resident', fail_at='stage', diagnostic_failure=True)


if __name__ == '__main__':
    unittest.main()
