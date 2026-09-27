"""Bounded, serial model retention. Input-derived tensors never enter this store."""
from contextlib import contextmanager, nullcontext
from pathlib import Path

MODEL_NAMES = frozenset(('detector', 'pose', 'features', 'gvhmr', 'body'))
PRECISIONS = ('fp32', 'amp-fp16', 'weights-fp16')
BATCH_SIZES = (2, 4, 8)
RESIDENCY_MODES = {
    'resident': 'GPU-resident weights; fresh predictor/tracker per take',
    'cpu-offload': 'CPU-retained sequential offload; fresh predictor/tracker per take',
}


def validate_controls(precision='fp32', variant='960-15', batch_size=2, vo_seed=0):
    from fast import VARIANTS
    if precision not in PRECISIONS or variant not in VARIANTS:
        raise ValueError('unsupported precision or variant')
    if type(batch_size) is not int or batch_size not in BATCH_SIZES:
        raise ValueError('batch size must be 2, 4 or 8')
    if type(vo_seed) is not int or vo_seed < 0:
        raise ValueError('VO seed must be a nonnegative integer')
    return dict(precision=precision, variant=variant, batch_size=batch_size, vo_seed=vo_seed)


def reset_detector(yolo, callbacks):
    """8.2.42: discard the entire predictor, restore pre-track callbacks, keep weights.

    BYTETracker.reset clears track lists/frame ID/Kalman filter/global ID counter;
    BOTSORT.reset also clears GMC state. Rebuilding the predictor clears batch,
    results, dataset, vid_path, seen and per-take warmup/device state. Detector
    retains the initialized AutoBackend separately and binds it to each fresh
    predictor without setup_model, weight conversion, fusion or checkpoint I/O.
    Only local file loaders are accepted by the worker, never streams/URLs.
    """
    predictor = yolo.predictor
    if predictor is not None:
        for tracker in getattr(predictor, 'trackers', ()):
            tracker.reset()
        cap = getattr(getattr(predictor, 'dataset', None), 'cap', None)
        if cap is not None:
            cap.release()
        for writer in getattr(predictor, 'vid_writer', {}).values():
            writer.release()
    yolo.predictor = None
    yolo.callbacks = {name: list(functions) for name, functions in callbacks.items()}


def record_cleanup_error(error, cleanup, stage):
    """Keep the primary exception; serialize secondary cleanup failures separately."""
    error.cleanup_errors = getattr(error, 'cleanup_errors', []) + [
        dict(stage=stage, error_type=type(cleanup).__name__, error=str(cleanup))]


class IdentityRecords:
    """Hash operator-trusted immutable assets once per worker, not per segment."""
    def __init__(self, root, names, digest):
        self.root, self.names, self.digest = Path(root), tuple(names), digest
        self.records = None
        self.hash_calls = 0

    def get(self):
        if self.records is None:
            records = {}
            for name in self.names:
                path = self.root / name
                if not path.is_file() or not path.stat().st_size:
                    raise ValueError(f'missing or empty trusted asset: {name}')
                records[name] = self.digest(path)
                self.hash_calls += 1
            self.records = records
        return dict(self.records)


class RetainedModels:
    def __init__(self, move, measure=None, residency='resident'):
        if residency not in RESIDENCY_MODES:
            raise ValueError('unknown residency mode')
        self.residency = residency
        self.models = {}
        self.constructors, self.uses = {}, {}
        self.move = move
        self.measure = measure or (lambda name: nullcontext())
        self.active = None
        self.failed = False

    def activate(self, name, factory):
        new = name not in self.models
        if new:
            with self.measure('constructor_deserialization/' + name):
                self.models[name] = factory()
            self.constructors[name] = 1
        if new or self.residency == 'cpu-offload':
            with self.measure('transfer_cuda/' + name):
                self.move(name, self.models[name], 'cuda')

    def preload(self, factories):
        """Resident startup only. No stage uses or input-derived state here."""
        if self.residency != 'resident' or set(factories) != MODEL_NAMES:
            raise ValueError('resident preload requires exactly five model factories')
        if self.failed or self.active is not None:
            raise RuntimeError('worker failed or a GPU stage is already active')
        try:
            for name, factory in factories.items():
                self.active = name
                self.activate(name, factory)
        except BaseException:
            self.failed = True
            raise
        finally:
            self.active = None

    @contextmanager
    def use(self, name, factory):
        if name not in MODEL_NAMES:
            raise ValueError('unknown retained model')
        if self.failed or self.active is not None:
            raise RuntimeError('worker failed or a GPU stage is already active')
        if self.residency == 'resident' and set(self.models) != MODEL_NAMES:
            raise RuntimeError('preload all five resident models before inference')
        self.active = name
        error = None
        try:
            self.activate(name, factory)
            self.uses[name] = self.uses.get(name, 0) + 1
            yield self.models[name]
        except BaseException as primary:
            error = primary
            self.failed = True
            raise
        finally:
            try:
                if self.residency == 'cpu-offload' and name in self.models:
                    with self.measure('transfer_cpu/' + name):
                        self.move(name, self.models[name], 'cpu')
            except BaseException as cleanup:
                self.failed = True
                if error is None:
                    raise
                record_cleanup_error(error, cleanup, 'transfer_cpu/' + name)
            finally:
                self.active = None


class Counters:
    def __init__(self):
        self.values = {}

    def add(self, name, count=1):
        if type(count) is not int or count < 0:
            raise ValueError('invalid counter increment')
        self.values[name] = self.values.get(name, 0) + count

    def finish(self, observations, grid, batch_size=2):
        validate_controls(batch_size=batch_size)
        values, self.values = self.values, {}
        expected = dict(detection_frames=observations, pose_frames=observations, feature_frames=observations,
                        scatter_frames=grid, export_frames=grid, pose_calls=(observations+batch_size-1)//batch_size,
                        feature_calls=(observations+batch_size-1)//batch_size, gvhmr_calls=1,
                        vo_sample_frames=len(set(range(0, grid, 8)) | {grid-1}))
        if values != expected:
            raise ValueError(f'stage counters differ: actual={values}, expected={expected}')
        return values


def validate_segment(plan):
    bounds = {'960-15': (960, 540, 15, 32), '640-10': (640, 360, 10, 22),
              '640-15': (640, 360, 15, 32)}
    variant = plan.get('variant', '960-15')
    if variant not in bounds:
        raise ValueError('unsupported segment variant')
    width, height, hz, maximum = bounds[variant]
    if (plan['width'], plan['height']) != (width, height):
        raise ValueError(f'{variant} requires {width}x{height}')
    if plan['sampling'].get('observation_hz', hz) != hz:
        raise ValueError('observation frequency differs from variant')
    if not 2 <= len(plan['selected_indices']) <= 63:
        raise ValueError('segment grid must fit about two seconds')
    if not 2 <= len(plan['sampling']['observation_indices']) <= maximum:
        raise ValueError('segment observation bound exceeded')
