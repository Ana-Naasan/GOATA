"""Real codec checks when the inference runtime's PyAV dependency is installed."""

import importlib.util
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from test_runtime import sidecar

from processing.reconstruction import runtime


@unittest.skipUnless(importlib.util.find_spec('av'), 'PyAV unavailable; run inside the built runtime')
class MediaRuntimeTests(unittest.TestCase):
    def make_video(self, path):
        import av
        with av.open(str(path), 'w') as output:
            stream = output.add_stream('libx264', rate=30)
            stream.width, stream.height, stream.pix_fmt = 64, 48, 'yuv420p'
            for i in range(8):
                frame = av.VideoFrame(64, 48, 'rgb24')
                for plane in frame.planes:
                    plane.update(bytes([i * 20]) * plane.buffer_size)
                frame.pts, frame.time_base = i, Fraction(1, 30)
                for packet in stream.encode(frame):
                    output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)

    def test_actual_decode_bind_prepare_and_reopen(self):
        import av
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original, prepared = root / 'source.mp4', root / 'prepared.mp4'
            self.make_video(original)
            doc = sidecar()
            doc['image'].update(width_px=64, height_px=48)
            plan = runtime.plan_input(doc)
            with patch.object(runtime, 'video_reader', wraps=runtime.video_reader) as reader:
                runtime.prepare_video(original, prepared, plan, 1000000000)
            self.assertEqual([call.args for call in reader.call_args_list],
                             [(original,), (original,), (prepared,)])
            self.assertEqual(plan['decoder_binding']['offset_ns'], '1000000000')
            with av.open(str(prepared)) as container:
                frames = list(container.decode(video=0))
            self.assertEqual(len(frames), len(plan['selected_indices']))
            self.assertEqual([Fraction(f.pts) * f.time_base for f in frames],
                             [Fraction(i, 30) for i in range(len(frames))])
            means = [float(f.to_ndarray(format='rgb24').mean()) for f in frames]
            self.assertEqual(means, sorted(means))
            self.assertGreater(means[-1] - means[0], 100)

    def test_actual_equal_count_wrong_clock_rejected_before_encoding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_video(root / 'source.mp4')
            doc = sidecar()
            doc['image'].update(width_px=64, height_px=48)
            with self.assertRaisesRegex(ValueError, 'PTS'):
                runtime.prepare_video(root / 'source.mp4', root / 'prepared.mp4', runtime.plan_input(doc), 0)
            self.assertFalse((root / 'prepared.mp4').exists())


if __name__ == '__main__':
    unittest.main()
