"""Serial GPU worker for completed uploads. No streaming or automatic retries."""

import argparse
import gc
import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path
from uuid import UUID

PROTOCOL = 'gvhmr-resident-1'
MAX_MESSAGE_BYTES = 16 * 1024
MODEL_NAMES = ('detector', 'pose', 'features', 'gvhmr', 'body')
REQUEST_KEYS = {'id', 'video', 'sidecar', 'output',
                'allow_estimated_intrinsics', 'allow_unverified_pinhole'}


class ResidentEngine:
    """Retain only models and counters, never a take's tensors or predictions."""

    def __init__(self, *, factories=None, assets=None, synchronize=None):
        from .gvhmr import asset_identities
        from .resident_models import model_factories

        self.models = {}
        self.constructors = {}
        self.uses = dict.fromkeys(MODEL_NAMES, 0)
        self.failed = False
        self.active = False
        self.closed = False
        self.warmup_complete = False
        self.job_index = 0
        self.assets = asset_identities(include_auxiliary=True) if assets is None else dict(assets)
        if synchronize is None:
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError('CUDA GPU unavailable')
            synchronize = torch.cuda.synchronize
        self.synchronize = synchronize
        factories = model_factories() if factories is None else factories
        if set(factories) != set(MODEL_NAMES):
            raise ValueError('resident preload requires exactly five models')
        try:
            for name in MODEL_NAMES:
                self.models[name] = factories[name]()
                self.constructors[name] = 1
            self.synchronize()
        except BaseException:
            self.failed = True
            self.close()
            raise

    def _check(self):
        if self.failed or self.closed or self.active:
            raise RuntimeError('resident engine unavailable')

    def use(self, name):
        if not self.active or self.failed or self.closed:
            raise RuntimeError('no active resident inference')
        model = self.models[name]
        self.uses[name] += 1
        return model

    def infer(self, video, plan, output):
        from .gvhmr import infer_native

        self._check()
        self.active = True
        try:
            result = infer_native(video, plan, output, resident_models=self, batch_size=8)
            result['resident'] = {
                'mode': 'gpu-resident', 'precision': 'weights-fp16', 'batch_size': 8,
                'fp16_scope': ['pose', 'features'],
                'fp32_scope': ['detector', 'gvhmr', 'body', 'camera_motion'],
                'constructors': dict(self.constructors), 'uses': dict(self.uses),
                'warmup_complete': self.warmup_complete, 'resident_pid': os.getpid(),
                'job_index': self.job_index,
            }
            return result
        except BaseException:
            self.failed = True
            raise
        finally:
            self.active = False

    def process(self, video, sidecar, output, estimated, pinhole):
        from .runtime import run

        self._check()
        if self.warmup_complete:
            self.job_index += 1
        try:
            run(video, sidecar, output, 0, estimated, pinhole,
                inferer=self.infer, require_media_mapping=True)
            self.reset()
        except BaseException:
            self.failed = True
            raise

    def reset(self):
        try:
            self.models['detector'].reset()
            gc.collect()
            self.synchronize()
        except BaseException:
            self.failed = True
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if 'detector' in self.models:
                self.models['detector'].reset()
        finally:
            self.models.clear()
            # Keep allocator policy unchanged. Process exit releases CUDA memory.


def decode_request(line):
    from .native import _finite_float, _reject_constant, _unique_object

    if not isinstance(line, bytes) or len(line) > MAX_MESSAGE_BYTES or not line.endswith(b'\n'):
        raise ValueError('invalid protocol line')
    try:
        value = json.loads(line.decode('utf-8'), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant, parse_float=_finite_float)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid protocol JSON') from error
    if type(value) is not dict or set(value) != REQUEST_KEYS:
        raise ValueError('invalid request fields')
    try:
        if type(value['id']) is not str or str(UUID(value['id'])) != value['id']:
            raise ValueError('noncanonical request UUID')
    except (ValueError, AttributeError) as error:
        raise ValueError('invalid request UUID') from error
    for field in ('allow_estimated_intrinsics', 'allow_unverified_pinhole'):
        if type(value[field]) is not bool:
            raise ValueError('calibration flags must be booleans')
    for field in ('video', 'sidecar', 'output'):
        raw = value[field]
        if (type(raw) is not str or '\x00' in raw or not Path(raw).is_absolute()
                or '..' in Path(raw).parts or str(Path(raw)) != raw):
            raise ValueError('paths must be absolute and normalized')
    return value


def validate_paths(request, data_root):
    """Paths belong to one private job. Do not resolve away untrusted symlinks."""
    job = data_root / 'jobs' / request['id']
    paths = tuple(Path(request[name]) for name in ('video', 'sidecar', 'output'))
    video, sidecar, output = paths
    if (video.parent != job / 'input/files' or video.suffix != '.mp4'
            or sidecar.parent != job / 'input/files' or sidecar.suffix != '.json'
            or output != job / 'output.tmp/native.tmp'):
        raise ValueError('paths outside the requested job')
    for path in paths:
        if '..' in path.parts:
            raise ValueError('path traversal')
        cursor = data_root
        for part in path.relative_to(data_root).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError('symlink in job path')
        if path != output and not stat.S_ISREG(path.stat().st_mode):
            raise ValueError('input is not a regular file')
    if output.exists() or not output.parent.is_dir():
        raise ValueError('output must be a new directory under an existing parent')
    return paths


def emit(writer, event, **fields):
    line = json.dumps(dict(protocol=PROTOCOL, event=event, **fields), allow_nan=False,
                      separators=(',', ':')) + '\n'
    if len(line.encode('utf-8')) > MAX_MESSAGE_BYTES:
        raise ValueError('oversized protocol response')
    writer.write(line)
    writer.flush()


def serve(reader, writer, data_root, warmup_video, warmup_sidecar,
          allow_estimated_intrinsics=False, allow_unverified_pinhole=False, *, engine_factory=None):
    engine = None
    try:
        started = time.monotonic()
        if not data_root.is_absolute() or not data_root.is_dir() or data_root.is_symlink():
            raise ValueError('data root must be an existing private directory')
        if not warmup_video.is_absolute() or not warmup_sidecar.is_absolute():
            raise ValueError('warmup paths must be absolute')
        scratch = data_root / 'resident.tmp'
        # Never remove stale/foreign scratch. The parent must reconcile a failed worker.
        scratch.mkdir(mode=0o700, exist_ok=False)
        try:
            engine = (ResidentEngine if engine_factory is None else engine_factory)()
            engine.process(warmup_video, warmup_sidecar, scratch / 'native.tmp',
                           allow_estimated_intrinsics, allow_unverified_pinhole)
        finally:
            shutil.rmtree(scratch)
        engine.reset()
        engine.warmup_complete = True
        emit(writer, 'ready', warmup_complete=True, pid=os.getpid(),
             constructors=engine.constructors, warmup_seconds=time.monotonic() - started)
        while True:
            line = reader.readline(MAX_MESSAGE_BYTES + 1)
            if not line:
                return 0
            request = decode_request(line)
            try:
                video, sidecar, output = validate_paths(request, data_root)
                engine.process(video, sidecar, output, request['allow_estimated_intrinsics'],
                               request['allow_unverified_pinhole'])
            except Exception:  # noqa: BLE001 - every job fault discards the process, including CUDA faults
                emit(writer, 'result', id=request['id'], ok=False)
                return 1
            emit(writer, 'result', id=request['id'], ok=True, constructors=engine.constructors,
                 job_index=engine.job_index, resident_pid=os.getpid())
    except Exception:  # noqa: BLE001 - startup/protocol boundary must fail closed for library errors
        # No paths, exception text, partial readiness or retry on the wire.
        return 1
    finally:
        if engine is not None:
            engine.close()


def protocol_stdout():
    """Reserve original fd 1, then redirect Python AND native library writes."""
    sys.stdout.flush()
    writer = os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf-8', buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    return writer


def main(argv=None):
    # Only stdlib imports precede this. YOLO/Hydra may print during import itself.
    with protocol_stdout() as writer:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--warmup-video', type=Path, required=True)
        parser.add_argument('--warmup-sidecar', type=Path, required=True)
        parser.add_argument('--data-root', type=Path, required=True)
        parser.add_argument('--allow-estimated-intrinsics', action='store_true')
        parser.add_argument('--allow-unverified-pinhole', action='store_true')
        args = parser.parse_args(argv)
        return serve(sys.stdin.buffer, writer, args.data_root, args.warmup_video, args.warmup_sidecar,
                     args.allow_estimated_intrinsics, args.allow_unverified_pinhole)


if __name__ == '__main__':
    sys.exit(main())
