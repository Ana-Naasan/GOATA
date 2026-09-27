"""CPU stand-ins exercise precision ownership and boundaries, not CUDA arithmetic."""
from contextlib import contextmanager, nullcontext
import importlib.util
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import models


class Tensor:
    def __init__(self, dtype='torch.float32', value=1, device='cuda'):
        self.dtype, self.value, self.device = dtype, value, NS(type=device)
    def is_floating_point(self):
        return self.dtype in ('torch.float16','torch.float32','torch.float64')
    def numel(self):
        return 2
    def element_size(self):
        return 2 if self.dtype == 'torch.float16' else 4
    def float(self):
        return Tensor('torch.float32', self.value, self.device.type)


class Module:
    def __init__(self):
        self._modules, self._parameters, self._buffers = {}, {}, {}
        self.conversions = []
    def __setattr__(self,name,value):
        object.__setattr__(self,name,value)
        if isinstance(value,Module):
            self._modules[name] = value
    def named_parameters(self):
        yield from self._parameters.items()
        for name,child in self._modules.items():
            yield from ((name+'.'+key,value) for key,value in child.named_parameters())
    def named_buffers(self):
        yield from self._buffers.items()
        for name,child in self._modules.items():
            yield from ((name+'.'+key,value) for key,value in child.named_buffers())
    def parameters(self):
        return (v for _,v in self.named_parameters())
    def buffers(self):
        return (v for _,v in self.named_buffers())
    def float(self):
        return self.convert('torch.float32')
    def half(self):
        return self.convert('torch.float16')
    def convert(self,dtype):
        self.conversions.append(dtype)
        for value in [*self.parameters(), *self.buffers()]:
            if value.is_floating_point():
                value.dtype = dtype
        return self
    def eval(self):
        return self
    def __call__(self,*args,**kwargs):
        return self.forward(*args,**kwargs)


def boundary():
    modes = [False]
    caches = [True]
    @contextmanager
    def autocast(device_type,enabled=True,dtype=None,cache_enabled=True):
        assert device_type == 'cuda'
        assert not enabled or dtype == 'torch.float16'
        modes.append(enabled)
        caches.append(cache_enabled)
        try:
            yield
        finally:
            modes.pop()
            caches.pop()
    torch = NS(nn=NS(Module=Module),Tensor=Tensor,float16='torch.float16',float32='torch.float32',
               is_autocast_cache_enabled=lambda: caches[-1],
               autocast=autocast,isfinite=lambda x:NS(all=lambda:math.isfinite(x.value)))
    spec = importlib.util.spec_from_file_location('precision_under_test',Path(models.__file__).with_name('precision.py'))
    precision = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'torch':torch}):
        spec.loader.exec_module(precision)
    return torch,precision,modes


class PrecisionTests(unittest.TestCase):
    def test_only_neural_forward_autocasts_and_returns_finite_fp32(self):
        torch, precision, modes = boundary()
        class Neural(Module):
            def __init__(self):
                super().__init__()
                self._parameters['weight'] = Tensor()
                self._buffers.update(scale=Tensor(), index=Tensor('torch.int64'))
                self.calls = []
            def forward(self,inputs):
                image = inputs['img'] if isinstance(inputs,dict) else inputs
                assert torch.is_autocast_cache_enabled() is False
                self.calls.append((modes[-1],image.dtype))
                return Tensor('torch.float16' if modes[-1] else 'torch.float32')
        for label in ('pose','features'):
            for mode in ('fp32','amp-fp16','weights-fp16'):
                with self.subTest(label=label,mode=mode):
                    original = Neural()
                    wrapped = precision.NeuralForward(original,mode,label)
                    self.assertEqual(list(wrapped._modules.values()),[original])
                    expected = 'torch.float16' if mode == 'weights-fp16' else 'torch.float32'
                    self.assertEqual(original.conversions,[expected])
                    self.assertEqual([v.dtype for v in wrapped.parameters()],[expected])
                    self.assertEqual([v.dtype for v in wrapped.buffers()],[expected,'torch.int64'])
                    for _ in range(2):
                        image = Tensor()
                        # fp32 must disable an inherited autocast too.
                        with torch.autocast('cuda',dtype=torch.float16):
                            output = wrapped({'img':image} if label == 'features' else image)
                            self.assertTrue(modes[-1])
                        self.assertEqual(output.dtype,torch.float32)
                        self.assertEqual(image.dtype,torch.float32)
                    self.assertEqual(original.calls,[(mode != 'fp32',torch.float32)]*2)
                    self.assertEqual(original.conversions,[expected])
                    inventory = precision.dtype_inventory(wrapped)
                    self.assertEqual(inventory['parameters'][expected],dict(tensors=1,numel=2,bytes=4 if mode=='weights-fp16' else 8))
                    self.assertIn('torch.int64',inventory['buffers'])

    def test_real_torch_registration_and_dtype_inventory_on_cpu_when_available(self):
        if importlib.util.find_spec('torch') is None:
            self.skipTest('Torch is not installed locally; target runtime runs this CPU ownership check')
        import torch
        from precision import NeuralForward, dtype_inventory
        for mode in ('fp32','amp-fp16','weights-fp16'):
            neural = torch.nn.Linear(3,2)
            neural.register_buffer('scale',torch.ones(2))
            neural.register_buffer('index',torch.arange(2))
            wrapper = NeuralForward(neural,mode,'features')
            expected = torch.float16 if mode=='weights-fp16' else torch.float32
            self.assertEqual(list(wrapper.children()),[neural])
            self.assertEqual({id(p) for p in wrapper.parameters()},{id(p) for p in neural.parameters()})
            self.assertEqual({p.dtype for p in wrapper.parameters()},{expected})
            self.assertEqual(neural.scale.dtype,expected)
            self.assertEqual(neural.index.dtype,torch.int64)
            self.assertEqual(set(wrapper.state_dict()),{'neural.weight','neural.bias','neural.scale','neural.index'})
            wrapper.to('cpu')
            self.assertEqual(dtype_inventory(wrapper)['parameters'][str(expected)]['numel'],8)

    def test_bad_precision_inputs_and_nonfinite_outputs_never_fall_back(self):
        torch,precision,modes = boundary()
        original = Module()
        original.forward = Mock(return_value=Tensor(value=float('inf')))
        for mode in ('fp32','amp-fp16','weights-fp16'):
            wrapped = precision.NeuralForward(original,mode,'pose')
            with self.assertRaisesRegex(ValueError,'nonfinite'):
                wrapped(Tensor())
            for image in (Tensor('torch.float16'),Tensor(device='cpu')):
                before = original.forward.call_count
                with self.assertRaises(ValueError):
                    wrapped(image)
                self.assertEqual(original.forward.call_count,before)
        with self.assertRaises(ValueError):
            precision.NeuralForward(original,'bf16','pose')
        with self.assertRaises(ValueError):
            precision.NeuralForward(original,'amp-fp16','gvhmr')
        self.assertEqual(modes,[False])

    def test_pinned_extractors_keep_flip_and_numpy_decode_outside_autocast(self):
        import ast
        import hashlib
        import json
        import numpy as np
        torch,precision,modes = boundary()
        test = self
        class ArrayTensor(Tensor):
            def __init__(self,array,device='cuda'):
                self.array = np.asarray(array)
                super().__init__('torch.'+str(self.array.dtype),device=device)
                self.shape = self.array.shape
            def __getitem__(self,key):
                return ArrayTensor(self.array[key],self.device.type)
            def cpu(self):
                return ArrayTensor(self.array,'cpu')
            def cuda(self):
                return ArrayTensor(self.array,'cuda')
            def clone(self):
                return ArrayTensor(self.array.copy(),self.device.type)
            def detach(self):
                return self
            def float(self):
                return ArrayTensor(self.array.astype(np.float32),self.device.type)
            def flip(self,axis):
                return ArrayTensor(np.flip(self.array,axis),self.device.type)
            def chunk(self,n):
                return tuple(ArrayTensor(a,self.device.type) for a in np.split(self.array,n))
            def numpy(self):
                test.assertFalse(modes[-1])
                test.assertEqual(self.dtype,torch.float32)
                return self.array
            def __add__(self,other):
                return ArrayTensor(self.array+other.array,self.device.type)
            def __mul__(self,other):
                return ArrayTensor(self.array*other,self.device.type)
            def __truediv__(self,other):
                return ArrayTensor(self.array/other,self.device.type)
        torch.Tensor = ArrayTensor
        torch.cat = lambda arrays,dim=0:ArrayTensor(np.concatenate([a.array for a in arrays],axis=dim),arrays[0].device.type)
        torch.from_numpy = lambda array:ArrayTensor(array,'cpu')
        torch.no_grad = nullcontext
        torch.isfinite = lambda array:np.isfinite(array.array)
        source = os.environ.get('PHYSIO_GVHMR_SOURCE')
        if source:
            source_root = Path(source)
        else:
            spec = importlib.util.find_spec('hmr4d')
            if spec is None:
                self.skipTest('pinned extractor checks require GVHMR or PHYSIO_GVHMR_SOURCE')
            source_root = Path(spec.origin).parent.parent
        hashes = json.loads(Path(models.__file__).with_name('source-inspection.json').read_text())['read_only_sources']['gvhmr']['sha256']
        decoded, flipped = [], []
        def decode(heatmaps,center,scale,use_udp):
            self.assertFalse(modes[-1])
            self.assertTrue(use_udp)
            self.assertTrue(all(a.dtype==np.float32 for a in (heatmaps,center,scale)))
            decoded.append(len(heatmaps))
            return np.zeros((len(heatmaps),17,2),np.float32),np.ones((len(heatmaps),17,1),np.float32)
        def flip(heatmaps):
            self.assertFalse(modes[-1])
            self.assertEqual(heatmaps.dtype,torch.float32)
            flipped.append(len(heatmaps.array))
            return heatmaps
        for filename,class_name,method_name,label in (
            ('vitpose.py','VitPoseExtractor','extract','pose'),
            ('vitfeat_extractor.py','Extractor','extract_video_features','features'),
        ):
            relative = 'hmr4d/utils/preproc/'+filename
            source = (source_root/relative).read_bytes()
            self.assertEqual(hashlib.sha256(source).hexdigest(),hashes[relative])
            node = next(n for n in ast.parse(source).body if getattr(n,'name',None)==class_name)
            node.body = [n for n in node.body if getattr(n,'name',None)==method_name]
            node.body[0].decorator_list = []
            namespace = dict(torch=torch,np=np,tqdm=lambda values,**kwargs:values,
                             flip_heatmap_coco17=flip,keypoints_from_heatmaps=decode)
            exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),relative,'exec'),namespace)
            for mode in ('fp32','amp-fp16','weights-fp16'):
                for batch in (2,4,8):
                    extractor = namespace[class_name]()
                    extractor.flip_test,extractor.tqdm_leave = True,False
                    def neural_forward(inputs):
                        image = inputs['img'] if label=='features' else inputs
                        self.assertEqual(image.dtype,torch.float32)
                        self.assertEqual(modes[-1],mode!='fp32')
                        self.assertEqual(image.shape[0],batch*(2 if label=='pose' else 1))
                        shape = (batch*2,17,64,48) if label=='pose' else (batch,1024)
                        return ArrayTensor(np.ones(shape,np.float16 if modes[-1] else np.float32))
                    neural = Module()
                    neural.forward = neural_forward
                    setattr(extractor,'pose' if label=='pose' else 'extractor',precision.NeuralForward(neural,mode,label))
                    crops = ArrayTensor(np.ones((batch,3,256,256),np.float32),'cpu')
                    boxes = ArrayTensor(np.ones((batch,3),np.float32),'cpu')
                    output = getattr(extractor,method_name)(crops,boxes)
                    self.assertEqual(output.dtype,torch.float32)
                    self.assertEqual(output.shape,(batch,17,3) if label=='pose' else (batch,1024))
        self.assertEqual(decoded,[2,4,8]*3)
        self.assertEqual(flipped,decoded)

    def test_worker_converts_and_logs_only_once_and_keeps_other_models_fp32(self):
        from models import WorkerModels
        torch,precision,_ = boundary()
        metrics = Mock()
        metrics.measure.side_effect = lambda name:nullcontext()
        for mode in ('fp32','amp-fp16','weights-fp16'):
            modules = {name:Module() for name in ('pose','features','detector','gvhmr','body')}
            for module in modules.values():
                module._parameters['weight'] = Tensor()
                module._buffers['scale'] = Tensor()
            objects = dict(pose=NS(pose=modules['pose'],flip_test=True),features=NS(extractor=modules['features']),
                           detector=NS(yolo=NS(model=modules['detector'])),gvhmr=modules['gvhmr'],body=modules['body'])
            factories = {name:Mock(return_value=obj) for name,obj in objects.items()}
            with patch.dict(sys.modules,{'torch':torch,'precision':precision}), \
                 patch.object(WorkerModels,'move'),patch.object(WorkerModels,'residency'):
                worker = WorkerModels(metrics,'.',(),Mock(),precision=mode)
                worker.preload(factories)
                for _ in range(2):
                    for name,factory in factories.items():
                        with worker.use(name,factory):
                            pass
                for name,module in modules.items():
                    dtype = 'torch.float16' if mode=='weights-fp16' and name in ('pose','features') else 'torch.float32'
                    self.assertEqual([v.dtype for v in module.parameters()],[dtype])
                    self.assertLessEqual(len(module.conversions),1)
                    self.assertIn(dtype,worker.dtype_inventories[name]['parameters'])
                    factories[name].assert_called_once()
                self.assertTrue(objects['pose'].flip_test)
                worker.close()
        events = [c.args[0] for c in metrics.emit.call_args_list if c.args[0].get('event')=='model_precision']
        self.assertEqual(len(events),15)


if __name__ == '__main__':
    unittest.main()
