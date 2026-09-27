"""CPU fakes only. Run: python3 -m unittest -v test_resident"""
from contextlib import contextmanager
import unittest
from unittest.mock import Mock, patch

from lifecycle import MODEL_NAMES, RetainedModels


class ResidentTests(unittest.TestCase):
    def test_default_preloads_all_five_once_and_never_offloads_between_takes(self):
        moves, events = [], []
        @contextmanager
        def measure(name):
            events.append(name)
            yield
        store = RetainedModels(lambda n, obj, device: moves.append((n, device)), measure)
        factories = {name: Mock(return_value=object()) for name in sorted(MODEL_NAMES)}
        store.preload(factories)
        identities = dict(store.models)
        self.assertEqual(set(identities), MODEL_NAMES)
        self.assertEqual(store.uses, {})
        store.preload(factories)
        for _ in range(4):
            for name in factories:
                with store.use(name, factories[name]) as model:
                    self.assertIs(model, identities[name])
                    self.assertEqual(len(store.models), 5)
        for factory in factories.values():
            factory.assert_called_once()
        self.assertEqual(moves, [(name, 'cuda') for name in factories])
        self.assertEqual(len(events), 10)
        self.assertEqual(store.constructors, dict.fromkeys(MODEL_NAMES, 1))
        self.assertEqual(store.uses, dict.fromkeys(MODEL_NAMES, 4))
        self.assertIsNone(store.active)

    def test_worker_models_preload_audits_each_constructor_and_close_does_not_offload(self):
        from models import WorkerModels
        metrics = Mock()
        from contextlib import nullcontext
        metrics.measure.side_effect = lambda name: nullcontext()
        factories = {name: Mock(return_value=object()) for name in sorted(MODEL_NAMES)}
        with patch.object(WorkerModels, 'move') as move, patch.object(WorkerModels, 'residency') as audit:
            worker = WorkerModels(metrics, '.', (), Mock())
            worker.preload(factories)
            self.assertEqual(audit.call_count, 5)
            for name in factories:
                with worker.use(name, factories[name]):
                    pass
            worker.close()
        self.assertEqual(move.call_count, 5)
        self.assertTrue(all(call.args[2] == 'cuda' for call in move.call_args_list))
        self.assertEqual(worker.store.models, {})
        self.assertTrue(all(factory.call_count == 1 for factory in factories.values()))

    def test_resident_failure_never_offloads_or_retries(self):
        for failure in ('constructor', 'transfer', 'stage'):
            with self.subTest(failure=failure):
                moves = []
                def move(name, model, device):
                    moves.append((name, device))
                    if failure == 'transfer':
                        raise RuntimeError('CUDA out of memory')
                factories = {name: Mock(return_value=object()) for name in sorted(MODEL_NAMES)}
                if failure == 'constructor':
                    factories['detector'].side_effect = RuntimeError('CUDA out of memory')
                store = RetainedModels(move)
                with self.assertRaisesRegex(RuntimeError, 'CUDA out of memory'):
                    store.preload(factories)
                    with store.use('pose', factories['pose']):
                        raise RuntimeError('CUDA out of memory')
                self.assertTrue(store.failed)
                self.assertIsNone(store.active)
                self.assertTrue(all(device == 'cuda' for _, device in moves))
                with self.assertRaises(RuntimeError):
                    store.preload(factories)
                with self.assertRaises(RuntimeError):
                    with store.use('pose', factories['pose']):
                        pass
                self.assertTrue(all(factory.call_count <= 1 for factory in factories.values()))

    def test_resident_requires_full_preload_and_serial_ownership(self):
        with self.assertRaises(ValueError):
            RetainedModels(Mock(), residency='automatic')
        store = RetainedModels(Mock())
        factory = Mock(return_value=object())
        with self.assertRaisesRegex(RuntimeError, 'preload'):
            with store.use('pose', factory):
                pass
        with self.assertRaises(ValueError):
            store.preload({'pose': factory})
        factory.assert_not_called()
        store.preload(dict.fromkeys(MODEL_NAMES, factory))
        with store.use('pose', factory):
            with self.assertRaises(RuntimeError):
                store.preload(dict.fromkeys(MODEL_NAMES, factory))
            with self.assertRaises(RuntimeError):
                with store.use('features', factory):
                    pass
        with self.assertRaises(ValueError):
            with store.use('unbounded', factory):
                pass


if __name__ == '__main__':
    unittest.main()
