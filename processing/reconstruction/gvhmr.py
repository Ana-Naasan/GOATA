"""GPU adapter for the inspected GVHMR revision. Imports stay off the CPU CLI path."""

import gc
import importlib.metadata
import time
from contextlib import nullcontext
from pathlib import Path

from .native import UPSTREAM_COMMIT, prepare
from .runtime import digest, geometry_metadata, select_track, write_json

ASSETS = (
    'body_models/smplx/SMPLX_NEUTRAL.npz',
    'gvhmr/gvhmr_siga24_release.ckpt',
    'hmr2/epoch=10-step=25000.ckpt',
    'vitpose/vitpose-h-multi-coco.pth',
    'yolo/yolov8x.pt',
)


def asset_identities(*, include_auxiliary=False):
    """Hash only operator-trusted assets in the installed, pinned model tree."""
    from hmr4d import PROJ_ROOT

    if (Path(PROJ_ROOT) / 'INSPECTED_REVISION').read_text().strip() != UPSTREAM_COMMIT:
        raise ValueError('runtime source revision does not match this adapter')
    if Path.cwd().resolve() != Path(PROJ_ROOT).resolve():
        raise ValueError('run from the installed GVHMR root for upstream relative asset paths')
    paths = {name: 'inputs/checkpoints/' + name for name in ASSETS}
    if include_auxiliary:
        for name in ('hmr4d/network/hmr2/configs/smpl_mean_params.npz',
                     'hmr4d/utils/body_model/smplx2smpl_sparse.pt',
                     'hmr4d/utils/body_model/smpl_coco17_J_regressor.pt',
                     'hmr4d/utils/body_model/smplx_verts437.pt'):
            paths[name] = name
    assets = {}
    for name, relative in paths.items():
        path = Path(PROJ_ROOT) / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'missing operator-provided asset: {name}')
        assets[name] = digest(path)
    return assets


def load_demo_model():
    import hydra
    from hmr4d.configs import register_store_gvhmr

    # This import registers model/gvhmr/gvhmr_pl_demo. The general store omits it.
    # Match tools/demo/demo.py before Hydra resolves the demo defaults.
    from hmr4d.model.gvhmr.gvhmr_pl_demo import DemoPL  # noqa: F401
    from hydra import compose, initialize_config_module

    register_store_gvhmr()
    with initialize_config_module(version_base='1.3', config_module='hmr4d.configs'):
        cfg = compose(config_name='demo')
    model = hydra.utils.instantiate(cfg.model, _recursive_=False)
    model.load_pretrained_model(cfg.ckpt_path)
    return model.eval().cuda()


class CameraMotionSolver:
    """Serial SimpleVO solver with an explicit pycolmap no-pose failure."""

    def __init__(self, params):
        from hmr4d.utils.preproc.relpose.solver_two_view import (
            PycolmapRansacTwoViewGeometrySolver,
        )
        self.backend = PycolmapRansacTwoViewGeometrySolver(params)

    def solve(self, pts0, pts1):
        import numpy as np
        import pycolmap
        # Keep the pinned upstream estimator, matches and options unchanged.
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


def extract_batches(extract, crops, crop_boxes, batch_size):
    import torch

    return torch.cat([extract(crops[i:i+batch_size], crop_boxes[i:i+batch_size])
                      for i in range(0, len(crops), batch_size)])


def infer_native(video, plan, output, *, resident_models=None, batch_size=2):
    import numpy as np
    import torch
    from hmr4d.utils.geo.hmr_cam import get_bbx_xys_from_xyxy
    from hmr4d.utils.geo_transform import compute_cam_angvel
    from hmr4d.utils.preproc import Extractor, SimpleVO, Tracker, VitPoseExtractor
    from hmr4d.utils.preproc.relpose.matcher_wrapper import Matcher
    from hmr4d.utils.preproc.relpose.solver_two_view import (
        CameraParams,
        interpolate_missing_frames,
    )
    from hmr4d.utils.preproc.vitfeat_extractor import get_batch
    from hmr4d.utils.smplx_utils import make_smplx
    from hmr4d.utils.video_io_utils import read_video_np
    from smplx.joint_names import JOINT_NAMES

    if type(batch_size) is not int or batch_size != (8 if resident_models is not None else 2):
        raise ValueError('resident batches must be 8; cold batches remain 2')
    assets = asset_identities() if resident_models is None else dict(resident_models.assets)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA GPU unavailable')
    torch.cuda.reset_peak_memory_stats()
    stages = {}

    def mark(name, start):
        torch.cuda.synchronize()
        stages[name] = time.monotonic() - start

    def release():
        if resident_models is None:
            gc.collect()
            torch.cuda.empty_cache()

    def model_for(name, factory):
        return factory() if resident_models is None else resident_models.use(name)

    def checked(tensor, shape, label):
        if tuple(tensor.shape) != tuple(shape) or not torch.isfinite(tensor).all():
            raise ValueError(f'invalid {label} shape or nonfinite values')
        return tensor

    count = len(plan['selected_indices'])
    # FP16 is confined to the resident pose/feature neural wrappers. In particular,
    # flip averaging, heatmap decoding, VO, GVHMR and body fitting remain FP32.
    precision = nullcontext() if resident_models is None else torch.autocast('cuda', enabled=False)
    with torch.inference_mode(), precision:
        started = time.monotonic()
        tracker = model_for('detector', Tracker)
        history = tracker.track(str(video))
        boxes = select_track(history)
        if len(boxes) != count:
            raise ValueError('tracking output does not match prepared input')
        bbx = get_bbx_xys_from_xyxy(torch.tensor(boxes), base_enlarge=1.2).float()
        checked(bbx, (count, 3), 'boxes')
        del tracker, history
        release()
        mark('tracking_s', started)

        # ViTPose doubles each batch for flip tests. Cold retains its batch of 2;
        # resident uses 8 plus the actual tail, without changing selected images.
        started = time.monotonic()
        crops, crop_boxes = get_batch(str(video), bbx)
        pose = model_for('pose', VitPoseExtractor)
        kp2d = extract_batches(pose.extract, crops, crop_boxes, batch_size)
        checked(kp2d, (count, 17, 3), 'ViTPose output')
        del pose
        release()
        mark('vitpose_s', started)
        started = time.monotonic()
        extractor = model_for('features', Extractor)
        features = extract_batches(extractor.extract_video_features, crops, crop_boxes, batch_size)
        checked(features, (count, 1024), 'HMR2 features')
        del extractor, crops, crop_boxes
        release()
        mark('hmr2_features_s', started)

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
        transforms = vo.process_video_T_w2c_list_np(images[sample_ids], Matcher('sift'), CameraMotionSolver(params))
        transforms = interpolate_missing_frames(transforms, sample_ids)
        rotations = torch.from_numpy(transforms[:, :3, :3]).float()
        checked(rotations, (count, 3, 3), 'camera rotations')
        if (not torch.allclose(rotations.mT @ rotations, torch.eye(3).expand(count, 3, 3), atol=1e-3)
                or not torch.allclose(torch.linalg.det(rotations), torch.ones(count), atol=1e-3)):
            raise ValueError('VO returned invalid rotation matrices')
        del images, transforms, vo
        mark('camera_motion_s', started)

        started = time.monotonic()
        model = model_for('gvhmr', load_demo_model)
        data = {'length': torch.tensor(count), 'bbx_xys': bbx, 'kp2d': kp2d,
                'K_fullimg': K.repeat(count, 1, 1), 'cam_angvel': compute_cam_angvel(rotations),
                'f_imgseq': features}
        prediction = model.predict(data, static_cam=False)
        parameters = {space: {key: value.detach().cpu() for key, value in prediction[space].items()}
                      for space in ('smpl_params_global', 'smpl_params_incam')}
        plain = {space: {key: value.tolist() for key, value in fields.items()} for space, fields in parameters.items()}
        plain['K_fullimg'] = prediction['K_fullimg'].detach().cpu().tolist()
        validated = prepare({'take_id': plan['take_id'],
                             'frames': [{k: f[k] for k in ('frame_id', 'pts_ns', 'image_valid')}
                                        for f in plan['source_frames']],
                             'selected_indices': plan['selected_indices'], 'prediction': plain})
        write_json(output / 'parameters.json', validated['parameters'])
        write_json(output / 'observations.json', {'bbx_xys': bbx.tolist(), 'coco17_xy_score': kp2d.tolist(),
                                                'camera_rotation_w2c': rotations.tolist(),
                                                'vo_sample_indices': sample_ids,
                                                'score_is_calibrated_confidence': False})
        del model, prediction, data, features
        release()
        mark('gvhmr_s', started)

        started = time.monotonic()
        body = model_for('body', lambda: make_smplx('supermotion').cuda().eval())
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
        # A true bit means a finite fitted estimate, not an observed joint.
        (output / 'fitted_valid.u8').write_bytes(bytes([1]) * count * 22)
        mark('geometry_s', started)

    files = ('parameters.json', 'observations.json', 'triangles.u32', 'vertices.f32', 'joints.f32', 'fitted_valid.u8',
             'selection.json', 'source-sidecar.json')
    artifacts = {name: {'byte_size': (output / name).stat().st_size, 'sha256': digest(output / name)} for name in files}
    return {'geometry': metadata, 'frame_count': count, 'artifacts': artifacts,
            'array_layout': 'little endian, frame-major then vertex/joint-major XYZ; triangle triples u32',
            'fitted_valid_layout': 'u8 frame-major then 22 joints; 1 finite estimate, 0 unavailable',
            'asset_sha256': assets, 'stage_seconds': stages,
            'runtime_versions': {name: importlib.metadata.version(name) for name in
                                 ('torch', 'torchvision', 'av', 'numpy', 'smplx', 'pycolmap', 'ultralytics')},
            'gpu': {'name': torch.cuda.get_device_name(),
                    'total_memory_bytes': torch.cuda.get_device_properties(0).total_memory,
                    'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
                    'peak_reserved_bytes': torch.cuda.max_memory_reserved()},
            'limitations': ['No Quest/world registration or Unity conversion.',
                            'No clinical or held-out-person validation.',
                            'Source-frame repetitions remain repeated timestamps. Do not replace them with index/30.',
                            'Missing image/track intervals fail the take; no interpolation across rejected evidence.',
                            'VO rotations between sampled images are interpolated estimates.',
                            'Movement findings, foot analysis and microscope are not implemented.']}
