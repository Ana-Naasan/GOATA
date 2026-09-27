"""Authored observations check API/evidence rules, never clinical accuracy."""

import copy
from uuid import uuid4

import pytest

from processing.api_contract import validate_schema
from processing.export import export_native
from processing.publication import validate_result
from processing.settings import Limits
from tests.backend.test_export import native_fixture
from tests.backend.test_pipeline import context


@pytest.fixture
def observed_result(tmp_path):
    capture, inputs, native, output, sidecar, _ = native_fixture(tmp_path, joint_names=["left_hip", "right_hip", "left_shoulder", "right_shoulder"])
    job, result_id = context(capture), str(uuid4())
    replay, artifacts, _ = export_native(native, output, capture["takes"][0], sidecar, result_id, Limits())
    settings_id = str(uuid4())
    settings_path = output / settings_id
    settings_path.write_text('{"synthetic":true}')
    from processing.export import artifact
    result = {
        "schema_version": "1.1", "result_id": result_id, **job,
        "created_at": "2026-09-27T00:00:00Z", "pipeline_version": "synthetic-only",
        "protocol_id": "elk", "protocol_version": "1.0", "validation_status": "research_demo_unvalidated",
        "methods": [{"method_id": "synthetic", "name": "Synthetic geometry", "version": "1",
                     "settings_artifact_id": settings_id}],
        "features": [{"name": name, "status": status, "detail": "Synthetic evidence test only"}
                     for name, status in (("replay", "available"), ("movement", "unavailable"),
                                          ("microscope", "unavailable"), ("observations", "available"))],
        "replay": {"source_take_id": capture["replay_take_id"], "manifest_artifact_id": artifacts[0]["artifact_id"]},
        "findings": [], "microscopes": [],
        "observations": [{"observation_id": str(uuid4()), "method_id": "synthetic",
                          "quantity_code": "elk.lateral_torso_lean", "label": "Estimated torso lean",
                          "explanation": "Authored test only", "region": "torso", "side": "not_applicable",
                          "limitations": ["Not clinically validated"], "highlight_joint_names": ["left_hip"],
                          "metrics": [{"name": "peak", "value": 24.0, "unit": "deg", "basis": "pose_estimate",
                                       "scale_status": "not_required"}],
                          "evidence": {"take_id": capture["replay_take_id"], "start_s": 0, "end_s": 0,
                                       "first_frame_id": 10, "last_frame_id": 10, "condition": "seated",
                                       "quality": "limited", "quality_reason": "Model estimate only"}}],
        "artifacts": artifacts + [artifact(settings_path, "processing_settings", "application/json")],
    }
    record = {"job": job, "manifest": capture, "input_digest": job["input_digest"]}
    return result, record, inputs, output, replay


def publish(values):
    return validate_result(*values[:4], Limits())


def test_estimated_observation_keeps_clinical_assessment_unavailable(observed_result):
    publish(observed_result)
    assert observed_result[0]["findings"] == []


@pytest.mark.parametrize("change", [
    lambda r: r.update(schema_version="1.0"),
    lambda r: r.pop("observations"),
    lambda r: r["features"].pop(),
    lambda r: r["features"][-1].update(status="unavailable"),
    lambda r: r.update(observations=[]),
    lambda r: r["observations"].append(copy.deepcopy(r["observations"][0])),
    lambda r: r["observations"][0].update(method_id="absent"),
    lambda r: r["observations"][0].update(quantity_code="rtk.shoulder_pelvis_rotation"),
    lambda r: r["observations"][0].update(quantity_code="walking.knee_flexion"),
    lambda r: r["observations"][0].update(highlight_joint_names=["imaginary_joint"]),
    lambda r: r["observations"][0].update(limitations=[]),
    lambda r: r["observations"][0]["metrics"][0].update(value=float("nan")),
    lambda r: r["observations"][0]["metrics"][0].update(value=181),
    lambda r: r["observations"][0]["metrics"][0].update(basis="model_score"),
    lambda r: r["observations"][0]["metrics"][0].update(unit="m"),
    lambda r: r["observations"][0]["evidence"].update(quality="usable"),
    lambda r: r["observations"][0]["evidence"].update(last_frame_id=999),
    lambda r: r["observations"][0]["evidence"].update(take_id=str(uuid4())),
    lambda r: r["observations"][0]["evidence"].update(end_s=.05),
    lambda r: r["observations"][0].update(confidence=.99),
])
def test_observations_reject_unproven_or_incoherent_evidence(observed_result, change):
    result = copy.deepcopy(observed_result[0])
    change(result)
    with pytest.raises(ValueError):
        publish((result, *observed_result[1:]))


def test_historical_result_remains_strictly_readable(observed_result):
    result = copy.deepcopy(observed_result[0])
    result["schema_version"] = "1.0"
    result.pop("observations")
    result["features"].pop()
    publish((result, *observed_result[1:]))
    result["features"].append({"name": "observations", "status": "unavailable", "detail": "Historical unsupported"})
    with pytest.raises(ValueError):
        publish((result, *observed_result[1:]))


def test_observation_array_is_bounded(observed_result):
    result = copy.deepcopy(observed_result[0])
    result["observations"] = [{**result["observations"][0], "observation_id": str(uuid4())} for _ in range(17)]
    with pytest.raises(ValueError):
        validate_schema("ResultManifest", result)


@pytest.mark.parametrize("mode", ["source_invalid", "joint_invalid", "joint_invalid_without_highlights", "gap", "interrupted"])
def test_observation_cannot_bridge_invalid_source_or_joint_samples(observed_result, mode):
    import json

    from processing.export import artifact
    result, record, inputs, output, replay = observed_result
    take = record["manifest"]["takes"][0]
    path = inputs / "files" / take["frame_metadata"]["member"]
    sidecar = json.loads(path.read_text())
    observation = result["observations"][0]
    if mode == "interrupted":
        sidecar["capture"]["interrupted"] = True
    elif mode.startswith("joint_invalid"):
        replay["joint_valid"][0][0] = False
        if mode.endswith("without_highlights"):
            observation.pop("highlight_joint_names")
    else:
        observation["evidence"].update(end_s=.2, last_frame_id=13)
        if mode == "source_invalid":
            sidecar["frames"][1]["image_valid"] = False
            replay["frame_valid"][1] = False
            replay["joint_valid"][1] = [False] * replay["joint_count"]
        else:
            # A gap can lie between sampled frames; checking masks alone misses it.
            sidecar["capture"]["gaps"] = [{"start_pts_ns": "1010000000", "end_pts_ns": "1020000000", "reason": "Authored gap"}]
            replay["gaps"] = [{"start_s": .01, "end_s": .02, "reason": "Authored gap"}]
    path.write_text(json.dumps(sidecar))
    replay_path = output / "replay_manifest.json"
    replay_path.write_text(json.dumps(replay))
    manifest_id = result["replay"]["manifest_artifact_id"]
    result["artifacts"] = [artifact(replay_path, "replay_manifest", "application/json", manifest_id)
                           if item["artifact_id"] == manifest_id else item for item in result["artifacts"]]
    with pytest.raises(ValueError, match="(Observation|observation)"):
        publish(observed_result)
