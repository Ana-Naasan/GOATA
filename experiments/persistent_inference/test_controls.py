"""CPU checks for experiment controls, source timing and per-solver seed injection."""
import ast
from fractions import Fraction
import io
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import fast
import lifecycle
import worker


class ControlTests(unittest.TestCase):
    arguments = ['--inputs', 'in', '--output', 'out', '--indices', '0', '--launched-ns', '1']

    def test_cli_defaults_and_explicit_controls(self):
        for flags, expected in (
            ([], dict(precision='fp32', variant='960-15', batch_size=2, vo_seed=0)),
            (['--precision', 'weights-fp16', '--variant', '640-10', '--batch-size', '8', '--vo-seed', '17'],
             dict(precision='weights-fp16', variant='640-10', batch_size=8, vo_seed=17)),
            (['--precision', 'amp-fp16', '--batch-size', '4'],
             dict(precision='amp-fp16', variant='960-15', batch_size=4, vo_seed=0)),
        ):
            with patch('sys.argv', ['worker.py', *self.arguments, *flags]), patch('worker.run') as run:
                worker.main()
                self.assertEqual({k: run.call_args.kwargs[k] for k in expected}, expected)

    def test_unsupported_cli_and_programmatic_controls_fail_before_output(self):
        bad = [('precision', 'bf16'), ('variant', '1280-30'), ('batch_size', 16), ('vo_seed', -1)]
        for key, value in bad:
            with self.subTest(key=key), patch('sys.argv', ['worker.py', *self.arguments,
                 '--'+key.replace('_', '-'), str(value)]), patch('sys.stderr', new=io.StringIO()), patch('worker.run') as run:
                with self.assertRaises(SystemExit) as error:
                    worker.main()
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()
            with self.assertRaises(ValueError):
                worker.run(Path('unused-input'), Path('must-not-create'), [0], 1, **{key: value})
        for options in (dict(batch_size=True), dict(batch_size=2.0), dict(vo_seed=True), dict(vo_seed=1.5)):
            with self.assertRaises(ValueError):
                lifecycle.validate_controls(**options)
        self.assertFalse(Path('must-not-create').exists())

    def test_ten_hz_causal_sampling_preserves_original_identity_and_calibration(self):
        for times in ([round(Fraction(i*10**9,30)) for i in range(60)],
                      [t*10**6 for t in (0,20,73,94,134,167,199,241,267,300)]):
            frames = [dict(frame_id=500+i, pts_ns=str(10**12+t), image_valid=True) for i,t in enumerate(times)]
            sample = fast.sampling(frames, 10, len(times))
            self.assertEqual(sample['observation_hz'], 10)
            self.assertIn('10Hz', sample['policy'])
            self.assertEqual(sample['observations'], [frames[i] for i in sample['observation_indices']])
            for i,j in enumerate(sample['grid_to_observation']):
                target = 10**12+round(Fraction(i*10**9,30))
                self.assertLessEqual(int(sample['observations'][j]['pts_ns']), target)
                if j+1 < len(sample['observations']):
                    self.assertGreater(int(sample['observations'][j+1]['pts_ns']), target)
            if len(times) == 60:
                self.assertEqual(sample['observation_indices'], list(range(0,60,3)))
                self.assertEqual(len(fast.scatter(sample['observations'], sample['grid_to_observation'])),60)
        self.assertEqual(fast.resized(1920,1080,640,dict(fx=1321.,fy=1321.,cx=960.,cy=540.)),
                         (640,360,dict(fx=1321/3,fy=1321/3,cx=320.,cy=180.)))
        for hz in (0, 12, 30, 10.0, True):
            with self.assertRaises(ValueError):
                fast.sampling(frames,hz,10)
        frames[1]['image_valid'] = False
        with self.assertRaises(ValueError):
            fast.sampling(frames,10,10)

    def test_variant_bounds_are_extended_not_removed(self):
        for variant,w,h,hz,n in [('960-15',960,540,15,32), ('640-10',640,360,10,22), ('640-15',640,360,15,32)]:
            plan = dict(variant=variant,width=w,height=h,selected_indices=list(range(63)),
                        sampling=dict(observation_hz=hz,observation_indices=list(range(n))))
            lifecycle.validate_segment(plan)
            for bad in (dict(width=1280), dict(height=480), dict(variant='1280-30'),
                        dict(selected_indices=list(range(64))),
                        dict(sampling=dict(observation_hz=hz, observation_indices=list(range(n+1)))),
                        dict(sampling=dict(observation_hz=30, observation_indices=list(range(n))))):
                with self.assertRaises(ValueError):
                    lifecycle.validate_segment(dict(plan, **bad))

    def test_selected_640_15_uses_fifteen_observations_without_retiming_source(self):
        frames = [dict(frame_id=500+i, pts_ns=str(round(Fraction(i*10**9,30))), image_valid=True)
                  for i in range(60)]
        width,hz = fast.VARIANTS['640-15']
        self.assertEqual(width,640)
        sample = fast.sampling(frames,hz,60)
        self.assertEqual(sample['observation_indices'],list(range(0,60,2)))
        self.assertEqual([f['frame_id'] for f in sample['observations']],list(range(500,560,2)))
        self.assertEqual(len(sample['grid_to_observation']),60)
        self.assertEqual(lifecycle.validate_controls('weights-fp16','640-15',8)['variant'],'640-15')

    def test_both_actual_adapter_slice_loops_use_the_selected_batch(self):
        tree = ast.parse(Path(worker.__file__).with_name('adapter.py').read_text())
        loops = [n for n in ast.walk(tree) if isinstance(n, ast.For) and isinstance(n.target, ast.Name)
                 and n.target.id == 'i']
        self.assertEqual(len(loops), 2)
        # Execute the real adapter loop statements with plain list crops.
        for batch_size in (2,4,8):
            calls = []
            class Part(list):
                def cpu(self):
                    return self
            def extract(crops, boxes):
                calls.append((crops, boxes))
                return Part(crops)
            for loop in loops:
                calls.clear()
                counts = lifecycle.Counters()
                scope = dict(count=21,batch_size=batch_size,crops=list(range(21)),crop_boxes=list(range(21)),
                             worker=NS(settings=dict(batch_size=batch_size)), parts=[], counters=counts,
                             pose=NS(extract=extract), extractor=NS(extract_video_features=extract))
                exec(compile(ast.Module(body=[loop],type_ignores=[]),'adapter-slice-loop','exec'), scope)
                self.assertEqual([len(c[0]) for c in calls],
                                 [min(batch_size,21-i) for i in range(0,21,batch_size)])
                self.assertTrue(all(crops == boxes for crops,boxes in calls))
                self.assertEqual(sum(scope['parts'], []), list(range(21)))
            counts = lifecycle.Counters()
            for key,value in dict(detection_frames=21,pose_frames=21,feature_frames=21,scatter_frames=60,
                                  export_frames=60,pose_calls=(21+batch_size-1)//batch_size,
                                  feature_calls=(21+batch_size-1)//batch_size,gvhmr_calls=1,vo_sample_frames=9).items():
                counts.add(key,value)
            counts.finish(21,60,batch_size=batch_size)

    def test_adapter_explicitly_disables_outer_autocast_for_all_stages(self):
        tree = ast.parse(Path(worker.__file__).with_name('adapter.py').read_text())
        scopes = [node for node in ast.walk(tree) if isinstance(node,ast.With)
                  and any(isinstance(item.context_expr,ast.Call)
                          and ast.unparse(item.context_expr.func)=='torch.autocast'
                          and any(k.arg=='enabled' and isinstance(k.value,ast.Constant) and k.value.value is False
                                  for k in item.context_expr.keywords)
                          for item in node.items)]
        self.assertEqual(len(scopes),1)
        calls = {ast.unparse(node.func) for node in ast.walk(scopes[0]) if isinstance(node,ast.Call)}
        self.assertTrue({'tracker.track','pose.extract','extractor.extract_video_features','model.predict','body',
                         'vo.process_video_T_w2c_list_np'}.issubset(calls))

    def test_each_vo_solver_sets_nested_seed_without_changing_other_options(self):
        from adapter import CameraMotionSolver
        backends = []
        def construct(params):
            result = NS(camera=params, options=NS(ransac=NS(random_seed=-1), min_num_inliers=10))
            backends.append(result)
            return result
        module = 'hmr4d.utils.preproc.relpose.solver_two_view'
        with patch.dict(sys.modules,{module:NS(PycolmapRansacTwoViewGeometrySolver=construct)}):
            a, b = CameraMotionSolver('camera', seed=0), CameraMotionSolver('camera', seed=29)
        self.assertIs(a.backend,backends[0])
        self.assertIs(b.backend,backends[1])
        self.assertEqual([x.options.ransac.random_seed for x in backends],[0,29])
        self.assertEqual([x.options.min_num_inliers for x in backends],[10,10])

    def test_installed_pycolmap_seed_api_when_available(self):
        import importlib.util
        if importlib.util.find_spec('pycolmap') is None:
            self.skipTest('pycolmap is not installed locally; target runtime must pass this check')
        import pycolmap
        options = pycolmap.TwoViewGeometryOptions()
        self.assertTrue(hasattr(options.ransac, 'random_seed'))
        options.ransac.random_seed = 73
        self.assertEqual(options.ransac.random_seed, 73)
        self.assertEqual(options.todict()['ransac']['random_seed'], 73)

    def test_vo_seed_unavailable_readonly_ignored_or_unrepresentable_fails_explicitly(self):
        from adapter import CameraMotionSolver
        class ReadOnly:
            @property
            def random_seed(self):
                return -1
        class Ignored(ReadOnly):
            @ReadOnly.random_seed.setter
            def random_seed(self,value):
                pass
        class Overflow(ReadOnly):
            @ReadOnly.random_seed.setter
            def random_seed(self,value):
                raise OverflowError('C++ integer overflow')
        module = 'hmr4d.utils.preproc.relpose.solver_two_view'
        for options in (NS(),NS(ransac=NS()),NS(ransac=ReadOnly()),NS(ransac=Ignored()),NS(ransac=Overflow())):
            with patch.dict(sys.modules,{module:NS(PycolmapRansacTwoViewGeometrySolver=lambda p:NS(options=options))}):
                with self.assertRaisesRegex(RuntimeError,'random_seed'):
                    CameraMotionSolver('camera', seed=7)
        for seed in (-1, True, 0.5):
            with self.assertRaises(ValueError):
                CameraMotionSolver('camera',seed=seed)


if __name__ == '__main__':
    unittest.main()
