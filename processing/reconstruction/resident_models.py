"""Pinned model lifetime and precision boundaries, with no input/result cache.

Adapted from experiments/persistent_inference/{models,lifecycle,precision}.py.
Only retained AutoBackend, fresh predictor cleanup and FP16 neural I/O mechanics
are reused. Experiment sampling, offload and quantization are not imported.
"""

import importlib.metadata
from pathlib import Path

from .runtime import MAX_INFERENCE_FRAMES


def reset_detector(yolo, callbacks):
    predictor = yolo.predictor
    try:
        if predictor is not None:
            for tracker in getattr(predictor, 'trackers', ()):
                tracker.reset()
            cap = getattr(getattr(predictor, 'dataset', None), 'cap', None)
            if cap is not None:
                cap.release()
            for writer in getattr(predictor, 'vid_writer', {}).values():
                writer.release()
    finally:
        yolo.predictor = None
        yolo.callbacks = {name: list(functions) for name, functions in callbacks.items()}


class Detector:
    def __init__(self):
        from hmr4d.utils.preproc import Tracker

        self.yolo = Tracker().yolo
        self.callbacks = {key: list(value) for key, value in self.yolo.callbacks.items()}
        # Ultralytics 8.2.42 setup_model does fusion and FP32 conversion once.
        predictor = self.new_predictor()
        predictor.setup_model(model=self.yolo.model, verbose=False)
        self.backend = predictor.model
        self.reset()

    def new_predictor(self):
        return self.yolo._smart_load('predictor')(
            overrides={**self.yolo.overrides, 'device': 'cuda', 'half': False, 'batch': 1},
            _callbacks=self.yolo.callbacks)

    def reset(self):
        reset_detector(self.yolo, self.callbacks)

    def track(self, video_path):
        if not Path(video_path).is_file():
            raise ValueError('detector accepts a prepared local video only')
        self.reset()
        results = None
        try:
            predictor = self.new_predictor()
            predictor.model = self.backend
            predictor.device = self.backend.device
            predictor.args.half = self.backend.fp16
            self.yolo.predictor = predictor
            results = self.yolo.track(str(video_path), device='cuda', conf=0.5, classes=0,
                                      verbose=False, stream=True, persist=False, save=False, half=False)
            history = []
            for result in results:
                if len(history) >= MAX_INFERENCE_FRAMES:
                    raise ValueError('detector input exceeds inference frame bound')
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
                self.reset()


def wrap_fp16(module, label):
    """Convert weights once, autocast without a weight cache, return FP32."""
    import torch

    if label not in ('pose', 'features'):
        raise ValueError('FP16 allowed only for pose and features')

    class NeuralForward(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.neural = module.half()
            self.eval()

        def forward(self, inputs):
            image = inputs['img'] if label == 'features' else inputs
            if not isinstance(image, torch.Tensor) or image.dtype != torch.float32 or image.device.type != 'cuda':
                raise ValueError('neural input must be a CUDA FP32 tensor')
            with torch.autocast(device_type='cuda', dtype=torch.float16, cache_enabled=False):
                output = self.neural(inputs)
            if not isinstance(output, torch.Tensor) or not output.is_floating_point():
                raise ValueError('invalid neural output')
            output = output.float()
            if not torch.isfinite(output).all():
                raise ValueError('nonfinite neural output; no precision fallback')
            return output

    return NeuralForward()


def model_factories():
    from hmr4d.utils.preproc import Extractor, VitPoseExtractor
    from hmr4d.utils.smplx_utils import make_smplx

    from .gvhmr import load_demo_model

    if importlib.metadata.version('ultralytics') != '8.2.42':
        raise ValueError('resident detector requires inspected Ultralytics 8.2.42')

    def pose():
        model = VitPoseExtractor()
        model.pose = wrap_fp16(model.pose, 'pose')
        return model

    def features():
        model = Extractor()
        model.extractor = wrap_fp16(model.extractor, 'features')
        return model

    return {'detector': Detector, 'pose': pose, 'features': features,
            'gvhmr': lambda: load_demo_model().float(),
            'body': lambda: make_smplx('supermotion').cuda().eval().float()}
