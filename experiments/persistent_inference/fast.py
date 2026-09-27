"""Sparse observation preparation, retaining the full 30 Hz model and VO grid."""
from bisect import bisect_right
from contextlib import ExitStack
from fractions import Fraction
import math
import time
from pathlib import Path

VARIANTS = {'960-15': (960,15), '640-10': (640,10), '640-15': (640,15)}


def resized(width,height,maxwidth,k):
    if any(type(x) is not int or x < 2 for x in (width,height,maxwidth)):
        raise ValueError('invalid dimensions')
    # Exact aspect ratio and even dimensions, rather than anisotropic rounding.
    divisor=math.gcd(width,height)
    a,b=width//divisor,height//divisor
    multiplier=min(divisor,maxwidth//a)
    multiplier-=multiplier%2 if a%2 or b%2 else 0
    w,h=a*multiplier,b*multiplier
    if min(w,h)<32: raise ValueError('cannot preserve aspect with even dimensions')
    return w,h,{name:value*(w/width if name in ('fx','cx') else h/height) for name,value in k.items()}


def sampling(frames,hz,count):
    if (type(hz) is not int or hz not in (10, 15) or type(count) is not int
            or not 2 <= count <= 63 or not 2 <= len(frames) <= 600):
        raise ValueError('invalid sampling settings')
    times=[int(f['pts_ns']) for f in frames]
    if any(not f['image_valid'] for f in frames) or any(not 0 < b-a <= 100000000 for a,b in zip(times,times[1:])):
        raise ValueError('invalid source observations')
    def nearest(target,indices):
        return min(indices,key=lambda i:(abs(times[i]-target),i))
    duration=times[-1]-times[0]
    target_count=duration*hz//10**9+1
    # Match plan_input's tolerance for rounded capture-clock endpoints.
    if abs(Fraction(target_count*10**9,hz)-duration) <= 1:
        target_count+=1
    targets=range(target_count)
    chosen=sorted(set(nearest(times[0]+Fraction(i*10**9,hz),range(len(times))) for i in targets))
    # Hold the latest available observation, with target PTS rounded to the
    # source's integer-nanosecond clock. Never borrow a later observation.
    observed_times = [times[i] for i in chosen]
    grid=[max(0, bisect_right(observed_times, times[0]+round(Fraction(i*10**9,30)))-1)
          for i in range(count)]
    return dict(observation_hz=hz, observation_indices=chosen, observations=[frames[i] for i in chosen],
                grid_to_observation=grid,grid_times_s=[i/30 for i in range(count)],
                omitted_source_frame_ids=[f['frame_id'] for i,f in enumerate(frames) if i not in chosen],
                policy=f'{hz}Hz nearest-source sampling; causal latest-observation hold on rounded-ns 30Hz targets; omitted images not identity-verified; GVHMR and VO remain segment-level estimators')


def scatter(values,indices):
    if any(type(i) is not int or not 0 <= i < len(values) for i in indices):
        raise ValueError('invalid scatter index')
    return [values[i] for i in indices]


def provenance():
    from importlib import import_module
    from buffered import sha
    modules = {name: import_module('processing.reconstruction.'+name)
               for name in ('runtime', 'native', 'timing')}
    hashes = {name+'.py': sha(Path(module.__file__)) for name, module in modules.items()}
    hashes.update({name: sha(Path(__file__).with_name(name))
                   for name in ('adapter.py', 'fast.py', 'buffered.py', 'benchmark.py', 'worker.py',
                                'models.py', 'lifecycle.py', 'metrics.py', 'precision.py', 'ultralytics-identity.json')})
    return dict(upstream_commit=modules['native'].UPSTREAM_COMMIT, adapter_sha256=hashes,
                asset_hash_policy='operator-trusted readonly assets; identity SHA-256 once/process; not expected-manifest approval')


def run(video,sidecar,output,offset_ns,variant,worker):
    if variant not in VARIANTS or variant != worker.settings['variant']:
        raise ValueError('unsupported or inconsistent worker variant')
    import av
    import cv2
    from processing.reconstruction import runtime as r
    from processing.reconstruction.timing import map_selected_frames
    from adapter import infer_native
    from buffered import writer,encode,close_writer
    started=time.monotonic()
    doc=r.load_json(sidecar)
    plan=r.plan_input(doc)
    source_hash=r.digest(video); sidecar_hash=r.digest(sidecar)
    width,hz=VARIANTS[variant]
    w,h,k=resized(plan['width'],plan['height'],width,doc['camera']['intrinsics'])
    obs=sampling(plan['source_frames'],hz,len(plan['selected_indices']))
    from lifecycle import RESIDENCY_MODES, validate_segment
    validate_segment(dict(variant=variant, width=w, height=h, selected_indices=plan['selected_indices'], sampling=obs))
    output.mkdir()
    # First bind every original decoded PTS before sampling anything.
    with av.open(str(video)) as source:
        if len(source.streams.video) != 1 or source.streams.video[0].metadata.get('rotate', '0') != '0':
            raise ValueError('require one upright source video stream')
        decoded=[]
        for i,f in enumerate(source.decode(video=0)):
            if any('DISPLAYMATRIX' in str(x.type) for x in f.side_data):
                raise ValueError('unsupported source display transform')
            if i >= len(plan['source_frames']) or f.pts is None or (f.width,f.height)!=(plan['width'],plan['height']):
                raise ValueError('invalid source decode')
            decoded.append((i,Fraction(f.pts)*f.time_base))
    r.bind_pts(plan['source_frames'],decoded,offset_ns)
    full_indices=plan['selected_indices'][:]
    plan.update(width=w,height=h,K=[[k['fx'],0,k['cx']],[0,k['fy'],k['cy']],[0,0,1]],sampling=obs,
                variant=variant,vo_source_indices=full_indices,
                decoder_binding=dict(offset_ns=str(offset_ns),decoded_pts_seconds=[str(t) for _,t in decoded]))
    plan['selected_indices']=[obs['observation_indices'][i] for i in obs['grid_to_observation']]
    plan['frame_mapping']=map_selected_frames(plan['source_frames'],plan['selected_indices'])
    for i,row in enumerate(plan['frame_mapping']):
        row.update(inference_time_s=i/30,observation_index=obs['grid_to_observation'][i],
                   selection_error_ns=str(Fraction(int(row['source_pts_ns'])-int(plan['source_frames'][0]['pts_ns']))-Fraction(i*10**9,30)),
                   evidence='latest available sampled observation held on model grid; segment-level fitted estimate')
    plan['resampling']=f'30Hz latest-observation hold from {hz}Hz sampling; VO retains original 30Hz mapping'
    outputs=[]
    try:
        for name,indices in (('inference.mp4',full_indices),('observations.mp4',obs['observation_indices'])):
            out,stream=writer(output/name,w,h,lossless=True)
            outputs.append((out,stream,indices,0))
        with av.open(str(video)) as source:
            decoded_count = 0
            for i,f in enumerate(source.decode(video=0)):
                decoded_count += 1
                if i>=len(decoded) or f.pts is None or Fraction(f.pts)*f.time_base!=decoded[i][1]:
                    raise ValueError('decoder changed')
                image=cv2.resize(f.to_ndarray(format='bgr24'),(w,h),interpolation=cv2.INTER_AREA)
                for j,(out,stream,indices,cursor) in enumerate(outputs):
                    while cursor<len(indices) and indices[cursor]==i:
                        encode(out,stream,image,cursor,Fraction(1,30));cursor+=1
                    outputs[j]=(out,stream,indices,cursor)
        if decoded_count != len(decoded):
            raise ValueError('source decode truncated between preparation passes')
        for out,stream,indices,cursor in outputs:
            if cursor!=len(indices): raise ValueError('incomplete preparation')
    finally:
        with ExitStack() as closing:
            for out,stream,_,_ in outputs:
                closing.callback(close_writer, out, stream)
    for name,indices in (('inference.mp4',full_indices),('observations.mp4',obs['observation_indices'])):
        with av.open(str(output/name)) as check:
            pts=[Fraction(f.pts)*f.time_base for f in check.decode(video=0)]
        if pts!=[Fraction(i,30) for i in range(len(indices))]: raise ValueError('prepared PTS mismatch')
    if r.digest(video)!=source_hash or r.digest(sidecar)!=sidecar_hash: raise ValueError('source changed')
    r.write_json(output/'selection.json',plan)
    r.write_json(output/'source-sidecar.json',doc)
    preparation=time.monotonic()-started
    worker.metrics.emit(dict(event='preparation', seconds=preparation, ok=True))
    result=infer_native(output/'inference.mp4',plan,output,worker)
    result.update(schema_version='gvhmr-native-1',take_id=doc['take_id'],variant=variant,
                  experiment=dict(worker.settings), dtype_inventories=dict(worker.dtype_inventories),
                  precision_scope='only ViTPose and HMR2 feature neural forward; autocast weight cache disabled; FP32 inputs/outputs and postprocessing; detector/GVHMR/SMPL/VO unchanged',
                  width=w, height=h, observation_hz=hz, pose_flip_test=True,
                  pose_neural_batch_limit=2*worker.settings['batch_size'], body_batch_size=16,
                  detector_half=False, model_hz=30, vo_grid_hz=30, vo_step=8, vo_scale=0.5,
                  vo_method='sift', vo_num_workers=1, static_camera=False,
                  torch_seed=0, vo_seed_api='options.ransac.random_seed',
                  source_video_sha256=source_hash,source_sidecar_sha256=sidecar_hash,
                  preparation_s=preparation,local_elapsed_s=time.monotonic()-started,
                  **provenance(), residency_mode=worker.store.residency,
                  model_cache=RESIDENCY_MODES[worker.store.residency]+'; no cross-input predictions/features',
                  camera_motion='moving camera VO on full 30Hz source mapping; no static fallback',
                  validation_status='research_demo_unvalidated')
    r.write_json(output/'handoff.json',result)
    return result
