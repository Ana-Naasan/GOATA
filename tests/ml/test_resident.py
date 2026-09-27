"""CPU protocol/lifecycle controls. Stand-ins do not establish GPU inference."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from processing.reconstruction import resident, runtime


class FakeEngine:
    def __init__(self):
        self.warmup_complete = False
        self.constructors = dict.fromkeys(resident.MODEL_NAMES, 1)
        self.calls = []
        self.closed = False
        self.job_index = 0

    def process(self, video, sidecar, output, estimated, pinhole):
        self.calls.append((video, sidecar, output, estimated, pinhole))
        output.mkdir()
        (output / 'handoff.json').write_text('{}')
        if self.warmup_complete:
            self.job_index += 1

    def reset(self):
        pass

    def close(self):
        self.closed = True


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.warmup_video = self.root / 'operator.mp4'
        self.warmup_sidecar = self.root / 'operator.json'
        self.warmup_video.write_bytes(b'original')
        self.warmup_sidecar.write_text('{}')
        self.engine = FakeEngine()
        self.writer = io.StringIO()

    def request(self):
        key = str(uuid4())
        job = self.root / 'jobs' / key
        files = job / 'input/files'
        files.mkdir(parents=True)
        (job / 'output.tmp').mkdir()
        video, sidecar = files / 'source.mp4', files / 'source.json'
        video.write_bytes(b'original')
        sidecar.write_text('{}')
        return {'id': key, 'video': str(video), 'sidecar': str(sidecar),
                'output': str(job / 'output.tmp/native.tmp'),
                'allow_estimated_intrinsics': False, 'allow_unverified_pinhole': True}

    @staticmethod
    def line(request):
        return (json.dumps(request) + '\n').encode()

    def serve(self, data=b''):
        return resident.serve(io.BytesIO(data), self.writer, self.root,
                              self.warmup_video, self.warmup_sidecar, False, True,
                              engine_factory=lambda: self.engine)

    def events(self):
        return [json.loads(row) for row in self.writer.getvalue().splitlines()]

    def test_warmup_then_two_jobs_then_eof(self):
        requests = [self.request(), self.request()]
        self.assertEqual(self.serve(b''.join(map(self.line, requests))), 0)
        events = self.events()
        self.assertEqual(events[0]['event'], 'ready')
        self.assertIs(events[0]['warmup_complete'], True)
        self.assertFalse(set(events[0]) - {'protocol', 'event', 'warmup_complete',
                                          'pid', 'constructors', 'warmup_seconds'})
        self.assertEqual([e['id'] for e in events[1:]], [r['id'] for r in requests])
        self.assertTrue(all(e['ok'] for e in events[1:]))
        self.assertEqual([e['job_index'] for e in events[1:]], [1, 2])
        self.assertTrue(all(e['protocol'] == 'gvhmr-resident-1' for e in events))
        self.assertEqual(len(self.engine.calls), 3)
        self.assertEqual(self.engine.calls[0][3:], (False, True))
        self.assertFalse((self.root / 'resident.tmp').exists())
        self.assertEqual(self.warmup_video.read_bytes(), b'original')
        self.assertTrue(self.engine.closed)

    def test_ready_only_after_warmup_output_cleanup_and_reset(self):
        resets = []
        self.engine.reset = lambda: resets.append((self.root / 'resident.tmp').exists())
        write = self.writer.write

        def observe(text):
            self.assertEqual(len(self.engine.calls), 1)
            self.assertFalse((self.root / 'resident.tmp').exists())
            self.assertEqual(resets[-1], False)
            return write(text)

        self.writer.write = observe
        self.assertEqual(self.serve(), 0)
        self.assertTrue(self.engine.closed)

    def test_startup_failure_never_ready_and_preserves_existing_scratch(self):
        scratch = self.root / 'resident.tmp'
        scratch.mkdir()
        keep = scratch / 'not-ours'
        keep.write_text('keep')
        self.assertEqual(self.serve(), 1)
        self.assertEqual(self.events(), [])
        self.assertEqual(keep.read_text(), 'keep')

    def test_warmup_and_reset_failures_never_ready(self):
        for method in ('process', 'reset'):
            self.engine = FakeEngine()
            setattr(self.engine, method, Mock(side_effect=RuntimeError('private error')))
            with self.subTest(method=method):
                self.assertEqual(self.serve(), 1)
                self.assertFalse(self.engine.warmup_complete)
                self.assertEqual(self.events(), [])
                self.assertTrue(self.engine.closed)
                self.assertFalse((self.root / 'resident.tmp').exists())

    def test_job_failure_is_static_and_fatal_no_second_job(self):
        requests = [self.request(), self.request()]
        original = self.engine.process

        def process(*args):
            if self.engine.warmup_complete:
                raise RuntimeError('secret path /patient')
            original(*args)

        self.engine.process = process
        self.assertEqual(self.serve(b''.join(map(self.line, requests))), 1)
        self.assertEqual(self.events()[1], {'protocol': resident.PROTOCOL, 'event': 'result',
                                           'id': requests[0]['id'], 'ok': False})
        self.assertEqual(len(self.events()), 2)
        self.assertNotIn('secret', self.writer.getvalue())
        self.assertTrue(self.engine.closed)

    def test_strict_json_and_line_bounds(self):
        good = self.line(self.request())
        cases = [good[:-1], b'\n', b'{}\n', b'[]\n', b'\xff\n',
                 b'{"id":"a","id":"b"}\n', b'{"x":NaN}\n',
                 b'{"x":1e999}\n', b'[' * 2000 + b']' * 2000 + b'\n',
                 b' ' * resident.MAX_MESSAGE_BYTES + b'\n']
        for row in cases:
            with self.subTest(row=row[:30]), self.assertRaises(ValueError):
                resident.decode_request(row)
        for field, value in [('id', str(uuid4()).upper()), ('video', 'relative.mp4'),
                             ('sidecar', 5), ('allow_estimated_intrinsics', 1),
                             ('allow_unverified_pinhole', None), ('extra', False)]:
            request = self.request()
            request[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                resident.decode_request(self.line(request))
        self.assertEqual(resident.decode_request(good), json.loads(good))

    def test_reader_requests_only_bounded_line_and_stops_on_malformed(self):
        reader = Mock()
        reader.readline.return_value = b'x' * (resident.MAX_MESSAGE_BYTES + 1)
        status = resident.serve(reader, self.writer, self.root, self.warmup_video,
                                self.warmup_sidecar, False, False,
                                engine_factory=lambda: self.engine)
        self.assertEqual(status, 1)
        reader.readline.assert_called_once_with(resident.MAX_MESSAGE_BYTES + 1)
        self.assertEqual(len(self.events()), 1)
        self.assertTrue(self.engine.closed)

    def test_paths_reject_outside_cross_job_existing_and_symlinks(self):
        good, other = self.request(), self.request()
        resident.validate_paths(good, self.root)
        for field, value in [('video', str(self.warmup_video)), ('sidecar', other['sidecar']),
                             ('output', other['output']), ('output', good['video']),
                             ('video', good['video'] + '/../../source.mp4')]:
            request = dict(good, **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                resident.validate_paths(request, self.root)
        output = Path(good['output'])
        output.mkdir()
        with self.assertRaises(ValueError):
            resident.validate_paths(good, self.root)
        output.rmdir()
        video = Path(good['video'])
        video.unlink()
        video.symlink_to(self.warmup_video)
        with self.assertRaises(ValueError):
            resident.validate_paths(good, self.root)
        video.unlink()
        video.write_bytes(b'original')
        files = video.parent
        moved = files.with_name('other')
        files.rename(moved)
        files.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            resident.validate_paths(good, self.root)

    def test_bad_job_path_emits_failure_and_never_runs_it(self):
        request = self.request()
        request['video'] = str(self.warmup_video)
        self.assertEqual(self.serve(self.line(request)), 1)
        self.assertFalse(self.events()[-1]['ok'])
        self.assertEqual(len(self.engine.calls), 1)

    def test_directory_inputs_and_dangling_output_symlink_are_rejected(self):
        request = self.request()
        video = Path(request['video'])
        video.unlink()
        video.mkdir()
        with self.assertRaises(ValueError):
            resident.validate_paths(request, self.root)
        video.rmdir()
        video.write_bytes(b'control')
        Path(request['output']).symlink_to(self.root / 'absent')
        with self.assertRaises(ValueError):
            resident.validate_paths(request, self.root)

    def test_cli_forwards_only_operator_options_and_real_binary_reader(self):
        with patch.object(resident, 'protocol_stdout', return_value=nullcontext(self.writer)), \
             patch.object(resident, 'serve', return_value=1) as serve, \
             patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO())):
            self.assertEqual(resident.main(['--warmup-video', str(self.warmup_video),
                                           '--warmup-sidecar', str(self.warmup_sidecar),
                                           '--data-root', str(self.root),
                                           '--allow-unverified-pinhole']), 1)
        args = serve.call_args.args
        self.assertIsInstance(args[0], io.BytesIO)
        self.assertEqual(args[1:], (self.writer, self.root, self.warmup_video,
                                   self.warmup_sidecar, False, True))

    def test_invalid_operator_root_and_relative_warmup_never_construct(self):
        factory = Mock()
        for root, video in ((self.root / 'missing', self.warmup_video),
                            (self.root, Path('relative.mp4'))):
            self.assertEqual(resident.serve(io.BytesIO(), self.writer, root, video,
                                           self.warmup_sidecar, engine_factory=factory), 1)
        factory.assert_not_called()
        self.assertEqual(self.events(), [])

    def test_response_size_is_bounded(self):
        with self.assertRaises(ValueError):
            resident.emit(self.writer, 'ready', extra='x' * resident.MAX_MESSAGE_BYTES)
        self.assertEqual(self.events(), [])

    def test_fd_redirection_catches_python_and_native_stdout(self):
        code = '''
import os
from processing.reconstruction.resident import protocol_stdout
with protocol_stdout() as writer:
    print("library python output", flush=True)
    os.write(1, b"native output\\n")
    writer.write('{"protocol":"gvhmr-resident-1","event":"ready"}\\n')
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)['event'], 'ready')
        self.assertIn(b'library python output', result.stderr)
        self.assertIn(b'native output', result.stderr)


class EngineTests(unittest.TestCase):
    def make_engine(self):
        factories = {name: Mock(return_value=Mock()) for name in resident.MODEL_NAMES}
        sync = Mock()
        engine = resident.ResidentEngine(factories=factories, assets={'approved': 'hash'}, synchronize=sync)
        return engine, factories, sync

    def test_constructors_once_uses_fresh_inputs_no_predictions_retained(self):
        engine, factories, sync = self.make_engine()
        self.assertEqual(sync.call_count, 1)
        predictions = []

        def infer(video, plan, output, resident_models, batch_size):
            self.assertEqual(batch_size, 8)
            for name in resident.MODEL_NAMES:
                self.assertIs(resident_models.use(name), factories[name].return_value)
            result = {'input': video}
            predictions.append(result)
            return result

        with patch('processing.reconstruction.gvhmr.infer_native', side_effect=infer):
            first = engine.infer('first', {}, None)
            second = engine.infer('second', {}, None)
        self.assertIsNot(first, second)
        self.assertEqual(first['input'], 'first')
        self.assertEqual(second['input'], 'second')
        self.assertEqual(engine.constructors, dict.fromkeys(resident.MODEL_NAMES, 1))
        self.assertEqual(engine.uses, dict.fromkeys(resident.MODEL_NAMES, 2))
        for factory in factories.values():
            factory.assert_called_once_with()
        self.assertFalse(any(value is first or value is second for value in vars(engine).values()))
        engine.close()
        self.assertEqual(engine.models, {})
        with self.assertRaises(RuntimeError):
            engine.infer('third', {}, None)

    def test_engine_failure_cannot_be_reused(self):
        engine, _, _ = self.make_engine()
        with patch('processing.reconstruction.gvhmr.infer_native', side_effect=RuntimeError('GPU fault')), \
             self.assertRaises(RuntimeError):
            engine.infer('first', {}, None)
        with self.assertRaises(RuntimeError):
            engine.infer('second', {}, None)
        engine.close()

    def test_constructor_failure_discards_preloaded_models(self):
        detector = Mock()
        factories = {name: Mock(side_effect=RuntimeError('constructor')) for name in resident.MODEL_NAMES}
        factories['detector'] = Mock(return_value=detector)
        with self.assertRaisesRegex(RuntimeError, 'constructor'):
            resident.ResidentEngine(factories=factories, assets={}, synchronize=Mock())
        detector.reset.assert_called_once_with()
        factories['body'].assert_not_called()
        with self.assertRaises(ValueError):
            resident.ResidentEngine(factories={}, assets={}, synchronize=Mock())

    def test_default_cuda_sync_and_unavailable_device(self):
        factories = {name: Mock(return_value=Mock()) for name in resident.MODEL_NAMES}
        cuda = SimpleNamespace(is_available=Mock(return_value=True), synchronize=Mock())
        with patch.dict(sys.modules, torch=SimpleNamespace(cuda=cuda)):
            engine = resident.ResidentEngine(factories=factories, assets={})
            cuda.synchronize.assert_called_once_with()
            engine.close()
            engine.close()
            cuda.is_available.return_value = False
            with self.assertRaisesRegex(RuntimeError, 'CUDA'):
                resident.ResidentEngine(factories=factories, assets={})

    def test_runtime_or_reset_failure_poison_engine(self):
        for failed_stage in ('runtime', 'reset'):
            engine, factories, _ = self.make_engine()
            with self.subTest(stage=failed_stage), patch.object(runtime, 'run') as run:
                if failed_stage == 'runtime':
                    run.side_effect = RuntimeError('prepare')
                else:
                    factories['detector'].return_value.reset.side_effect = RuntimeError('reset')
                with self.assertRaises(RuntimeError):
                    engine.process(Path('/v'), Path('/s'), Path('/o'), False, False)
                self.assertTrue(engine.failed)
                with self.assertRaises(RuntimeError):
                    engine.process(Path('/v'), Path('/s'), Path('/o'), False, False)
                factories['detector'].return_value.reset.side_effect = None
                engine.close()

    def test_full_runtime_injection_requires_mapping_and_resets(self):
        engine, factories, sync = self.make_engine()
        with patch.object(runtime, 'run') as run:
            engine.process(Path('/v'), Path('/s'), Path('/o'), True, False)
        args, kwargs = run.call_args
        self.assertEqual(args, (Path('/v'), Path('/s'), Path('/o'), 0, True, False))
        self.assertEqual(kwargs, {'inferer': engine.infer, 'require_media_mapping': True})
        factories['detector'].return_value.reset.assert_called()
        self.assertGreater(sync.call_count, 1)
        self.assertFalse(engine.warmup_complete)
        engine.close()


if __name__ == '__main__':
    unittest.main()
