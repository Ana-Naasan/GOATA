"""Call the real adapter cleanup helper; CUDA and GC are counting stand-ins."""
import ast
import inspect
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import adapter


class AdapterCleanupTests(unittest.TestCase):
    def test_actual_release_helper_for_two_takes_in_both_modes(self):
        for mode, calls in (('resident', 0), ('cpu-offload', 8)):
            with self.subTest(mode=mode):
                worker = SimpleNamespace(store=SimpleNamespace(residency=mode))
                cuda = SimpleNamespace(empty_cache=Mock())
                with patch.dict(sys.modules, torch=SimpleNamespace(cuda=cuda)), patch.object(adapter.gc, 'collect') as collect:
                    for _ in range(2):
                        for _ in range(4):
                            adapter.release(worker)
                self.assertEqual(collect.call_count, calls)
                self.assertEqual(cuda.empty_cache.call_count, calls)

    def test_all_four_adapter_stage_boundaries_use_the_tested_helper(self):
        tree = ast.parse(inspect.getsource(adapter.infer_native))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'release']
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(len(call.args) == 1 and isinstance(call.args[0], ast.Name)
                            and call.args[0].id == 'worker' for call in calls))
        self.assertFalse(any(isinstance(node, ast.FunctionDef) and node.name == 'release'
                             for node in ast.walk(tree)))


if __name__ == '__main__':
    unittest.main()
