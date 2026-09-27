"""Pinned lifecycle and precision controls. CUDA checks skip without real Torch/CUDA."""

import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from processing.reconstruction import gvhmr, resident, resident_models


class FakePredictor:
    def __init__(self, backend, setups, **kwargs):
        self.args = SimpleNamespace(half=None)
        self.backend = backend
        self.setups = setups
        self.callbacks = kwargs['_callbacks']

    def setup_model(self, **kwargs):
        self.setups.append(kwargs)
        self.model = self.backend


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.video = Path(self.temp.name) / 'prepared.mp4'
        self.video.write_bytes(b'control')
        self.backend = SimpleNamespace(device='cuda', fp16=False)
        self.setups, self.predictors, self.closed = [], [], []
        self.callback = object()
        self.yolo = SimpleNamespace(predictor=None, overrides={}, model=object(),
                                    callbacks={'start': [self.callback]})
        self.yolo._smart_load = Mock(return_value=self.predictor)
        self.yolo.track = self.track
        self.factory = Mock(return_value=SimpleNamespace(yolo=self.yolo))
        with patch.dict(sys.modules, {'hmr4d.utils.preproc': SimpleNamespace(Tracker=self.factory)}):
            self.detector = resident_models.Detector()

    def predictor(self, **kwargs):
        predictor = FakePredictor(self.backend, self.setups, **kwargs)
        self.predictors.append(predictor)
        return predictor

    def track(self, source, **kwargs):
        self.assertEqual(source, str(self.video))
        self.assertEqual(kwargs, {'device': 'cuda', 'conf': 0.5, 'classes': 0, 'verbose': False,
                                  'stream': True, 'persist': False, 'save': False, 'half': False})
        predictor = self.yolo.predictor
        self.assertIs(predictor.model, self.backend)
        self.assertFalse(hasattr(predictor, 'trackers'))
        self.assertEqual(self.yolo.callbacks, {'start': [self.callback]})
        self.yolo.callbacks['start'].append('new tracking callback')
        predictor.trackers = [Mock()]
        predictor.dataset = SimpleNamespace(cap=Mock())
        predictor.vid_writer = {'out': Mock()}
        value = len(self.predictors)
        boxes = Mock()
        boxes.id.int.return_value.cpu.return_value.tolist.return_value = [value]
        boxes.xyxy.cpu.return_value.numpy.return_value = [[value, 2, 30, 40]]
        try:
            yield SimpleNamespace(boxes=boxes)
        finally:
            self.closed.append(predictor)

    def test_two_takes_retain_backend_but_replace_predictor_tracks_and_callbacks(self):
        first = self.detector.track(self.video)
        second = self.detector.track(self.video)
        self.assertNotEqual(first[0][0]['id'], second[0][0]['id'])
        self.assertEqual(len(self.setups), 1)
        self.factory.assert_called_once_with()
        self.assertEqual(len(self.predictors), 3)
        self.assertEqual(len(self.closed), 2)
        self.assertIsNone(self.yolo.predictor)
        self.assertEqual(self.yolo.callbacks, {'start': [self.callback]})
        for predictor in self.predictors[1:]:
            predictor.trackers[0].reset.assert_called_once_with()
            predictor.dataset.cap.release.assert_called_once_with()
            predictor.vid_writer['out'].release.assert_called_once_with()

    def test_tracking_failure_still_closes_generator_and_drops_take(self):
        original = self.yolo.track

        def fail(*args, **kwargs):
            yield from original(*args, **kwargs)
            raise RuntimeError('tracker fault')

        self.yolo.track = fail
        with self.assertRaisesRegex(RuntimeError, 'tracker fault'):
            self.detector.track(self.video)
        self.assertIsNone(self.yolo.predictor)
        self.assertEqual(self.yolo.callbacks, {'start': [self.callback]})
        self.assertEqual(len(self.closed), 1)

    def test_production_bound_is_not_experiment_32_frames(self):
        result = SimpleNamespace(boxes=SimpleNamespace(id=None))
        self.yolo.track = lambda *a, **kw: (result for _ in range(600))
        self.assertEqual(len(self.detector.track(self.video)), 600)
        self.yolo.track = lambda *a, **kw: (result for _ in range(601))
        with self.assertRaisesRegex(ValueError, 'bound'):
            self.detector.track(self.video)
        self.assertIsNone(self.yolo.predictor)


class BatchingAndIdentityTests(unittest.TestCase):
    def test_normal_batch8_all_tails_and_cold_batch2_no_padding_or_reuse(self):
        cat = lambda rows: [item for row in rows for item in row]
        with patch.dict(sys.modules, torch=SimpleNamespace(cat=cat)):
            for size in (2, 8):
                for count in range(2, 26):
                    with self.subTest(size=size, count=count):
                        crop = list(range(count))
                        boxes = list(range(100, 100 + count))
                        calls = []

                        def extract(a, b, calls=calls):
                            calls.append((list(a), list(b)))
                            return [v * 2 for v in a]

                        first = gvhmr.extract_batches(extract, crop, boxes, size)
                        self.assertEqual(first, [v * 2 for v in crop])
                        self.assertEqual([len(a) for a, _ in calls],
                                         [min(size, count - i) for i in range(0, count, size)])
                        self.assertEqual(cat([b for _, b in calls]), boxes)
                        second = gvhmr.extract_batches(extract, [v + 1 for v in crop], boxes, size)
                        self.assertNotEqual(first, second)

    def test_engine_hashes_approved_assets_once_not_per_inference(self):
        factories = {name: Mock(return_value=Mock()) for name in resident.MODEL_NAMES}
        with patch.object(gvhmr, 'asset_identities', return_value={'approved': 'hash'}) as identities:
            engine = resident.ResidentEngine(factories=factories, synchronize=Mock())
            with patch.object(gvhmr, 'infer_native', side_effect=[{}, {}]):
                engine.infer('first', {}, None)
                engine.infer('second', {}, None)
            identities.assert_called_once_with(include_auxiliary=True)
            engine.close()

    def test_asset_inventory_only_from_pinned_root_and_nonempty_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'INSPECTED_REVISION').write_text(gvhmr.UPSTREAM_COMMIT)
            for name in gvhmr.ASSETS:
                path = root / 'inputs/checkpoints' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'operator-trusted')
            with patch.dict(sys.modules, hmr4d=SimpleNamespace(PROJ_ROOT=root)), \
                 patch.object(Path, 'cwd', return_value=root), patch.object(gvhmr, 'digest', return_value='hash') as digest:
                self.assertEqual(gvhmr.asset_identities(), dict.fromkeys(gvhmr.ASSETS, 'hash'))
                self.assertEqual(digest.call_count, 5)
                (root / 'inputs/checkpoints' / gvhmr.ASSETS[0]).write_bytes(b'')
                with self.assertRaisesRegex(ValueError, 'missing'):
                    gvhmr.asset_identities()
                (root / 'INSPECTED_REVISION').write_text('different')
                with self.assertRaisesRegex(ValueError, 'revision'):
                    gvhmr.asset_identities()


class PrecisionControlTests(unittest.TestCase):
    def test_factories_confine_half_to_pose_features_and_pin_tracker_version(self):
        pose, features, demo, body = Mock(), Mock(), Mock(), Mock()
        demo.float.return_value = demo
        body.cuda.return_value.eval.return_value.float.return_value = body
        modules = {
            'hmr4d.utils.preproc': SimpleNamespace(VitPoseExtractor=Mock(return_value=pose),
                                                 Extractor=Mock(return_value=features)),
            'hmr4d.utils.smplx_utils': SimpleNamespace(make_smplx=Mock(return_value=body)),
        }
        wrapped = [object(), object()]
        with patch.dict(sys.modules, modules), patch.object(gvhmr, 'load_demo_model', return_value=demo), \
             patch.object(resident_models.importlib.metadata, 'version', return_value='8.2.42') as version, \
             patch.object(resident_models, 'wrap_fp16', side_effect=wrapped) as half:
            factories = resident_models.model_factories()
            self.assertEqual(set(factories), set(resident.MODEL_NAMES))
            self.assertIs(factories['detector'], resident_models.Detector)
            self.assertIs(factories['pose'](), pose)
            self.assertIs(pose.pose, wrapped[0])
            self.assertIs(factories['features'](), features)
            self.assertIs(features.extractor, wrapped[1])
            self.assertIs(factories['gvhmr'](), demo)
            self.assertIs(factories['body'](), body)
            self.assertEqual([call.args[1] for call in half.call_args_list], ['pose', 'features'])
            demo.float.assert_called_once_with()
            body.cuda.return_value.eval.return_value.float.assert_called_once_with()
            version.return_value = 'different'
            with self.assertRaisesRegex(ValueError, '8.2.42'):
                resident_models.model_factories()

    def test_explicit_half_no_autocast_cache_fp32_io_and_nonfinite_failure(self):
        class Tensor:
            dtype = 'float32'
            device = SimpleNamespace(type='cuda')

            def float(self):
                self.dtype = 'float32'
                return self

            def is_floating_point(self):
                return True

        class Module:
            def eval(self):
                return self

            def __call__(self, inputs):
                return self.forward(inputs)

        output = Tensor()
        autocast = Mock(side_effect=lambda **kw: nullcontext())
        finite = Mock(return_value=SimpleNamespace(all=lambda: True))
        fake_torch = SimpleNamespace(nn=SimpleNamespace(Module=Module), Tensor=Tensor,
                                     float32='float32', float16='float16', autocast=autocast, isfinite=finite)
        with patch.dict(sys.modules, torch=fake_torch):
            for label in ('pose', 'features'):
                module = Mock(return_value=output)
                module.half.return_value = module
                wrapper = resident_models.wrap_fp16(module, label)
                module.half.assert_called_once_with()
                image = Tensor()
                inputs = {'img': image} if label == 'features' else image
                output.dtype = 'float16'
                self.assertIs(wrapper(inputs), output)
                self.assertEqual(output.dtype, 'float32')
                autocast.assert_called_with(device_type='cuda', dtype='float16', cache_enabled=False)
                module.assert_called_once_with(inputs)
                image.dtype = 'float16'
                with self.assertRaisesRegex(ValueError, 'FP32'):
                    wrapper(inputs)
                image.dtype = 'float32'
                finite.return_value = SimpleNamespace(all=lambda: False)
                with self.assertRaisesRegex(ValueError, 'nonfinite'):
                    wrapper(inputs)
                finite.return_value = SimpleNamespace(all=lambda: True)
            with self.assertRaises(ValueError):
                resident_models.wrap_fp16(Mock(), 'body')


class ActualCudaPrecisionTests(unittest.TestCase):
    def test_real_cuda_fp16_weights_fp32_boundaries_and_tails(self):
        try:
            import torch
        except ImportError:
            self.skipTest('Torch missing; real CUDA precision check not run')
        if not torch.cuda.is_available():
            self.skipTest('CUDA missing; real CUDA precision check not run')

        class Neural(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(4, 4)

            def forward(self, inputs):
                return self.linear(inputs['img'] if isinstance(inputs, dict) else inputs)

        for label in ('pose', 'features'):
            module = Neural().cuda().eval()
            wrapped = resident_models.wrap_fp16(module, label)
            self.assertTrue(all(p.dtype == torch.float16 for p in wrapped.parameters()))
            for count in (8, 1, 3, 7):
                image = torch.randn(count, 4, device='cuda', dtype=torch.float32)
                with torch.inference_mode(), torch.autocast('cuda', enabled=False):
                    result = wrapped({'img': image} if label == 'features' else image)
                self.assertEqual(result.dtype, torch.float32)
                self.assertEqual(result.shape, (count, 4))
                self.assertTrue(torch.isfinite(result).all())
            torch.cuda.synchronize()


if __name__ == '__main__':
    unittest.main()
