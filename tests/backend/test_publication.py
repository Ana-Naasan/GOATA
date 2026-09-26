import copy
import hashlib
import json
from uuid import uuid4

import pytest

from processing.contracts import generate_fixture, read_json_file
from processing.publication import validate_result
from processing.settings import Limits
from tests.backend.helpers import SYNTHETIC_MP4, build_capture, read_members


def artifact(path, role, media_type, artifact_id=None):
    return {"artifact_id": artifact_id or path.name, "role": role, "media_type": media_type,
            "byte_size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def publication(tmp_path):
    capture, media = build_capture(tmp_path)
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    (inputs / "files").mkdir(parents=True)
    outputs.mkdir()
    for name, value in read_members(media):
        (inputs / "files" / name).write_bytes(value)
    job = {"job_id": str(uuid4()), **{k: capture[k] for k in ("patient_id", "session_id", "test_type")}}
    record = {"job": job, "manifest": capture, "input_digest": "a" * 64, "idempotency_key": str(uuid4())}
    settings_id = str(uuid4())
    (outputs / settings_id).write_text('{"synthetic": true}')
    result = {
        "schema_version": "1.0", "result_id": str(uuid4()), **job,
        "created_at": "2026-09-26T17:10:00Z", "pipeline_version": "synthetic-tests-only-1",
        "protocol_id": capture["protocol_id"], "protocol_version": capture["protocol_version"],
        "input_digest": record["input_digest"], "validation_status": "research_demo_unvalidated",
        "methods": [{"method_id": "synthetic", "name": "Test-only worker", "version": "1",
                     "settings_artifact_id": settings_id}],
        "features": [{"name": name, "status": "unavailable", "detail": "Synthetic test; no analysis"}
                     for name in ("replay", "movement", "microscope")],
        "findings": [], "microscopes": [],
        "artifacts": [artifact(outputs / settings_id, "processing_settings", "application/json")],
    }
    return result, record, inputs, outputs


def test_valid_unavailable_result(publication):
    result, record, inputs, outputs = publication
    mapping = validate_result(result, record, inputs, outputs, Limits())
    assert mapping == {result["artifacts"][0]["artifact_id"]: result["artifacts"][0]["artifact_id"]}


@pytest.mark.parametrize("field,value", [("patient_id", str(uuid4())), ("session_id", str(uuid4())),
                                      ("job_id", str(uuid4())), ("test_type", "rtk"),
                                      ("input_digest", "b" * 64), ("protocol_version", "2")])
def test_result_identity_must_match_accepted_input(publication, field, value):
    result, record, inputs, outputs = publication
    with pytest.raises(ValueError):
        validate_result({**result, field: value}, record, inputs, outputs, Limits())


@pytest.mark.parametrize("change", [
    lambda r: r["artifacts"].append(copy.deepcopy(r["artifacts"][0])),
    lambda r: r["methods"].append(copy.deepcopy(r["methods"][0])),
    lambda r: r["features"].append(copy.deepcopy(r["features"][0])),
    lambda r: r["features"].pop(),
    lambda r: r["features"][0].update(status="available"),
    lambda r: r["methods"][0].update(settings_artifact_id=str(uuid4())),
    lambda r: r["artifacts"][0].update(sha256="b" * 64),
    lambda r: r["artifacts"][0].update(byte_size=999),
])
def test_result_cross_references_and_bytes_are_checked(publication, change):
    result, record, inputs, outputs = publication
    change(result)
    with pytest.raises(ValueError):
        validate_result(result, record, inputs, outputs, Limits())


def test_unlisted_files_and_links_cannot_be_published(publication, tmp_path):
    result, record, inputs, outputs = publication
    extra = outputs / "unlisted"
    extra.write_text("extra")
    with pytest.raises(ValueError):
        validate_result(result, record, inputs, outputs, Limits())
    extra.unlink()
    name = result["artifacts"][0]["artifact_id"]
    target = tmp_path / "external"
    target.write_bytes((outputs / name).read_bytes())
    (outputs / name).unlink()
    (outputs / name).symlink_to(target)
    with pytest.raises(ValueError):
        validate_result(result, record, inputs, outputs, Limits())


def test_output_bytes_are_bounded(publication):
    with pytest.raises(ValueError):
        validate_result(*publication, Limits(max_output_bytes=1))


def test_artifact_ids_must_use_canonical_download_identity(publication):
    result, record, inputs, outputs = publication
    original = result["artifacts"][0]["artifact_id"]
    upper = original.upper()
    (outputs / original).rename(outputs / upper)
    result["artifacts"][0]["artifact_id"] = upper
    result["methods"][0]["settings_artifact_id"] = upper
    with pytest.raises(ValueError):
        validate_result(result, record, inputs, outputs, Limits())


def add_finding(result, record):
    return {**result, "features": [{**feature, "status": "available"} if feature["name"] == "movement"
                                  else feature for feature in result["features"]],
            "findings": [{"finding_id": str(uuid4()), "method_id": "synthetic", "label_code": "test-only",
                          "label": "Synthetic finding", "explanation": "Only a publication test",
                          "region": "synthetic", "side": "not_applicable", "limitations": [], "metrics": [],
                          "evidence": {"take_id": record["manifest"]["takes"][0]["take_id"],
                                       "start_s": 0, "end_s": .04, "first_frame_id": 100, "last_frame_id": 101,
                                       "condition": "seated", "quality": "usable"}}]}


def test_evidence_is_tied_to_original_take_and_frames(publication):
    result, record, inputs, outputs = publication
    result = add_finding(result, record)
    validate_result(result, record, inputs, outputs, Limits())
    for field, value in [("take_id", str(uuid4())), ("last_frame_id", 103), ("condition", "standing"),
                         ("end_s", .01), ("start_s", .1)]:
        invalid = copy.deepcopy(result)
        invalid["findings"][0]["evidence"][field] = value
        with pytest.raises(ValueError):
            validate_result(invalid, record, inputs, outputs, Limits())


@pytest.mark.parametrize("with_finding", [True, False])
def test_interrupted_capture_cannot_feed_assessment(publication, with_finding):
    result, record, inputs, outputs = publication
    take = record["manifest"]["takes"][0]
    path = inputs / "files" / take["frame_metadata"]["member"]
    sidecar = read_json_file(path)
    sidecar["capture"]["interrupted"] = True
    path.write_text(json.dumps(sidecar))
    result = add_finding(result, record)
    if not with_finding:
        result["findings"] = []
    with pytest.raises(ValueError):
        validate_result(result, record, inputs, outputs, Limits())


def test_replay_artifacts_use_fixed_names_and_original_identity(publication):
    result, record, inputs, outputs = publication
    generate_fixture(outputs)
    (outputs / "capture_sidecar.json").unlink()
    replay = read_json_file(outputs / "replay_manifest.json")
    replay = {**replay, "source_take_id": record["manifest"]["replay_take_id"], "result_id": result["result_id"]}
    (outputs / "replay_manifest.json").write_text(json.dumps(replay))
    manifest_id = str(uuid4())
    binary_artifacts = [artifact(outputs / item["filename"], "replay_binary", "application/octet-stream", item["artifact_id"])
                        for item in replay["artifacts"].values()]
    result = {**result, "replay": {"source_take_id": replay["source_take_id"], "manifest_artifact_id": manifest_id},
              "features": [{**f, "status": "available"} if f["name"] == "replay" else f for f in result["features"]],
              "artifacts": [*result["artifacts"], artifact(outputs / "replay_manifest.json", "replay_manifest", "application/json", manifest_id),
                            *binary_artifacts]}
    mapping = validate_result(result, record, inputs, outputs, Limits())
    assert mapping[manifest_id] == "replay_manifest.json"
    invalid = {**result, "replay": {**result["replay"], "source_take_id": str(uuid4())}}
    with pytest.raises(ValueError):
        validate_result(invalid, record, inputs, outputs, Limits())


def test_microscope_pair_must_match_finding_source(publication):
    result, record, inputs, outputs = publication
    result = add_finding(result, record)
    microscope_id, original_id, amplified_id = (str(uuid4()) for _ in range(3))
    for identifier in (original_id, amplified_id):
        (outputs / identifier).write_bytes(SYNTHETIC_MP4)
    microscope = {"microscope_id": microscope_id, "method_id": "synthetic",
                  "evidence": copy.deepcopy(result["findings"][0]["evidence"]),
                  "region": "synthetic", "side": "not_applicable", "status": "available",
                  "detail": "Test only; no actual amplification", "original_artifact_id": original_id,
                  "amplified_artifact_id": amplified_id, "settings_artifact_id": result["methods"][0]["settings_artifact_id"]}
    result["findings"][0]["microscope_id"] = microscope_id
    result = {**result, "microscopes": [microscope],
              "features": [{**f, "status": "available"} if f["name"] == "microscope" else f for f in result["features"]],
              "artifacts": [*result["artifacts"], artifact(outputs / original_id, "microscope_original", "video/mp4"),
                            artifact(outputs / amplified_id, "microscope_amplified", "video/mp4")]}
    validate_result(result, record, inputs, outputs, Limits())
    for change in (lambda r: r["microscopes"][0].update(original_artifact_id=str(uuid4())),
                   lambda r: r["microscopes"][0].update(method_id="unknown"),
                   lambda r: r["microscopes"][0]["evidence"].update(end_s=.05),
                   lambda r: r["findings"][0].update(microscope_id=str(uuid4()))):
        invalid = copy.deepcopy(result)
        change(invalid)
        with pytest.raises(ValueError):
            validate_result(invalid, record, inputs, outputs, Limits())
    (outputs / original_id).write_bytes(b"x" * len(SYNTHETIC_MP4))
    invalid = copy.deepcopy(result)
    invalid["artifacts"][1] = artifact(outputs / original_id, "microscope_original", "video/mp4")
    with pytest.raises(ValueError):
        validate_result(invalid, record, inputs, outputs, Limits())


def test_unavailable_microscope_references_still_must_resolve(publication):
    result, record, inputs, outputs = publication
    evidence = add_finding(result, record)["findings"][0]["evidence"]
    result = {**result, "microscopes": [{"microscope_id": str(uuid4()), "method_id": "synthetic",
              "evidence": evidence, "region": "synthetic", "side": "not_applicable",
              "status": "unavailable", "detail": "Synthetic test only", "original_artifact_id": str(uuid4())}]}
    with pytest.raises(ValueError):
        validate_result(result, record, inputs, outputs, Limits())
