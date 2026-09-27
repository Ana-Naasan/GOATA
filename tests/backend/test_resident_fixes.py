"""Review regressions: real OS leases/children; no model or GPU evidence."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from processing import resident as controller
from processing.errors import ServiceError
from processing.pipeline import Pipeline
from processing.resident import Resident, ResidentError
from processing.service import create_app
from processing.settings import Limits, Settings
from processing.storage import Store
from tests.backend.helpers import build_capture
from tests.backend.test_pipeline import no_microscope
from tests.backend.test_resident import config, job_paths, launches, until
from tests.backend.test_resident_service import mapped_capture, ready, settings
from tests.backend.test_service import (
    AUTH,
    TOKEN,
    submit,
    synthetic_processor,
    terminal,
)


def file_snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_orphan_lease_blocks_recovery_until_group_stops_then_first_restart_warms(tmp_path):
    base = Settings(tmp_path / "store", TOKEN)
    with TestClient(create_app(base, synthetic_processor)) as client:
        job_id = submit(client, build_capture(tmp_path)).json()["job_id"]
        assert terminal(client, job_id).json()["status"] == "succeeded"
        result = client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).json()
    evidence = file_snapshot(base.data_dir / "jobs")
    # A real service parent dies without running lifespan cleanup. Its direct
    # cooperative child remains asleep in warmup, retaining the inherited flock.
    code = """
import sys,time
from pathlib import Path
from fastapi.testclient import TestClient
from processing.service import create_app
from tests.backend.test_resident_service import settings
with TestClient(create_app(settings(Path(sys.argv[1]), '--ready-delay', '60'))):
    time.sleep(60)
"""
    parent = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid = None
    try:
        until(lambda: (base.data_dir / "resident.tmp/marker").exists())
        pid = launches(base.data_dir)[0]["pid"]
        parent.kill()
        parent.wait(timeout=2)
        os.kill(pid, 0)  # Orphan is alive, not merely a mocked PID.
        contender = Store(base)
        try:
            with pytest.raises(RuntimeError, match="active service"):
                contender.open()
            assert (base.data_dir / "resident.tmp/marker").read_bytes() == b"warmup"
            assert file_snapshot(base.data_dir / "jobs") == evidence
        finally:
            contender.close()
        os.killpg(pid, signal.SIGKILL)
        until(lambda: not process_exists(pid))  # OS reaper owns this orphan.
        pid = None
        app = create_app(settings(tmp_path))
        with TestClient(app) as client:
            until(lambda: ready(client).status_code == 200)
            assert len(launches(base.data_dir)) == 2
            assert file_snapshot(base.data_dir / "jobs") == evidence
            assert client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).json() == result
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=2)
        if pid is not None and process_exists(pid):
            os.killpg(pid, signal.SIGKILL)
            until(lambda: not process_exists(pid))


def process_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_standalone_resident_never_removes_unknown_warmup(tmp_path):
    scratch = tmp_path / "resident.tmp"
    scratch.mkdir()
    (scratch / "unknown").write_bytes(b"retain")
    manager = Resident(config(tmp_path))
    try:
        manager.start()
        until(lambda: manager._thread is not None and not manager._thread.is_alive())
        assert not manager.snapshot()["ready"]
        assert (scratch / "unknown").read_bytes() == b"retain"
    finally:
        manager.close()


def test_standalone_launch_race_does_not_claim_scratch_ownership(tmp_path, monkeypatch):
    real_popen = subprocess.Popen
    scratch = tmp_path / "resident.tmp"

    def late_scratch(*args, **kwargs):
        scratch.mkdir()
        (scratch / "unknown").write_bytes(b"retain")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(controller.subprocess, "Popen", late_scratch)
    manager = Resident(config(tmp_path))
    try:
        manager.start()
        until(lambda: manager._thread is not None and not manager._thread.is_alive())
        assert not manager.snapshot()["ready"]
        assert (scratch / "unknown").read_bytes() == b"retain"
    finally:
        manager.close()


@pytest.mark.parametrize("constraint", ["total", "free"])
def test_initial_warmup_checks_capacity_without_deleting_saved_evidence(tmp_path, monkeypatch, constraint):
    cfg = replace(settings(tmp_path), inference_workspace_bytes=8192,
                  limits=Limits(max_storage_bytes=12288 if constraint == "total" else 100000))
    cfg.data_dir.mkdir()
    evidence = cfg.data_dir / "saved-evidence"
    evidence.write_bytes(b"x" * 6144)
    if constraint == "free":
        monkeypatch.setattr("processing.storage.shutil.disk_usage", lambda _: SimpleNamespace(free=8191))
    with TestClient(create_app(cfg)) as client:
        until(lambda: ready(client).json()["state"] != "warming")
        assert ready(client).json() == {"state": "failed", "ready": False}
        assert launches(cfg.data_dir) == []
        assert evidence.read_bytes() == b"x" * 6144


def small_config(tmp_path):
    return replace(settings(tmp_path), inference_workspace_bytes=8192,
                   limits=Limits(max_zip_bytes=100, max_expanded_bytes=200,
                                 max_manifest_bytes=100, max_metadata_bytes=100,
                                 max_output_bytes=200, max_storage_bytes=100000))


@pytest.mark.parametrize("constraint", ["total", "free"])
def test_upload_and_active_job_cannot_spend_fixed_warmup_headroom(tmp_path, monkeypatch, constraint):
    cfg = small_config(tmp_path)
    store = Store(cfg).open()
    try:
        upload = max(2 * cfg.limits.max_zip_bytes, cfg.limits.max_zip_bytes + cfg.limits.max_expanded_bytes)
        upload += store.record_limit + cfg.limits.max_manifest_bytes
        for active in (False, True):
            store.records = {"fixture": {"job": {"status": "running"}}} if active else {}
            reserve = upload
            if active:
                reserve += cfg.limits.max_output_bytes + cfg.limits.max_metadata_bytes + store.record_limit
            # Even the old, smaller reserve must leave the fixed warmup budget.
            if constraint == "total":
                store.settings = replace(cfg, limits=replace(cfg.limits, max_storage_bytes=reserve + 8191))
            else:
                monkeypatch.setattr("processing.storage.shutil.disk_usage", lambda _, reserve=reserve: SimpleNamespace(free=reserve + 8191))
            with pytest.raises(ServiceError, match="capacity|space"):
                store.staging()
    finally:
        store.close()


@pytest.mark.parametrize("overlap", ["staging", "active", "disk"])
def test_recovery_checks_overlapping_allocations_before_launch(tmp_path, monkeypatch, overlap):
    cfg = small_config(tmp_path)
    app = create_app(cfg)
    with TestClient(app) as client:
        until(lambda: ready(client).status_code == 200)
        store = app.state.store
        # Existing allocations are counted AND their remaining growth reserved.
        if overlap == "disk":
            monkeypatch.setattr("processing.storage.shutil.disk_usage", lambda _: SimpleNamespace(free=8191))
        else:
            if overlap == "staging":
                stage = store.staging()
                (stage / "upload.zip").write_bytes(b"x" * 10)
            else:
                store.records = {"fixture": {"job": {"status": "running"}}}
            used = sum(path.stat().st_size for path in cfg.data_dir.rglob("*") if path.is_file())
            store.settings = replace(cfg, limits=replace(cfg.limits, max_storage_bytes=used + 8192 + 100))
        os.kill(launches(cfg.data_dir)[0]["pid"], signal.SIGKILL)
        until(lambda: ready(client).status_code == 503)
        time.sleep(.25)
        assert ready(client).json() == {"state": "failed", "ready": False}
        assert len(launches(cfg.data_dir)) == 1


def test_disk_accounting_tolerates_disappearance_and_rejects_links(tmp_path, monkeypatch):
    cfg = small_config(tmp_path)
    store = Store(cfg).open()
    try:
        scratch = cfg.data_dir / "resident.tmp"
        scratch.mkdir()
        transient = scratch / "transient"
        transient.write_bytes(b"x")
        original = os.stat
        counted = []

        def disappearing(path, *args, **kwargs):
            if path == "transient" and kwargs.get("dir_fd") is not None:
                assert kwargs["follow_symlinks"] is False
                counted.append(path)
                transient.unlink(missing_ok=True)
                raise FileNotFoundError
            return original(path, *args, **kwargs)

        with monkeypatch.context() as change:
            change.setattr(os, "stat", disappearing)
            store.ensure_capacity(0)
        assert counted == ["transient"]
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "evidence").write_bytes(b"keep")
        (scratch / "link").symlink_to(outside, target_is_directory=True)
        with pytest.raises((RuntimeError, ServiceError), match="link"):
            store.ensure_capacity(0)
        assert (outside / "evidence").read_bytes() == b"keep"
    finally:
        store.close()


@pytest.mark.parametrize("operation", ["run", "invalidate", "warmup", "pipe", "scratch", "reap"])
@pytest.mark.parametrize("failure", [PermissionError, OSError, subprocess.TimeoutExpired])
def test_cleanup_failure_releases_waiters_retains_scratch_and_never_recovers(tmp_path, monkeypatch, operation, failure):
    cfg = config(tmp_path, *(('--ready-delay', '60') if operation == 'warmup' else ('--mode', 'timeout')))
    cfg = replace(cfg, inference_timeout_seconds=.2 if operation != "invalidate" else 2)
    if operation == "invalidate":
        cfg = config(tmp_path)
    store = Store(cfg).open()
    manager = Resident(cfg, store=store)
    real_stop = controller.stop_process
    process, worker = None, None
    errors = []

    def fail(*_args, **_kwargs):
        if failure is subprocess.TimeoutExpired:
            raise failure("private secret", 2)
        raise failure("private secret")

    def call(action):
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - assert the actual cross-thread error.
            errors.append(exc)

    try:
        manager.start()
        until(lambda: manager._process is not None and bool(launches(tmp_path)))
        process = manager._process
        if operation != "warmup":
            until(lambda: manager.snapshot()["ready"])
        request = job_paths(tmp_path)
        if operation in {"pipe", "scratch"}:
            manager.warmup.mkdir()
            (manager.warmup / "marker").write_bytes(b"retain")
        if operation == "invalidate":
            manager.run(*request)
        if operation == "pipe":
            monkeypatch.setattr(process.stdin, "close", fail)
        elif operation == "scratch":
            monkeypatch.setattr(controller.shutil, "rmtree", fail)
        elif operation == "reap":
            monkeypatch.setattr(process, "wait", fail)
        else:
            # Exercise actual stop_process error handling, not just its caller.
            monkeypatch.setattr(controller.os, "killpg", fail)
        action = (lambda: manager.invalidate(process.pid)) if operation == "invalidate" else (lambda: manager.run(*request))
        if operation != "warmup":
            worker = threading.Thread(target=lambda: call(action), daemon=True)
            worker.start()
            worker.join(3)
            assert not worker.is_alive(), "cleanup exception stranded waiting caller"
            assert len(errors) == 1
            assert isinstance(errors[0], ResidentError)
            assert "cleanup" in str(errors[0]) and "secret" not in str(errors[0])
            assert request[-1].exists()
            if operation in {"pipe", "scratch"}:
                assert (manager.warmup / "marker").read_bytes() == b"retain"
        else:
            until(lambda: not manager._thread.is_alive())
            assert (tmp_path / "resident.tmp/marker").exists()
        assert manager.snapshot() == {"state": "failed", "ready": False}
        assert len(launches(tmp_path)) == 1
        with pytest.raises(ResidentError, match="cleanup"):
            manager.close()
    finally:
        monkeypatch.undo()
        if process is not None:
            real_stop(process)
            process.stdin.close()
            process.stdout.close()
        # Also release waiters in the unfixed baseline, so a red test leaks no thread.
        with manager._condition:
            if manager._job is not None:
                manager._job.error = ResidentError("Test teardown after real stop")
                manager._job.done.set()
            manager._process = None
            manager._condition.notify_all()
        if worker is not None:
            worker.join(1)
        try:
            manager.close()
        except ResidentError:
            pass
        store.close()


@pytest.mark.parametrize("invalidate", [False, True])
def test_service_fatal_cleanup_retains_both_outputs_and_closes_store(tmp_path, monkeypatch, invalidate):
    cfg = replace(settings(tmp_path, *( () if invalidate else ('--mode', 'timeout'))),
                  inference_timeout_seconds=60)
    managers = []
    real_init = Resident.__init__
    real_stop = controller.stop_process

    def capture_manager(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        managers.append(self)

    def fail(*_args, **_kwargs):
        raise PermissionError("private secret")

    monkeypatch.setattr(Resident, "__init__", capture_manager)
    # create_app constructs Resident eagerly.
    app = create_app(cfg)
    monkeypatch.setattr(Pipeline, "_microscopes", lambda *_: no_microscope())
    manager, process = managers[0], None
    client = TestClient(app)
    client.__enter__()
    try:
        until(lambda: ready(client).status_code == 200)
        process = manager._process
        monkeypatch.setattr(controller.os, "killpg", fail)
        job_id = submit(client, mapped_capture(tmp_path)).json()["job_id"]
        until(lambda: (cfg.data_dir / "requests.jsonl").exists())
        if invalidate:
            assert terminal(client, job_id).json()["status"] == "failed"
            assert ready(client).json() == {"state": "failed", "ready": False}
        started = time.monotonic()
        with pytest.raises(ResidentError, match="cleanup"):
            client.__exit__(None, None, None)
        assert time.monotonic() - started < 3
        record = app.state.store.read(job_id)["job"]
        assert record["status"] == "failed"
        assert "cleanup" in record["error"]["message"]
        assert "secret" not in json.dumps(record)
        assert (cfg.data_dir / "jobs" / job_id / "output.tmp/native.tmp/pid").exists()
        assert app.state.store._lock_stream is None
        assert app.state.executor._shutdown
        contender = Store(cfg)
        try:
            with pytest.raises(RuntimeError, match="active service"):
                contender.open()  # Parent closed; live child still owns flock.
        finally:
            contender.close()
        assert len(launches(cfg.data_dir)) == 1
    finally:
        monkeypatch.undo()
        if process is not None:
            real_stop(process)
        with manager._condition:
            if manager._job is not None:
                manager._job.error = ResidentError("Test teardown after real stop")
                manager._job.done.set()
            manager._process = None
            manager._condition.notify_all()
        try:
            client.__exit__(None, None, None)
        except (ResidentError, RuntimeError):
            pass
        app.state.store.close()


def test_legacy_kill_failure_is_bounded_and_preserves_output(tmp_path, monkeypatch):
    # Shared stop_process must not reintroduce Popen.__exit__'s unbounded wait.
    script = ("import pathlib,sys,time; p=pathlib.Path(sys.argv[sys.argv.index('--output')+1]); "
              "p.mkdir(); (p/'marker').write_text('retain'); time.sleep(60)")
    cfg = Settings(tmp_path / "store", TOKEN, inference_cwd=tmp_path,
                   inference_command=(sys.executable, "-c", script), inference_timeout_seconds=.15)
    real_popen, real_stop = subprocess.Popen, controller.stop_process
    processes = []

    def capture_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    def fail(*_args):
        raise OSError("private secret")

    monkeypatch.setattr("processing.pipeline.subprocess.Popen", capture_process)
    monkeypatch.setattr(controller.os, "killpg", fail)
    try:
        with TestClient(create_app(cfg)) as client:
            job_id = submit(client, mapped_capture(tmp_path)).json()["job_id"]
            final = terminal(client, job_id).json()
            assert final["status"] == "failed"
            assert "cleanup" in final["error"]["message"]
            assert "secret" not in json.dumps(final)
            assert (cfg.data_dir / "jobs" / job_id / "output.tmp/native.tmp/marker").read_text() == "retain"
            assert submit(client, mapped_capture(tmp_path)).status_code == 503
            assert processes[0].poll() is None
        evidence = file_snapshot(cfg.data_dir / "jobs")
        inputs = file_snapshot(cfg.data_dir / "jobs" / job_id / "input")
        contender = Store(cfg)
        try:
            with pytest.raises(RuntimeError, match="active service"):
                contender.open()
            assert file_snapshot(cfg.data_dir / "jobs") == evidence
        finally:
            contender.close()
    finally:
        monkeypatch.undo()
        for process in processes:
            real_stop(process)
    restarted = Store(cfg).open()
    try:
        assert restarted.read(job_id)["job"] == final
        assert file_snapshot(cfg.data_dir / "jobs" / job_id / "input") == inputs
        assert not (cfg.data_dir / "jobs" / job_id / "output.tmp").exists()
    finally:
        restarted.close()


def test_accept_reserves_native_and_output_separately_from_warmup(tmp_path):
    cfg = small_config(tmp_path)
    store = Store(cfg).open()
    try:
        stage = store.staging()
        used = sum(path.stat().st_size for path in cfg.data_dir.rglob("*") if path.is_file())
        remaining = (cfg.limits.max_output_bytes + cfg.limits.max_metadata_bytes + store.record_limit
                     + 2 * cfg.inference_workspace_bytes - 1)
        store.settings = replace(cfg, limits=replace(cfg.limits, max_storage_bytes=used + remaining))
        with pytest.raises(ServiceError, match="capacity"):
            store.accept(stage, {}, "digest", "key")
        assert store.records == {}
        assert stage.exists()
    finally:
        store.close()
