"""One GPU owner, resident upstream models, CPU-only serial VO, final FP32 export."""
from contextlib import contextmanager
from fractions import Fraction
import json
import queue
import threading

from fixture import save, inventory, decode_released, playback_duration
from stream_core import GlobalPairs


def checked(tensor, shape, label):
    import torch
    if tuple(tensor.shape)!=tuple(shape) or tensor.dtype!=torch.float32 or not torch.isfinite(tensor).all():
        raise ValueError('invalid FP32 '+label)
    return tensor


@contextmanager
def gpu_span(worker, trace, name, **fields):
    with trace.span(name, **fields), worker.metrics.measure(name):
        yield


def observe(worker, tracker, path, count, trace, chunk):
    import torch
    from hmr4d.utils.preproc import Extractor, VitPoseExtractor
    from hmr4d.utils.preproc.vitfeat_extractor import get_batch
    from hmr4d.utils.geo.hmr_cam import get_bbx_xys_from_xyxy
    from models import Detector
    batch=worker.settings['batch_size']
    with torch.inference_mode(), torch.autocast('cuda', enabled=False):
        with gpu_span(worker,trace,'detection',chunk=chunk), worker.use('detector',Detector):
            boxes=tracker.append(path,count)
        bbx=checked(get_bbx_xys_from_xyxy(torch.tensor(boxes),base_enlarge=1.2).float(),(count,3),'boxes')
        with trace.span('crop_preparation',chunk=chunk):
            crops,crop_boxes=get_batch(str(path),bbx,img_ds=1.0)
        with gpu_span(worker,trace,'pose',chunk=chunk), worker.use('pose',VitPoseExtractor) as model:
            pieces=[]
            for i in range(0,count,batch):
                piece=model.extract(crops[i:i+batch],crop_boxes[i:i+batch]).cpu()
                pieces.append(piece)
                trace.emit('neural_batch_done',stage='pose',chunk=chunk,count=len(piece))
            kp=torch.cat(pieces)
        checked(kp,(count,17,3),'pose')
        with gpu_span(worker,trace,'features',chunk=chunk), worker.use('features',Extractor) as model:
            pieces=[]
            for i in range(0,count,batch):
                piece=model.extract_video_features(crops[i:i+batch],crop_boxes[i:i+batch]).cpu()
                pieces.append(piece)
                trace.emit('neural_batch_done',stage='features',chunk=chunk,count=len(piece))
            features=torch.cat(pieces)
        checked(features,(count,1024),'features')
    trace.emit('observation_done',chunk=chunk,count=count,completed_total=tracker.frames,
               predictor_id=id(tracker.predictor),tracker_id=id(tracker.tracker),track_id=tracker.track_id)
    return bbx,kp,features


class VO:
    """Exactly the pinned SIFT/strict pycolmap serial accumulation; no CUDA calls."""
    def __init__(self, manifest, trace, overlap):
        import numpy as np
        from hmr4d.utils.preproc.relpose.matcher_wrapper import Matcher
        from hmr4d.utils.preproc.relpose.solver_two_view import CameraParams
        from adapter import CameraMotionSolver
        k=manifest['K']; w,h=manifest['width'],manifest['height']
        if k[0][0]!=k[1][1]: raise ValueError('SIMPLE_PINHOLE requires equal focal lengths')
        self.matcher=Matcher('sift')
        self.solver=CameraMotionSolver(CameraParams(w//2,h//2,k[0][0]/2,k[0][2]/2,k[1][2]/2),seed=0)
        self.trace,self.overlap=trace,overlap
        self.previous=None; self.transforms=[np.eye(4)]; self.pairs=GlobalPairs()
        self.queue=queue.Queue(2); self.error=None; self.cancel=threading.Event()
        self.thread=threading.Thread(target=self.run,name='cpu-vo',daemon=True)
        if overlap: self.thread.start()

    def process(self, task):
        import numpy as np
        from hmr4d.utils.video_io_utils import read_video_np
        path,samples,chunk=task
        with self.trace.span('vo',chunk=chunk):
            # Freeze upstream RGB decode + libav scale, including the upstream
            # matcher's COLOR_BGR2GRAY applied to these RGB bytes.
            images=read_video_np(str(path),scale=.5)
            if len(images)!=len(samples): raise ValueError('VO source count mismatch')
            for image,(grid,source) in zip(images,samples):
                with self.trace.span('vo_pair',chunk=chunk,previous=self.pairs.previous,grid=grid,source=source):
                    self.pairs.append(grid,source)
                    if self.previous is not None:
                        # FLANN uses OpenCV thread-local randomness. Reset for
                        # each pair so scheduling cannot change its RNG history.
                        import cv2
                        cv2.setRNGSeed(0)
                        self.trace.emit('vo_rng_seed', opencv_seed=0, pycolmap_ransac_seed=0,
                                        scope='each image pair before matching', previous=self.pairs.ids[-1][0], grid=grid)
                        pts0,pts1=self.matcher.match_np(self.previous,image)
                        transform=self.solver.solve(pts0,pts1) @ self.transforms[-1]
                        if not np.isfinite(transform).all(): raise ValueError('nonfinite VO')
                        self.transforms.append(transform)
                    self.previous=image.copy()
        self.trace.emit('vo_done',chunk=chunk,samples=[list(x) for x in samples],pairs_done=len(self.pairs.ids))

    def run(self):
        try:
            while not self.cancel.is_set():
                try: task=self.queue.get(timeout=.05)
                except queue.Empty: continue
                if task is None: return
                self.process(task)
        except BaseException as error:
            self.error=error
            self.trace.emit('vo_failure',error=repr(error))

    def submit(self, task):
        if self.error: raise self.error
        if self.overlap:
            depth=self.queue.qsize()+1
            self.queue.put_nowait(task)  # overflow FAILS, never hidden stalls/drops
            self.trace.emit('vo_submitted',chunk=task[2],backlog=depth)
        else: self.process(task)

    def finish(self):
        if self.overlap:
            while self.thread.is_alive():
                if self.error: raise self.error
                try: self.queue.put(None,timeout=.05); break
                except queue.Full: continue
            self.thread.join()  # external watchdog bounds native solver hangs
        if self.error: raise self.error
        self.previous=None
        return self.transforms,[grid for grid,_ in self.pairs.sources]

    def close(self):
        self.cancel.set()
        if self.thread.is_alive(): self.thread.join(timeout=1)


def reconstruct(worker, plan, parts, transforms, samples, output, trace, tracker):
    import numpy as np
    import torch
    from adapter import load_demo_model
    from hmr4d.utils.preproc.relpose.solver_two_view import interpolate_missing_frames
    from hmr4d.utils.geo_transform import compute_cam_angvel
    from hmr4d.utils.smplx_utils import make_smplx
    from processing.reconstruction.native import prepare
    from processing.reconstruction.runtime import geometry_metadata
    from smplx.joint_names import JOINT_NAMES
    n=len(plan['selected_indices']); obs=len(plan['sampling']['observation_indices'])
    calls=0; exported={'smpl_params_global':0,'smpl_params_incam':0}
    bbx,kp,features=[torch.cat([part[i] for part in parts]) for i in range(3)]
    for tensor,shape,name in ((bbx,(obs,3),'boxes'),(kp,(obs,17,3),'pose'),(features,(obs,1024),'features')):
        checked(tensor,shape,name)
    # Persist pre-scatter observations for paired numeric comparison, not reuse.
    np.savez(output/'intermediates.npz',boxes=bbx.numpy(),keypoints=kp.numpy(),features=features.numpy())
    indices=plan['sampling']['grid_to_observation']
    with trace.span('vo_interpolation'):
        rotations=checked(torch.from_numpy(interpolate_missing_frames(transforms,samples)[:,:3,:3]).float(),(n,3,3),'rotations')
        if (not torch.allclose(rotations.mT@rotations,torch.eye(3).expand(n,3,3),atol=1e-3)
                or not torch.allclose(torch.linalg.det(rotations),torch.ones(n),atol=1e-3)):
            raise ValueError('invalid camera rotations')
    k=torch.tensor(plan['K'],dtype=torch.float32)
    with torch.inference_mode(),torch.autocast('cuda',enabled=False):
        data=dict(length=torch.tensor(n),bbx_xys=bbx[indices],kp2d=kp[indices],f_imgseq=features[indices],
                  K_fullimg=k.repeat(n,1,1),cam_angvel=compute_cam_angvel(rotations))
        checked(data['cam_angvel'],(n,6),'camera angular velocity')
        with gpu_span(worker,trace,'final_prediction'),worker.use('gvhmr',load_demo_model) as model:
            prediction=model.predict(data,static_cam=False)  # the ONLY GVHMR call for this whole take
            calls+=1
            parameters={space:{key:value.detach().cpu() for key,value in prediction[space].items()}
                        for space in ('smpl_params_global','smpl_params_incam')}
            for fields in parameters.values():
                for key,value in fields.items(): checked(value,(n,{'body_pose':63,'betas':10,'global_orient':3,'transl':3}[key]),key)
                if not torch.allclose(fields['betas'],fields['betas'][:1].expand(n,-1),atol=1e-6,rtol=0):
                    raise ValueError('whole-take shape is not constant')
            plain={space:{key:value.tolist() for key,value in fields.items()} for space,fields in parameters.items()}
            plain['K_fullimg']=prediction['K_fullimg'].detach().cpu().tolist()
            del prediction
        with trace.span('export_parameters'):
            validated=prepare(dict(take_id=plan['take_id'],frames=[{k:r[k] for k in ('frame_id','pts_ns','image_valid')}
                                   for r in plan['source_frames']],selected_indices=plan['selected_indices'],prediction=plain))
            save(output/'parameters.json',validated['parameters'])
            save(output/'observations.json',dict(camera_rotation_w2c=rotations.tolist(),vo_sample_indices=samples,
                                                tracker_snapshots=tracker.snapshots,processed_track_id=tracker.track_id,
                                                sampling=plan['sampling'],omitted_images_identity_verified=False))
        with gpu_span(worker,trace,'export_geometry'),worker.use('body',lambda:make_smplx('supermotion').cuda().eval()) as body:
            faces=np.asarray(body.faces); vertices=int(body.bm.v_template.shape[0])
            if (faces.ndim!=2 or faces.shape[1]!=3 or not np.issubdtype(faces.dtype,np.integer)
                    or faces.min()<0 or faces.max()>=vertices): raise ValueError('invalid topology')
            if n*(vertices+44)*3*4>256*1024**2: raise ValueError('geometry budget')
            metadata=geometry_metadata(list(JOINT_NAMES[:22]),body.bm.parents[:22].cpu().tolist(),vertices,len(faces))
            faces.astype('<u4').tofile(output/'triangles.u32')
            with (open(output/'vertices.f32','wb') as vf,open(output/'joints.f32','wb') as jf,
                  open(output/'incam-joints.f32','wb') as cf):
                for start in range(0,n,16):
                    length=min(16,n-start)
                    for space in parameters:
                        batch={key:value[start:start+16].cuda() for key,value in parameters[space].items()}
                        fitted=body(**batch)
                        joints=checked(fitted.joints[:,:22],(length,22,3),'fitted joints')
                        if space=='smpl_params_global':
                            checked(fitted.vertices,(length,vertices,3),'vertices').cpu().numpy().astype('<f4').tofile(vf)
                            joints.cpu().numpy().astype('<f4').tofile(jf)
                        else: joints.cpu().numpy().astype('<f4').tofile(cf)
                        exported[space]+=length
                        del fitted,batch,joints
            (output/'fitted_valid.u8').write_bytes(bytes([1])*n*22)
    with trace.span('native_verification'):
        for name,count in (('vertices.f32',n*vertices*3),('joints.f32',n*22*3),('incam-joints.f32',n*22*3)):
            if (output/name).stat().st_size!=count*4: raise ValueError('native byte count mismatch')
            values=np.memmap(output/name,dtype='<f4',mode='r')
            for start in range(0,count,1000000):
                if not np.isfinite(values[start:start+1000000]).all(): raise ValueError('nonfinite native file')
        # No recentering: verify the serialized translation is exactly the predicted root translation.
        reloaded=json.loads((output/'parameters.json').read_text())
        if reloaded!=plain: raise ValueError('serialized parameter/root motion changed')
        if not np.array_equal(np.fromfile(output/'triangles.u32',dtype='<u4'),faces.reshape(-1)):
            raise ValueError('serialized topology changed')
        names=('parameters.json','observations.json','vertices.f32','joints.f32','incam-joints.f32','triangles.u32',
               'fitted_valid.u8','intermediates.npz','selection.json','source-sidecar.json')
        native=dict(frame_count=n,geometry=metadata,artifacts={name:inventory(output/name) for name in names},
                    incam_joints='first 22 same-body-model SMPL-X joints in camera coordinates, for supplied-K projection only',
                    layout='little-endian frame-major XYZ f32 / triangle triples u32',
                    counters=dict(gvhmr_calls=calls,detection_frames=tracker.frames,pose_frames=len(kp),feature_frames=len(features),
                                  global_export_frames=exported['smpl_params_global'],incam_export_frames=exported['smpl_params_incam'],
                                  vo_samples=len(transforms)))
        if (native['counters']!=dict(gvhmr_calls=1,detection_frames=obs,pose_frames=obs,feature_frames=obs,
                                    global_export_frames=n,incam_export_frames=n,vo_samples=len(samples))
                or (output/'fitted_valid.u8').read_bytes()!=bytes([1])*n*22):
            raise ValueError('completed stage counters/validity mismatch')
        save(output/'native.json',native)
    trace.emit('native_verified')
    return native


def verify_rendered_timing(actual, expected, duration, manifest):
    if actual != expected or duration != playback_duration(manifest):
        raise ValueError('annotation differs from normal-rate source-frame playback')


def render(manifest, fixture, output, native, trace):
    """Simple joint overlay from the SAME SMPL-X incamera body model, not clinical findings."""
    import av
    import cv2
    import numpy as np
    from buffered import writer,encode,close_writer
    n=native['frame_count']; w,h=manifest['width'],manifest['height']
    joints=np.memmap(output/'incam-joints.f32',dtype='<f4',mode='r',shape=(n,22,3))
    k=np.asarray(manifest['K'],dtype=np.float32)
    parents=native['geometry']['joint_parents']
    metadata=[]
    selection=json.loads((output/'selection.json').read_text())
    with trace.span('annotation_projection'):
        projections=[]
        for xyz in joints:
            projected=xyz@k.T
            valid=np.isfinite(projected).all(axis=1)&(xyz[:,2]>1e-4)
            xy=np.zeros((22,2),dtype=np.float32)
            xy[valid]=projected[valid,:2]/projected[valid,2:]
            valid &= (np.abs(xy)<1e6).all(axis=1)
            projections.append((xy,valid))
        annotations=dict(label='estimated SMPL-X skeleton; unvalidated; no clinical findings',
             coordinate_system='incamera projection with supplied resized K',K=manifest['K'],
             joint_names=native['geometry']['joint_names'],joint_parents=parents,
             projected_xy=[xy.tolist() for xy,_ in projections],projection_valid=[ok.tolist() for _,ok in projections])
        save(output/'annotation.json',annotations)
        if json.loads((output/'annotation.json').read_text())!=annotations: raise ValueError('annotation roundtrip mismatch')
    trace.emit('annotation_package_verified',identity=inventory(output/'annotation.json'))
    rate=Fraction(manifest['rate']); base=Fraction(manifest['original_time_base'])
    origin=Fraction(manifest['original_origin_seconds'])
    video=output/'annotated.mp4'; out,stream=writer(video,w,h,rate,base)
    expected=[]
    with trace.span('render'):
        try:
            for row in manifest['chunks']:
                images=decode_released(fixture,manifest,row)
                for image,frame in zip(images,row['frames']):
                    source_time=Fraction(frame['original_pts'])*Fraction(frame['original_time_base'])-origin
                    grid=min(n-1,int(source_time*30))
                    xy,valid=projections[grid]
                    for joint,parent in enumerate(parents):
                        if parent>=0 and valid[joint] and valid[parent]:
                            a,b=tuple(map(int,xy[joint])),tuple(map(int,xy[parent]))
                            visible,a,b=cv2.clipLine((0,0,w,h),a,b)
                            if visible: cv2.line(image,a,b,(0,255,255),2,cv2.LINE_AA)
                        if valid[joint] and 0<=xy[joint,0]<w and 0<=xy[joint,1]<h:
                            cv2.circle(image,tuple(map(int,xy[joint])),3,(0,255,255),-1)
                    labels=[f"source {float(source_time):.3f}s | ID {frame['frame_id']} | PTS {frame['pts_ns']} ns",
                            'Estimated SMPL-X skeleton | unvalidated | no clinical findings',
                            f"Held observation ID {selection['frame_mapping'][grid]['source_frame_id']} | whole-take estimate"]
                    for line,text in enumerate(labels):
                        y=20+line*20
                        cv2.putText(image,text,(8,y),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),3,cv2.LINE_AA)
                        cv2.putText(image,text,(8,y),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,255,255),1,cv2.LINE_AA)
                    if not expected: trace.emit('first_rendered_frame',source_frame_id=frame['frame_id'])
                    encode(out,stream,image,int(source_time/base),base)
                    expected.append(source_time)
                    metadata.append(dict(source_frame_id=frame['frame_id'],source_pts_ns=frame['pts_ns'],model_grid=grid,
                                         held_observation_source_frame_id=selection['frame_mapping'][grid]['source_frame_id']))
        finally: close_writer(out,stream)
    trace.emit('video_closed')
    with trace.span('video_decode_verification'):
        with av.open(str(video)) as src:
            actual=[Fraction(f.pts)*f.time_base for f in src.decode(video=0)]
            duration=Fraction(src.streams.video[0].duration)*src.streams.video[0].time_base
        verify_rendered_timing(actual, expected, duration, manifest)
        save(output/'video.json',dict(identity=inventory(video),duration_s=float(duration),frame_count=len(actual),
                                     rate=str(rate),mapping=metadata,clinical_findings_available=False))
    trace.emit('video_decoded_verified')
