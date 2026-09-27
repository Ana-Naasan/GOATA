import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_persistent_first_then_fresh_serial_cold_processes(self):
        for residency in ('resident', 'cpu-offload'):
            with self.subTest(residency=residency):
                self.check_serial_processes(residency)

    def test_completed_resident_fit_requires_all_worker_evidence(self):
        self.check_serial_processes('resident', fit_evidence=True)
        self.check_serial_processes('cpu-offload', fit_evidence=True)

    def check_serial_processes(self, residency, fit_evidence=False):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            calls = []
            def launch(command, output_root, timeout):
                self.assertGreater(timeout,0)
                calls.append(command)
                output = Path(command[command.index('--output')+1])
                output.mkdir()
                if '--prepare' not in command:
                    start = command.index('--indices')+1
                    stop = command.index('--launched-ns')
                    indices = [int(x) for x in command[start:stop]]
                    (output/'result.json').write_text(json.dumps({'status': 'complete', 'all_resident_fit_proven': fit_evidence,
                        'segments': [dict(seconds=1, output_since_launch_s=2) for i in indices]}))
                return 1
            args = SimpleNamespace(video=root/'video', calibration=root/'calib', output=root/'result', timeout_s=30,
                                   residency=residency)
            with patch('benchmark.launch', side_effect=launch):
                benchmark.benchmark(args)
            self.assertEqual(len(calls),6)
            self.assertIn('--prepare',calls[0])
            self.assertEqual(calls[1][calls[1].index('--indices')+1:calls[1].index('--launched-ns')],['0','1','2','3'])
            self.assertEqual([c[c.index('--indices')+1] for c in calls[2:]],['0','1','2','3'])
            result = json.loads((args.output/'benchmark.json').read_text())
            self.assertEqual(result['persistent_process_wall_s'],1)
            self.assertEqual(result['cold_process_wall_sum_s'],4)
            self.assertEqual(result['all_resident_fit_proven'], fit_evidence and residency == 'resident')
            self.assertEqual(result['residency_mode'], residency)
            from lifecycle import RESIDENCY_MODES
            self.assertEqual(result['lifecycle'], RESIDENCY_MODES[residency])
            for command in calls[1:]:
                self.assertEqual(command[command.index('--residency')+1], residency)

    def test_failure_stops_without_retry_and_retains_status(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            args = SimpleNamespace(video=root/'video', calibration=root/'calib', output=root/'result', timeout_s=30,
                                   residency='resident')
            with patch('benchmark.launch', side_effect=ValueError('failed')) as launch:
                with self.assertRaises(ValueError):
                    benchmark.benchmark(args)
            launch.assert_called_once()
            self.assertFalse((args.output/'benchmark.json').exists())
            self.assertEqual(json.loads((args.output/'failure.json').read_text())['status'],'failed')

    def test_cli_defaults_to_resident_and_accepts_only_explicit_modes(self):
        import worker
        for module, target, arguments in (
            (benchmark, 'benchmark', ['--video', 'v', '--calibration', 'c', '--output', 'out']),
            (worker, 'run', ['--inputs', 'in', '--output', 'out', '--indices', '0', '--launched-ns', '1']),
        ):
            for options, expected in (([], 'resident'), (['--residency', 'resident'], 'resident'),
                                      (['--residency', 'cpu-offload'], 'cpu-offload')):
                with patch('sys.argv', [module.__file__, *arguments, *options]), patch.object(module, target) as run:
                    module.main()
                    actual = run.call_args.args[0].residency if module is benchmark else run.call_args.kwargs['residency']
                    self.assertEqual(actual, expected)
            import io
            with patch('sys.argv', [module.__file__, *arguments, '--residency', 'auto']), \
                 patch('sys.stderr', new=io.StringIO()), patch.object(module, target) as run:
                with self.assertRaises(SystemExit) as error:
                    module.main()
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
