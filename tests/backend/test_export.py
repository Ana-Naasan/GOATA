"""Native handoff mechanics use tiny authored geometry, never inference claims."""

import hashlib
import json
import struct
from uuid import uuid4

import pytest

from processing.contracts import validate_replay
from processing.export import export_native
from processing.reconstruction.native import UPSTREAM_COMMIT
from processing.reconstruction.runtime import geometry_metadata, plan_input
from processing.settings import Limits
from tests.backend.helpers import build_capture, file_reference, read_members


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def native_fixture(tmp_path, *, unverified_pinhole=False, test_type="elk", joint_names=None):
    capture, media = build_capture(tmp_path, test_type=test_type)
    inputs, native, output = (tmp_path / name for name in ("input", "native", "output"))
    (inputs / "files").mkdir(parents=True)
    native.mkdir()
    output.mkdir()
    for name, data in read_members(media):
        (inputs / "files" / name).write_bytes(data)
    take = capture["takes"][0]
    path = inputs / "files" / take["frame_metadata"]["member"]
    sidecar = json.loads(path.read_text())
    sidecar["capture"]["gaps"] = []
    sidecar["frames"] = [{"frame_id": 10 + i, "pts_ns": str(10**9 + round(i * 10**9 / 15)),
                           "image_valid": True} for i in range(4)]
    sidecar["camera"] = {"id": "authored-camera", "calibration_status": "estimated",
                         "intrinsics": {"fx": 640, "fy": 640, "cx": 320, "cy": 240},
                         "distortion_model": "none", "distortion_coefficients": []}
    if unverified_pinhole:
        sidecar["camera"]["distortion_model"] = "unknown"
    write_json(path, sidecar)
    take["frame_metadata"] = file_reference(path.name, path.read_bytes())
    plan = plan_input(sidecar, allow_unverified_pinhole=unverified_pinhole)
    plan["decoder_binding"] = {
        "offset_ns": "1000000000",
        "rule": "round(decoded_pts_seconds * 1e9) + offset_ns == source_pts_ns",
        "decoded_pts_seconds": [str((int(f["pts_ns"]) - 10**9) / 10**9) for f in sidecar["frames"]],
    }
    count = len(plan["selected_indices"])
    joint_names = joint_names or ["pelvis", "spine1"]
    write_json(native / "selection.json", plan)
    write_json(native / "source-sidecar.json", sidecar)
    write_json(native / "parameters.json", {"test_only": True})
    write_json(native / "observations.json", {"test_only": True})
    (native / "triangles.u32").write_bytes(struct.pack("<3I", 0, 1, 2))
    for name, width in (("vertices.f32", 3), ("joints.f32", len(joint_names))):
        values = [value for row in range(count) for point in range(width)
                  for value in (row + point / 10, point + .5, row + .25)]
        (native / name).write_bytes(struct.pack(f"<{len(values)}f", *values))
    (native / "fitted_valid.u8").write_bytes(bytes([1]) * count * len(joint_names))
    handoff = {
        "schema_version": "gvhmr-native-1", "take_id": take["take_id"],
        "upstream_commit": UPSTREAM_COMMIT, "source_video_sha256": take["video"]["sha256"],
        "source_sidecar_sha256": take["frame_metadata"]["sha256"], "selection": "selection.json",
        "frame_count": count, "geometry": geometry_metadata(joint_names, [-1] + [0] * (len(joint_names) - 1), 3, 1),
        "array_layout": "little endian, frame-major then vertex/joint-major XYZ; triangle triples u32",
        "fitted_valid_layout": "u8 frame-major then 22 joints; 1 finite estimate, 0 unavailable",
        "asset_sha256": {"body_models/smplx/SMPLX_NEUTRAL.npz": "a" * 64},
        "validation_status": "research_demo_unvalidated",
        "artifacts": {p.name: {"byte_size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p in native.iterdir()},
    }
    write_json(native / "handoff.json", handoff)
    return capture, inputs, native, output, sidecar, handoff


def test_export_preserves_time_roots_and_full_duplicate_provenance(tmp_path):
    capture, _inputs, native, output, sidecar, handoff = native_fixture(tmp_path)
    take = capture["takes"][0]
    replay, artifacts, provenance = export_native(native, output, take, sidecar, str(uuid4()), Limits())
    validate_replay(replay, output)
    assert replay["synthetic"] is False  # Export mechanics; the fixture is never shipped as participant data.
    assert replay["source_frame_ids"] == [10, 11, 12, 13]
    assert replay["source_pts_ns"] == [f["pts_ns"] for f in sidecar["frames"]]
    assert len(replay["resampling_map"]) == handoff["frame_count"] > replay["frame_count"]
    assert struct.unpack("<3I", (output / "mesh_triangles.u32").read_bytes()) == (0, 2, 1)
    vertices = list(struct.iter_unpack("<3f", (output / "mesh_vertices.f32").read_bytes()))
    rows = provenance["selected_inference_rows"]
    for index, row in enumerate(rows):
        assert vertices[index * 3] == (row, .5, -row - .25)
    assert len(artifacts) == 4
    assert replay["scale_status"] == "estimated"
    assert replay["source_to_replay"][10] == -1


@pytest.mark.parametrize("change", [
    lambda h: h.update(take_id=str(uuid4())),
    lambda h: h.update(source_video_sha256="b" * 64),
    lambda h: h.update(source_sidecar_sha256="b" * 64),
    lambda h: h.update(schema_version="other"),
    lambda h: h.update(frame_count=10**12),
    lambda h: h["geometry"].update(handedness="left"),
    lambda h: h["geometry"].update(unity_conversion_applied=True),
    lambda h: h["geometry"].update(vertex_count=True),
    lambda h: h["artifacts"].update({"../outside": {"byte_size": 1, "sha256": "a" * 64}}),
])
def test_export_rejects_invalid_handoff_before_publication(tmp_path, change):
    capture, _, native, output, sidecar, handoff = native_fixture(tmp_path)
    change(handoff)
    write_json(native / "handoff.json", handoff)
    with pytest.raises(ValueError):
        export_native(native, output, capture["takes"][0], sidecar, str(uuid4()), Limits())


@pytest.mark.parametrize("bad", ["hash", "link", "nan", "index", "mask", "mapping", "binding"])
def test_export_rejects_bad_native_bytes_or_source_mapping(tmp_path, bad):
    capture, _, native, output, sidecar, handoff = native_fixture(tmp_path)
    name = {"index": "triangles.u32", "mask": "fitted_valid.u8", "mapping": "selection.json",
            "binding": "selection.json"}.get(bad, "vertices.f32")
    path = native / name
    if bad == "link":
        external = tmp_path / "external"
        path.rename(external)
        path.symlink_to(external)
    elif bad in ("mapping", "binding"):
        plan = json.loads(path.read_text())
        if bad == "mapping":
            plan["frame_mapping"][0]["source_pts_ns"] = "999"
        else:
            plan["decoder_binding"]["offset_ns"] = "0"
        write_json(path, plan)
    else:
        raw = path.read_bytes()
        prefix = {"nan": struct.pack("<f", float("nan")), "index": struct.pack("<I", 999),
                  "mask": b"\x02", "hash": b"\xff"}[bad]
        path.write_bytes(prefix + raw[len(prefix):])
    if bad != "hash":
        handoff["artifacts"][name] = {"byte_size": path.stat().st_size,
                                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        write_json(native / "handoff.json", handoff)
    with pytest.raises(ValueError):
        export_native(native, output, capture["takes"][0], sidecar, str(uuid4()), Limits())


def test_export_rejects_output_quota(tmp_path):
    capture, _, native, output, sidecar, _ = native_fixture(tmp_path)
    with pytest.raises(ValueError):
        export_native(native, output, capture["takes"][0], sidecar, str(uuid4()), Limits(max_output_bytes=1))


def test_export_binds_fractional_media_pts_using_android_microseconds(tmp_path):
    capture, inputs, native, output, sidecar, handoff = native_fixture(tmp_path)
    sidecar["media"] = {"binding": "indexed_presentation_time_us", "presentation_time_us": ["0", "33333", "66666", "100000"]}
    path = inputs / "files" / capture["takes"][0]["frame_metadata"]["member"]
    write_json(path, sidecar)
    capture["takes"][0]["frame_metadata"] = file_reference(path.name, path.read_bytes())
    write_json(native / "source-sidecar.json", sidecar)
    plan = plan_input(sidecar)
    plan["decoder_binding"] = {"binding": "indexed_presentation_time_us",
                               "decoded_pts_seconds": ["0", "1/30", "1/15", "1/10"]}
    write_json(native / "selection.json", plan)
    handoff["source_sidecar_sha256"] = capture["takes"][0]["frame_metadata"]["sha256"]
    for name in ("source-sidecar.json", "selection.json"):
        path = native / name
        handoff["artifacts"][name] = {"byte_size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    write_json(native / "handoff.json", handoff)
    replay, _, _ = export_native(native, output, capture["takes"][0], sidecar, str(uuid4()), Limits())
    assert replay["source_pts_ns"] == [row["pts_ns"] for row in sidecar["frames"]]


def test_oversized_fitted_mask_rejected_before_unbounded_read(tmp_path, monkeypatch):
    from pathlib import Path

    capture, _, native, output, sidecar, handoff = native_fixture(tmp_path)
    path = native / 'fitted_valid.u8'
    raw = b'\x01' * 1024**2
    path.write_bytes(raw)
    handoff['artifacts'][path.name] = {'byte_size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    write_json(native / 'handoff.json', handoff)
    original_read = Path.read_bytes

    def bounded_read(self):
        assert self != path, 'mask must be size-checked before allocation'
        return original_read(self)

    monkeypatch.setattr(Path, 'read_bytes', bounded_read)
    with pytest.raises(ValueError, match='mask'):
        export_native(native, output, capture['takes'][0], sidecar, str(uuid4()), Limits())


def test_export_requires_opt_in_and_retains_unverified_camera_provenance(tmp_path):
    capture, _, native, output, sidecar, _ = native_fixture(tmp_path, unverified_pinhole=True)
    with pytest.raises(ValueError, match='distortion'):
        export_native(native, output, capture['takes'][0], sidecar, str(uuid4()), Limits())
    replay, _, provenance = export_native(native, output, capture['takes'][0], sidecar, str(uuid4()),
                                          Limits(), allow_unverified_pinhole=True)
    assert sidecar['camera']['distortion_model'] == 'unknown'
    assert replay['scale_status'] == 'estimated'
    assert provenance['selection']['intrinsics_status'] == 'estimated'
    assert 'unverified' in provenance['selection']['camera_model_assumption']


def test_exponential_decoder_pts_rejected_before_fraction_allocation(tmp_path, monkeypatch):
    capture, _, native, output, sidecar, handoff = native_fixture(tmp_path)
    path = native / 'selection.json'
    selection = json.loads(path.read_text())
    selection['decoder_binding']['decoded_pts_seconds'][0] = '1e1000000000'
    write_json(path, selection)
    handoff['artifacts'][path.name] = {'byte_size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    write_json(native / 'handoff.json', handoff)
    monkeypatch.setattr('processing.export.Fraction', lambda _: pytest.fail('Unbounded Fraction input reached allocation'))
    with pytest.raises(ValueError, match='syntax'):
        export_native(native, output, capture['takes'][0], sidecar, str(uuid4()), Limits())
