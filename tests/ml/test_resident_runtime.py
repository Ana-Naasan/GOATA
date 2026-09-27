"""Shared cold/resident preparation controls, including PyAV 13 decoder cleanup."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_runtime import sidecar

from processing.reconstruction import runtime


class ReaderCleanupTests(unittest.TestCase):
    def reader(self, codec):
        events = []
        container = Mock()
        container.streams.video = [SimpleNamespace(codec_context=codec)]
        container.__enter__ = Mock(return_value=container)
        container.__exit__ = Mock(side_effect=lambda *a: events.append('container'))
        return container, events

    def test_open_codec_closed_before_container_even_on_decode_failure(self):
        codec = SimpleNamespace(is_open=True, close=Mock())
        container, events = self.reader(codec)
        codec.close.side_effect = lambda: events.append('codec')
        with patch.dict(sys.modules, av=SimpleNamespace(open=Mock(return_value=container))), \
             self.assertRaisesRegex(ValueError, 'decode'), runtime.video_reader(Path('source.mp4')):
            raise ValueError('decode')
        self.assertEqual(events, ['codec', 'container'])

    def test_later_pyav_without_codec_close_and_unopened_codec(self):
        for codec in (SimpleNamespace(is_open=True), SimpleNamespace(is_open=False, close=Mock())):
            container, events = self.reader(codec)
            with patch.dict(sys.modules, av=SimpleNamespace(open=Mock(return_value=container))), \
                 runtime.video_reader(Path('source.mp4')) as actual:
                self.assertIs(actual, container)
            self.assertEqual(events, ['container'])
            if hasattr(codec, 'close'):
                codec.close.assert_not_called()

    def test_codec_close_failure_still_closes_container(self):
        codec = SimpleNamespace(is_open=True, close=Mock(side_effect=RuntimeError('close')))
        container, events = self.reader(codec)
        with patch.dict(sys.modules, av=SimpleNamespace(open=Mock(return_value=container))), \
             self.assertRaisesRegex(RuntimeError, 'close'), runtime.video_reader(Path('source.mp4')):
            pass
        self.assertEqual(events, ['container'])


class InjectionTests(unittest.TestCase):
    def test_injected_inferer_preserves_plan_and_cold_default(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, metadata = root / 'v.mp4', root / 's.json'
            video.write_bytes(b'control')
            doc = sidecar()
            runtime.write_json(metadata, doc)
            injected = Mock(return_value={})
            with patch.object(runtime, 'prepare_video'), patch.object(runtime, 'infer', return_value={}) as cold:
                runtime.run(video, metadata, root / 'warm', 0, False, inferer=injected)
                cold.assert_not_called()
                self.assertEqual(injected.call_args.args[1], runtime.plan_input(doc))
                runtime.run(video, metadata, root / 'cold', 0, False)
                cold.assert_called_once()
            for out in ('warm', 'cold'):
                result = runtime.load_json(root / out / 'handoff.json')
                self.assertEqual(result['source_video_sha256'], runtime.digest(video))
                self.assertEqual(result['source_sidecar_sha256'], runtime.digest(metadata))

    def test_resident_explicit_binding_required_before_any_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, metadata = root / 'v.mp4', root / 's.json'
            video.write_bytes(b'control')
            doc = sidecar()
            runtime.write_json(metadata, doc)
            infer = Mock(return_value={})
            with patch.object(runtime, 'prepare_video') as prepare:
                with self.assertRaisesRegex(ValueError, 'media'):
                    runtime.run(video, metadata, root / 'out', 0, False,
                                inferer=infer, require_media_mapping=True)
                prepare.assert_not_called()
                infer.assert_not_called()
                self.assertFalse((root / 'out').exists())
                doc['media'] = {'binding': 'indexed_presentation_time_us',
                                'presentation_time_us': [str(i * 33333) for i in range(8)]}
                runtime.write_json(metadata, doc)
                runtime.run(video, metadata, root / 'out', 0, False,
                            inferer=infer, require_media_mapping=True)
                self.assertEqual(infer.call_args.args[1]['media'], doc['media'])


if __name__ == '__main__':
    unittest.main()
