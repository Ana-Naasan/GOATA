"""V1 capture/replay validation and an explicitly synthetic importer fixture.

Run ``python -m processing.contracts generate DIR`` or ``validate DIR``.
The fixture is already in Unity coordinates; this is not a model exporter.
"""

import argparse
import hashlib
import json
import math
import struct
from itertools import pairwise
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.validators import extend

SCHEMA_DIR = Path(__file__).with_name("schemas")
MAX_DECODED_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
ContractValidator = extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda checker, value: type(value) is int),
)
_FILES = {
    "mesh_triangles": "mesh_triangles.u32",
    "mesh_vertices": "mesh_vertices.f32",
    "skeleton_joints": "skeleton_joints.f32",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _finite_tree(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) in (int, float):
            try:
                _require(math.isfinite(item), "Nonfinite JSON number")
            except OverflowError as exc:
                raise ValueError("JSON number exceeds finite numeric range") from exc
        elif isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def load_json(data: bytes | str, *, max_bytes: int = MAX_JSON_BYTES) -> dict | list:
    """Parse strict UTF-8 JSON; reject duplicate keys and nonfinite numbers."""
    try:
        _require(len(data) <= max_bytes, "JSON metadata exceeds byte limit")
        raw = data.encode("utf-8") if isinstance(data, str) else data
        _require(len(raw) <= max_bytes, "JSON metadata exceeds byte limit")
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
        _require(isinstance(value, (dict, list)), "Expected JSON object or array")
        _finite_tree(value)
        return value
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid UTF-8 JSON or excessive nesting") from exc


def read_json_file(path: Path, *, max_bytes: int = MAX_JSON_BYTES) -> dict | list:
    """Read bounded metadata before parsing, including files larger than claimed."""
    _require(type(max_bytes) is int and max_bytes > 0, "JSON byte limit must be positive")
    with Path(path).open("rb") as source:
        return load_json(source.read(max_bytes + 1), max_bytes=max_bytes)


def _schema_validate(data, filename):
    _finite_tree(data)
    schema = read_json_file(SCHEMA_DIR / filename)
    try:
        ContractValidator(schema, format_checker=FormatChecker()).validate(data)
    except (ValidationError, RecursionError) as exc:
        # Do not echo patient metadata or payload fragments into service errors.
        raise ValueError(f"Invalid {filename} document") from exc


def _increasing(values, label):
    _require(all(a < b for a, b in pairwise(values)), f"{label} must increase")


def _gaps_valid(gaps, start_key, end_key, first, last, convert=float):
    previous_end = first
    for gap in gaps:
        start, end = convert(gap[start_key]), convert(gap[end_key])
        _require(first <= start < end <= last, "Gap outside source interval")
        _require(start >= previous_end, "Gaps must be ordered and disjoint")
        previous_end = end


def _check_gap_samples(samples, intervals):
    """Intervals and samples are ordered; closed gap boundaries stay invalid."""
    remaining = iter(intervals)
    gap = next(remaining, None)
    for time, valid in samples:
        while gap is not None and time > gap[1]:
            gap = next(remaining, None)
        if gap is not None and gap[0] <= time:
            _require(not valid, "Gap samples must remain invalid")


def validate_sidecar(data: dict) -> None:
    """Validate original capture timing, calibration and available camera poses."""
    _schema_validate(data, "capture_sidecar.schema.json")
    frames = data["frames"]
    ids = [frame["frame_id"] for frame in frames]
    _require(len(set(ids)) == len(ids), "Duplicate source frame ID")
    times = [int(frame["pts_ns"]) for frame in frames]
    _increasing(times, "Source timestamps")
    _require(int(data["clock"]["origin_pts_ns"]) == times[0], "Origin must be first source PTS")
    _gaps_valid(data["capture"]["gaps"], "start_pts_ns", "end_pts_ns", times[0], times[-1], int)
    _check_gap_samples(zip(times, (frame["image_valid"] for frame in frames)),
                       ((int(gap["start_pts_ns"]), int(gap["end_pts_ns"])) for gap in data["capture"]["gaps"]))
    for frame in frames:
        pose = frame.get("camera_pose")
        if pose:
            norm = math.hypot(*pose["rotation_xyzw"])
            _require(math.isclose(norm, 1.0, abs_tol=1e-4), "Camera quaternion must be normalized")


def _validate_parents(manifest):
    count = manifest["joint_count"]
    names, parents = manifest["joint_names"], manifest["joint_parents"]
    _require(len(names) == len(parents) == count, "Joint metadata count mismatch")
    _require(len(set(names)) == count, "Duplicate joint names")
    _require(parents.count(-1) == 1, "Exactly one root parent must be -1")
    _require(all(-1 <= parent < count for parent in parents), "Joint parent out of bounds")
    # Each node is visited at most once; malformed long chains cannot cause recursion.
    resolved = set()
    for joint in range(count):
        chain = set()
        cursor = joint
        while cursor != -1 and cursor not in resolved:
            _require(cursor not in chain, "Joint parent cycle")
            chain.add(cursor)
            cursor = parents[cursor]
        resolved.update(chain)
    known_names = set(names)
    for regions in manifest["joint_regions"].values():
        _require(len(set(regions)) == len(regions), "Duplicate region joint name")
        _require(set(regions) <= known_names, "Unknown joint in finding region map")


def _validate_replay_timing(manifest):
    count = manifest["frame_count"]
    fields = ("frame_times_s", "source_frame_ids", "source_pts_ns", "frame_valid", "joint_valid")
    _require(all(len(manifest[key]) == count for key in fields), "Frame metadata count mismatch")
    times, ids = manifest["frame_times_s"], manifest["source_frame_ids"]
    pts = [int(value) for value in manifest["source_pts_ns"]]
    origin = int(manifest["source_clock"]["origin_pts_ns"])
    _increasing(times, "Replay timestamps")
    _increasing(pts, "Original source PTS")
    _require(len(set(ids)) == count, "Duplicate original source frame ID")
    for timestamp, source_pts in zip(times, pts):
        _require(math.isclose(timestamp, (source_pts - origin) / 1e9, abs_tol=1e-9, rel_tol=0),
                 "Replay time does not match original PTS")
    gaps = manifest["gaps"]
    _gaps_valid(gaps, "start_s", "end_s", 0, times[-1])
    _check_gap_samples(zip(times, manifest["frame_valid"]), ((gap["start_s"], gap["end_s"]) for gap in gaps))
    for valid, joints in zip(manifest["frame_valid"], manifest["joint_valid"]):
        _require(len(joints) == manifest["joint_count"], "Joint validity width mismatch")
        _require(valid or not any(joints), "Invalid frame cannot contain valid joints")
    source = dict(zip(ids, manifest["source_pts_ns"]))
    mapping = manifest["resampling_map"]
    _increasing([item["inference_frame_id"] for item in mapping], "Inference IDs")
    mapped_times = [int(item["source_pts_ns"]) for item in mapping]
    _require(all(a <= b for a, b in pairwise(mapped_times)), "Resampling map reverses source time")
    for item in mapping:
        _require(source.get(item["source_frame_id"]) == item["source_pts_ns"], "Unknown resampling source")


def _validate_transform(manifest):
    matrix = [float(value) for value in manifest["source_to_replay"]]
    _require(matrix[12:] == [0, 0, 0, 1], "Expected row-major affine matrix")
    determinant = (matrix[0] * (matrix[5] * matrix[10] - matrix[6] * matrix[9])
                   - matrix[1] * (matrix[4] * matrix[10] - matrix[6] * matrix[8])
                   + matrix[2] * (matrix[4] * matrix[9] - matrix[5] * matrix[8]))
    _require(math.isfinite(determinant) and abs(determinant) > 1e-12, "Singular source transform")


def _validate_binary(path, metadata, expected, role, vertex_count):
    _require(not path.is_symlink() and path.is_file(), "Missing or linked replay artifact")
    _require(path.stat().st_size == metadata["byte_size"] == expected, "Binary byte count mismatch")
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            byte_count += len(chunk)
            _require(byte_count <= expected, "Binary exceeds expected byte count")
            digest.update(chunk)
            _require(len(chunk) % 4 == 0, "Unaligned binary data")
            encoding = "<I" if role == "mesh_triangles" else "<f"
            for (value,) in struct.iter_unpack(encoding, chunk):
                if role == "mesh_triangles":
                    _require(value < vertex_count, "Triangle index out of bounds")
                else:
                    _require(math.isfinite(value), "Nonfinite binary coordinate")
    _require(byte_count == expected, "Binary byte count changed during read")
    _require(digest.hexdigest() == metadata["sha256"], "Artifact hash mismatch")


def validate_replay(manifest: dict, artifact_dir: Path) -> None:
    """Check a package before allocation/rendering; paths are fixed allowlisted names.

    The 256 MiB ceiling includes binaries, decoded numeric metadata/masks and
    serialized metadata. It is a conservative input bound, not measured RAM use.
    """
    _schema_validate(manifest, "replay_manifest.schema.json")
    frames, vertices, joints = (manifest[key] for key in ("frame_count", "vertex_count", "joint_count"))
    expected = {"mesh_triangles": manifest["triangle_count"] * 12,
                "mesh_vertices": frames * vertices * 12, "skeleton_joints": frames * joints * 12}
    decoded_metadata = frames * (25 + joints) + joints * 4 + 64 + len(manifest["resampling_map"]) * 24
    decoded = sum(expected.values()) + decoded_metadata + len(json.dumps(manifest).encode("utf-8"))
    _require(decoded <= MAX_DECODED_BYTES, "Decoded replay exceeds 256 MiB")
    _validate_parents(manifest)
    _validate_replay_timing(manifest)
    _validate_transform(manifest)
    artifacts = manifest["artifacts"]
    ids = [entry["artifact_id"] for entry in artifacts.values()]
    _require(len(set(ids)) == len(ids), "Duplicate artifact ID")
    for role, filename in _FILES.items():
        _validate_binary(Path(artifact_dir) / filename, artifacts[role], expected[role], role, vertices)


def _fixture_id(label):
    return str(uuid5(NAMESPACE_URL, "urn:physio-motion-replay:synthetic-fixture:" + label))


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def generate_fixture(directory: Path) -> None:
    """Write deterministic mechanics-only data, never a participant result."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    times, ids = [0.0, 0.04, 0.11, 0.2], [100, 101, 103, 107]
    pts = [str(1_000_000_000 + round(time * 1e9)) for time in times]
    clock = {"id": "synthetic_pts", "unit": "nanoseconds", "origin_pts_ns": pts[0]}
    sidecar = {
        "schema_version": "1.0", "take_id": _fixture_id("take"),
        "adapter": {"name": "synthetic_mechanics_fixture", "version": "1.0"},
        "image": {"width_px": 640, "height_px": 480, "rotation_degrees": 0, "mirrored": False},
        "camera": {"id": "synthetic_no_camera", "calibration_status": "unavailable"},
        "clock": clock,
        "frames": [{"frame_id": frame_id, "pts_ns": time, "image_valid": index != 2}
                   for index, (frame_id, time) in enumerate(zip(ids, pts))],
        "capture": {"view": "front", "condition": "seated", "side": "not_applicable",
                    "interrupted": False,
                    "gaps": [{"start_pts_ns": "1080000000", "end_pts_ns": "1150000000",
                              "reason": "Synthetic invalid interval; do not interpolate"}]},
    }
    _write_json(directory / "capture_sidecar.json", sidecar)
    # Asymmetric tetrahedron: unequal X tips, high Y tip, forward Z apex.
    base = [(-0.25, 0, 0), (0.5, 0, 0), (0, 0.7, 0), (0, 0.1, 0.4)]
    roots = [(0, 0, 0), (0.1, 0, 0.05), (0, 0, 0), (0.3, 0, 0.15)]
    mesh, skeleton = [], []
    for index, root in enumerate(roots):
        mesh.extend(component + root[axis] if index != 2 else 0.0
                    for vertex in base for axis, component in enumerate(vertex))
        for joint, point in enumerate([(0, 0, 0), base[2], base[1]]):
            skeleton.extend(component + root[axis] if index != 2 and (index != 1 or joint != 2) else 0.0
                            for axis, component in enumerate(point))
    triangles = [0, 2, 1, 0, 1, 3, 1, 2, 3, 2, 0, 3]
    values = {"mesh_triangles": triangles, "mesh_vertices": mesh, "skeleton_joints": skeleton}
    artifacts = {}
    for role, filename in _FILES.items():
        code = "I" if role == "mesh_triangles" else "f"
        raw = struct.pack(f"<{len(values[role])}{code}", *values[role])
        (directory / filename).write_bytes(raw)
        artifacts[role] = {"artifact_id": _fixture_id(role), "filename": filename,
                           "byte_size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                           "encoding": "uint32_le" if code == "I" else "float32_le_frame_major_xyz"}
    manifest = {
        "schema_version": "1.0", "result_id": _fixture_id("result"), "source_take_id": _fixture_id("take"),
        "synthetic": True,
        "model": {"name": "synthetic_asymmetric_tetrahedron", "revision": "1.0", "topology_revision": "tetrahedron-4v-4t-v1"},
        "frame_count": 4, "vertex_count": 4, "triangle_count": 4, "joint_count": 3,
        "joint_names": ["root", "high_tip", "right_tip"], "joint_parents": [-1, 0, 0],
        "joint_regions": {"synthetic_upper": ["high_tip"], "synthetic_right": ["right_tip"]},
        "frame_times_s": times, "source_frame_ids": ids, "source_pts_ns": pts, "source_clock": clock,
        "frame_valid": [True, True, False, True],
        "joint_valid": [[True, True, True], [True, True, False], [False, False, False], [True, True, True]],
        "gaps": [{"start_s": 0.08, "end_s": 0.15, "reason": "Synthetic invalid interval; do not interpolate"}],
        "coordinate_system": "unity_left_handed_y_up_z_forward", "units": "metres",
        "scale_status": "estimated", "scale_provenance": "Authored synthetic units; no physical measurement or calibration",
        "source_coordinate_system": "unity_left_handed_y_up_z_forward",
        "source_to_replay": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        "resampling_map": [{"inference_frame_id": i, "source_frame_id": ids[source], "source_pts_ns": pts[source]}
                           for i, source in enumerate([0, 1, 1, 2, 2, 3, 3])],
        "artifacts": artifacts,
    }
    _write_json(directory / "replay_manifest.json", manifest)
    validate_sidecar(sidecar)
    validate_replay(manifest, directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "validate"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "generate":
        generate_fixture(args.directory)
    validate_sidecar(read_json_file(args.directory / "capture_sidecar.json"))
    validate_replay(read_json_file(args.directory / "replay_manifest.json"), args.directory)
    print("Valid capture sidecar and replay package (mechanical checks only).")


if __name__ == "__main__":
    main()
