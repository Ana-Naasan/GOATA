"""Contract tests deliberately use asymmetric data and original irregular timing."""

import hashlib
import json
import struct
from pathlib import Path

import pytest

from processing.contracts import (
    generate_fixture,
    load_json,
    read_json_file,
    validate_replay,
    validate_sidecar,
)


@pytest.fixture
def package(tmp_path):
    generate_fixture(tmp_path)
    return tmp_path, load_json((tmp_path / "replay_manifest.json").read_bytes())


@pytest.mark.parametrize("raw", ['{"a": 1, "a": 2}', '{"a": NaN}', '[Infinity]', '[1e400]', '42'])
def test_json_rejects_ambiguous_or_nonfinite_values(raw):
    with pytest.raises(ValueError):
        load_json(raw)


def test_json_accepts_utf8_objects_and_arrays():
    assert load_json('{"label": "é"}'.encode()) == {"label": "é"}
    assert load_json("[true, 1, null]") == [True, 1, None]


def test_json_rejects_invalid_utf8_and_deep_nesting():
    for raw in (b"\xff", "[" * 2000 + "]" * 2000):
        with pytest.raises(ValueError):
            load_json(raw)


def test_json_byte_limits_apply_before_parse(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b'["123456789"]')
    with pytest.raises(ValueError):
        read_json_file(path, max_bytes=8)
    with pytest.raises(ValueError):
        load_json('["éé"]', max_bytes=7)
    assert read_json_file(path, max_bytes=100) == ["123456789"]


def test_fixture_is_valid_and_deterministic(package, tmp_path):
    directory, manifest = package
    validate_replay(manifest, directory)
    sidecar = load_json((directory / "capture_sidecar.json").read_bytes())
    validate_sidecar(sidecar)
    other = tmp_path / "again"
    generate_fixture(other)
    for artifact in directory.iterdir():
        if artifact.is_file():
            assert artifact.read_bytes() == (other / artifact.name).read_bytes()
    assert manifest["frame_times_s"] == [0.0, 0.04, 0.11, 0.2]
    assert manifest["source_frame_ids"] == [100, 101, 103, 107]
    assert manifest["frame_valid"] == [True, True, False, True]


def test_geometry_preserves_root_motion_and_asymmetry(package):
    directory, manifest = package
    values = struct.unpack("<48f", (directory / "mesh_vertices.f32").read_bytes())
    joints = struct.unpack("<36f", (directory / "skeleton_joints.f32").read_bytes())
    assert values[:3] == pytest.approx((-0.25, 0.0, 0.0))
    assert values[6:9] == pytest.approx((0.0, 0.7, 0.0))
    assert values[9:12] == pytest.approx((0.0, 0.1, 0.4))
    assert values[36] - values[0] == pytest.approx(0.3)
    assert joints[27] - joints[0] == pytest.approx(0.3)
    assert manifest["joint_parents"] == [-1, 0, 0]
    assert manifest["joint_valid"][1] == [True, True, False]


@pytest.mark.parametrize("change", [
    lambda x: x["frames"][1].update(frame_id=100),
    lambda x: x["frames"][1].update(pts_ns=x["frames"][0]["pts_ns"]),
    lambda x: x["clock"].update(origin_pts_ns="1"),
    lambda x: x["camera"].update(intrinsics={"fx": -1, "fy": 1, "cx": 0, "cy": 0}),
    lambda x: x["capture"]["gaps"][0].update(end_pts_ns="1"),
    lambda x: x["frames"][0].update(image_valid=1),
    lambda x: x.update(unknown=True),
])
def test_invalid_sidecars_rejected(package, change):
    directory, _ = package
    data = load_json((directory / "capture_sidecar.json").read_bytes())
    change(data)
    with pytest.raises(ValueError):
        validate_sidecar(data)


@pytest.mark.parametrize("change", [
    lambda x: x.update(frame_count=5),
    lambda x: x.update(frame_times_s=[0, 0.1, 0.09, 0.2]),
    lambda x: x.update(source_frame_ids=[100, 100, 103, 107]),
    lambda x: x.update(source_pts_ns=["1000000000"] * 4),
    lambda x: x.update(joint_parents=[-1, 2, 1]),
    lambda x: x.update(joint_parents=[-1, 0, 4]),
    lambda x: x.update(joint_names=["root", "root", "right_tip"]),
    lambda x: x.update(frame_valid=[True, True, True, True]),
    lambda x: x.update(joint_valid=[[True, True, True]] * 4),
    lambda x: x.update(source_to_replay=[1] * 16),
    lambda x: x["artifacts"]["mesh_vertices"].update(filename="../mesh_vertices.f32"),
    lambda x: x["artifacts"]["mesh_vertices"].update(byte_size=4),
    lambda x: x["artifacts"]["mesh_vertices"].update(sha256="0" * 64),
    lambda x: x["resampling_map"][0].update(source_frame_id=999),
    lambda x: x["resampling_map"][0].update(source_pts_ns="123"),
    lambda x: x.update(frame_count=100_000_000),
    lambda x: x.update(scale_provenance=""),
    lambda x: x.update(unknown=True),
])
def test_invalid_replay_metadata_rejected(package, change):
    directory, manifest = package
    change(manifest)
    with pytest.raises(ValueError):
        validate_replay(manifest, directory)


@pytest.mark.parametrize("kind,packed", [
    ("mesh_triangles", struct.pack("<I", 99)),
    ("mesh_vertices", struct.pack("<f", float("nan"))),
    ("skeleton_joints", struct.pack("<f", float("inf"))),
])
def test_bad_binary_content_rejected_even_with_matching_hash(package, kind, packed):
    directory, manifest = package
    item = manifest["artifacts"][kind]
    path = directory / item["filename"]
    raw = packed + path.read_bytes()[4:]
    path.write_bytes(raw)
    item["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        validate_replay(manifest, directory)


def test_wrong_size_and_symlinks_rejected(package, tmp_path):
    directory, manifest = package
    target = directory / "mesh_vertices.f32"
    original = target.read_bytes()
    target.write_bytes(original[:-4])
    with pytest.raises(ValueError):
        validate_replay(manifest, directory)
    outside = tmp_path / "outside.f32"
    outside.write_bytes(original)
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(ValueError):
        validate_replay(manifest, directory)


def test_replay_keeps_original_origin_after_first_sample_rejected(package):
    directory, manifest = package
    # New source clock origin is earlier than all retained samples.
    manifest["source_clock"]["origin_pts_ns"] = "900000000"
    manifest["frame_times_s"] = [0.1, 0.14, 0.21, 0.3]
    manifest["gaps"] = [{"start_s": 0.18, "end_s": 0.25, "reason": "Rejected samples"}]
    validate_replay(manifest, directory)


def test_camera_pose_validity_and_calibration(package):
    directory, _ = package
    sidecar = load_json((directory / "capture_sidecar.json").read_bytes())
    sidecar["camera"].update(calibration_status="calibrated", intrinsics={"fx": 500, "fy": 500, "cx": 320, "cy": 240})
    pose = {"position_m": [0, 0, 0], "rotation_xyzw": [0, 0, 0, 1],
            "coordinate_system": "unity_left_handed_y_up_z_forward", "pose_time_ns": "1000000000",
            "tracking_valid": True, "alignment_method": "Synthetic exact timestamp"}
    sidecar["frames"][0]["camera_pose"] = pose
    validate_sidecar(sidecar)
    sidecar["frames"][0]["camera_pose"]["rotation_xyzw"] = [0, 0, 0, 2]
    with pytest.raises(ValueError):
        validate_sidecar(sidecar)


@pytest.mark.parametrize("field,value", [("joint_count", 3.0), ("frame_count", 4.0), ("joint_parents", [-1.0, 0, 0])])
def test_integer_fields_reject_float_representation(package, field, value):
    directory, manifest = package
    manifest[field] = value
    with pytest.raises(ValueError):
        validate_replay(manifest, directory)


def test_extreme_quaternion_returns_validation_error(package):
    directory, _ = package
    sidecar = load_json((directory / "capture_sidecar.json").read_bytes())
    sidecar["frames"][0]["camera_pose"] = {
        "position_m": [0, 0, 0], "rotation_xyzw": [1e308, 0, 0, 1],
        "coordinate_system": "unity", "pose_time_ns": "1000000000",
        "tracking_valid": True, "alignment_method": "Synthetic exact timestamp",
    }
    with pytest.raises(ValueError):
        validate_sidecar(sidecar)


@pytest.mark.parametrize("field,value", [
    ("frame_times_s", [0, 0.04, 0.11, 10 ** 400]),
    ("source_to_replay", [10 ** 400] + [0] * 15),
])
def test_oversized_integers_return_validation_error(package, field, value):
    directory, manifest = package
    manifest[field] = value
    with pytest.raises(ValueError):
        validate_replay(manifest, directory)


def test_gaps_can_describe_rejected_leading_samples(package):
    directory, manifest = package
    manifest["source_clock"]["origin_pts_ns"] = "900000000"
    manifest["frame_times_s"] = [0.1, 0.14, 0.21, 0.3]
    manifest["gaps"] = [{"start_s": 0, "end_s": 0.09, "reason": "Rejected leading samples"},
                        {"start_s": 0.18, "end_s": 0.25, "reason": "Rejected middle samples"}]
    validate_replay(manifest, directory)


def test_capture_gap_cannot_claim_valid_image(package):
    directory, _ = package
    sidecar = load_json((directory / "capture_sidecar.json").read_bytes())
    sidecar["frames"][2]["image_valid"] = True
    with pytest.raises(ValueError):
        validate_sidecar(sidecar)


def test_schemas_are_standalone_draft_2020_12():
    from jsonschema import Draft202012Validator

    for path in Path("processing/schemas").glob("*.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text()))
