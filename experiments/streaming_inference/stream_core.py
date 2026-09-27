"""Small CPU contracts for one bounded eight-second take; no model imports."""
from bisect import bisect_left, bisect_right
from fractions import Fraction
import math
from pathlib import Path
import queue
import threading
import time


class IncrementalSelection:
    """Nearest sampling waits for a right bracket; only EOS may clamp a target."""
    def __init__(self, hz):
        if hz not in (10, 15): raise ValueError('observation Hz must be 10 or 15')
        self.hz, self.rows, self.times = hz, [], []
        self.observations, self.grid, self.samples = [], [], []
        self.next_obs, self.done = 0, False

    def _nearest(self, target):
        r = bisect_left(self.times, target)
        return min((i for i in (r-1, r) if 0 <= i < len(self.times)),
                   key=lambda i: (abs(self.times[i]-target), i))

    def _advance(self, final=False):
        a, b = len(self.observations), len(self.samples)
        origin, last = self.times[0], self.times[-1]
        # Only EOS may include a target rounded up to 1ns beyond the final PTS.
        limit = last + (1 if final else 0)
        while origin+Fraction(self.next_obs*10**9, self.hz) <= limit:
            selected = self._nearest(origin+Fraction(self.next_obs*10**9, self.hz))
            if not self.observations or self.observations[-1] != selected:
                self.observations.append(selected)
            self.next_obs += 1
        count = (last-origin)*30//10**9+1
        if final and abs(Fraction(count*10**9, 30)-(last-origin)) <= 1: count += 1
        while len(self.grid) < count:
            i = len(self.grid)
            self.grid.append(self._nearest(origin+Fraction(i*10**9, 30)))
            if i % 8 == 0: self.samples.append((i, self.grid[-1]))
        if final and self.samples[-1][0] != len(self.grid)-1:
            self.samples.append((len(self.grid)-1, self.grid[-1]))
        return self.observations[a:], self.samples[b:]

    def append(self, rows):
        if self.done or not rows or len(self.rows)+len(rows)>600: raise ValueError('invalid append/bound')
        previous = self.times[-1] if self.times else None
        prior_id = self.rows[-1]['frame_id'] if self.rows else -1
        for row in rows:
            t = int(row['pts_ns'])
            if (row['image_valid'] is not True or type(row['frame_id']) is not int or row['frame_id'] <= prior_id
                    or (previous is not None and not 0 < t-previous <= 100_000_000)):
                raise ValueError('invalid source order, ID, image or gap')
            previous, prior_id = t, row['frame_id']
        origin=self.times[0] if self.times else int(rows[0]['pts_ns'])
        if int(rows[-1]['pts_ns'])-origin >= 8*10**9:
            raise ValueError('take exceeds first eight seconds')
        self.rows.extend(rows); self.times.extend(int(r['pts_ns']) for r in rows)
        return self._advance()

    def finish(self):
        if self.done or len(self.rows)<2: raise ValueError('invalid EOS')
        result = self._advance(final=True)
        self.done = True
        return result

    def result(self):
        if not self.done: raise ValueError('selection not finalized')
        times = [self.times[i] for i in self.observations]
        hold = [max(0, bisect_right(times, self.times[0]+round(Fraction(i*10**9,30)))-1)
                for i in range(len(self.grid))]
        return dict(observation_indices=self.observations, grid_to_observation=hold,
                    vo_source_indices=self.grid, vo_sample_indices=[i for i, _ in self.samples])


class GlobalPairs:
    def __init__(self): self.previous, self.ids, self.sources, self.ended = None, [], [], False

    def append(self, grid, source):
        if self.ended or (self.previous is None and grid != 0): raise ValueError('invalid first VO sample')
        if self.previous is not None:
            if not 0 < grid-self.previous <= 8: raise ValueError('invalid global VO pair')
            self.ids.append((self.previous, grid))
            self.ended = grid-self.previous != 8
        self.sources.append((grid, source)); self.previous=grid


class PacedProducer:
    """Absolute releases; never block/stall the capture clock on backpressure."""
    def __init__(self, chunks, origin, emit, capacity=4, monotonic=time.monotonic, wait=None):
        if chunks != [0,1,2,3] or not 1<=capacity<=4: raise ValueError('require four ordered chunks')
        self.chunks, self.origin, self.emit = chunks, origin, emit
        self.queue, self.error = queue.Queue(capacity), None
        self.cancel, self.eos = threading.Event(), threading.Event()
        self.clock, self.wait = monotonic, wait or self.cancel.wait
        self.thread = threading.Thread(target=self.publish, name='paced-input', daemon=True)
        self.stop_s = None

    def publish(self):
        try:
            for index in self.chunks:
                scheduled=self.origin+2*(index+1)
                while self.clock()<scheduled:
                    if self.wait(scheduled-self.clock()): raise RuntimeError('capture cancelled')
                actual=self.clock()
                if actual-scheduled>.25: raise TimeoutError('release missed absolute deadline by >250ms')
                depth=self.queue.qsize()+1
                self.queue.put_nowait((index, actual))
                # Timestamp immediately before nonblocking publication, not
                # before potentially slow JSONL I/O. Consumer logs may race this
                # log entry; the explicit actual_s is the availability clock.
                self.emit('chunk_release', chunk=index, scheduled_s=scheduled, actual_s=actual,backlog=depth)
            self.stop_s=self.clock()
            self.emit('stop', scheduled_s=self.origin+8, actual_s=self.stop_s)
        except BaseException as error:
            self.error=error
        finally:
            self.eos.set()

    def receive(self):
        while True:
            if self.error: raise self.error
            try: return self.queue.get(timeout=.05)
            except queue.Empty:
                if self.eos.is_set(): raise ValueError('missing/extra chunk')

    def close(self):
        self.cancel.set()
        if self.thread.is_alive(): self.thread.join(timeout=1)


class ContinuousTracker:
    """Experiment lifecycle around the retained pinned Detector/AutoBackend."""
    def __init__(self, detector, reset=None):
        if reset is None:
            from lifecycle import reset_detector
            reset=reset_detector
        self.detector, self.reset = detector, reset
        self.active=False

    def begin(self):
        if self.active: raise ValueError('take already active')
        d=self.detector
        self.reset(d.yolo, d.callbacks)
        p=d.new_predictor()
        p.model, p.device, p.args.half=d.backend, d.backend.device, d.backend.fp16
        d.yolo.predictor=p
        self.predictor, self.tracker, self.track_id, self.frames = p, None, None, 0
        self.callback_counts=None
        self.snapshots=[]
        self.active=True

    def append(self, path, count):
        results=None
        try:
            if not self.active or not Path(path).is_file() or not 1<=count<=33 or self.frames+count>122:
                raise ValueError('invalid tracker append')
            d=self.detector
            results=d.yolo.track(str(path), device='cuda', conf=.5, classes=0, verbose=False,
                                 stream=True, persist=True, save=False, half=False, tracker='botsort.yaml')
            boxes=[]
            for result in results:
                if result.boxes.id is None: raise ValueError('missing track')
                ids=result.boxes.id.int().cpu().tolist()
                if len(ids)!=1: raise ValueError('require exactly one tracked person')
                if self.track_id is None: self.track_id=ids[0]
                if ids[0]!=self.track_id: raise ValueError('track ID changed; no relabel/interpolation')
                box=[float(x) for x in result.boxes.xyxy.cpu().numpy()[0]]
                if (len(box)!=4 or not all(math.isfinite(x) for x in box) or box[2]<=box[0] or box[3]<=box[1]):
                    raise ValueError('invalid bounding box')
                boxes.append(box)
                if len(boxes)>count: raise ValueError('excess tracking frames')
            if len(boxes)!=count: raise ValueError('tracking count mismatch')
            p=d.yolo.predictor
            if p is not self.predictor or len(p.trackers)!=1: raise ValueError('predictor/tracker changed')
            counts={k:len(v) for k,v in d.yolo.callbacks.items()}
            if self.tracker is not None and (p.trackers[0] is not self.tracker or counts!=self.callback_counts):
                raise ValueError('tracker state/callback continuity lost')
            self.tracker, self.callback_counts=p.trackers[0], counts
            self.frames+=count
            if self.tracker.frame_id!=self.frames: raise ValueError('tracker frame counter reset or skipped a processed frame')
            self.snapshots.append(dict(predictor_id=id(p), tracker_id=id(self.tracker),
                                       tracker_frame_id=self.tracker.frame_id, callbacks=counts,
                                       gmc_id=id(getattr(self.tracker,'gmc',None)),
                                       tracked=len(getattr(self.tracker,'tracked_stracks',())),
                                       lost=len(getattr(self.tracker,'lost_stracks',())),
                                       removed=len(getattr(self.tracker,'removed_stracks',())),
                                       processed_frames=self.frames, track_id=self.track_id))
            return boxes
        except BaseException:
            self.end()
            raise
        finally:
            if results is not None: results.close()
            cap=getattr(getattr(self.predictor, 'dataset', None), 'cap', None)
            if cap is not None: cap.release()

    def end(self):
        if self.active:
            self.reset(self.detector.yolo, self.detector.callbacks)
            self.active=False
