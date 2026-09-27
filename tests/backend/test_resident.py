"""Stdlib-only supervisor tests using real pipes/processes, not a mocked GPU."""

import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from processing.resident import Resident, ResidentError
from processing.settings import Settings

FAKE = Path(__file__).with_name("fake_resident.py")


def config(root, *args, **changes):
    return Settings(root, "x" * 32, resident_command=(sys.executable, "-u", str(FAKE), *args),
                    inference_cwd=root, inference_timeout_seconds=2, **changes)


def until(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Timed out waiting for subprocess state")


def launches(root):
    path = root / "launches.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def job_paths(root):
    job_id = str(uuid4())
    folder = root / "jobs" / job_id
    folder.mkdir(parents=True)
    video, sidecar = folder / "video.mp4", folder / "sidecar.json"
    video.write_bytes(b"synthetic")
    sidecar.write_text("{}")
    return job_id, video, sidecar, folder / "native.tmp"


class ResidentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def manager(self, *args, timeout=2, **changes):
        from dataclasses import replace
        manager = Resident(replace(config(self.root, *args, **changes), inference_timeout_seconds=timeout))
        self.addCleanup(manager.close)
        manager.start()
        return manager

    def test_warmup_gate_one_launch_sequential_jobs_and_private_environment(self):
        with patch.dict(os.environ, {"PROCESSING_TOKEN": "never-forward-this"}):
            manager = self.manager("--ready-delay", ".2", allow_estimated_intrinsics=True,
                                   allow_unverified_pinhole=True)
            manager.start()
            self.assertEqual(manager.snapshot(), {"state": "warming", "ready": False})
            with self.assertRaises(ResidentError):
                manager.run(*job_paths(self.root))
            until(lambda: manager.snapshot()["ready"])
            pids = []
            for _ in range(2):
                request = job_paths(self.root)
                manager.run(*request)
                pids.append(int((request[-1] / "pid").read_text()))
            self.assertEqual(pids[0], pids[1])
            log = launches(self.root)
            self.assertEqual(len(log), 1)
            self.assertFalse(log[0]["token_present"])
            self.assertEqual(log[0]["cwd"], str(self.root))
            self.assertIn(str(Path(__file__).resolve().parents[2]), log[0]["pythonpath"])
            self.assertTrue(log[0]["estimated"] and log[0]["pinhole"])
            sent = [json.loads(line) for line in (self.root / "requests.jsonl").read_text().splitlines()]
            self.assertEqual(set(sent[0]), {"id", "video", "sidecar", "output", "allow_estimated_intrinsics", "allow_unverified_pinhole"})
            self.assertEqual(sent[0]["allow_estimated_intrinsics"], True)
            manager.close()
            with self.assertRaises(ProcessLookupError):
                os.kill(pids[0], 0)
            manager.start()
            self.assertEqual(manager.snapshot(), {"state": "stopped", "ready": False})

    def test_busy_is_warm_without_queue_or_blocking_readiness(self):
        manager = self.manager("--job-delay", ".3")
        until(lambda: manager.snapshot()["ready"])
        errors = []
        worker = threading.Thread(target=lambda: self.run_catching(manager, job_paths(self.root), errors))
        worker.start()
        until(lambda: manager.snapshot()["state"] == "busy")
        start = time.monotonic()
        self.assertTrue(manager.snapshot()["ready"])
        with self.assertRaises(ResidentError):
            manager.run(*job_paths(self.root))
        self.assertLess(time.monotonic() - start, .1)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len((self.root / "requests.jsonl").read_text().splitlines()), 1)

    @staticmethod
    def run_catching(manager, request, errors):
        try:
            manager.run(*request)
        except ResidentError as exc:
            errors.append(str(exc))

    def test_failed_job_is_reaped_before_return_and_only_one_recovery(self):
        for mode in ("timeout", "oversized", "malformed", "mismatched", "partial", "job-exit",
                     "not-bool", "failure", "duplicate", "overflow", "extra", "budget", "linked", "files"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                from dataclasses import replace
                root = Path(temporary).resolve()
                manager = Resident(replace(config(root, "--mode", mode), inference_timeout_seconds=.4,
                                           inference_workspace_bytes=4096))
                try:
                    manager.start()
                    until(lambda manager=manager: manager.snapshot()["ready"])
                    old_pid = launches(root)[0]["pid"]
                    started = time.monotonic()
                    with self.assertRaises(ResidentError) as error:
                        manager.run(*job_paths(root))
                    self.assertNotIn("secret", str(error.exception))
                    self.assertLess(time.monotonic() - started, 2)
                    with self.assertRaises(ProcessLookupError):
                        os.kill(old_pid, 0)
                    until(lambda root=root, manager=manager: len(launches(root)) == 2 and manager.snapshot()["ready"])
                    with self.assertRaises(ResidentError):
                        manager.run(*job_paths(root))
                    until(lambda manager=manager: manager.snapshot()["state"] == "failed")
                    time.sleep(.1)
                    self.assertEqual(len(launches(root)), 2)
                    self.assertFalse(manager.snapshot()["ready"])
                finally:
                    manager.close()

    def test_startup_failure_never_restarts(self):
        for mode in ("startup-exit", "warmup-partial", "warmup-budget", "warmup-bad"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                from dataclasses import replace
                root = Path(temporary).resolve()
                manager = Resident(replace(config(root, "--mode", mode), inference_timeout_seconds=.3,
                                           inference_workspace_bytes=4096))
                try:
                    manager.start()
                    until(lambda manager=manager: manager.snapshot()["state"] == "failed")
                    time.sleep(.1)
                    self.assertEqual(len(launches(root)), 1)
                    self.assertFalse(manager.snapshot()["ready"])
                finally:
                    manager.close()

    def test_idle_death_recovers_without_a_request_and_then_stays_failed(self):
        manager = self.manager("--mode", "idle-exit", "--ready-delay", ".1")
        until(lambda: len(launches(self.root)) == 2)
        self.assertFalse(manager.snapshot()["ready"])
        until(lambda: manager.snapshot()["ready"])
        until(lambda: manager.snapshot()["state"] == "failed")
        time.sleep(.2)
        self.assertEqual(len(launches(self.root)), 2)

    def test_failed_recovery_stays_unavailable(self):
        manager = self.manager("--mode", "recovery-exit")
        until(lambda: manager.snapshot()["ready"])
        with self.assertRaises(ResidentError):
            manager.run(*job_paths(self.root))
        until(lambda: len(launches(self.root)) == 2 and manager.snapshot()["state"] == "failed")
        time.sleep(.15)
        self.assertFalse(manager.snapshot()["ready"])
        self.assertEqual(len(launches(self.root)), 2)

    def test_shutdown_during_warmup_or_job_is_bounded(self):
        for busy in (False, True):
            with self.subTest(busy=busy), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                manager = Resident(config(root, *(('--mode', 'timeout') if busy else ('--ready-delay', '60'))))
                manager.start()
                until(lambda root=root: bool(launches(root)))
                worker, errors = None, []
                if busy:
                    until(lambda manager=manager: manager.snapshot()["ready"])
                    worker = threading.Thread(target=self.run_catching, args=(manager, job_paths(root), errors))
                    worker.start()
                    until(lambda root=root: (root / "requests.jsonl").exists())
                started = time.monotonic()
                manager.close()
                self.assertLess(time.monotonic() - started, 1)
                if worker:
                    worker.join(1)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(len(errors), 1)
                with self.assertRaises(ProcessLookupError):
                    os.kill(launches(root)[0]["pid"], 0)
                self.assertEqual(manager.snapshot(), {"state": "stopped", "ready": False})
                self.assertEqual(len(launches(root)), 1)

    def test_invalid_request_paths_never_reach_child(self):
        manager = self.manager()
        until(lambda: manager.snapshot()["ready"])
        job_id, video, sidecar, output = job_paths(self.root)
        for request in ((job_id.upper(), video, sidecar, output),
                        (job_id, self.root / 'outside.mp4', sidecar, output),
                        (job_id, video, sidecar, self.root / 'outside')):
            with self.assertRaises(ResidentError):
                manager.run(*request)
        self.assertTrue(manager.snapshot()["ready"])
        self.assertFalse((self.root / "requests.jsonl").exists())

    def test_process_group_descendant_cannot_write_after_failed_return(self):
        import shutil

        manager = self.manager("--mode", "grandchild", timeout=.4)
        until(lambda: manager.snapshot()["ready"])
        request = job_paths(self.root)
        with self.assertRaises(ResidentError):
            manager.run(*request)
        self.assertTrue((request[-1] / "heartbeat").is_file())
        shutil.rmtree(request[-1])
        time.sleep(.15)
        self.assertFalse(request[-1].exists())

    def test_concurrent_start_still_launches_once(self):
        manager = self.manager("--ready-delay", ".1")
        threads = [threading.Thread(target=manager.start) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)
        until(lambda: manager.snapshot()["ready"])
        self.assertEqual(len(launches(self.root)), 1)

    def test_external_kill_is_seen_immediately_by_snapshot(self):
        manager = self.manager("--ready-delay", ".1")
        until(lambda: manager.snapshot()["ready"])
        os.kill(launches(self.root)[0]["pid"], signal.SIGKILL)
        until(lambda: not manager.snapshot()["ready"])


if __name__ == "__main__":
    unittest.main()
