"""Adapter boundary regressions. These do not establish CUDA/model correctness."""

import builtins
import sys
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from processing.reconstruction import gvhmr

try:
    import numpy as np
except ImportError:
    np = None


class ModelLoadTests(unittest.TestCase):
    def test_demo_registration_precedes_composition_and_checkpoint_load(self):
        events = []
        model = Mock()
        model.eval.return_value = model
        model.cuda.return_value = model
        model.load_pretrained_model.side_effect = lambda path: events.append(('load', path))
        cfg = SimpleNamespace(model=object(), ckpt_path='approved.ckpt')

        def compose(**kwargs):
            self.assertIn('demo import', events)
            self.assertIn('store', events)
            events.append('compose')
            self.assertEqual(kwargs, {'config_name': 'demo'})
            return cfg

        instantiate = Mock(return_value=model)
        initialize = Mock(return_value=nullcontext())
        modules = {
            'hydra': SimpleNamespace(compose=compose, initialize_config_module=initialize,
                                     utils=SimpleNamespace(instantiate=instantiate)),
            'hmr4d.configs': SimpleNamespace(register_store_gvhmr=lambda: events.append('store')),
            'hmr4d.model.gvhmr.gvhmr_pl_demo': SimpleNamespace(DemoPL=object()),
        }
        original_import = builtins.__import__

        def import_module(name, *args, **kwargs):
            if name == 'hmr4d.model.gvhmr.gvhmr_pl_demo':
                events.append('demo import')
            return original_import(name, *args, **kwargs)

        with patch.dict(sys.modules, modules), patch('builtins.__import__', side_effect=import_module):
            self.assertIs(gvhmr.load_demo_model(), model)
        self.assertEqual(events, ['demo import', 'store', 'compose', ('load', 'approved.ckpt')])
        initialize.assert_called_once_with(version_base='1.3', config_module='hmr4d.configs')
        instantiate.assert_called_once_with(cfg.model, _recursive_=False)
        model.eval.assert_called_once_with()
        model.cuda.assert_called_once_with()


@unittest.skipIf(np is None, 'NumPy unavailable; run inside the built runtime')
class CameraMotionTests(unittest.TestCase):
    def setUp(self):
        self.backend = SimpleNamespace(camera=object(), options=object())
        self.factory = Mock(return_value=self.backend)
        self.estimate = Mock()
        self.modules = {
            'hmr4d.utils.preproc.relpose.solver_two_view': SimpleNamespace(
                PycolmapRansacTwoViewGeometrySolver=self.factory),
            'pycolmap': SimpleNamespace(estimate_calibrated_two_view_geometry=self.estimate),
        }
        self.pts = np.arange(24, dtype=np.float32).reshape(12, 2)

    def solve(self):
        with patch.dict(sys.modules, self.modules):
            return gvhmr.CameraMotionSolver('params').solve(self.pts, self.pts + 1)

    def test_success_preserves_upstream_pose_and_solver_settings(self):
        matrix = np.array([[0, -1, 0, 2], [1, 0, 0, 3], [0, 0, 1, 4]], dtype=np.float64)
        self.estimate.return_value = SimpleNamespace(cam2_from_cam1=SimpleNamespace(matrix=lambda: matrix))
        actual = self.solve()
        np.testing.assert_array_equal(actual[:3], matrix.astype(np.float32))
        np.testing.assert_array_equal(actual[3], [0, 0, 0, 1])
        self.factory.assert_called_once_with('params')
        args, kwargs = self.estimate.call_args
        self.assertIs(args[0], self.backend.camera)
        self.assertIs(args[2], self.backend.camera)
        self.assertEqual(args[1].dtype, np.float64)
        self.assertIs(kwargs['options'], self.backend.options)
        np.testing.assert_array_equal(kwargs['matches'], np.column_stack([np.arange(12)] * 2))

    def test_missing_pose_fails_without_fabricating_transform(self):
        self.estimate.return_value = SimpleNamespace(cam2_from_cam1=None)
        with self.assertRaisesRegex(ValueError, 'Camera motion unavailable.*no relative pose.*static'):
            self.solve()

    def test_unrelated_estimator_and_api_failures_propagate(self):
        failure = RuntimeError('estimator defect')
        self.estimate.side_effect = failure
        with self.assertRaises(RuntimeError) as raised:
            self.solve()
        self.assertIs(raised.exception, failure)
        self.estimate.side_effect = None
        self.estimate.return_value = SimpleNamespace()
        with self.assertRaises(AttributeError):
            self.solve()


if __name__ == '__main__':
    unittest.main()
