"""Bounded native GVHMR geometry to the existing source-timed Unity contract."""

import hashlib
import json
import math
import re
import struct
from fractions import Fraction
from uuid import uuid4

from processing.contracts import (
    MAX_DECODED_BYTES,
    _require,
    read_json_file,
    validate_replay,
    validate_sidecar,
)
from processing.reconstruction.native import UPSTREAM_COMMIT
from processing.reconstruction.runtime import MAX_INFERENCE_FRAMES, bind_pts, plan_input

NATIVE_FILES = frozenset(("parameters.json", "observations.json", "triangles.u32", "vertices.f32",
                          "joints.f32", "fitted_valid.u8", "selection.json", "source-sidecar.json"))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact(path, role, media_type, artifact_id=None):
    return {"artifact_id": artifact_id or path.name, "role": role, "media_type": media_type,
            "byte_size": path.stat().st_size, "sha256": digest(path)}


def write_json(path, value, max_bytes):
    raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
    _require(len(raw) <= max_bytes, "Export JSON exceeds metadata limit")
    with path.open("xb") as stream:
        stream.write(raw)


def _regular(path):
    _require(not path.is_symlink() and path.is_file(), "Native artifacts must be regular files")


def _native(native, take, sidecar, limits):
    _require(not native.is_symlink() and native.is_dir(), "Native directory must not be linked")
    _regular(native / "handoff.json")
    handoff = read_json_file(native / "handoff.json", max_bytes=limits.max_metadata_bytes)
    _require(handoff["schema_version"] == "gvhmr-native-1", "Unknown native format")
    _require(handoff["upstream_commit"] == UPSTREAM_COMMIT, "Unknown upstream revision")
    _require(handoff["take_id"] == take["take_id"] == sidecar["take_id"], "Native take mismatch")
    _require(handoff["source_video_sha256"] == take["video"]["sha256"], "Native video hash mismatch")
    _require(handoff["source_sidecar_sha256"] == take["frame_metadata"]["sha256"], "Native sidecar hash mismatch")
    _require(handoff["selection"] == "selection.json", "Unknown native selection file")
    _require(handoff["array_layout"] == "little endian, frame-major then vertex/joint-major XYZ; triangle triples u32",
             "Unsupported native binary layout")
    files = handoff["artifacts"]
    _require(set(files) == NATIVE_FILES, "Unknown native artifact inventory")
    total = 0
    for name, item in files.items():
        path = native / name
        _regular(path)
        size = item["byte_size"]
        _require(type(size) is int and 0 < size <= limits.max_output_bytes, "Native file exceeds limit")
        total += size
        _require(total <= limits.max_output_bytes, "Native output exceeds limit")
        _require(path.stat().st_size == size and digest(path) == item["sha256"], "Native artifact hash or size mismatch")
        if name.endswith(".json"):
            read_json_file(path, max_bytes=limits.max_metadata_bytes)
    _require(read_json_file(native / "source-sidecar.json") == sidecar, "Preserved sidecar differs")
    return handoff


def _selection(native, sidecar, handoff, allow_unverified_pinhole=False):
    selection = read_json_file(native / "selection.json")
    expected = plan_input(sidecar, allow_estimated_intrinsics=True,
                          allow_unverified_pinhole=allow_unverified_pinhole)
    _require(all(selection.get(key) == value for key, value in expected.items()), "Native source selection differs")
    binding = selection.get("decoder_binding", {})
    decoded = binding.get("decoded_pts_seconds", [])
    _require(isinstance(decoded, list) and len(decoded) == len(sidecar["frames"]), "Missing decoder binding")
    _require(all(type(value) is str and 1 <= len(value) <= 80 for value in decoded), "Invalid decoder PTS representation")
    _require(all(re.fullmatch(r"-?[0-9]{1,30}(?:/[1-9][0-9]{0,29}|\.[0-9]{1,30})?", value)
                 for value in decoded), "Invalid decoder PTS syntax")
    pts = [Fraction(value) for value in decoded]
    offset = 0 if "media" in sidecar else int(binding["offset_ns"])
    bind_pts(sidecar["frames"], list(enumerate(pts)), offset, media=sidecar.get("media"))
    count = handoff["frame_count"]
    _require(type(count) is int and 2 <= count <= MAX_INFERENCE_FRAMES, "Invalid inference count")
    _require(len(selection["frame_mapping"]) == count, "Native row count mismatch")
    # Duplicate source selections get one display row. Retain all inference rows
    # in provenance; averaging would create motion that was never reconstructed.
    rows = [index for index, source in enumerate(selection["selected_indices"])
            if index == 0 or source != selection["selected_indices"][index - 1]]
    return selection, rows


def _geometry(handoff, rows):
    geometry = handoff["geometry"]
    required = {"coordinate_system": "gvhmr_global_ay", "handedness": "right", "up_axis": "+Y",
                "units": "model_metres", "scale_status": "estimated", "unity_conversion_applied": False,
                "root_translation": "preserved, no per-frame recentering"}
    _require(all(geometry.get(key) == value for key, value in required.items()), "Unsupported native coordinates")
    _require(geometry.get("unity_conversion_applied") is False, "Native geometry was already converted")
    vertices, triangles = geometry["vertex_count"], geometry["triangle_count"]
    names, parents = geometry["joint_names"], geometry["joint_parents"]
    _require(type(vertices) is int and vertices >= 3 and type(triangles) is int and triangles >= 1,
             "Invalid native topology counts")
    _require(isinstance(names, list) and 1 <= len(names) <= 256 and len(names) == len(parents), "Invalid native joints")
    raw_size = handoff["frame_count"] * (vertices + len(names)) * 12 + triangles * 12
    _require(raw_size <= MAX_DECODED_BYTES, "Native geometry exceeds decoded budget")
    final_size = len(rows) * (vertices + len(names)) * 12 + triangles * 12
    _require(final_size <= MAX_DECODED_BYTES, "Replay geometry exceeds decoded budget")
    body_hash = handoff.get("asset_sha256", {}).get("body_models/smplx/SMPLX_NEUTRAL.npz", "")
    _require(isinstance(body_hash, str) and re.fullmatch("[a-f0-9]{64}", body_hash), "Missing body asset identity")
    return vertices, triangles, names, parents, body_hash


def _coordinates(source, destination, frame_count, width, rows):
    stride = width * 12
    _require(source.stat().st_size == frame_count * stride, "Native coordinate size mismatch")
    selected = set(rows)
    with source.open("rb") as reader, destination.open("xb") as writer:
        for index in range(frame_count):
            raw = reader.read(stride)
            _require(len(raw) == stride, "Native coordinate data truncated")
            converted = bytearray()
            for x, y, z in struct.iter_unpack("<3f", raw):
                _require(all(math.isfinite(v) for v in (x, y, z)), "Nonfinite native coordinates")
                if index in selected:
                    converted.extend(struct.pack("<3f", x, y, -z))
            if index in selected:
                writer.write(converted)
        _require(not reader.read(1), "Native coordinates grew during export")


def _triangles(source, destination, triangles, vertices):
    _require(source.stat().st_size == triangles * 12, "Native triangle size mismatch")
    with source.open("rb") as reader, destination.open("xb") as writer:
        for _ in range(triangles):
            raw = reader.read(12)
            _require(len(raw) == 12, "Native triangles truncated")
            a, b, c = struct.unpack("<3I", raw)
            _require(max(a, b, c) < vertices, "Native triangle index outside topology")
            writer.write(struct.pack("<3I", a, c, b))
        _require(not reader.read(1), "Native triangles grew during export")


def export_native(native, output, take, sidecar, result_id, limits, *, allow_unverified_pinhole=False):
    """Return (replay manifest, HTTP artifacts, provenance); write fixed binaries.

    Geometry remains model-estimated in a take-local gauge. Reflect Z and reverse
    triangle winding once. No recentering, pose interpolation or physical scaling.
    """
    validate_sidecar(sidecar)
    handoff = _native(native, take, sidecar, limits)
    selection, rows = _selection(native, sidecar, handoff, allow_unverified_pinhole)
    vertices, triangles, names, parents, body_hash = _geometry(handoff, rows)
    count, joints = handoff["frame_count"], len(names)
    mask_path = native / "fitted_valid.u8"
    _require(mask_path.stat().st_size == count * joints, "Invalid native fitted-joint mask size")
    with mask_path.open("rb") as stream:
        masks = stream.read(count * joints + 1)
    _require(len(masks) == count * joints and set(masks) <= {0, 1}, "Invalid native fitted-joint mask")
    frame_map = selection["frame_mapping"]
    binaries = {}
    definitions = (("mesh_triangles", "triangles.u32", "mesh_triangles.u32"),
                   ("mesh_vertices", "vertices.f32", "mesh_vertices.f32"),
                   ("skeleton_joints", "joints.f32", "skeleton_joints.f32"))
    for role, original, filename in definitions:
        if role == "mesh_triangles":
            _triangles(native / original, output / filename, triangles, vertices)
        else:
            _coordinates(native / original, output / filename, count,
                         vertices if role == "mesh_vertices" else joints, rows)
        binaries[role] = {"artifact_id": str(uuid4()), "filename": filename,
                          "byte_size": (output / filename).stat().st_size, "sha256": digest(output / filename),
                          "encoding": "uint32_le" if role == "mesh_triangles" else "float32_le_frame_major_xyz"}
    replay = {
        "schema_version": "1.0", "result_id": result_id, "source_take_id": take["take_id"], "synthetic": False,
        "model": {"name": "GVHMR / SMPL-X", "revision": UPSTREAM_COMMIT, "topology_revision": body_hash},
        "frame_count": len(rows), "vertex_count": vertices, "triangle_count": triangles, "joint_count": joints,
        "joint_names": names, "joint_parents": parents, "joint_regions": {"body": names},
        "frame_times_s": [frame_map[i]["source_time_s"] for i in rows],
        "source_frame_ids": [frame_map[i]["source_frame_id"] for i in rows],
        "source_pts_ns": [frame_map[i]["source_pts_ns"] for i in rows], "source_clock": sidecar["clock"],
        "frame_valid": [True] * len(rows),
        "joint_valid": [[bool(v) for v in masks[i * joints:(i + 1) * joints]] for i in rows], "gaps": [],
        "coordinate_system": "unity_left_handed_y_up_z_forward", "units": "metres", "scale_status": "estimated",
        "scale_provenance": "SMPL-X model metres; no measured physical scale or Quest-world registration. Fitted joints are estimated anatomy.",
        "source_coordinate_system": "gvhmr_global_ay",
        "source_to_replay": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1],
        "resampling_map": [{"inference_frame_id": row["inference_index"],
                            "source_frame_id": row["source_frame_id"], "source_pts_ns": row["source_pts_ns"]}
                           for row in frame_map], "artifacts": binaries,
    }
    validate_replay(replay, output)
    write_json(output / "replay_manifest.json", replay, limits.max_metadata_bytes)
    artifacts = [artifact(output / "replay_manifest.json", "replay_manifest", "application/json", str(uuid4()))]
    artifacts += [artifact(output / item["filename"], "replay_binary", "application/octet-stream", item["artifact_id"])
                  for item in binaries.values()]
    _require(sum(item["byte_size"] for item in artifacts) <= limits.max_output_bytes, "Replay output exceeds budget")
    provenance = {"native_handoff": handoff, "selection": selection, "selected_inference_rows": rows,
                  "selection_policy": "First inference row per unique original source frame; all mappings retained.",
                  "conversion": "Reflect native Z, reverse triangle winding, preserve root translation; model gauge, not Quest registration."}
    return replay, artifacts, provenance
