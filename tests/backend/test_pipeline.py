"""Pipeline integration checks use declared synthetic native geometry only."""

import json
import shutil
import sys
from dataclasses import replace
from uuid import uuid4

import pytest

from processing.pipeline import Pipeline, PipelineError, run_inference
from processing.publication import validate_result
from processing.settings import Settings
from tests.backend.test_export import native_fixture


def settings(tmp_path, **kwargs):
    return Settings(tmp_path / "store", "x" * 32, **kwargs)


def context(capture):
    return {"job_id": str(uuid4()), "input_digest": "a" * 64,
            **{key: capture[key] for key in ("patient_id", "session_id", "test_type")}}


def no_microscope(*args, **kwargs):
    return {"feature": {"name": "microscope", "status": "unavailable", "detail": "Test-only unavailable processor."},
            "methods": [], "microscopes": [], "artifacts": []}


def test_pipeline_real_adapter_boundary_publishes_bound_replay(tmp_path, monkeypatch):
    capture, inputs, native, output, _, _ = native_fixture(tmp_path)
    job = context(capture)
    stages = []

    def authored_inference(video, sidecar, destination, config):
        assert video == inputs / "files" / capture["takes"][0]["video"]["member"]
        shutil.copytree(native, destination)

    monkeypatch.setattr("processing.pipeline.run_inference", authored_inference)
    result = Pipeline(settings(tmp_path), microscope=no_microscope)(inputs, output, capture, job, stages.append)
    assert result["findings"] == []
    assert {item["name"]: item["status"] for item in result["features"]} == {
        "replay": "available", "movement": "unavailable", "microscope": "unavailable", "observations": "unavailable"}
    assert stages == ["preparing_recording", "estimating_movement", "analysing_test", "preparing_replay"]
    record = {"manifest": capture, "job": job, "input_digest": job["input_digest"]}
    validate_result(result, record, inputs, output, settings(tmp_path).limits)
    assert not (output / "native.tmp").exists()


def test_unconfigured_inference_never_synthesizes_geometry(tmp_path):
    capture, inputs, _, output, _, _ = native_fixture(tmp_path)
    with pytest.raises(PipelineError, match="inference"):
        Pipeline(settings(tmp_path), microscope=no_microscope)(inputs, output, capture, context(capture), lambda _: None)
    assert not (output / "replay_manifest.json").exists()


def test_barefoot_does_not_run_full_body_inference(tmp_path, monkeypatch):
    capture, inputs, _, output, _, _ = native_fixture(tmp_path)
    capture = {**capture, "test_type": "barefoot", "protocol_id": "barefoot",
               "takes": [{**capture["takes"][0], "kind": "foot_closeup"}]}
    del capture["replay_take_id"]
    monkeypatch.setattr("processing.pipeline.run_inference", lambda *_: pytest.fail("Foot closeup reached full-body estimator"))
    result = Pipeline(settings(tmp_path), microscope=no_microscope)(inputs, output, capture, context(capture), lambda _: None)
    assert {item["name"] for item in result["features"]} == {"foot", "microscope", "observations"}
    assert not result["findings"]


def test_runtime_requires_explicit_verified_media_mapping(tmp_path):
    capture, inputs, _, output, _, _ = native_fixture(tmp_path)
    take = capture["takes"][0]
    config = settings(tmp_path, inference_command=(sys.executable, "-c", "pass"), inference_cwd=tmp_path)
    with pytest.raises(PipelineError, match="timestamp"):
        run_inference(inputs / "files" / take["video"]["member"],
                      inputs / "files" / take["frame_metadata"]["member"], output / "run", config)


def runtime_inputs(tmp_path):
    video, sidecar = tmp_path / "take.mp4", tmp_path / "sidecar.json"
    video.write_bytes(b"test")
    sidecar.write_text(json.dumps({"media": {"binding": "indexed_presentation_time_us", "presentation_time_us": ["0", "33333"]}}))
    return video, sidecar


def test_runtime_command_uses_arguments_without_shell_and_strips_token(tmp_path, monkeypatch):
    video, sidecar = runtime_inputs(tmp_path)
    destination = tmp_path / "run; not a shell"
    script = "import sys,os,pathlib; p=pathlib.Path(sys.argv[sys.argv.index('--output')+1]); p.mkdir(); (p/'ok').write_text(str('PROCESSING_TOKEN' in os.environ))"
    config = settings(tmp_path, inference_command=(sys.executable, "-c", script), inference_cwd=tmp_path)
    monkeypatch.setenv("PROCESSING_TOKEN", "secret")
    run_inference(video, sidecar, destination, config)
    assert (destination / "ok").read_text() == "False"


@pytest.mark.parametrize("script,limit,timeout,match", [
    ("import time; time.sleep(10)", 1024, .1, "deadline"),
    ("raise SystemExit(4)", 1024, 2, "failed"),
    ("import pathlib,sys; p=pathlib.Path(sys.argv[sys.argv.index('--output')+1]);p.mkdir();(p/'big').write_bytes(b'x'*2048)", 1024, 2, "budget"),
    ("import pathlib,sys; p=pathlib.Path(sys.argv[sys.argv.index('--output')+1]);p.mkdir();(p/'link').symlink_to('/tmp')", 1024, 2, "linked"),
])
def test_runtime_kills_or_rejects_failed_oversized_and_linked_output(tmp_path, script, limit, timeout, match):
    video, sidecar = runtime_inputs(tmp_path)
    config = settings(tmp_path, inference_command=(sys.executable, "-c", script), inference_cwd=tmp_path,
                      inference_timeout_seconds=timeout, inference_workspace_bytes=limit)
    with pytest.raises(PipelineError, match=match):
        run_inference(video, sidecar, tmp_path / "run", config)


def test_pipeline_cleans_native_output_after_export_failure(tmp_path, monkeypatch):
    capture, inputs, native, output, _, _ = native_fixture(tmp_path)
    monkeypatch.setattr("processing.pipeline.run_inference", lambda v, s, d, c: shutil.copytree(native, d))
    monkeypatch.setattr("processing.pipeline.export_native", lambda *_, **__: (_ for _ in ()).throw(ValueError("invalid native")))
    with pytest.raises(ValueError):
        Pipeline(settings(tmp_path), microscope=no_microscope)(inputs, output, capture, context(capture), lambda _: None)
    assert not (output / "native.tmp").exists()


def test_inference_environment_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("PROCESSING_TOKEN", "x" * 32)
    monkeypatch.setenv("PROCESSING_INFERENCE_COMMAND", json.dumps([sys.executable, "-m", "processing.reconstruction.runtime"]))
    monkeypatch.setenv("PROCESSING_INFERENCE_CWD", str(tmp_path))
    monkeypatch.setenv("PROCESSING_INFERENCE_TIMEOUT_SECONDS", "123")
    config = Settings.from_env()
    assert config.inference_command == (sys.executable, "-m", "processing.reconstruction.runtime")
    assert config.inference_cwd == tmp_path
    assert config.inference_timeout_seconds == 123
    for changes in ({"inference_command": "python"}, {"inference_timeout_seconds": float("nan")},
                    {"inference_workspace_bytes": True}, {"inference_cwd": tmp_path / "absent"},
                    {"inference_command": ("",)}):
        with pytest.raises(ValueError):
            replace(config, **changes)


def test_default_service_pipeline_publishes_a_verified_native_result(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from processing.service import create_app
    from tests.backend.helpers import zip_members
    from tests.backend.test_service import AUTH, TOKEN, submit, terminal

    capture, inputs, native, _, _, _ = native_fixture(tmp_path)
    archive = zip_members([(path.name, path.read_bytes()) for path in (inputs / "files").iterdir()])
    monkeypatch.setattr("processing.pipeline.run_inference", lambda v, s, d, c: shutil.copytree(native, d))
    monkeypatch.setattr(Pipeline, "_microscopes", lambda *_: no_microscope())
    config = Settings(tmp_path / "store", TOKEN)
    with TestClient(create_app(config)) as client:
        job_id = submit(client, (capture, archive)).json()["job_id"]
        final = terminal(client, job_id).json()
        assert final["status"] == "succeeded", final
        result = client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).json()
        assert result["replay"]["source_take_id"] == capture["replay_take_id"]
        assert result["patient_id"] == capture["patient_id"]
        replay_id = result["replay"]["manifest_artifact_id"]
        replay = client.get(f"/v1/jobs/{job_id}/artifacts/{replay_id}", headers=AUTH).json()
        assert replay["source_frame_ids"] == [10, 11, 12, 13]


def test_unverified_camera_option_is_explicit_and_reaches_cli(tmp_path, monkeypatch):
    monkeypatch.setenv('PROCESSING_TOKEN', 'x' * 32)
    assert not Settings.from_env().allow_unverified_pinhole
    monkeypatch.setenv('PROCESSING_ALLOW_UNVERIFIED_PINHOLE', 'true')
    assert Settings.from_env().allow_unverified_pinhole
    monkeypatch.setenv('PROCESSING_ALLOW_UNVERIFIED_PINHOLE', '1')
    with pytest.raises(ValueError, match='PINHOLE'):
        Settings.from_env()
    with pytest.raises(ValueError, match='pinhole'):
        settings(tmp_path, allow_unverified_pinhole='yes')
    video, sidecar = runtime_inputs(tmp_path)
    script = "import sys; assert '--allow-unverified-pinhole' in sys.argv"
    config = settings(tmp_path, inference_command=(sys.executable, '-c', script), inference_cwd=tmp_path,
                      allow_unverified_pinhole=True)
    run_inference(video, sidecar, tmp_path / 'out', config)


def test_walking_reuses_one_reconstruction_and_publishes_observation_status(tmp_path, monkeypatch):
    capture, inputs, native, output, _, _ = native_fixture(tmp_path, test_type="walking")
    calls = []
    def inference(video, sidecar, destination, config):
        calls.append(video)
        shutil.copytree(native, destination)
    monkeypatch.setattr("processing.pipeline.run_inference", inference)
    result = Pipeline(settings(tmp_path), microscope=no_microscope)(inputs, output, capture, context(capture), lambda _: None)
    assert len(calls) == 1
    assert result["schema_version"] == "1.1"
    assert result["observations"] == []  # Two-joint fixture cannot support walking angles.
    features = {item["name"]: item for item in result["features"]}
    assert features["observations"]["status"] == "unavailable"
    assert features["movement"]["status"] == "unavailable"
    assert "gait" in features["movement"]["detail"].lower()
    assert result["replay"]["source_take_id"] == capture["replay_take_id"]
    validate_result(result, {"manifest": capture, "job": context(capture) | {"job_id": result["job_id"]},
                             "input_digest": result["input_digest"]}, inputs, output, settings(tmp_path).limits)


def test_pipeline_calculates_known_walking_angles_from_exported_source(tmp_path, monkeypatch):
    import hashlib
    import struct

    from processing.reconstruction.runtime import geometry_metadata

    capture, inputs, native, output, _, handoff = native_fixture(tmp_path, test_type="walking")
    names = ["left_hip", "right_hip", "left_shoulder", "right_shoulder",
             "left_knee", "right_knee", "left_ankle", "right_ankle"]
    flat = []
    mapping = json.loads((native / "selection.json").read_text())["frame_mapping"]
    for index in range(handoff["frame_count"]):
        last = mapping[index]["source_frame_id"] == 13
        pose = [(-.2, 1, 0), (.2, 1, 0), (-.2, 2, int(last)), (.2, 2, int(last)),
                (-.2, .5, 0), (.2, .5, 0), (-.2, .5 if last else 0, .5 if last else 0), (.2, 0, 0)]
        flat.extend(value for point in pose for value in point)
    (native / "joints.f32").write_bytes(struct.pack(f"<{len(flat)}f", *flat))
    (native / "fitted_valid.u8").write_bytes(bytes([1]) * handoff["frame_count"] * len(names))
    handoff["geometry"] = geometry_metadata(names, [-1] + [0] * (len(names) - 1), 3, 1)
    for name in ("joints.f32", "fitted_valid.u8"):
        path = native / name
        handoff["artifacts"][name] = {"byte_size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (native / "handoff.json").write_text(json.dumps(handoff))
    monkeypatch.setattr("processing.pipeline.run_inference", lambda v, s, d, c: shutil.copytree(native, d))
    job = context(capture)
    result = Pipeline(settings(tmp_path), microscope=no_microscope)(inputs, output, capture, job, lambda _: None)
    by_quantity = {(item["quantity_code"], item["side"]): item for item in result["observations"]}
    expected = {("walking.knee_flexion", "left"): (90, 13),
                ("walking.knee_flexion", "right"): (0, 10),
                ("walking.trunk_lean", "not_applicable"): (45, 13)}
    for key, (angle, source_frame) in expected.items():
        observation = by_quantity[key]
        assert observation["metrics"][0]["value"] == pytest.approx(angle)
        assert observation["evidence"]["first_frame_id"] == source_frame
    assert result["findings"] == []
    assert next(feature for feature in result["features"] if feature["name"] == "movement")["status"] == "unavailable"
    validate_result(result, {"manifest": capture, "job": job, "input_digest": job["input_digest"]},
                    inputs, output, settings(tmp_path).limits)
    method = next(method for method in result["methods"] if method["method_id"] == "pose-geometry-v1")
    saved_settings = json.loads((output / method["settings_artifact_id"]).read_text())
    assert saved_settings["source_take_id"] == capture["replay_take_id"]
    assert saved_settings["unavailable_quantities"] == []
