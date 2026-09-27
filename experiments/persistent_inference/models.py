"""Pinned upstream lifecycle adapters. No prediction or feature cache."""
import gc
from pathlib import Path

from lifecycle import IdentityRecords, RetainedModels, reset_detector, validate_controls


class Detector:
    def __init__(self):
        from hmr4d.utils.preproc import Tracker
        self.yolo = Tracker().yolo
        self.callbacks = {k: list(v) for k, v in self.yolo.callbacks.items()}
        # 8.2.42 setup_model performs .to(), fusion and FP32 conversion. Do this
        # once during construction, before resident_ready, never per take.
        predictor = self.new_predictor()
        predictor.setup_model(model=self.yolo.model, verbose=False)
        self.backend = predictor.model
        reset_detector(self.yolo, self.callbacks)

    def new_predictor(self):
        return self.yolo._smart_load('predictor')(
            overrides={**self.yolo.overrides, 'device': 'cuda', 'half': False, 'batch': 1},
            _callbacks=self.yolo.callbacks)

    def to(self, device):
        import torch
        reset_detector(self.yolo, self.callbacks)
        # Do not call YOLO._apply, which also mutates overrides. Offload moves
        # the shared Torch module and updates the retained backend's device.
        self.yolo.model.to(device)
        self.backend.device = torch.device(device)

    def track(self, video_path):
        if not Path(video_path).is_file():
            raise ValueError('detector accepts a prepared local file only')
        reset_detector(self.yolo, self.callbacks)
        results = None
        try:
            predictor = self.new_predictor()
            predictor.model = self.backend
            predictor.device = self.backend.device
            predictor.args.half = self.backend.fp16
            self.yolo.predictor = predictor
            # Model.predict now only updates args; stream_inference sees a ready
            # backend. Fresh predictors still perform the existing take warmup.
            results = self.yolo.track(str(video_path), device='cuda', conf=0.5, classes=0,
                                      verbose=False, stream=True, persist=False, save=False, half=False)
            history = []
            for result in results:
                if len(history) >= 32:
                    raise ValueError('detector input exceeds observation bound')
                if result.boxes.id is None:
                    history.append([])
                else:
                    ids = result.boxes.id.int().cpu().tolist()
                    boxes = result.boxes.xyxy.cpu().numpy()
                    history.append([{'id': key, 'bbx_xyxy': boxes[i]} for i, key in enumerate(ids)])
            return history
        finally:
            try:
                if results is not None:
                    results.close()
            finally:
                reset_detector(self.yolo, self.callbacks)


class WorkerModels:
    def __init__(self, metrics, root, assets, digest, residency='resident', *,
                 precision='fp32', variant='960-15', batch_size=2, vo_seed=0):
        self.metrics = metrics
        self.settings = validate_controls(precision, variant, batch_size, vo_seed)
        self.dtype_inventories = {}
        names = tuple('inputs/checkpoints/' + name for name in assets) + (
            'hmr4d/network/hmr2/configs/smpl_mean_params.npz',
            'hmr4d/utils/body_model/smplx2smpl_sparse.pt',
            'hmr4d/utils/body_model/smpl_coco17_J_regressor.pt',
            'hmr4d/utils/body_model/smplx_verts437.pt',
        )
        self.identities = IdentityRecords(root, names, digest)
        self.store = RetainedModels(self.move, metrics.measure, residency)

    @staticmethod
    def module(name, obj):
        if name == 'detector':
            return obj.yolo.model
        attribute = {'pose': 'pose', 'features': 'extractor'}.get(name)
        return getattr(obj, attribute) if attribute else obj

    def residency(self, name, obj, expected=None):
        import torch
        module = self.module(name, obj)
        tensors = {}
        for part in module.modules():
            for value in list(part.parameters(recurse=False)) + list(part.buffers(recurse=False)) + list(vars(part).values()):
                if isinstance(value, torch.Tensor):
                    tensors[id(value)] = value
        sizes = {}
        for tensor in tensors.values():
            device = tensor.device.type
            sizes[device] = sizes.get(device, 0) + tensor.numel()*tensor.element_size()
            # DetectionModel.stride is a CPU metadata alias after head._apply.
            # It is not an input feature. CPU parking must retain no CUDA tensor.
            if expected == 'cpu' and device != 'cpu':
                raise RuntimeError(f'{name} retained a tensor on {device} after CPU offload')
        if expected == 'cuda' and any(t.device.type != 'cuda' for t in list(module.parameters()) + list(module.buffers())):
            raise RuntimeError(f'{name} parameters/buffers did not activate on CUDA')
        self.metrics.emit(dict(event='model_residency', model=name, expected_device=expected,
                               logical_tensor_bytes_by_device=sizes, memory=self.metrics.memory(),
                               accounting='unique tensor objects; logical bytes, not physical storage or allocator bytes'))

    def move(self, name, obj, device):
        import torch
        target = obj if name == 'detector' else self.module(name, obj)
        target.to(device)
        self.residency(name, obj, device)
        if device == 'cpu':
            gc.collect()
            torch.cuda.empty_cache()

    def setup_precision(self, name, obj):
        import torch
        from precision import NeuralForward, dtype_inventory
        mode = self.settings['precision']
        attribute = {'pose': 'pose', 'features': 'extractor'}.get(name)
        if attribute:
            setattr(obj, attribute, NeuralForward(getattr(obj, attribute), mode, name))
        elif name != 'detector':
            # YOLO's pinned backend already converts to FP32 exactly once.
            self.module(name, obj).float()
        module = self.module(name, obj)
        expected = torch.float16 if attribute and mode == 'weights-fp16' else torch.float32
        if any(t.is_floating_point() and t.dtype != expected
               for t in list(module.parameters()) + list(module.buffers())):
            raise RuntimeError(f'{name} parameters/buffers differ from requested precision')
        self.dtype_inventories[name] = dtype_inventory(module)
        self.metrics.emit(dict(event='model_precision', model=name, precision=mode,
                               expected_floating_dtype=str(expected),
                               dtype_inventory=self.dtype_inventories[name], memory=self.metrics.memory()))

    def factory(self, name, factory):
        def construct():
            obj = factory()
            self.setup_precision(name, obj)
            self.residency(name, obj)
            return obj
        return construct

    def preload(self, factories):
        self.store.preload({name: self.factory(name, factory) for name, factory in factories.items()})

    def use(self, name, factory):
        return self.store.use(name, self.factory(name, factory))

    def close(self):
        if self.store.residency == 'cpu-offload':
            for name, model in self.store.models.items():
                self.move(name, model, 'cpu')
        self.store.models.clear()
