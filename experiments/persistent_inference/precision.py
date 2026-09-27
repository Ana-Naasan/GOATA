"""Selective CUDA neural precision. Decoding and all other stages stay FP32."""
import torch

from lifecycle import PRECISIONS


def dtype_inventory(module):
    result = {}
    for label, tensors in (('parameters', module.parameters()), ('buffers', module.buffers())):
        counts = result[label] = {}
        for tensor in tensors:
            row = counts.setdefault(str(tensor.dtype), dict(tensors=0, numel=0, bytes=0))
            row['tensors'] += 1
            row['numel'] += tensor.numel()
            row['bytes'] += tensor.numel() * tensor.element_size()
    return result


class NeuralForward(torch.nn.Module):
    """Own the original module as a registered child; convert its weights once."""
    def __init__(self, module, precision, label):
        super().__init__()
        if precision not in PRECISIONS or label not in ('pose', 'features'):
            raise ValueError('unsupported selective neural precision boundary')
        self.precision, self.label = precision, label
        self.neural = module.half() if precision == 'weights-fp16' else module.float()
        self.eval()

    def forward(self, inputs):
        # Pinned HMR2 feature forward accepts only {img}; ViTPose takes a tensor.
        image = inputs['img'] if self.label == 'features' else inputs
        if not isinstance(image, torch.Tensor) or image.dtype != torch.float32 or image.device.type != 'cuda':
            raise ValueError(f'{self.label} neural input must be a CUDA FP32 tensor')
        # The adapter has an outer disabled-autocast scope. Its nesting keeps
        # cached weight casts alive across both large neural models. Disable
        # that cache explicitly so AMP cannot retain both FP16 copies together.
        with torch.autocast(device_type='cuda', dtype=torch.float16,
                            enabled=self.precision != 'fp32', cache_enabled=False):
            output = self.neural(inputs)
        if not isinstance(output, torch.Tensor) or not output.is_floating_point():
            raise ValueError(f'invalid {self.label} neural output')
        output = output.float()
        # This check precedes flip averaging and NumPy heatmap decoding, so
        # overflow cannot disappear into a plausible keypoint or feature.
        if not torch.isfinite(output).all():
            raise ValueError(f'nonfinite {self.label} neural output; no precision fallback')
        return output
