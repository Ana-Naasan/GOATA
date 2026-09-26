"""Validate worker output against accepted evidence before making it downloadable."""

import hashlib
from bisect import bisect_right
from pathlib import Path
from uuid import UUID

from processing.api_contract import validate_schema
from processing.contracts import _require, read_json_file, validate_replay
from processing.errors import ServiceError
from processing.settings import Limits


def _index(items, key):
    result = {item[key]: item for item in items}
    _require(len(result) == len(items), f"Duplicate {key}")
    return result


def _sources(capture, input_dir, limits):
    sources = {}
    for take in capture["takes"]:
        sidecar = read_json_file(input_dir / "files" / take["frame_metadata"]["member"],
                                 max_bytes=limits.max_metadata_bytes)
        sources[take["take_id"]] = (take, sidecar, _index(sidecar["frames"], "frame_id"))
    return sources


def _evidence(evidence, sources):
    _require(evidence["take_id"] in sources, "Unknown evidence take")
    take, sidecar, frames = sources[evidence["take_id"]]
    start, end = evidence["start_s"], evidence["end_s"]
    _require(0 <= start <= end <= take["duration_s"], "Evidence interval outside capture")
    _require(evidence["condition"] == take["condition"], "Evidence condition differs from capture")
    first, last = evidence["first_frame_id"], evidence["last_frame_id"]
    _require(first in frames and last in frames, "Unknown evidence frame")
    origin = int(sidecar["clock"]["origin_pts_ns"])
    first_time, last_time = ((int(frames[index]["pts_ns"]) - origin) / 1e9 for index in (first, last))
    _require(start - 1e-9 <= first_time <= last_time <= end + 1e-9, "Evidence time/frame mismatch")
    _require(frames[first]["image_valid"] and frames[last]["image_valid"], "Evidence endpoint is invalid")


def _replay(result, sources, artifacts, output_dir, limits):
    if "replay" not in result:
        return None, {}
    reference = result["replay"]
    manifest_id = reference["manifest_artifact_id"]
    _require(manifest_id in artifacts and artifacts[manifest_id]["role"] == "replay_manifest"
             and artifacts[manifest_id]["media_type"] == "application/json",
             "Missing replay manifest artifact")
    manifest_path = output_dir / "replay_manifest.json"
    _require(not manifest_path.is_symlink() and manifest_path.is_file(), "Missing or linked replay manifest")
    replay = read_json_file(manifest_path, max_bytes=limits.max_metadata_bytes)
    validate_replay(replay, output_dir)
    _require(replay["result_id"] == result["result_id"], "Replay result identity mismatch")
    source_id = reference["source_take_id"]
    _require(replay["source_take_id"] == source_id and source_id in sources, "Replay source mismatch")
    take, sidecar, frames = sources[source_id]
    _require(take["kind"] == "full_body", "Replay requires full-body evidence")
    _require(replay["source_clock"] == sidecar["clock"], "Replay clock differs from capture")
    for frame_id, pts, valid in zip(replay["source_frame_ids"], replay["source_pts_ns"], replay["frame_valid"]):
        _require(frame_id in frames and pts == frames[frame_id]["pts_ns"], "Replay frame differs from capture")
        _require(not valid or frames[frame_id]["image_valid"], "Replay makes missing evidence valid")
    origin = int(sidecar["clock"]["origin_pts_ns"])
    gap_starts = [item["start_s"] for item in replay["gaps"]]
    for gap in sidecar["capture"]["gaps"]:
        start = (int(gap["start_pts_ns"]) - origin) / 1e9
        end = min((int(gap["end_pts_ns"]) - origin) / 1e9, replay["frame_times_s"][-1])
        if start < end:
            index = bisect_right(gap_starts, start) - 1
            _require(index >= 0 and replay["gaps"][index]["end_s"] >= end, "Replay omitted capture gap")
    files = {manifest_id: "replay_manifest.json"}
    for binary in replay["artifacts"].values():
        identifier = binary["artifact_id"]
        _require(identifier in artifacts, "Replay binary missing from result")
        item = artifacts[identifier]
        _require(item["role"] == "replay_binary" and item["media_type"] == "application/octet-stream",
                 "Replay binary artifact type mismatch")
        _require(all(item[key] == binary[key] for key in ("byte_size", "sha256")), "Replay inventory mismatch")
        files[identifier] = binary["filename"]
    return replay, files


def _artifact_files(artifacts, files, output_dir, limits):
    _require(sum(item["byte_size"] for item in artifacts.values()) <= limits.max_output_bytes,
             "Result output budget exceeded")
    resolved = {identifier: files.get(identifier, identifier) for identifier in artifacts}
    _require({path.name for path in output_dir.iterdir()} == set(resolved.values()), "Unlisted output files")
    for identifier, filename in resolved.items():
        item, path = artifacts[identifier], output_dir / filename
        _require(not path.is_symlink() and path.is_file(), "Missing or linked artifact")
        _require(path.stat().st_size == item["byte_size"], "Artifact size mismatch")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                digest.update(chunk)
        _require(digest.hexdigest() == item["sha256"], "Artifact hash mismatch")
        if item["media_type"] == "application/json":
            read_json_file(path, max_bytes=limits.max_metadata_bytes)
        elif item["media_type"] == "video/mp4":
            from processing.uploads import validate_mp4_signature

            try:
                validate_mp4_signature(path, item["byte_size"])
            except ServiceError as exc:
                raise ValueError("Invalid output video signature") from exc
    return resolved


def _validate_findings(result, sources, methods, replay):
    findings = _index(result["findings"], "finding_id")
    for finding in findings.values():
        _require(finding["method_id"] in methods, "Unknown finding method")
        _require(finding["evidence"]["quality"] != "insufficient", "Insufficient evidence cannot produce a finding")
        _evidence(finding["evidence"], sources)
        take, sidecar, _ = sources[finding["evidence"]["take_id"]]
        _require(not sidecar["capture"]["interrupted"], "Interrupted capture cannot produce assessment findings")
        kind = "foot_closeup" if result["test_type"] == "barefoot" else "full_body"
        _require(take["kind"] == kind, "Finding uses the wrong capture kind")
        if kind == "foot_closeup":
            _require(finding["side"] == take["side"], "Foot finding side differs from capture")
        names = finding.get("highlight_joint_names", [])
        _require(not names or (replay is not None and set(names) <= set(replay["joint_names"])),
                 "Unknown highlight joints")
    return findings


def _validate_microscopes(result, sources, artifacts, methods, findings):
    microscopes = _index(result["microscopes"], "microscope_id")
    for microscope in microscopes.values():
        _require(microscope["method_id"] in methods, "Unknown microscope method")
        _evidence(microscope["evidence"], sources)
        if microscope["status"] == "available":
            _require(microscope["evidence"]["quality"] != "insufficient", "Insufficient microscope evidence")
        for field, role, media in (("original_artifact_id", "microscope_original", "video/mp4"),
                                   ("amplified_artifact_id", "microscope_amplified", "video/mp4"),
                                   ("settings_artifact_id", "processing_settings", "application/json")):
            if field in microscope:
                identifier = microscope[field]
                _require(identifier in artifacts and artifacts[identifier]["role"] == role
                         and artifacts[identifier]["media_type"] == media, "Missing microscope artifact")
    for finding in findings.values():
        if "microscope_id" in finding:
            microscope = microscopes.get(finding["microscope_id"])
            fields = ("take_id", "start_s", "end_s", "first_frame_id", "last_frame_id", "condition")
            _require(microscope is not None and all(microscope["evidence"][field] == finding["evidence"][field]
                                                   for field in fields),
                     "Finding/microscope evidence mismatch")
    return microscopes


def validate_result(result: dict, record: dict, input_dir: Path, output_dir: Path,
                    limits: Limits) -> dict[str, str]:
    """Return the only filenames eligible for authenticated artifact delivery."""
    validate_schema("ResultManifest", result)
    capture, job = record["manifest"], record["job"]
    for field in ("job_id", "patient_id", "session_id", "test_type"):
        _require(result[field] == job[field], "Result identity differs from accepted job")
    for field in ("protocol_id", "protocol_version"):
        _require(result[field] == capture[field], "Result protocol differs from capture")
    _require(result["input_digest"] == record["input_digest"], "Result input digest mismatch")
    sources = _sources(capture, input_dir, limits)
    artifacts = _index(result["artifacts"], "artifact_id")
    _require(all(str(UUID(identifier)) == identifier for identifier in artifacts),
             "Artifact IDs must be canonical lowercase UUIDs")
    methods = _index(result["methods"], "method_id")
    features = _index(result["features"], "name")
    expected = {"foot", "microscope"} if capture["test_type"] == "barefoot" else {"replay", "movement", "microscope"}
    if capture["test_type"] == "barefoot" and "replay_take_id" in capture:
        expected.add("replay")
    _require(set(features) == expected, "Result features do not match selected test")
    for method in methods.values():
        item = artifacts.get(method["settings_artifact_id"])
        _require(item is not None and item["role"] == "processing_settings"
                 and item["media_type"] == "application/json", "Missing method settings")
    if "replay" in result:
        _require(result["replay"]["source_take_id"] == capture.get("replay_take_id"), "Wrong replay source take")
    replay, files = _replay(result, sources, artifacts, output_dir, limits)
    _require((features.get("replay", {}).get("status") == "available") == (replay is not None),
             "Replay availability differs from artifacts")
    _require(all(item["role"] not in {"replay_manifest", "replay_binary"} or identifier in files
                 for identifier, item in artifacts.items()), "Unreferenced replay artifact")
    findings = _validate_findings(result, sources, methods, replay)
    analysis = "foot" if capture["test_type"] == "barefoot" else "movement"
    _require(not findings or features[analysis]["status"] == "available", "Unavailable analysis has findings")
    if features[analysis]["status"] == "available":
        kind = "foot_closeup" if analysis == "foot" else "full_body"
        _require(any(take["kind"] == kind and not sidecar["capture"]["interrupted"]
                     for take, sidecar, _ in sources.values()), "Assessment requires a complete eligible take")
    microscopes = _validate_microscopes(result, sources, artifacts, methods, findings)
    _require((features["microscope"]["status"] == "available") ==
             any(item["status"] == "available" for item in microscopes.values()), "Microscope availability mismatch")
    return _artifact_files(artifacts, files, output_dir, limits)
