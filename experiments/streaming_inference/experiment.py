#!/usr/bin/env python3
"""Bounded same-pixels control / streaming-serial / streaming-CPU-VO-overlap experiment."""
import argparse
from contextlib import contextmanager
from fractions import Fraction
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from fixture import save, sha, inventory, verify, decode_released, write_video
from stream_core import IncrementalSelection, PacedProducer, ContinuousTracker

PROCESS_ENTRY=time.monotonic()
ROOT=Path(__file__).resolve().parent
MODES=('after-stop','streaming-serial','streaming-cpu-vo-overlap')


class Trace:
    """Thread-safe monotonic journal, deliberately NO torch/CUDA/memory calls."""
    def __init__(self,path):
        self.path=path; self.events=[]; self.lock=threading.Lock()

    def emit(self,event,**fields):
        with self.lock:
            row=dict(event=event,monotonic_s=time.monotonic(),thread=threading.current_thread().name,**fields)
            with self.path.open('a') as f: f.write(json.dumps(row,allow_nan=False)+'\n')
            self.events.append(row)
        return row

    @contextmanager
    def span(self,name,**fields):
        start=self.emit(name+'_start',**fields)['monotonic_s']; ok=False
        try:
            yield
            ok=True
        finally: self.emit(name+'_end',start_s=start,seconds=time.monotonic()-start,ok=ok,**fields)


def validate_fixture(m):
    from fast import VARIANTS
    width,hz=VARIANTS[m['variant']]
    scale=width/1920
    expected=[[1321*scale,0,960*scale],[0,1321*scale,540*scale],[0,0,1]]
    if (m['schema']!='stream-fixture-1' or m['width']!=width or m['height']!=width*9//16 or m['hz']!=hz
            or m['K']!=expected or m['source_duration_s']!=8 or len(m['chunks'])!=4):
        raise ValueError('fixture calibration/resize/contract mismatch')
    total=0
    for i,row in enumerate(m['chunks']):
        if (row['index']!=i or row['path']!=f'chunk-{i}.mp4' or row['release_offset_s']!=2*(i+1)
                or not 2<=len(row['frames'])<=120): raise ValueError('missing/duplicate/reordered chunk')
        for r in row['frames']:
            original=Fraction(r['original_pts'])*Fraction(r['original_time_base'])
            if (r['frame_id']!=total or str(round(original*10**9))!=r['pts_ns'] or r['image_valid'] is not True
                    or not 2*i<=original-Fraction(m['original_origin_seconds'])<2*(i+1)):
                raise ValueError('invalid original source clock or chunk binding')
            total+=1
    if total!=m['source_frame_count'] or not 80<=total<=480: raise ValueError('source count bound')


def make_plan(manifest,selector,availability):
    from bisect import bisect_right
    from processing.reconstruction.runtime import plan_input
    from processing.reconstruction.timing import map_selected_frames
    k=manifest['K']
    sidecar=dict(schema_version='1.0',take_id=manifest['take_id'],adapter=dict(name='paced-public-WHAM',version='1'),
                 image=dict(width_px=manifest['width'],height_px=manifest['height'],rotation_degrees=0,mirrored=False),
                 camera=dict(id='WHAM-drone-provided-calibration',calibration_status='estimated',
                             intrinsics=dict(fx=k[0][0],fy=k[1][1],cx=k[0][2],cy=k[1][2]),
                             distortion_model='none',distortion_coefficients=[]),
                 clock=dict(id=manifest['take_id'],unit='nanoseconds',origin_pts_ns=manifest['origin_pts_ns']),
                 frames=selector.rows,capture=dict(view='other',condition='exercise',side='not_applicable',interrupted=False),
                 fixture=manifest,calibration_assumption=manifest['calibration_basis'])
    plan=plan_input(sidecar)
    actual=selector.result(); times=selector.times; hz=selector.hz
    # Independent whole-take reference, evaluated ONLY after EOS; no image/feature cache.
    duration=times[-1]-times[0]
    count=duration*hz//10**9+1
    if abs(Fraction(count*10**9,hz)-duration)<=1: count+=1
    obs=sorted({min(range(len(times)),key=lambda j:(abs(times[j]-times[0]-Fraction(i*10**9,hz)),j))
                for i in range(count)})
    hold=[max(0,bisect_right([times[j] for j in obs],times[0]+round(Fraction(i*10**9,30)))-1)
          for i in range(len(plan['selected_indices']))]
    samples=list(range(0,len(hold),8))
    if samples[-1]!=len(hold)-1: samples.append(len(hold)-1)
    expected=dict(observation_indices=obs,grid_to_observation=hold,vo_source_indices=plan['selected_indices'],vo_sample_indices=samples)
    if actual!=expected: raise ValueError('incremental selections differ from independent whole-take reference')
    plan['sampling']=actual
    plan['selected_indices']=[obs[i] for i in hold]
    plan['frame_mapping']=map_selected_frames(selector.rows,plan['selected_indices'])
    for i,row in enumerate(plan['frame_mapping']):
        row.update(inference_time_s=i/30,observation_index=hold[i],
                   evidence='latest selected observation held; whole-take fitted estimate, not live prediction')
    plan.update(source_availability=availability,offline_selection_exact=True,
                resampling=f'{hz}Hz nearest with right bracket, earlier tie, rounded-ns 30Hz latest hold')
    return plan,sidecar


def run_take(worker,manifest,fixture,output,mode,ordinal):
    import torch
    from inference import VO,observe,reconstruct,render
    from metrics import host_memory
    output.mkdir(); trace=Trace(output/'events.jsonl')
    metric_index=len(worker.metrics.events)
    selector=IncrementalSelection(manifest['hz'])
    tracker=ContinuousTracker(worker.store.models['detector'])
    vo=producer=None
    torch.manual_seed(0); torch.cuda.manual_seed_all(0)
    setup_start=time.monotonic()
    try:
        tracker.begin()
        vo=VO(manifest,trace,mode=='streaming-cpu-vo-overlap')
        torch.cuda.synchronize()
        before=worker.metrics.memory()
        origin=time.monotonic()
        trace.emit('capture_start',origin_s=origin,mode=mode,ordinal=ordinal,
                   source_take_id=manifest['take_id'],constructors=dict(worker.store.constructors))
        producer=PacedProducer([0,1,2,3],origin,trace.emit)
        producer.thread.start()
        if mode=='after-stop':
            producer.eos.wait()  # explicit control withholding, NOT claimed as inference
            if producer.error: raise producer.error
        previous=None; parts=[]; availability=[]; observation_chunks=[]
        for expected in range(4):
            index,released=producer.receive()
            if index!=expected or time.monotonic()<released or released<origin+2*(index+1):
                raise ValueError('future/duplicate/out-of-order release')
            row=manifest['chunks'][index]
            trace.emit('chunk_receive',chunk=index,released_s=released,backlog=producer.queue.qsize())
            with trace.span('released_decode_selection_prepare',chunk=index):
                images=decode_released(fixture,manifest,row)
                trace.emit('receive_verified',chunk=index,first_source_frame_id=row['frames'][0]['frame_id'],
                           last_source_frame_id=row['frames'][-1]['frame_id'])
                offset=len(selector.rows)
                image_map={offset+i:image for i,image in enumerate(images)}
                if previous is not None: image_map[previous[0]]=previous[1]
                selected,samples=selector.append(row['frames'])
                if index==3:
                    producer.eos.wait()
                    if producer.error: raise producer.error
                    tail_obs,tail_vo=selector.finish(); selected+=tail_obs; samples+=tail_vo
                for r in row['frames']:
                    availability.append(dict(source_frame_id=r['frame_id'],source_pts_ns=r['pts_ns'],
                                             chunk=index,available_s=released))
                obs_path=output/f'observations-{index}.mp4'; vo_path=output/f'vo-{index}.mp4'
                obs_identity=write_video(obs_path,[image_map[i] for i in selected],manifest['width'],manifest['height'])
                vo_identity=write_video(vo_path,[image_map[i] for _,i in samples],manifest['width'],manifest['height'])
                observation_chunks.append(dict(chunk=index,source_indices=selected,vo_samples=samples,
                                               observations=obs_identity,vo=vo_identity))
                previous=(offset+len(images)-1,images[-1])
                del image_map,images
            task=(vo_path,samples,index)
            if mode=='streaming-cpu-vo-overlap': vo.submit(task)
            parts.append(observe(worker,tracker,obs_path,len(selected),trace,index))
            if mode!='streaming-cpu-vo-overlap': vo.submit(task)
            if vo.error: raise vo.error
        previous=None
        transforms,samples=vo.finish()
        trace.emit('drain_complete')
        if producer.stop_s is None or producer.error: raise RuntimeError('capture did not complete')
        stop=origin+8  # capture end, NOT late EOS availability; never subtract delivery skew from tail
        done_before_stop=sum(e['count'] for e in trace.events if e['event']=='observation_done' and e['monotonic_s']<stop)
        if mode!='after-stop' and done_before_stop==0:
            raise RuntimeError('no completed observations before EOS; streaming acceptance failed, no fake idle claim')
        if tracker.frames!=len(selector.observations): raise ValueError('incomplete observations')
        plan,sidecar=make_plan(manifest,selector,availability)
        plan['observation_chunks']=observation_chunks
        plan['vo_pairs']=[list(pair) for pair in vo.pairs.ids]
        save(output/'selection.json',plan); save(output/'source-sidecar.json',sidecar)
        native=reconstruct(worker,plan,parts,transforms,samples,output,trace,tracker)
        render(manifest,fixture,output,native,trace)
        tracker.end()
        events=list(trace.events)
        when=lambda name:next(e['monotonic_s'] for e in events if e['event']==name)
        latencies={name:when(event)-stop for name,event in
                   (('stop_to_native_verified_s','native_verified'),
                    ('stop_to_annotation_package_verified_s','annotation_package_verified'),
                    ('stop_to_first_rendered_frame_s','first_rendered_frame'),
                    ('stop_to_video_closed_s','video_closed'),
                    ('stop_to_video_closed_decoded_s','video_decoded_verified'))}
        chunks=[e for e in events if e['event']=='observation_done']
        counters=dict(native['counters'])
        for stage,key in (('pose','pose_calls'),('features','feature_calls')):
            completed=[e for e in events if e['event']=='neural_batch_done' and e['stage']==stage]
            counters[key]=len(completed)
            if (sum(e['count'] for e in completed)!=tracker.frames
                    or len(completed)!=sum((e['count']+worker.settings['batch_size']-1)//worker.settings['batch_size'] for e in chunks)):
                raise ValueError('completed neural calls/frames mismatch')
        report=dict(status='complete',mode=mode,ordinal=ordinal,first_take_in_process=ordinal==0,
                    source_take_id=manifest['take_id'],capture_origin_s=origin,stop_s=stop,eos_available_s=producer.stop_s,
                    take_setup_excluded_s=origin-setup_start,
                    take_setup_scope='fresh predictor, SIFT matcher, seeded CPU VO solver, synchronized resident readiness; no input work',
                    stop_definition='scheduled eight-second source capture end; release skew remains in output latency',latencies=latencies,
                    source_first_available_s=availability[0]['available_s'],source_last_available_s=availability[-1]['available_s'],
                    source_first_available_offset_s=availability[0]['available_s']-origin,
                    source_last_available_offset_s=availability[-1]['available_s']-origin,
                    completed_observations_before_stop=done_before_stop,
                    completed_vo_pairs_before_stop=sum(e['event']=='vo_pair_end' and e.get('previous') is not None and e['monotonic_s']<stop for e in events),
                    post_stop_drain_s=when('drain_complete')-stop,
                    maximum_input_queue_depth=max(e['backlog'] for e in events if e['event']=='chunk_release'),
                    maximum_vo_queue_depth=max((e['backlog'] for e in events if e['event']=='vo_submitted'),default=0),
                    source_availability=availability,constructors=dict(worker.store.constructors),model_uses=dict(worker.store.uses),
                    take_state_constructors=dict(predictor=1,botsort=1,sift_matcher=1,vo_solver=1),
                    counters=counters,host_memory=host_memory(),before_capture=before,after=worker.metrics.memory(),
                    process_gpu_peaks_bytes=dict(worker.metrics.peaks),
                    take_gpu_peaks_bytes={kind:max((e.get('peak_'+kind+'_bytes',0) for e in worker.metrics.events[metric_index:]),default=0)
                                          for kind in ('allocated','reserved')},events=events,
                    input_derived_cache_before_clock=False,clinical_findings_available=False)
        save(output/'result.json',report)
        return report
    except BaseException as error:
        trace.emit('failure',error_type=type(error).__name__,error=str(error),fallback_applied=False)
        save(output/'failure.json',dict(status='failed',error=repr(error),fallback_applied=False,events=trace.events))
        raise
    finally:
        tracker.end()
        if producer is not None: producer.close()
        if vo is not None: vo.close()


def compare(output,order):
    import numpy as np
    ref=output/'after-stop'
    a=json.loads((ref/'selection.json').read_text())
    comparisons={}
    for mode in order:
        folder=output/mode; b=json.loads((folder/'selection.json').read_text())
        for field in ('sampling','selected_indices','vo_pairs'):
            if a[field]!=b[field]: raise ValueError('scheduling changed '+field)
        for x,y in zip(a['observation_chunks'],b['observation_chunks']):
            for field in ('chunk','source_indices','vo_samples'):
                if x[field]!=y[field]: raise ValueError('scheduling changed prepared inputs')
            for kind in ('observations','vo'):
                for field in ('decoded_bgr24_sha256','frame_count'):
                    if x[kind][field]!=y[kind][field]: raise ValueError('prepared pixels differ across modes')
        deltas={}
        def delta(name,x,y):
            if x.shape!=y.shape or not np.isfinite(x).all() or not np.isfinite(y).all(): raise ValueError('comparison shape/finite mismatch')
            diff=np.abs(x.astype(np.float64)-y.astype(np.float64))
            deltas[name]=dict(max_abs=float(diff.max()),rms=float(np.sqrt(np.mean(diff**2))))
        with np.load(ref/'intermediates.npz',allow_pickle=False) as x,np.load(folder/'intermediates.npz',allow_pickle=False) as y:
            for name in x.files: delta(name,x[name],y[name])
        for name in ('joints.f32','incam-joints.f32','vertices.f32'):
            # Bounded arrays: <=31MiB each at 240 frames, FP64 difference <=63MiB.
            delta(name,np.fromfile(ref/name,dtype='<f4'),np.fromfile(folder/name,dtype='<f4'))
        for space in ('smpl_params_global','smpl_params_incam'):
            x=json.loads((ref/'parameters.json').read_text())[space]
            y=json.loads((folder/'parameters.json').read_text())[space]
            for name in x: delta(space+'.'+name,np.asarray(x[name]),np.asarray(y[name]))
        x=json.loads((ref/'observations.json').read_text());y=json.loads((folder/'observations.json').read_text())
        delta('camera_rotation',np.asarray(x['camera_rotation_w2c']),np.asarray(y['camera_rotation_w2c']))
        comparisons[mode]=dict(selection_and_pairs_exact=True,prepared_pixels_exact=True,deltas=deltas,
                               acceptance='numerical deltas reported, not a clinical threshold or bitwise-equivalence claim')
    return comparisons


def execute(args):
    from metrics import Metrics
    import torch
    from hmr4d import PROJ_ROOT
    from hmr4d.utils.preproc import Extractor,VitPoseExtractor
    from hmr4d.utils.smplx_utils import make_smplx
    from adapter import ASSETS,load_demo_model
    from models import WorkerModels,Detector
    from worker import dependency_identity
    from processing.reconstruction.native import UPSTREAM_COMMIT
    from processing.reconstruction.runtime import digest
    manifest_path=args.fixture/'fixture.json'
    if not 0<manifest_path.stat().st_size<=4*1024**2: raise ValueError('fixture manifest byte bound')
    manifest_identity=inventory(manifest_path)
    manifest=json.loads(manifest_path.read_text()); validate_fixture(manifest)
    if args.variant is not None and args.variant!=manifest['variant']: raise ValueError('run variant must match prepared fixture')
    if Path.cwd().resolve()!=Path(PROJ_ROOT).resolve() or (Path(PROJ_ROOT)/'INSPECTED_REVISION').read_text().strip()!=UPSTREAM_COMMIT:
        raise ValueError('run from pinned GVHMR root')
    if not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable; no CPU/static fallback')
    metrics=Metrics(args.output/'metrics.jsonl'); worker=None; start=time.monotonic()
    try:
        torch.cuda.init(); torch.cuda.synchronize();metrics.torch=torch
        torch.manual_seed(0);torch.cuda.manual_seed_all(0)
        save(args.output/'dependency-identity.json',dependency_identity(digest))
        worker=WorkerModels(metrics,PROJ_ROOT,ASSETS,digest,residency='resident',precision=args.precision,
                            variant=manifest['variant'],batch_size=args.batch_size,vo_seed=0)
        assets=worker.identities.get()
        worker.preload(dict(detector=Detector,pose=VitPoseExtractor,features=Extractor,gvhmr=load_demo_model,
                            body=lambda:make_smplx('supermotion').cuda().eval()))
        ready_s=time.monotonic(); startup=ready_s-start
        metrics.emit(dict(event='resident_ready',seconds=startup,memory=metrics.memory()))
        results=[run_take(worker,manifest,args.fixture,args.output/mode,mode,i) for i,mode in enumerate(args.order)]
        if set(worker.store.constructors)!={'detector','pose','features','gvhmr','body'} or any(v!=1 for v in worker.store.constructors.values()):
            raise ValueError('model reloaded')
        if (worker.store.active is not None or worker.store.uses!=dict(detector=12,pose=12,features=12,gvhmr=3,body=3)):
            raise ValueError('completed whole-take model uses differ from three continuous four-chunk takes')
        verify(manifest_path,manifest_identity)
        report=dict(status='complete',config=worker.settings,startup_excluded_s=ready_s-PROCESS_ENTRY,
                    cuda_and_resident_initialization_s=startup,
                    startup_clock_scope='module entry after standard-library imports through resident ready; excludes interpreter launch',
                    fixture=manifest,fixture_manifest_identity=manifest_identity,
                    order=args.order,order_effects='first-use reported; rerun with reversed --order for order sensitivity',
                    results=results,comparisons=compare(args.output,args.order),trusted_asset_sha256=assets,
                    asset_hash_calls=worker.identities.hash_calls,constructors=dict(worker.store.constructors),
                    dtype_inventories=worker.dtype_inventories,upstream_commit=UPSTREAM_COMMIT,
                    runtime_versions={n:importlib.metadata.version(n) for n in ('torch','numpy','av','pycolmap','ultralytics','smplx')},
                    gpu=dict(name=torch.cuda.get_device_name(),total_memory_bytes=torch.cuda.get_device_properties(0).total_memory),
                    code_sha256={p.name:sha(p) for p in ROOT.glob('*.py')},
                    reused_code_sha256={p.name:sha(p) for p in args.code.glob('*.py')},
                    shared_api_ready=json.loads((args.code/'READY.json').read_text()),
                    limitations=['No capture/mux/network/Quest display latency measured.',
                                 'Provided calibration plus rectification assumption, not independent physical calibration.',
                                 'No clinical findings/foot assessment; omitted source images identity-unverified.',
                                 'CPU VO overlap only, no claim of simultaneous CUDA kernels.',
                                 'Whole-take bidirectional GVHMR output is available only after stop.'])
        save(args.output/'comparison.json',report)
    except BaseException as error:
        save(args.output/'failure.json',dict(status='failed',fallback_applied=False,**metrics.failure(error)))
        raise
    finally:
        if worker is not None: worker.close()


def supervise(args):
    """Parent-side watchdog bounds hangs, disk and resident RAM, including native calls."""
    command=[sys.executable,str(Path(__file__).resolve()),*sys.argv[1:],'--internal']
    start=time.monotonic(); process=subprocess.Popen(command,start_new_session=True)
    try:
        while process.poll() is None:
            if time.monotonic()-start>args.deadline: raise TimeoutError('experiment wall deadline')
            sizes=[]
            for p in ROOT.rglob('*'):
                try:
                    if p.is_file(): sizes.append(p.stat().st_size)
                except FileNotFoundError: pass  # cache/temp-file rename, not an inference retry
            if sum(sizes)>2*1024**3 or any(s>256*1024**2 for s in sizes): raise ValueError('stream disk budget exceeded')
            status=Path(f'/proc/{process.pid}/status')
            try: lines=status.read_text().splitlines()
            except FileNotFoundError: lines=[]  # exited child, or non-Linux CPU developer host
            for line in lines:
                if line.startswith('VmRSS:') and int(line.split()[1])*1024>16*1024**3:
                    raise MemoryError('worker RSS exceeds 16GiB')
            time.sleep(.05)
        if process.returncode: raise RuntimeError(f'worker failed, exit {process.returncode}; retained evidence, no retry')
    except BaseException as error:
        save(args.output/'supervisor-failure.json',dict(status='failed',error=repr(error),fallback_applied=False))
        raise
    finally:
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','run'))
    parser.add_argument('--code',type=Path,default=ROOT.parent/'persistent_inference',help='readonly shared controls implementation (requires READY.json for run)')
    parser.add_argument('--output',type=Path,required=True,help='new directory under this stream directory')
    parser.add_argument('--video',type=Path)
    parser.add_argument('--calibration',type=Path)
    parser.add_argument('--variant',choices=('960-15','640-10','640-15'),help='prepare default 640-15; run derives variant from fixture (optional assertion)')
    parser.add_argument('--fixture',type=Path)
    parser.add_argument('--precision',choices=('fp32','amp-fp16','weights-fp16'),default='weights-fp16')
    parser.add_argument('--batch-size',type=int,choices=(2,4,8),default=8)
    parser.add_argument('--order',nargs=3,choices=MODES,default=list(MODES))
    parser.add_argument('--deadline',type=int,default=900)
    parser.add_argument('--internal',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    args.output=args.output.resolve();args.code=args.code.resolve()
    if not args.output.is_relative_to(ROOT) or args.output==ROOT: parser.error('all writes must stay under stream/')
    if not 30<=args.deadline<=1800: parser.error('deadline must be 30..1800 seconds')
    if args.command=='prepare' and (args.video is None or args.calibration is None): parser.error('prepare needs --video and --calibration')
    if args.command=='run':
        if args.fixture is None or set(args.order)!=set(MODES): parser.error('run needs --fixture and three distinct modes')
        args.fixture=args.fixture.resolve()
        if not (args.code/'READY.json').is_file(): parser.error('shared controls API not READY; do not run against a moving implementation')
        ready=json.loads((args.code/'READY.json').read_text())
        if ready.get('status')!='complete': parser.error('shared API delivery is not complete')
        for name,expected in ready['helper_sha256'].items():
            if Path(name).name!=name or sha(args.code/name)!=expected:
                parser.error('shared API differs from its READY identity: '+name)
    if not args.internal:
        args.output.mkdir(parents=True,exist_ok=False)
        # Prevent import caches / upstream config writes in readonly code and assets.
        os.environ.update(PYTHONDONTWRITEBYTECODE='1',YOLO_OFFLINE='true',YOLO_AUTOINSTALL='false',
                          HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
                          YOLO_CONFIG_DIR=str(args.output/'ultralytics-config'),
                          XDG_CACHE_HOME=str(args.output/'cache'),MPLCONFIGDIR=str(args.output/'mpl'),
                          TORCH_HOME=str(args.output/'torch-cache'),CUDA_CACHE_PATH=str(args.output/'cuda-cache'),
                          TRITON_CACHE_DIR=str(args.output/'triton-cache'),HF_HOME=str(args.output/'hf-cache'),
                          NUMBA_CACHE_DIR=str(args.output/'numba-cache'),TMPDIR=str(args.output/'tmp'))
        (args.output/'tmp').mkdir()
        supervise(args)
    else:
        sys.dont_write_bytecode=True
        sys.path.insert(0,str(args.code))
        if args.command=='prepare':
            from fixture import prepare
            prepare(args.video.resolve(),args.calibration.resolve(),args.output,args.variant or '640-15')
        else: execute(args)


if __name__=='__main__': main()
