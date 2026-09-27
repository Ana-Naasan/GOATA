"""CPU-only contract tests; no learned inference or fabricated GPU measurements."""
import ast
from bisect import bisect_right
from fractions import Fraction
from functools import partial
import hashlib
import json
import importlib.util
import os
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from stream_core import IncrementalSelection, PacedProducer, ContinuousTracker, GlobalPairs

ROOT = Path(__file__).resolve().parent


def frames(times):
    return [dict(frame_id=i, pts_ns=str(t), image_valid=True) for i, t in enumerate(times)]


def offline(rows, hz):
    times = [int(r['pts_ns']) for r in rows]
    nearest = lambda t: min(range(len(times)), key=lambda i: (abs(times[i]-t), i))
    obs = sorted({nearest(times[0]+Fraction(i*10**9, hz))
                  for i in range((times[-1]-times[0])*hz//10**9+1)})
    n = (times[-1]-times[0])*30//10**9+1
    if abs(Fraction(n*10**9, 30)-(times[-1]-times[0])) <= 1:
        n += 1
    vo = [nearest(times[0]+Fraction(i*10**9, 30)) for i in range(n)]
    hold = [max(0, bisect_right([times[i] for i in obs], times[0]+round(Fraction(i*10**9, 30)))-1)
            for i in range(n)]
    return dict(observation_indices=obs, grid_to_observation=hold, vo_source_indices=vo,
                vo_sample_indices=list(range(0, n, 8))+([] if (n-1)%8 == 0 else [n-1]))


class SelectionTests(unittest.TestCase):
    def test_pending_boundary_earlier_tie_and_latest_hold(self):
        s = IncrementalSelection(15)
        rows = frames([0, 50_000_000, 83_333_334, 130_000_000, 160_000_000])
        self.assertEqual(s.append(rows[:2])[0], [0])  # 66.666ms needs right bracket
        self.assertEqual(s.append(rows[2:])[0], [1, 3])  # earlier tie at 66.666667
        s.finish()
        self.assertEqual(s.result(), offline(rows, 15))
        self.assertEqual(s.result()['grid_to_observation'][:4], [0, 0, 1, 1])

    def test_incremental_equals_offline_irregular_all_splits_and_rates(self):
        times = [7_000_000_000]
        for i in range(237):
            times.append(times[-1]+[31_000_000, 34_000_000, 36_000_000][i%3])
        rows = frames(times)
        for hz in (10, 15):
            for size in (1, 7, 59, 60, 61):
                s = IncrementalSelection(hz)
                for i in range(0, len(rows), size):
                    s.append(rows[i:i+size])
                s.finish()
                self.assertEqual(s.result(), offline(rows, hz))

    def test_eos_rounded_grid_endpoint_and_deduplication(self):
        for last in (99_999_999, 100_000_000, 100_000_001):
            rows = frames([0, 50_000_000, last])
            s = IncrementalSelection(15)
            s.append(rows)
            s.finish()
            self.assertEqual(s.result(), offline(rows, 15))
        s = IncrementalSelection(15)
        s.append(frames([0, 100_000_000, 200_000_000]))
        s.finish()
        self.assertEqual(s.result()['observation_indices'], [0, 1, 2])

    def test_invalid_frames_and_finalization(self):
        for times in ([0, 0], [10, 9], [0, 100_000_001]):
            with self.assertRaises(ValueError):
                IncrementalSelection(15).append(frames(times))
        s = IncrementalSelection(15)
        s.append(frames([0, 33_333_333]))
        with self.assertRaises(ValueError):
            s.append([dict(frame_id=0, pts_ns='66666667', image_valid=True)])
        s.finish()
        with self.assertRaises(ValueError):
            s.append(frames([100_000_000]))

    def test_global_vo_pairs_include_seams_and_only_final_endpoint(self):
        s = IncrementalSelection(15)
        rows = frames([round(Fraction(i*10**9, 30)) for i in range(240)])
        seen = []
        for i in range(0, 240, 60):
            _, samples = s.append(rows[i:i+60])
            seen.extend(samples)
        seen.extend(s.finish()[1])
        pairs = GlobalPairs()
        for grid, source in seen:
            pairs.append(grid, source)
        self.assertEqual(pairs.ids, list(zip(list(range(0, 233, 8)), list(range(8, 233, 8))+[239])))
        self.assertIn((56, 64), pairs.ids)
        self.assertIn((176, 184), pairs.ids)
        self.assertNotIn(59, [x for pair in pairs.ids for x in pair])
        with self.assertRaises(ValueError):
            pairs.append(239, 239)


class Clock:
    def __init__(self): self.now = 100.0
    def monotonic(self): return self.now
    def wait(self, seconds): self.now += seconds; return False


class ProducerTests(unittest.TestCase):
    def producer(self, capacity=4, delay=0):
        clock, events = Clock(), []
        def wait(s): clock.now += s+delay; return False
        p = PacedProducer(list(range(4)), 100., lambda event, **kw: events.append((event, kw)),
                          capacity=capacity, monotonic=clock.monotonic, wait=wait)
        return p, clock, events

    def test_absolute_release_no_future_and_control_withhold(self):
        p, clock, events = self.producer()
        p.publish()
        self.assertIsNone(p.error)
        self.assertEqual([p.receive()[1] for _ in range(4)], [102., 104., 106., 108.])
        self.assertEqual([e[1]['scheduled_s'] for e in events if e[0]=='chunk_release'], [102.,104.,106.,108.])
        self.assertTrue(p.eos.is_set())

    def test_backpressure_fails_not_stretches_or_drops(self):
        p, clock, _ = self.producer(capacity=1)
        p.publish()
        self.assertIsInstance(p.error, queue.Full)
        self.assertEqual(clock.now, 104.)
        with self.assertRaises(queue.Full): p.receive()

    def test_late_release_is_logged_and_excess_delay_fails(self):
        p, _, events = self.producer(delay=.05)
        p.publish()
        self.assertIsNone(p.error)
        self.assertAlmostEqual(events[0][1]['actual_s'], 102.05)
        p, _, _ = self.producer(delay=.5)
        p.publish()
        self.assertIsInstance(p.error, TimeoutError)

    def test_chunk_count_and_order(self):
        with self.assertRaises(ValueError): PacedProducer([0, 1, 1, 3], 0, lambda *a, **k: None)
        with self.assertRaises(ValueError): PacedProducer([0, 1, 2], 0, lambda *a, **k: None)


def pinned_function(name, **namespace):
    source=os.environ.get('PHYSIO_ULTRALYTICS_SOURCE')
    if source:
        root=Path(source)
    else:
        spec=importlib.util.find_spec('ultralytics')
        if spec is None:
            raise unittest.SkipTest('pinned tracker checks require Ultralytics 8.2.42 or PHYSIO_ULTRALYTICS_SOURCE')
        root=Path(spec.origin).parent
    path=root/'trackers/track.py'
    code=Path(os.environ.get('STREAM_SHARED_CODE',str(ROOT.parent/'persistent_inference')))
    identity = json.loads((code/'ultralytics-identity.json').read_text())
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == identity['files']['ultralytics/trackers/track.py']
    node = next(n for n in ast.parse(data).body if getattr(n, 'name', None)==name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


class TrackerTests(unittest.TestCase):
    def standin(self):
        made, registrations = [], []
        def tracker(**kw):
            t = NS(frame_id=0, reset=Mock(), active=[], lost=[], gmc=NS(previous=None))
            made.append(t)
            return t
        on_start = pinned_function('on_predict_start', IterableSimpleNamespace=NS, check_yaml=lambda x:x,
                                   yaml_load=lambda x:dict(tracker_type='botsort'), TRACKER_MAP={'botsort':tracker})
        yolo = NS(predictor=None, callbacks={'on_predict_start':[], 'on_predict_postprocess_end':[]})
        yolo.add_callback = lambda key, fn: yolo.callbacks[key].append(fn)
        register = pinned_function('register_tracker', partial=partial, on_predict_start=on_start,
                                   on_predict_postprocess_end=lambda *a, **kw:None)
        def new(): return NS(args=NS(tracker='botsort.yaml'), callbacks=yolo.callbacks)
        def reset(y, callbacks):
            if y.predictor:
                for t in getattr(y.predictor, 'trackers', []): t.reset()
            y.predictor=None
            y.callbacks={k:list(v) for k,v in callbacks.items()}
        def track(path, **kw):
            self.assertTrue(kw['persist'])
            p = yolo.predictor
            if not hasattr(p, 'trackers'):
                register(yolo, persist=kw['persist']); registrations.append(True)
            p.dataset = NS(bs=1, mode='video', cap=Mock())
            for fn in p.callbacks['on_predict_start']: fn(p)
            t=p.trackers[0]; t.frame_id+=1; t.active.append(path); t.gmc.previous=path
            ids, boxes = Mock(), Mock()
            ids.int.return_value.cpu.return_value.tolist.return_value=[1]
            boxes.cpu.return_value.numpy.return_value=[[1.,2.,30.,40.]]
            yield NS(boxes=NS(id=ids, xyxy=boxes))
        yolo.track=track
        d=NS(yolo=yolo, callbacks={k:[] for k in yolo.callbacks}, new_predictor=new,
             backend=NS(device='cuda', fp16=False))
        return ContinuousTracker(d, reset=reset), made, registrations

    def test_one_predictor_tracker_callbacks_across_chunks_fresh_next_take(self):
        c, made, registered = self.standin()
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            file=Path(tmp)/'obs.mp4'; file.touch()
            predictors=[]
            for take in range(2):
                c.begin(); predictors.append(c.detector.yolo.predictor)
                for i in range(4):
                    self.assertEqual(c.append(file, 1), [[1.,2.,30.,40.]])
                    self.assertIs(c.detector.yolo.predictor, predictors[-1])
                    self.assertEqual(made[-1].frame_id, i+1)
                    self.assertEqual(len(c.detector.yolo.callbacks['on_predict_start']), 1)
                c.end()
                made[-1].reset.assert_called_once()
                self.assertIsNone(c.detector.yolo.predictor)
            self.assertIsNot(predictors[0], predictors[1])
            self.assertEqual(len(made), 2)
            self.assertEqual(len(registered), 2)

    def test_pinned_postprocess_does_not_reset_on_new_chunk_filename(self):
        import numpy as np
        post=pinned_function('on_predict_postprocess_end',Path=Path,torch=NS(as_tensor=lambda a:a))
        class Detections:
            def cpu(self): return self
            def numpy(self): return np.ones((1,6))
        class Result:
            boxes=Detections()
            def __getitem__(self,index): return self
            def update(self,**kw): self.updated=kw
        tracker=NS(reset=Mock(),update=Mock(return_value=np.array([[1.,2.,3.,4.,1.,.9,0.,0.]])))
        p=NS(args=NS(task='detect'),dataset=NS(mode='video'),trackers=[tracker],save_dir=Path('unused'),
             vid_path=[None],batch=(['chunk-0.mp4'],[object()]),results=[Result()])
        post(p,persist=True)
        p.batch=(['chunk-1.mp4'],[object()]);p.results=[Result()]
        post(p,persist=True)
        tracker.reset.assert_not_called()
        self.assertEqual(tracker.update.call_count,2)
        self.assertEqual(p.vid_path,[None])
        self.assertIn('boxes',p.results[0].updated)

    def test_identity_change_or_wrong_count_fails_and_resets(self):
        for bad_count in (True, False):
            c, made, _=self.standin()
            with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                file=Path(tmp)/'obs.mp4'; file.touch()
                c.begin(); c.append(file,1)
                if not bad_count: c.track_id=999
                with self.assertRaises(ValueError): c.append(file,2 if bad_count else 1)
                self.assertIsNone(c.detector.yolo.predictor)
                made[-1].reset.assert_called_once()


if __name__ == '__main__': unittest.main()
