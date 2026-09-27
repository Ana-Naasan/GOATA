"""Execute hash-checked 8.2.42 lifecycle bodies with CPU stand-ins, not fake infer.

Torch, media, numeric postprocessing and tracker algorithms are not executed.
Model.track/predict, predictor init/setup/stream, AutoBackend init/forward/warmup
and tracker registration/start run from the exact pinned source.
"""
import ast
from contextlib import ExitStack, nullcontext
from functools import partial
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import models
from lifecycle import MODEL_NAMES, RetainedModels


def pinned_nodes(relative, name, methods=None, base=object, **namespace):
    source = os.environ.get('PHYSIO_ULTRALYTICS_SOURCE')
    if source:
        root = Path(source)
        if not root.is_dir():
            raise AssertionError('PHYSIO_ULTRALYTICS_SOURCE must point to the ultralytics package directory')
    else:
        spec = importlib.util.find_spec('ultralytics')
        if spec is None:
            raise unittest.SkipTest('pinned source checks require installed Ultralytics 8.2.42 or PHYSIO_ULTRALYTICS_SOURCE')
        root = Path(spec.origin).parent
    path = root / relative
    source = path.read_bytes()
    identity = json.loads(Path(models.__file__).with_name('ultralytics-identity.json').read_text())
    if hashlib.sha256(source).hexdigest() != identity['files']['ultralytics/' + relative]:
        raise AssertionError('pinned source identity mismatch: ' + str(path))
    node = next(n for n in ast.parse(source).body if getattr(n, 'name', None) == name)
    if methods is not None:
        node.bases = [ast.Name(id='_Base', ctx=ast.Load())]
        node.body = [n for n in node.body if getattr(n, 'name', None) in methods]
        if {n.name for n in node.body} != set(methods):
            raise AssertionError('missing pinned methods')
    # Only remove decorators and annotations. All method bodies stay intact.
    for child in ast.walk(node):
        if isinstance(child, ast.FunctionDef):
            child.decorator_list = []
            child.returns = None
        if isinstance(child, ast.arg):
            child.annotation = None
    namespace.update(_Base=base)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), namespace)
    return namespace[name]


class Profile(nullcontext):
    dt = 0


class Module:
    def eval(self):
        return self

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)


class PinnedDetectorTests(unittest.TestCase):
    def boundary(self, stack, fail=False, length=2):
        operations, predictors, results, tracker_objects = [], [], [], []
        class Weights(Module):
            names = {0: 'person'}
            stride = NS(max=lambda: 32)
            parameter = NS(requires_grad=True)

            def parameters(self):
                return [self.parameter]

            def to(self, device):
                operations.append(('to', device.type if hasattr(device, 'type') else device))
                return self

            def fuse(self, verbose=True):
                operations.append(('fuse',))
                self.parameter = NS(requires_grad=True)
                return self

            def float(self):
                operations.append(('float',))
                return self

            def forward(self, image, **kwargs):
                operations.append(('forward', image.marker))
                return NS(marker=image.marker)

        torch = NS(nn=NS(Module=Module), cuda=NS(is_available=lambda: True), device=lambda d: NS(type=d),
                   empty=lambda *shape, **kw: NS(shape=shape, marker='warmup'), float='float', half='half')
        backend = pinned_nodes('nn/autobackend.py', 'AutoBackend',
                               ('__init__', 'forward', 'from_numpy', 'warmup'), base=Module,
                               torch=torch, Path=Path, np=NS(ndarray=type('Array', (), {})),
                               check_class_names=lambda names: names)
        backend._model_type = staticmethod(lambda _: [False] * 14)
        defaults = dict(conf=None, data=None, show=False, model=None, device=None, half=False, batch=1,
                        dnn=False, verbose=False, save=False, save_txt=False, save_crop=False, embed=None,
                        visualize=False, augment=False, task='detect', tracker='botsort.yaml')
        def get_cfg(cfg, overrides=None):
            return NS(**{**defaults, **(vars(cfg) if isinstance(cfg, NS) else cfg), **(overrides or {})})
        predictor_class = pinned_nodes('engine/predictor.py', 'BasePredictor',
            ('__init__', 'setup_model', '__call__', 'stream_inference', 'inference', 'run_callbacks'),
            DEFAULT_CFG=defaults, get_cfg=get_cfg, get_save_dir=lambda _: Path('unused'),
            threading=threading, callbacks=NS(add_integration_callbacks=lambda _: None),
            AutoBackend=backend, select_device=lambda d, **kw: torch.device(d),
            ops=NS(Profile=lambda **kw: Profile()), cv2=NS(VideoWriter=type('Writer', (), {})))
        original_setup = predictor_class.setup_model
        setups = Mock(side_effect=lambda obj, *a, **kw: original_setup(obj, *a, **kw))
        predictor_class.setup_model = lambda obj, *a, **kw: setups(obj, *a, **kw)

        class Dataset:
            bs, mode = 1, 'video'
            def __init__(self, source, take):
                self.source, self.take, self.cap = source, take, Mock()
            def __iter__(self):
                for frame in range(length):
                    if fail:
                        raise ValueError('decode failed')
                    yield [self.source], [NS(shape=(1, 3, 540, 960), marker=(self.take, frame))], ['']

        def setup_source(predictor, source):
            # These must be fresh even when the same filename is reused.
            for field in ('dataset', 'batch', 'results', 'plotted_img', 'transforms', 'imgsz'):
                self.assertIsNone(getattr(predictor, field))
            self.assertEqual(predictor.seen, 0)
            self.assertFalse(predictor.done_warmup)
            self.assertFalse(hasattr(predictor, 'trackers'))
            self.assertFalse(hasattr(predictor, 'vid_path'))
            self.assertEqual(len(predictor.callbacks['on_predict_start']), 1)
            self.assertEqual(len(predictor.callbacks['on_predict_postprocess_end']), 1)
            self.assertEqual((predictor.args.device, predictor.args.half, predictor.args.batch,
                              predictor.args.conf, predictor.args.classes, predictor.args.mode),
                             ('cuda', False, 1, 0.5, 0, 'track'))
            predictors.append(predictor)
            predictor.dataset = Dataset(source, len(predictors))
            predictor.imgsz = [540, 960]
        predictor_class.setup_source = setup_source
        predictor_class.preprocess = lambda _, images: images[0]
        def postprocess(_, prediction, image, originals):
            ids, boxes = Mock(), Mock()
            ids.int.return_value.cpu.return_value.tolist.return_value = [1]
            boxes.cpu.return_value.numpy.return_value = [prediction.marker]
            result = NS(boxes=NS(id=ids, xyxy=boxes))
            results.append(result)
            return [result]
        predictor_class.postprocess = postprocess

        def tracker_factory(**kw):
            tracker = Mock()
            tracker_objects.append(tracker)
            return tracker
        on_start = pinned_nodes('trackers/track.py', 'on_predict_start',
            IterableSimpleNamespace=NS, check_yaml=lambda value: value,
            yaml_load=lambda _: dict(tracker_type='botsort'), TRACKER_MAP={'botsort': tracker_factory})
        on_post = Mock()
        register = pinned_nodes('trackers/track.py', 'register_tracker', partial=partial,
                                on_predict_start=on_start, on_predict_postprocess_end=on_post)
        yolo_class = pinned_nodes('engine/model.py', 'Model', ('predict', 'track', 'add_callback'),
                                 get_cfg=get_cfg, ARGV=['worker.py'])
        yolo = yolo_class()
        yolo.model, yolo.predictor = Weights(), None
        yolo.overrides = dict(task='detect', imgsz=640)
        yolo.callbacks = {'on_predict_start': [], 'on_predict_postprocess_end': []}
        yolo._smart_load = lambda name: predictor_class
        checkpoint = Mock(return_value=NS(yolo=yolo))
        stack.enter_context(patch.dict(sys.modules, {
            'torch': torch, 'torchvision': NS(),
            'hmr4d.utils.preproc': NS(Tracker=checkpoint),
            'ultralytics.trackers': NS(register_tracker=register),
        }))
        return NS(yolo=yolo, operations=operations, predictors=predictors, setups=setups,
                  checkpoint=checkpoint, results=results, trackers=tracker_objects, on_post=on_post)

    def test_one_backend_before_ready_no_weight_mutation_or_checkpoint_after_ready(self):
        with ExitStack() as stack, tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            boundary = self.boundary(stack)
            store = RetainedModels(lambda name, obj, device: obj.to(device) if name == 'detector' else None)
            store.preload({name: models.Detector if name == 'detector' else object for name in MODEL_NAMES})
            detector = store.models['detector']
            self.assertEqual(boundary.setups.call_count, 1, 'AutoBackend must initialize before resident_ready')
            backend = detector.backend
            backend_state = dict(vars(backend))
            parameter = boundary.yolo.model.parameter
            before_ready = list(boundary.operations)
            self.assertEqual(sum(op[0] == 'fuse' for op in before_ready), 1)
            self.assertEqual(sum(op[0] == 'float' for op in before_ready), 1)
            path = Path(folder) / 'observations.mp4'
            path.write_bytes(b'local fixture')
            histories = []
            for _ in range(2):
                with store.use('detector', models.Detector) as retained:
                    histories.append(retained.track(path))
                self.assertIsNone(detector.yolo.predictor)
                self.assertIs(detector.backend, backend)
                self.assertIs(detector.yolo.model.parameter, parameter)
                self.assertEqual(detector.yolo.callbacks, detector.callbacks)
            self.assertEqual(boundary.setups.call_count, 1)
            boundary.checkpoint.assert_called_once()
            self.assertEqual(boundary.operations[len(before_ready):],
                             [('forward', 'warmup'), ('forward', (1, 0)), ('forward', (1, 1)),
                              ('forward', 'warmup'), ('forward', (2, 0)), ('forward', (2, 1))])
            self.assertNotEqual(histories[0], histories[1])
            self.assertIsNot(boundary.predictors[0], boundary.predictors[1])
            self.assertIsNot(boundary.predictors[0].callbacks, boundary.predictors[1].callbacks)
            self.assertIsNot(boundary.trackers[0], boundary.trackers[1])
            self.assertEqual(len({id(result) for result in boundary.results}), 4)
            for predictor in boundary.predictors:
                self.assertIs(predictor.model, backend)
                predictor.dataset.cap.release.assert_called_once()
                predictor.trackers[0].reset.assert_called_once()
            self.assertEqual(boundary.on_post.call_count, 4)
            self.assertEqual(vars(backend), backend_state)
            self.assertEqual(backend.batch, 1)  # AutoBackend batch-size metadata, not input images.
            self.assertFalse(any(key in vars(backend) for key in ('results', 'dataset', 'features')))

    def test_cpu_offload_moves_same_backend_without_repeating_setup(self):
        with ExitStack() as stack, tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            boundary = self.boundary(stack)
            store = RetainedModels(lambda name, obj, device: obj.to(device), residency='cpu-offload')
            path = Path(folder) / 'observations.mp4'
            path.write_bytes(b'local fixture')
            backends = []
            for _ in range(2):
                with store.use('detector', models.Detector) as detector:
                    self.assertEqual(detector.backend.device.type, 'cuda')
                    backends.append(detector.backend)
                    detector.track(path)
                self.assertEqual(detector.backend.device.type, 'cpu')
            self.assertIs(backends[0], backends[1])
            self.assertEqual(boundary.setups.call_count, 1)
            boundary.checkpoint.assert_called_once()
            self.assertEqual([op for op in boundary.operations if op[0] != 'forward'],
                             [('to', 'cuda'), ('fuse',), ('float',), ('to', 'cuda'),
                              ('to', 'cpu'), ('to', 'cuda'), ('to', 'cpu')])

    def test_pinned_stream_failure_and_bound_dispose_per_take_state(self):
        for fail, length in ((True, 2), (False, 33)):
            with self.subTest(fail=fail), ExitStack() as stack, tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
                boundary = self.boundary(stack, fail=fail, length=length)
                detector = models.Detector()
                path = Path(folder) / 'observations.mp4'
                path.write_bytes(b'local fixture')
                with self.assertRaises(ValueError):
                    detector.track(path)
                self.assertIsNone(detector.yolo.predictor)
                self.assertEqual(detector.yolo.callbacks, detector.callbacks)
                boundary.predictors[0].dataset.cap.release.assert_called_once()
                boundary.trackers[0].reset.assert_called_once()


if __name__ == '__main__':
    unittest.main()
