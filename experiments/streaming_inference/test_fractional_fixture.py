"""Boundary regression for the actual public fixture's 30000/1001 frame rate."""
from fractions import Fraction
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import fixture
import buffered


class Frame:
    width, height, side_data = 1920, 1080, []
    def __init__(self, pts, base=Fraction(1, 30000)):
        self.pts, self.time_base = pts, base
    def to_ndarray(self, format):
        return self.pts


class Container:
    def __init__(self, frames):
        self.frames = frames
        self.streams = NS(video=[NS(average_rate=Fraction(30000, 1001), metadata={})])
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def decode(self, *args, **kwargs): return iter(self.frames)
    def close(self): pass


class BoundaryTests(unittest.TestCase):
    def test_renderer_checks_fractional_playback_not_capture_cutoff(self):
        from inference import verify_rendered_timing
        expected = [Fraction(i*1001, 30000) for i in range(240)]
        manifest = dict(source_frame_count=240, rate='30000/1001')
        verify_rendered_timing(expected, expected, Fraction(1001,125), manifest)
        with self.assertRaises(ValueError):
            verify_rendered_timing(expected, expected, Fraction(8), manifest)
        with self.assertRaises(ValueError):
            verify_rendered_timing(expected[:-1], expected, Fraction(1001,125), manifest)

    def test_excluded_lookahead_need_not_land_exactly_at_eight_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video, calibration, output = root/'drone_video.mp4', root/'drone_calib.txt', root/'out'
            video.write_bytes(b'fake input for boundary control-flow test')
            calibration.write_text('1321 1321 960 540')
            output.mkdir()
            encoded = {}
            def opened(path):
                if Path(path) == video:
                    return Container([Frame(i*1001) for i in range(241)])
                return Container(encoded[str(path)])
            def writer(path, *args):
                path.write_bytes(b'fake encoded fixture')
                encoded[str(path)] = []
                return NS(path=str(path)), None
            def encode(out, stream, image, pts, base):
                encoded[out.path].append(Frame(pts, base))
            av = NS(open=opened)
            cv2 = NS(INTER_AREA=3, resize=lambda image, size, interpolation: image)
            with patch.dict('sys.modules', {'av': av, 'cv2': cv2}), \
                 patch.object(buffered, 'writer', writer), patch.object(buffered, 'encode', encode), \
                 patch.object(buffered, 'close_writer', lambda out, stream: None):
                result = fixture.prepare(video, calibration, output, '960-15')
            self.assertEqual(fixture.playback_duration(result), Fraction(1001,125))
            self.assertEqual(result['source_frame_count'], 240)
            self.assertEqual([len(row['frames']) for row in result['chunks']], [60]*4)
            last = result['chunks'][-1]['frames'][-1]
            self.assertEqual(last['frame_id'], 239)
            self.assertEqual(last['pts_ns'], str(round(Fraction(239*1001, 30000)*10**9)))


if __name__ == '__main__': unittest.main()
