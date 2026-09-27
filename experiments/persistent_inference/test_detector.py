"""Exercise generator and predictor disposal without importing Torch or Ultralytics."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from models import Detector


class DetectorTests(unittest.TestCase):
    def detector(self, fail=False, length=2):
        detector = Detector.__new__(Detector)
        detector.callbacks = {'on_predict_start': ['default']}
        weights = object()
        detector.backend = SimpleNamespace(device='cuda', fp16=False)
        yolo = SimpleNamespace(model=weights, predictor=None, callbacks={}, overrides={},
            _smart_load=lambda _: lambda **kw: SimpleNamespace(args=SimpleNamespace()))
        detector.yolo = yolo
        closed = []
        predictors = []
        def track(path, **kwargs):
            self.assertFalse(kwargs['persist'])
            self.assertFalse(kwargs['half'])
            self.assertEqual(yolo.callbacks, detector.callbacks)
            yolo.callbacks['on_predict_start'].append('tracker-callback')
            self.assertIs(yolo.predictor.model, detector.backend)
            vars(yolo.predictor).update(dataset=SimpleNamespace(cap=Mock()),
                                       trackers=[Mock()], vid_writer={}, results=object(), batch=object())
            predictors.append(yolo.predictor)
            def stream():
                try:
                    for i in range(length):
                        if fail:
                            raise ValueError('decode failed')
                        ids = Mock()
                        ids.int.return_value.cpu.return_value.tolist.return_value = [1]
                        boxes = Mock()
                        boxes.cpu.return_value.numpy.return_value = [[0,0,10,10]]
                        yield SimpleNamespace(boxes=SimpleNamespace(id=ids, xyxy=boxes))
                finally:
                    closed.append(True)
            return stream()
        yolo.track = track
        return detector, predictors, closed

    def test_same_filename_four_takes_weights_stable_predictors_discarded(self):
        detector, predictors, closed = self.detector()
        weights = detector.yolo.model
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder)/'observations.mp4'
            path.write_bytes(b'file')
            histories = [detector.track(path) for _ in range(4)]
        self.assertEqual(len(predictors),4)
        self.assertEqual(len(closed),4)
        self.assertIsNone(detector.yolo.predictor)
        self.assertIs(detector.yolo.model, weights)
        self.assertEqual(detector.yolo.callbacks, detector.callbacks)
        for predictor in predictors:
            predictor.dataset.cap.release.assert_called_once()
            predictor.trackers[0].reset.assert_called_once()
        self.assertEqual(histories[0],histories[-1])
        self.assertIsNot(histories[0],histories[-1])

    def test_decode_failure_and_observation_overflow_close_generator(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder)/'observations.mp4'
            path.write_bytes(b'file')
            for fail, length in ((True,2),(False,33)):
                detector, predictors, closed = self.detector(fail,length)
                with self.assertRaises(ValueError):
                    detector.track(path)
                self.assertEqual(closed,[True])
                self.assertIsNone(detector.yolo.predictor)
                predictors[0].dataset.cap.release.assert_called_once()

    def test_no_remote_detector_input(self):
        detector, predictors, closed = self.detector()
        with self.assertRaises(ValueError):
            detector.track('https://example.invalid/input.mp4')
        self.assertEqual(predictors,[])


if __name__ == '__main__':
    unittest.main()
