"""CPU scheduling / strict VO / metadata tests. Every model/media dependency is a stand-in."""
from contextlib import ExitStack
import copy
from fractions import Fraction
import json
from pathlib import Path
import queue
import sys
import tempfile
import time
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import uuid

import numpy as np

import experiment
from experiment import Trace, validate_fixture, make_plan
from stream_core import IncrementalSelection, PacedProducer, GlobalPairs
from inference import VO

ROOT=Path(__file__).resolve().parent


def fixture(fps=30):
    origin=Fraction(3,1)
    rows=[dict(frame_id=i,pts_ns=str(round((origin+Fraction(i,fps))*10**9)),image_valid=True,
               original_pts=str(3*fps+i),original_time_base=f'1/{fps}',encoded_pts_seconds=str(Fraction(i%(2*fps),fps))) for i in range(8*fps)]
    return dict(schema='stream-fixture-1',take_id=str(uuid.uuid4()),variant='960-15',width=960,height=540,hz=15,
                K=[[660.5,0,480.],[0,660.5,270.],[0,0,1]],source_duration_s=8,source_frame_count=8*fps,
                original_origin_seconds='3',origin_pts_ns='3000000000',calibration_basis='stand-in only',
                chunks=[dict(index=i,path=f'chunk-{i}.mp4',release_offset_s=2*(i+1),frames=rows[i*2*fps:(i+1)*2*fps]) for i in range(4)])


class MetadataTests(unittest.TestCase):
    def test_resize_and_original_source_clock_validated(self):
        m=fixture();validate_fixture(m)
        for mutate in (lambda x:x['K'][1].__setitem__(1,661),
                       lambda x:x['chunks'].__setitem__(2,x['chunks'][1]),
                       lambda x:x['chunks'][1]['frames'][0].__setitem__('frame_id',0),
                       lambda x:x['chunks'][1]['frames'][0].__setitem__('pts_ns','123')):
            bad=copy.deepcopy(m);mutate(bad)
            with self.assertRaises(ValueError): validate_fixture(bad)

    def test_selected_640_15_fixture_retains_fifteen_hz_and_source_clock(self):
        m=fixture()
        m.update(variant='640-15',width=640,height=360,hz=15,
                 K=[[1321/3,0,320.],[0,1321/3,180.],[0,0,1]])
        validate_fixture(m)
        m['hz']=10
        with self.assertRaises(ValueError): validate_fixture(m)

    def test_eight_second_fifteen_fps_plan_preserves_final_source_frame(self):
        m = fixture(fps=15)
        validate_fixture(m)
        selector = IncrementalSelection(15)
        for chunk in m['chunks']:
            selector.append(chunk['frames'])
        selector.finish()
        plan, sidecar = make_plan(m, selector, [])
        self.assertEqual(plan['sampling']['observation_indices'], list(range(120)))
        self.assertEqual(plan['sampling']['grid_to_observation'][-1], 119)
        self.assertEqual(plan['selected_indices'][-1], 119)
        self.assertEqual(plan['frame_mapping'][-1]['source_frame_id'], 119)
        self.assertEqual(plan['frame_mapping'][-1]['source_pts_ns'], '10933333333')
        self.assertEqual(sidecar['frames'], [row for chunk in m['chunks'] for row in chunk['frames']])

    def test_trace_cpu_only_span_failure_and_threads(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            trace=Trace(Path(tmp)/'events.jsonl')
            with self.assertRaisesRegex(ValueError,'failure'):
                with trace.span('test',chunk=1): raise ValueError('failure')
            self.assertFalse(trace.events[-1]['ok'])
            self.assertEqual([r['event'] for r in trace.events],['test_start','test_end'])
            rows=[json.loads(s) for s in trace.path.read_text().splitlines()]
            self.assertEqual(rows,trace.events)
            self.assertGreaterEqual(rows[-1]['monotonic_s'],rows[0]['monotonic_s'])


class WatchdogTests(unittest.TestCase):
    def test_deadline_failure_retains_evidence_and_kills_only_child_group(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            child=NS(pid=987654321,poll=lambda:None,wait=lambda:None)
            args=NS(deadline=30,output=Path(tmp))
            with patch('experiment.subprocess.Popen',return_value=child),patch('experiment.os.killpg') as kill, \
                    patch('experiment.time',NS(monotonic=iter([0,31]).__next__)):
                with self.assertRaises(TimeoutError): experiment.supervise(args)
            kill.assert_called_once_with(child.pid,experiment.signal.SIGKILL)
            self.assertFalse(json.loads((Path(tmp)/'supervisor-failure.json').read_text())['fallback_applied'])

    def test_disk_budget_failure_without_large_allocation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            child=NS(pid=987654321,poll=lambda:None,wait=lambda:None)
            args=NS(deadline=30,output=Path(tmp))
            huge=NS(is_file=lambda:True,stat=lambda:NS(st_size=257*1024**2))
            with patch('experiment.subprocess.Popen',return_value=child),patch('experiment.os.killpg'), \
                    patch('experiment.ROOT',NS(rglob=lambda pattern:[huge])):
                with self.assertRaisesRegex(ValueError,'disk budget'): experiment.supervise(args)
            self.assertEqual(json.loads((Path(tmp)/'supervisor-failure.json').read_text())['status'],'failed')


class VOTests(unittest.TestCase):
    def modules(self,stack,fail=False):
        solved=[]
        self.seed_calls=[]
        class Solver:
            def __init__(self,params,seed):
                self.seed=seed
                if seed!=0: raise AssertionError('seed must be explicit zero')
            def solve(self,a,b):
                if fail: raise ValueError('no relative pose')
                solved.append((int(a),int(b)))
                t=np.eye(4);t[0,3]=int(b)-int(a)
                return t
        stack.enter_context(patch.dict(sys.modules,{
            'hmr4d.utils.preproc.relpose.matcher_wrapper':NS(Matcher=lambda name:NS(match_np=lambda a,b:(a.flat[0],b.flat[0]))),
            'hmr4d.utils.preproc.relpose.solver_two_view':NS(CameraParams=lambda *a:a),
            'hmr4d.utils.video_io_utils':NS(read_video_np=lambda path,scale:np.array([np.full((1,1,3),int(i)) for i in path.split(',')],dtype=np.uint8)),
            'adapter':NS(CameraMotionSolver=Solver),
            'cv2':NS(setRNGSeed=lambda seed:self.seed_calls.append((seed,threading.current_thread().name))),
        }))
        return solved

    def test_serial_and_cpu_overlap_same_pairs_accumulation_and_cross_boundary(self):
        for overlap in (False,True):
            with self.subTest(overlap=overlap),ExitStack() as stack,tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                solved=self.modules(stack)
                trace=Trace(Path(tmp)/'events.jsonl')
                vo=VO(fixture(),trace,overlap)
                # One global step phase; no endpoint at per-chunk end 59.
                a=list(range(0,57,8));b=list(range(64,121,8))+[127]
                vo.submit((','.join(map(str,a)),[(i,i) for i in a],0))
                vo.submit((','.join(map(str,b)),[(i,i) for i in b],1))
                transforms,ids=vo.finish();vo.close()
                self.assertEqual(solved,list(zip((a+b)[:-1],(a+b)[1:])))
                self.assertEqual(vo.pairs.ids,solved)
                self.assertIn((56,64),solved)
                self.assertEqual(transforms[-1][0,3],127)
                self.assertEqual(ids,a+b)
                self.assertEqual(self.seed_calls, [(0, 'cpu-vo' if overlap else 'MainThread')]*len(solved))
                threads={e['thread'] for e in trace.events if e['event']=='vo_done'}
                self.assertEqual(threads,{'cpu-vo' if overlap else 'MainThread'})

    def test_no_pose_failure_stops_without_fallback(self):
        for overlap in (False,True):
            with ExitStack() as stack,tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                self.modules(stack,fail=True);trace=Trace(Path(tmp)/'events.jsonl')
                vo=VO(fixture(),trace,overlap)
                with self.assertRaisesRegex(ValueError,'no relative pose'):
                    vo.submit(('0,8',[(0,0),(8,8)],0));vo.finish()
                vo.close()
                self.assertEqual(len(vo.transforms),1)

    def test_cpu_vo_queue_is_bounded_and_does_not_call_cuda_metrics(self):
        with ExitStack() as stack,tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            self.modules(stack)
            with patch('inference.threading.Thread.start'):
                vo=VO(fixture(),Trace(Path(tmp)/'events.jsonl'),True)
            vo.submit(('0',[(0,0)],0));vo.submit(('8',[(8,8)],1))
            with self.assertRaises(queue.Full): vo.submit(('16',[(16,16)],2))
            vo.close()


class SchedulingTests(unittest.TestCase):
    def test_all_three_modes_only_consume_released_chunks_and_one_final_call(self):
        # Scale wall clock for a quick *CPU stand-in* test. Production always uses
        # real monotonic seconds and exactly 2/4/6/8-second release offsets.
        clock=lambda:time.monotonic()*4
        m=fixture()
        class Tracker:
            def __init__(self,unused): self.frames=0;self.snapshots=[];self.track_id=1
            def begin(self): pass
            def end(self): pass
        class Motion:
            def __init__(self,*args): self.error=None;self.pairs=GlobalPairs()
            def submit(self,task):
                for grid,source in task[1]: self.pairs.append(grid,source)
            def finish(self): return [],[i for i,_ in self.pairs.sources]
            def close(self): pass
        def producer(chunks,origin,emit):
            p=PacedProducer(chunks,origin,emit,monotonic=clock)
            p.wait=lambda seconds:p.cancel.wait(seconds/4)
            return p
        calls=[];decoder=[]
        def decode(folder,manifest,row):
            decoder.append((row['index'],clock()))
            return list(range(row['index']*60,(row['index']+1)*60))
        def observe(worker,tracker,path,count,trace,index):
            tracker.frames+=count
            trace.emit('observation_done',chunk=index,count=count)
            for stage in ('pose','features'):
                for start in range(0,count,worker.settings['batch_size']):
                    trace.emit('neural_batch_done',stage=stage,chunk=index,count=min(worker.settings['batch_size'],count-start))
            return None
        def reconstruct(worker,plan,parts,transforms,samples,output,trace,tracker):
            calls.append(plan)
            trace.emit('native_verified')
            return dict(counters={})
        def render(m,f,o,n,trace):
            for event in ('annotation_package_verified','first_rendered_frame','video_closed','video_decoded_verified'):trace.emit(event)
        with ExitStack() as stack,tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            # Pure validation/reference uses the inspected processing package,
            # imported read-only with bytecode disabled by test command.
            stack.enter_context(patch.dict(sys.modules,{'torch':NS(manual_seed=lambda n:None,
                cuda=NS(manual_seed_all=lambda n:None,synchronize=lambda:None)),
                'metrics':NS(host_memory=lambda:{})}))
            for target,value in (
                ('experiment.time',NS(monotonic=clock)),('experiment.ContinuousTracker',Tracker),
                ('experiment.PacedProducer',producer),('experiment.decode_released',decode),
                ('experiment.write_video',lambda *a:None),('inference.VO',Motion),
                ('inference.observe',observe),('inference.reconstruct',reconstruct),('inference.render',render)):
                stack.enter_context(patch(target,value))
            worker=NS(settings=dict(batch_size=8),store=NS(models={'detector':None},constructors={'detector':1},uses={}),
                      metrics=NS(memory=lambda:{},events=[],peaks={}))
            reports=[]
            for i,mode in enumerate(experiment.MODES):
                reports.append(experiment.run_take(worker,m,Path(tmp),Path(tmp)/mode,mode,i))
            for report in reports:
                self.assertEqual(report['status'],'complete')
                emitted={e['chunk']:e['actual_s'] for e in report['events'] if e['event']=='chunk_release'}
                received={e['chunk']:e['monotonic_s'] for e in report['events'] if e['event']=='chunk_receive'}
                for i in range(4):self.assertGreaterEqual(received[i],emitted[i])
                if report['mode']=='after-stop':
                    self.assertEqual(report['completed_observations_before_stop'],0)
                    self.assertGreaterEqual(min(received.values()),report['stop_s'])
                else:self.assertGreater(report['completed_observations_before_stop'],0)
            self.assertEqual(len(calls),3)
            for plan in calls:
                self.assertEqual(plan['sampling'],calls[0]['sampling'])
                self.assertEqual(plan['vo_pairs'],calls[0]['vo_pairs'])
                self.assertEqual(plan['source_frames'][0]['pts_ns'],'3000000000')
                self.assertEqual(plan['vo_pairs'][-1],[232,239])
            for report,group in zip(reports,[decoder[i:i+4] for i in range(0,12,4)]):
                for index,when in group:self.assertGreaterEqual(when,report['capture_origin_s']+2*(index+1))


if __name__=='__main__':unittest.main()
