"""Resident admission and pipeline checks with a protocol-only child."""

import json
import os
import signal
import sys
import time
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from processing.api_contract import validate_schema
from processing.pipeline import Pipeline
from processing.service import create_app
from processing.settings import Settings
from tests.backend.helpers import (
    build_capture,
    file_reference,
    read_members,
    zip_members,
)
from tests.backend.test_pipeline import no_microscope
from tests.backend.test_resident import FAKE, launches, until
from tests.backend.test_service import (
    AUTH,
    TOKEN,
    submit,
    synthetic_processor,
    terminal,
)


def settings(tmp_path, *args):
    return Settings(tmp_path / "store", TOKEN, resident_command=(sys.executable, "-u", str(FAKE), *args),
                    inference_cwd=tmp_path, inference_timeout_seconds=2)


def ready(client):
    response = client.get("/v1/ready", headers=AUTH)
    validate_schema("Readiness", response.json())
    return response


def test_resident_settings_are_explicit_exclusive_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv("PROCESSING_TOKEN", TOKEN)
    monkeypatch.delenv("PROCESSING_INFERENCE_COMMAND", raising=False)
    monkeypatch.setenv("PROCESSING_RESIDENT_COMMAND", json.dumps([sys.executable, "-u", str(FAKE)]))
    monkeypatch.setenv("PROCESSING_INFERENCE_CWD", str(tmp_path))
    config = Settings.from_env()
    assert config.resident_command == (sys.executable, "-u", str(FAKE))
    assert config.inference_command == ()
    for change in ({"inference_command": ("python",)}, {"resident_command": "python"},
                   {"resident_command": ("",)}, {"resident_command": ("x" * 4097,)},
                   {"resident_command": ("x",) * 65}, {"inference_cwd": None}):
        with pytest.raises(ValueError):
            replace(config, **change)
    monkeypatch.setenv("PROCESSING_RESIDENT_COMMAND", '"python"')
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.parametrize("legacy", [False, True])
def test_unconfigured_or_legacy_readiness_does_not_claim_warmth(tmp_path, legacy):
    config = Settings(tmp_path / "store", TOKEN, inference_command=(sys.executable, "-c", "pass") if legacy else (),
                      inference_cwd=tmp_path if legacy else None)
    with TestClient(create_app(config, synthetic_processor)) as client:
        assert client.get("/v1/ready").status_code == 401
        response = ready(client)
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "2"
        assert response.json() == {"ready": False, "state": "legacy_cold" if legacy else "unconfigured"}
        assert submit(client, build_capture(tmp_path)).status_code == 202


def test_no_unwarm_acceptance_auth_and_unchanged_injected_processor(tmp_path):
    config = settings(tmp_path, "--ready-delay", ".5")
    app = create_app(config, synthetic_processor)
    with TestClient(app) as client:
        assert client.get("/v1/ready").status_code == 401
        assert ready(client).json() == {"ready": False, "state": "warming"}
        capture = build_capture(tmp_path)
        rejected = submit(client, capture)
        assert rejected.status_code == 503
        assert rejected.json()["error"] == {"code": "NOT_READY", "retryable": True,
                                             "message": "Resident inference is not ready; retry shortly."}
        assert rejected.headers["Retry-After"] == "2"
        validate_schema("ErrorEnvelope", rejected.json())
        assert app.state.store.records == {}
        assert list(app.state.store.jobs_dir.iterdir()) == []
        until(lambda: ready(client).status_code == 200)
        job_id = submit(client, capture).json()["job_id"]
        assert terminal(client, job_id).json()["status"] == "succeeded"
        assert not (config.data_dir / "requests.jsonl").exists()
        assert len(launches(config.data_dir)) == 1


def test_persisted_idempotency_and_downloads_survive_warming_and_failure(tmp_path):
    capture = build_capture(tmp_path)
    key = str(uuid4())
    base = Settings(tmp_path / "store", TOKEN)
    with TestClient(create_app(base, synthetic_processor)) as client:
        job_id = submit(client, capture, key).json()["job_id"]
        final = terminal(client, job_id).json()
        result = client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).json()
        artifact = result["artifacts"][0]["artifact_id"]
    config = replace(settings(tmp_path, "--ready-delay", "60"), inference_timeout_seconds=.5)
    with TestClient(create_app(config)) as client:
        for failed in (False, True):
            if failed:
                until(lambda: ready(client).json()["state"] == "failed")
            assert submit(client, capture, key).json() == final
            assert submit(client, capture).status_code == 503
            changed = {**capture[0], "session_id": str(uuid4())}
            assert submit(client, (changed, capture[1]), key).status_code == 409
            assert client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).json() == result
            assert client.get(f"/v1/jobs/{job_id}/artifacts/{artifact}", headers=AUTH).status_code == 200


def mapped_capture(tmp_path):
    manifest, archive = build_capture(tmp_path)
    members = []
    for name, data in read_members(archive):
        if name.endswith(".json"):
            sidecar = json.loads(data)
            sidecar["media"] = {"binding": "indexed_presentation_time_us",
                                "presentation_time_us": [str(i * 33333) for i in range(len(sidecar["frames"]))]}
            data = json.dumps(sidecar).encode()
            manifest["takes"][0]["frame_metadata"] = file_reference(name, data)
        members.append((name, data))
    return manifest, zip_members(members)


def test_active_job_capacity_ready_nonblocking_failure_retains_input(tmp_path):
    config = settings(tmp_path, "--mode", "timeout", "--ready-delay", ".15")
    app = create_app(config)
    capture, key = mapped_capture(tmp_path), str(uuid4())
    with TestClient(app) as client:
        until(lambda: ready(client).status_code == 200)
        job_id = submit(client, capture, key).json()["job_id"]
        until(lambda: (config.data_dir / "requests.jsonl").exists())
        start = time.monotonic()
        assert ready(client).json() == {"state": "busy", "ready": True}
        assert time.monotonic() - start < .2
        assert submit(client, capture).status_code == 429
        assert submit(client, capture, key).json()["job_id"] == job_id
        old_pid = launches(config.data_dir)[0]["pid"]
        os.kill(old_pid, signal.SIGKILL)
        final = terminal(client, job_id).json()
        assert final["status"] == "failed"
        assert "secret" not in json.dumps(final)
        directory = config.data_dir / "jobs" / job_id
        assert not (directory / "output.tmp").exists()
        assert not (directory / "artifacts").exists()
        assert (directory / "input/files" / capture[0]["takes"][0]["video"]["member"]).read_bytes() == dict(read_members(capture[1]))[capture[0]["takes"][0]["video"]["member"]]
        until(lambda: len(launches(config.data_dir)) == 2 and ready(client).status_code == 200)


def test_service_shutdown_interrupts_busy_child_before_executor_wait(tmp_path):
    config = replace(settings(tmp_path, "--mode", "timeout"), inference_timeout_seconds=60)
    app = create_app(config)
    with TestClient(app) as client:
        until(lambda: ready(client).status_code == 200)
        job_id = submit(client, mapped_capture(tmp_path)).json()["job_id"]
        until(lambda: (config.data_dir / "requests.jsonl").exists())
        started = time.monotonic()
    assert time.monotonic() - started < 2
    assert app.state.store.read(job_id)["job"]["status"] == "failed"
    with pytest.raises(ProcessLookupError):
        os.kill(launches(config.data_dir)[0]["pid"], 0)


def test_resident_pipeline_requires_mapping_without_dispatch_or_cold_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("processing.pipeline.run_inference", lambda *_: pytest.fail("Cold fallback"))
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        until(lambda: ready(client).status_code == 200)
        job_id = submit(client, build_capture(tmp_path)).json()["job_id"]
        final = terminal(client, job_id).json()
        assert final["status"] == "failed"
        assert "timestamp" in final["error"]["message"]
        assert not (config.data_dir / "requests.jsonl").exists()
        assert ready(client).status_code == 200


def test_invalid_native_handoff_retires_child_before_pipeline_cleanup(tmp_path, monkeypatch):
    from processing import pipeline

    config = settings(tmp_path)
    original_cleanup = pipeline.shutil.rmtree
    cleaned = []

    def checked_cleanup(path, *args, **kwargs):
        if path.name == "native.tmp":
            with pytest.raises(ProcessLookupError):
                os.kill(launches(config.data_dir)[0]["pid"], 0)
            cleaned.append(path)
        return original_cleanup(path, *args, **kwargs)

    monkeypatch.setattr(pipeline.shutil, "rmtree", checked_cleanup)
    monkeypatch.setattr(Pipeline, "_microscopes", lambda *_: no_microscope())
    with TestClient(create_app(config)) as client:
        until(lambda: ready(client).status_code == 200)
        job_id = submit(client, mapped_capture(tmp_path)).json()["job_id"]
        assert terminal(client, job_id).json()["status"] == "failed"
        assert len(cleaned) == 1
        until(lambda: len(launches(config.data_dir)) == 2 and ready(client).status_code == 200)


def test_resident_handoff_uses_existing_export_and_download_validation(tmp_path, monkeypatch):
    from processing.reconstruction.runtime import plan_input
    from tests.backend.test_export import native_fixture, write_json

    capture, inputs, native, _, sidecar, handoff = native_fixture(tmp_path)
    take = capture["takes"][0]
    sidecar["media"] = {"binding": "indexed_presentation_time_us", "presentation_time_us": ["0", "66666", "133333", "200000"]}
    path = inputs / "files" / take["frame_metadata"]["member"]
    write_json(path, sidecar)
    take["frame_metadata"] = file_reference(path.name, path.read_bytes())
    write_json(native / "source-sidecar.json", sidecar)
    plan = plan_input(sidecar)
    plan["decoder_binding"] = {"binding": "indexed_presentation_time_us",
                               "decoded_pts_seconds": ["0", "0.066666", "0.133333", "0.2"]}
    write_json(native / "selection.json", plan)
    handoff["source_sidecar_sha256"] = take["frame_metadata"]["sha256"]
    for name in ("source-sidecar.json", "selection.json"):
        reference = file_reference(name, (native / name).read_bytes())
        handoff["artifacts"][name] = {key: reference[key] for key in ("byte_size", "sha256")}
    write_json(native / "handoff.json", handoff)
    archive = zip_members([(path.name, path.read_bytes()) for path in (inputs / "files").iterdir()])
    monkeypatch.setattr(Pipeline, "_microscopes", lambda *_: no_microscope())
    monkeypatch.setattr("processing.pipeline.run_inference", lambda *_: pytest.fail("Cold fallback"))
    config = settings(tmp_path, "--copy-native", str(native))
    with TestClient(create_app(config)) as client:
        until(lambda: ready(client).status_code == 200)
        for _ in range(2):
            job_id = submit(client, (capture, archive)).json()["job_id"]
            final = terminal(client, job_id).json()
            assert final["status"] == "succeeded", final
            result = client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).json()
            assert result["schema_version"] == "1.1"
            assert result["findings"] == []
            replay_id = result["replay"]["manifest_artifact_id"]
            replay = client.get(f"/v1/jobs/{job_id}/artifacts/{replay_id}", headers=AUTH).json()
            assert replay["source_frame_ids"] == [10, 11, 12, 13]
            assert replay["source_pts_ns"] == [frame["pts_ns"] for frame in sidecar["frames"]]
            for artifact in result["artifacts"]:
                assert client.get(f"/v1/jobs/{job_id}/artifacts/{artifact['artifact_id']}", headers=AUTH).status_code == 200
        assert len(launches(config.data_dir)) == 1
