"""GPU adapter for the inspected GVHMR revision. Imports stay off the CPU CLI path."""

import gc
import importlib.metadata
from pathlib import Path
import time

from processing.reconstruction.native import UPSTREAM_COMMIT, prepare
from processing.reconstruction.runtime import digest, geometry_metadata, select_track, write_json

ASSETS = (
    'body_models/smplx/SMPLX_NEUTRAL.npz',
    'gvhmr/gvhmr_siga24_release.ckpt',
    'hmr2/epoch=10-step=25000.ckpt',
    'vitpose/vitpose-h-multi-coco.pth',
    'yolo/yolov8x.pt',
)


def load_demo_model():
    import hydra
    from hydra import compose, initialize_config_module
    from hmr4d.configs import register_store_gvhmr
    # This import registers model/gvhmr/gvhmr_pl_demo. The general store omits it.
    # Match tools/demo/demo.py before Hydra resolves the demo defaults.
    from hmr4d.model.gvhmr.gvhmr_pl_demo import DemoPL  # noqa: F401

    register_store_gvhmr()
    with initialize_config_module(version_base='1.3', config_module='hmr4d.configs'):
        cfg = compose(config_name='demo')
    model = hydra.utils.instantiate(cfg.model, _recursive_=False)
    model.load_pretrained_model(cfg.ckpt_path)
    return model.eval().cuda()


class CameraMotionSolver:
    """Serial SimpleVO solver with an explicit pycolmap no-pose failure."""

    def __init__(self, params, seed=0):
        if type(seed) is not int or seed < 0:
            raise ValueError('VO seed must be a nonnegative integer')
        from hmr4d.utils.preproc.relpose.solver_two_view import PycolmapRansacTwoViewGeometrySolver
        self.backend = PycolmapRansacTwoViewGeometrySolver(params)
        # The nested options belong to this solver, not the process-global RNG.
        # Require read/write/readback: unsupported bindings must not run unseeded.
        try:
            self.backend.options.ransac.random_seed
            self.backend.options.ransac.random_seed = seed
            if self.backend.options.ransac.random_seed != seed:
                raise ValueError('seed readback differs')
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError) as error:
            raise RuntimeError('pycolmap options.ransac.random_seed unavailable or rejected seed; no unseeded fallback') from error

    def solve(self, pts0, pts1):
        import numpy as np
        import pycolmap
        # Keep the pinned estimator, matches and options except the explicit seed.
        matches = np.stack([np.arange(len(pts0)), np.arange(len(pts0))], axis=-1)
        answer = pycolmap.estimate_calibrated_two_view_geometry(
            self.backend.camera, pts0.astype(np.float64),
            self.backend.camera, pts1.astype(np.float64),
            matches=matches, options=self.backend.options,
        )
        if answer.cam2_from_cam1 is None:
            raise ValueError(
                'Camera motion unavailable: pycolmap returned no relative pose for a sampled image pair. '
                'Inspect scene texture, blur, parallax and repeated source selections; use a new suitable take '
                'or a separately verified camera-motion method. No static-camera fallback was applied.'
            )
        transform = np.eye(4)
        transform[:3] = answer.cam2_from_cam1.matrix().astype(np.float32)
        return transform


def release(worker):
    """Only the explicit offload mode discards the CUDA allocator cache."""
    if worker.store.residency == 'cpu-offload':
        import torch
        gc.collect()
        torch.cuda.empty_cache()


def infer_native(video, plan, output, worker):
    import numpy as np
    import torch
    from hmr4d import PROJ_ROOT
    from hmr4d.utils.preproc import Extractor, VitPoseExtractor, SimpleVO
    from hmr4d.utils.preproc.vitfeat_extractor import get_batch
    from hmr4d.utils.preproc.relpose.matcher_wrapper import Matcher
    from hmr4d.utils.preproc.relpose.solver_two_view import CameraParams, interpolate_missing_frames
    from hmr4d.utils.geo.hmr_cam import get_bbx_xys_from_xyxy
    from hmr4d.utils.geo_transform import compute_cam_angvel
    from hmr4d.utils.smplx_utils import make_smplx
    from hmr4d.utils.video_io_utils import read_video_np
    from smplx.joint_names import JOINT_NAMES

    if (Path(PROJ_ROOT) / 'INSPECTED_REVISION').read_text().strip() != UPSTREAM_COMMIT:
        raise ValueError('runtime source revision does not match this adapter')
    if Path.cwd().resolve() != Path(PROJ_ROOT).resolve():
        raise ValueError('run from the installed GVHMR root for upstream relative asset paths')
    from lifecycle import RESIDENCY_MODES, Counters, validate_segment
    from models import Detector
    validate_segment(plan)
    counters = Counters()
    assets = {name.removeprefix('inputs/checkpoints/'): value
              for name, value in worker.identities.get().items()}
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA GPU unavailable')
    event_start = len(worker.metrics.events)
    stages = {}

    def mark(name, start):
        torch.cuda.synchronize()
        stages[name] = time.monotonic() - start

    def checked(tensor, shape, label):
        if (tensor.dtype != torch.float32 or tuple(tensor.shape) != tuple(shape)
                or not torch.isfinite(tensor).all()):
            raise ValueError(f'invalid {label} dtype, shape or nonfinite values')
        return tensor

    grid_count = len(plan['selected_indices'])
    count = len(plan['sampling']['observation_indices'])
    observation_video = output / 'observations.mp4'
    batch_size = worker.settings['batch_size']
    # Never inherit AMP into crop/heatmap postprocessing, GVHMR or body export.
    # Each of the two registered neural wrappers owns its own autocast scope.
    with torch.inference_mode(), torch.autocast(device_type='cuda', enabled=False):
        started = time.monotonic()
        with worker.use('detector', Detector) as tracker:
            with worker.metrics.measure('detection'):
                history = tracker.track(str(observation_video))
                counters.add('detection_frames', len(history))
                boxes = select_track(history)
                processed_track_ids = [frame[0]['id'] for frame in history]
        if len(boxes) != count:
            raise ValueError('tracking output does not match prepared input')
        bbx = get_bbx_xys_from_xyxy(torch.tensor(boxes), base_enlarge=1.2).float()
        checked(bbx, (count, 3), 'boxes')
        del tracker, history
        release(worker)
        mark('tracking_s', started)

        # Each outer slice fits upstream's fixed batch of 16. ViTPose's flip
        # test remains unchanged, so the neural pose batch is twice this size.
        started = time.monotonic()
        with worker.metrics.measure('crop_preparation'):
            crops, crop_boxes = get_batch(str(observation_video), bbx, img_ds=1.0)
            crops, crop_boxes = crops.float(), crop_boxes.float()
            checked(crops, (count, 3, 256, 256), 'normalized crops')
            checked(crop_boxes, (count, 3), 'crop boxes')
        with worker.use('pose', VitPoseExtractor) as pose:
            with worker.metrics.measure('pose'):
                parts = []
                for i in range(0, count, batch_size):
                    part = pose.extract(crops[i:i+batch_size], crop_boxes[i:i+batch_size]).cpu()
                    counters.add('pose_calls')
                    counters.add('pose_frames', len(part))
                    parts.append(part)
                kp2d = torch.cat(parts)
                del parts, part
        checked(kp2d, (count, 17, 3), 'ViTPose output')
        del pose
        release(worker)
        mark('vitpose_s', started)
        started = time.monotonic()
        with worker.use('features', Extractor) as extractor:
            with worker.metrics.measure('features'):
                parts = []
                for i in range(0, count, batch_size):
                    part = extractor.extract_video_features(crops[i:i+batch_size], crop_boxes[i:i+batch_size]).cpu()
                    counters.add('feature_calls')
                    counters.add('feature_frames', len(part))
                    parts.append(part)
                features = torch.cat(parts)
                del parts, part
        checked(features, (count, 1024), 'HMR2 features')
        del extractor, crops, crop_boxes
        release(worker)
        mark('hmr2_features_s', started)
        # Heavy observations are computed once, then expanded without model calls.
        observation_boxes, observation_kp = bbx.tolist(), kp2d.tolist()
        from fast import scatter
        indices = plan['sampling']['grid_to_observation']
        bbx, kp2d, features = (torch.stack(scatter(value, indices)) for value in (bbx, kp2d, features))
        count = grid_count
        counters.add('scatter_frames', count)

        started = time.monotonic()
        # Same SimpleVO solver/accumulation as upstream, but use the supplied K,
        # not its unrelated default 24mm full-frame camera estimate.
        images = read_video_np(str(video), scale=0.5)
        if len(images) != count:
            raise ValueError('VO decoder count differs from verified prepared input')
        sample_ids = list(range(0, count, 8))
        if sample_ids[-1] != count - 1:
            sample_ids.append(count - 1)
        K = torch.tensor(plan['K'], dtype=torch.float32)
        params = CameraParams(plan['width'] // 2, plan['height'] // 2,
                              focal_length=plan['K'][0][0] / 2,
                              cx=plan['K'][0][2] / 2, cy=plan['K'][1][2] / 2)
        vo = SimpleVO(str(video), scale=0.5, step=8, method='sift', num_workers=1)
        with worker.metrics.measure('vo'):
            solver = CameraMotionSolver(params, seed=worker.settings['vo_seed'])
            worker.metrics.emit(dict(event='vo_seed', seed=worker.settings['vo_seed'],
                                     api='options.ransac.random_seed', scope='fresh serial solver per segment'))
            transforms = vo.process_video_T_w2c_list_np(images[sample_ids], Matcher('sift'), solver)
            transforms = interpolate_missing_frames(transforms, sample_ids)
            counters.add('vo_sample_frames', len(sample_ids))
        rotations = torch.from_numpy(transforms[:, :3, :3]).float()
        checked(rotations, (count, 3, 3), 'camera rotations')
        if (not torch.allclose(rotations.mT @ rotations, torch.eye(3).expand(count, 3, 3), atol=1e-3)
                or not torch.allclose(torch.linalg.det(rotations), torch.ones(count), atol=1e-3)):
            raise ValueError('VO returned invalid rotation matrices')
        del images, transforms, vo, solver
        mark('camera_motion_s', started)

        started = time.monotonic()
        data = {'length': torch.tensor(count), 'bbx_xys': bbx, 'kp2d': kp2d,
                'K_fullimg': K.repeat(count, 1, 1), 'cam_angvel': compute_cam_angvel(rotations),
                'f_imgseq': features}
        for key, value in data.items():
            if key != 'length':
                checked(value, value.shape, 'GVHMR input ' + key)
        with worker.use('gvhmr', load_demo_model) as model:
            with worker.metrics.measure('gvhmr'):
                prediction = model.predict(data, static_cam=False)
                parameters = {space: {key: checked(value, value.shape, space + '/' + key).detach().cpu()
                                      for key, value in prediction[space].items()}
                              for space in ('smpl_params_global', 'smpl_params_incam')}
                plain = {space: {key: value.tolist() for key, value in fields.items()} for space, fields in parameters.items()}
                plain['K_fullimg'] = prediction['K_fullimg'].detach().cpu().tolist()
                del prediction
                counters.add('gvhmr_calls')
        with worker.metrics.measure('export_parameters'):
            validated = prepare({'take_id': plan['take_id'],
                                 'frames': [{k: f[k] for k in ('frame_id', 'pts_ns', 'image_valid')}
                                            for f in plan['source_frames']],
                                 'selected_indices': plan['selected_indices'], 'prediction': plain})
            write_json(output / 'parameters.json', validated['parameters'])
            write_json(output / 'observations.json', {'bbx_xys': bbx.tolist(), 'coco17_xy_score': kp2d.tolist(),
                                                    'camera_rotation_w2c': rotations.tolist(),
                                                    'vo_sample_indices': sample_ids,
                                                    'vo_seed': worker.settings['vo_seed'],
                                                    'vo_seed_api': 'options.ransac.random_seed',
                                                    'sampling': plan['sampling'],
                                                    'processed_track_ids': processed_track_ids,
                                                    'processed_observation_boxes': observation_boxes,
                                                    'processed_observation_kp': observation_kp,
                                                    'track_scope': 'strict identity on processed observations only; skipped images unverified',
                                                    'score_is_calibrated_confidence': False})
        del model, data, features
        release(worker)
        mark('gvhmr_s', started)

        started = time.monotonic()
        with worker.use('body', lambda: make_smplx('supermotion').cuda().eval()) as body:
            with worker.metrics.measure('export_geometry'):
                faces = np.asarray(body.faces)
                vertices = int(body.bm.v_template.shape[0])
                if faces.ndim != 2 or faces.shape[1] != 3 or not np.issubdtype(faces.dtype, np.integer):
                    raise ValueError('invalid body topology')
                if faces.min() < 0 or faces.max() >= vertices:
                    raise ValueError('body triangle index out of range')
                metadata = geometry_metadata(list(JOINT_NAMES[:22]), body.bm.parents[:22].cpu().tolist(), vertices, len(faces))
                if count * (vertices + 22) * 3 * 4 + faces.size * 4 > 256 * 1024 * 1024:
                    raise ValueError('native geometry exceeds 256MiB')
                faces.astype('<u4').tofile(output / 'triangles.u32')
                with open(output / 'vertices.f32', 'wb') as vf, open(output / 'joints.f32', 'wb') as jf:
                    for start in range(0, count, 16):
                        batch = {key: value[start:start+16].cuda() for key, value in parameters['smpl_params_global'].items()}
                        fitted = body(**batch)
                        length = len(batch['transl'])
                        checked(fitted.vertices, (length, vertices, 3), 'fitted vertices')
                        joints = checked(fitted.joints[:, :22], (length, 22, 3), 'fitted joints')
                        fitted.vertices.cpu().numpy().astype('<f4').tofile(vf)
                        joints.cpu().numpy().astype('<f4').tofile(jf)
                        counters.add('export_frames', length)
                        del batch, fitted, joints
                # A true bit means a finite fitted estimate, not an observed joint.
                (output / 'fitted_valid.u8').write_bytes(bytes([1]) * count * 22)
        mark('geometry_s', started)

    files = ('parameters.json', 'observations.json', 'triangles.u32', 'vertices.f32', 'joints.f32', 'fitted_valid.u8',
             'selection.json', 'source-sidecar.json')
    with worker.metrics.measure('export_artifact_identity'):
        artifacts = {name: {'byte_size': (output / name).stat().st_size, 'sha256': digest(output / name)} for name in files}
    segment_peaks = {kind: max((event.get('peak_' + kind + '_bytes', 0)
                               for event in worker.metrics.events[event_start:]), default=0)
                     for kind in ('allocated', 'reserved')}
    return {'geometry': metadata, 'frame_count': count, 'artifacts': artifacts,
            'array_layout': 'little endian, frame-major then vertex/joint-major XYZ; triangle triples u32',
            'fitted_valid_layout': 'u8 frame-major then 22 joints; 1 finite estimate, 0 unavailable',
            'asset_sha256': assets, 'stage_seconds': stages,
            'counters': counters.finish(len(plan['sampling']['observation_indices']), grid_count, batch_size),
            'model_lifecycle': RESIDENCY_MODES[worker.store.residency],
            'runtime_versions': {name: importlib.metadata.version(name) for name in
                                 ('torch', 'torchvision', 'av', 'numpy', 'smplx', 'pycolmap', 'ultralytics')},
            'gpu': {'name': torch.cuda.get_device_name(),
                    'total_memory_bytes': torch.cuda.get_device_properties(0).total_memory,
                    'peak_scope': 'segment maximum over synchronized measured stages',
                    'peak_allocated_bytes': segment_peaks['allocated'],
                    'peak_reserved_bytes': segment_peaks['reserved'],
                    'process_peaks_through_segment_bytes': dict(worker.metrics.peaks)},
            'limitations': ['No Quest/world registration or Unity conversion.',
                            'No clinical or held-out-person validation.',
                            'Source-frame repetitions remain repeated timestamps. Do not replace them with index/30.',
                            'Invalid source images and failed processed tracks fail; intentionally skipped images are not identity-verified.',
                            'VO rotations between sampled images are interpolated estimates.',
                            'Movement findings, foot analysis and microscope are not implemented.']}
