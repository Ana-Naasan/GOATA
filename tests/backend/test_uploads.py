"""Upload acceptance and hostile archive regressions, without real recordings."""

import copy
import io
import json
import stat
import struct
import warnings
import zipfile
import zlib
from dataclasses import replace
from uuid import uuid4

import pytest

from processing.errors import ServiceError
from processing.settings import Limits
from processing.uploads import validate_upload
from tests.backend.helpers import (
    build_capture,
    file_reference,
    read_members,
    zip_members,
)


def validate(tmp_path, manifest, archive, limits=None):
    destination = tmp_path / str(uuid4())
    destination.mkdir()
    archive_path = destination / "media.zip"
    archive_path.write_bytes(archive)
    raw = manifest if isinstance(manifest, (bytes, str)) else json.dumps(manifest).encode()
    result = validate_upload(raw, archive_path, destination, limits or Limits())
    return result, destination


def reject(tmp_path, manifest, archive, *, limits=None, status=422):
    with pytest.raises(ServiceError) as caught:
        validate(tmp_path, manifest, archive, limits)
    assert caught.value.status_code == status
    assert caught.value.code == ("UPLOAD_TOO_LARGE" if status == 413 else "VALIDATION_ERROR")
    return caught.value


def mutate_sidecar(manifest, archive, mutate):
    result = copy.deepcopy(manifest)
    members = read_members(archive)
    name = result["takes"][0]["frame_metadata"]["member"]
    sidecar = json.loads(dict(members)[name])
    mutate(sidecar)
    payload = json.dumps(sidecar).encode()
    result["takes"][0]["frame_metadata"] = file_reference(name, payload)
    return result, zip_members([(key, payload if key == name else data) for key, data in members])


@pytest.mark.parametrize("test_type", ["elk", "rtk", "walking", "barefoot"])
def test_valid_capture_preserves_original_bytes(tmp_path, test_type):
    manifest, archive = build_capture(tmp_path, test_type=test_type)
    (accepted, digest), destination = validate(tmp_path, manifest, archive)
    assert accepted == manifest
    assert len(digest) == 64
    assert (destination / "media.zip").read_bytes() == archive
    for name, data in read_members(archive):
        path = destination / "files" / name
        assert path.read_bytes() == data
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((destination / "files").stat().st_mode) == 0o700


def test_digest_is_independent_of_json_order_and_zip_encoding(tmp_path):
    manifest, archive = build_capture(tmp_path)
    (first, digest), _ = validate(tmp_path, manifest, archive)
    reordered = {key: manifest[key] for key in reversed(manifest)}
    recompressed = zip_members(reversed(read_members(archive)), compression=zipfile.ZIP_DEFLATED)
    (second, other), _ = validate(tmp_path, json.dumps(reordered, indent=4), recompressed)
    assert first == second and digest == other
    changed = {**manifest, "patient_id": str(uuid4())}
    (_, changed_digest), _ = validate(tmp_path, changed, archive)
    assert digest != changed_digest


@pytest.mark.parametrize("raw", [b"{", b"[]", b"{\"takes\": [], \"takes\": []}", b"{\"value\": NaN}", b"\xff"])
def test_strict_manifest_json(tmp_path, raw):
    _, archive = build_capture(tmp_path)
    reject(tmp_path, raw, archive)


@pytest.mark.parametrize("field,value", [
    ("unexpected", "sensitive-patient-name"), ("protocol_id", "rtk"),
    ("protocol_version", "2"), ("replay_take_id", str(uuid4())),
])
def test_manifest_relationships(tmp_path, field, value):
    manifest, archive = build_capture(tmp_path)
    manifest[field] = value
    error = reject(tmp_path, manifest, archive)
    assert "sensitive-patient-name" not in str(error)


@pytest.mark.parametrize("change", ["duplicate_take", "duplicate_file", "wrong_extension", "nonbody_replay"])
def test_manifest_unique_references_and_replay_kind(tmp_path, change):
    manifest, archive = build_capture(tmp_path, take_count=2)
    if change == "duplicate_take":
        manifest["takes"][1]["take_id"] = manifest["takes"][0]["take_id"]
    elif change == "duplicate_file":
        manifest["takes"][1]["video"] = manifest["takes"][0]["video"]
    elif change == "wrong_extension":
        manifest["takes"][0]["video"] = manifest["takes"][0]["frame_metadata"]
    else:
        manifest["takes"][0]["kind"] = "microscope"
    reject(tmp_path, manifest, archive)


@pytest.mark.parametrize("field,value", [("take_id", str(uuid4())), ("view", "rear"), ("side", "bilateral"), ("condition", "exercise")])
def test_sidecar_matches_declared_take(tmp_path, field, value):
    manifest, archive = build_capture(tmp_path)
    def mutate(sidecar):
        target = sidecar if field == "take_id" else sidecar["capture"]
        target[field] = value
    manifest, archive = mutate_sidecar(manifest, archive, mutate)
    reject(tmp_path, manifest, archive)


@pytest.mark.parametrize("duration", [0.1, 0.199])
def test_duration_contains_source_timestamp_span(tmp_path, duration):
    manifest, archive = build_capture(tmp_path)
    manifest["takes"][0]["duration_s"] = duration
    reject(tmp_path, manifest, archive)


def test_invalid_samples_cannot_be_valid_inside_gap(tmp_path):
    manifest, archive = build_capture(tmp_path)
    manifest, archive = mutate_sidecar(manifest, archive, lambda sidecar: sidecar["frames"][2].update(image_valid=True))
    reject(tmp_path, manifest, archive)


@pytest.mark.parametrize("mode", ["missing", "extra", "traversal", "duplicate", "directory", "link", "special", "nested"])
def test_unsafe_archive_members(tmp_path, mode):
    manifest, archive = build_capture(tmp_path)
    members = read_members(archive)
    if mode == "missing":
        members = members[:-1]
    elif mode in ("extra", "traversal", "directory", "nested"):
        name = {"extra": f"{uuid4()}.json", "traversal": "../outside.mp4", "directory": "directory/", "nested": "archive.zip"}[mode]
        members.append((name, b"PK\x03\x04"))
    elif mode == "duplicate":
        members.append(members[0])
    else:
        name, data = members[0]
        info = zipfile.ZipInfo(name)
        info.create_system = 3
        info.external_attr = ((stat.S_IFLNK if mode == "link" else stat.S_IFIFO) | 0o600) << 16
        members[0] = (info, data)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        malicious = zip_members(members)
    reject(tmp_path, manifest, malicious)
    assert not (tmp_path / "outside.mp4").exists()


@pytest.mark.parametrize("field,value", [("byte_size", 1), ("sha256", "0" * 64)])
def test_declared_bytes_and_hashes_must_match(tmp_path, field, value):
    manifest, archive = build_capture(tmp_path)
    manifest["takes"][0]["video"][field] = value
    reject(tmp_path, manifest, archive)


@pytest.mark.parametrize("content", [b"not a video", b"PK\x03\x04nested", struct.pack(">I4s", 4, b"ftyp"), struct.pack(">I4s", 65535, b"ftyp") + b"isom"])
def test_mp4_requires_bounded_ftyp_box(tmp_path, content):
    manifest, archive = build_capture(tmp_path)
    members = read_members(archive)
    name = members[0][0]
    manifest["takes"][0]["video"] = file_reference(name, content)
    reject(tmp_path, manifest, zip_members([(name, content), members[1]]))


@pytest.mark.parametrize("limit,value", [
    ("max_zip_bytes", 10), ("max_manifest_bytes", 10), ("max_expanded_bytes", 10),
    ("max_entries", 1), ("max_takes", 1), ("max_metadata_bytes", 10),
])
def test_configured_limits(tmp_path, limit, value):
    manifest, archive = build_capture(tmp_path, take_count=2)
    reject(tmp_path, manifest, archive, limits=replace(Limits(), **{limit: value}), status=413)


@pytest.mark.parametrize("mode", ["multidisk", "zip64", "oversize_directory", "count_mismatch", "truncated", "encrypted", "unsupported_compression"])
def test_archive_headers_are_checked_before_expansion(tmp_path, mode):
    manifest, archive = build_capture(tmp_path)
    raw = bytearray(archive)
    end = raw.rfind(b"PK\x05\x06")
    central = raw.find(b"PK\x01\x02")
    if mode == "multidisk":
        struct.pack_into("<H", raw, end + 4, 1)
    elif mode == "zip64":
        struct.pack_into("<H", raw, end + 10, 0xFFFF)
    elif mode == "oversize_directory":
        struct.pack_into("<I", raw, end + 12, 0x7FFFFFFF)
    elif mode == "count_mismatch":
        struct.pack_into("<H", raw, end + 8, 1)
        struct.pack_into("<H", raw, end + 10, 1)
    elif mode == "truncated":
        raw = raw[:-5]
    elif mode == "encrypted":
        struct.pack_into("<H", raw, central + 8, 1)
    else:
        struct.pack_into("<H", raw, central + 10, 99)
    reject(tmp_path, manifest, bytes(raw))


def test_no_file_io_error_is_relabelled_as_user_validation(tmp_path, monkeypatch):
    manifest, archive = build_capture(tmp_path)
    destination = tmp_path / "io_failure"
    destination.mkdir()
    archive_path = destination / "media.zip"
    archive_path.write_bytes(archive)
    original = type(destination).open
    def denied(path, *args, **kwargs):
        if path.name.endswith(".mp4"):
            raise PermissionError("disk denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(type(destination), "open", denied)
    with pytest.raises(PermissionError):
        validate_upload(json.dumps(manifest), archive_path, destination, Limits())


def test_duration_may_include_final_frame_presentation(tmp_path):
    manifest, archive = build_capture(tmp_path)
    manifest["takes"][0]["duration_s"] = 0.25
    validate(tmp_path, manifest, archive)


def test_actual_decompressed_size_cannot_be_hidden_by_forged_headers(tmp_path):
    """ZipExtFile truncates to file_size; validators must count the real stream."""
    manifest, archive = build_capture(tmp_path, compression=zipfile.ZIP_DEFLATED)
    members = read_members(archive)
    name, payload = members[0]
    forged_payload = payload + b"x" * 100000
    raw = bytearray(zip_members([(name, forged_payload), members[1]], compression=zipfile.ZIP_DEFLATED))
    central = raw.find(b"PK\x01\x02")
    struct.pack_into("<I", raw, 14, zlib.crc32(payload))
    struct.pack_into("<I", raw, 22, len(payload))
    struct.pack_into("<I", raw, central + 16, zlib.crc32(payload))
    struct.pack_into("<I", raw, central + 24, len(payload))
    reject(tmp_path, manifest, bytes(raw))


@pytest.mark.parametrize("mode", ["local_encryption", "local_zip64", "local_compression", "local_size", "nul_name"])
def test_local_header_and_original_name_are_validated(tmp_path, mode):
    manifest, archive = build_capture(tmp_path)
    raw = bytearray(archive)
    if mode == "local_encryption":
        struct.pack_into("<H", raw, 6, 1)
    elif mode == "local_zip64":
        struct.pack_into("<I", raw, 22, 0xFFFFFFFF)
    elif mode == "local_compression":
        struct.pack_into("<H", raw, 8, 8)
    elif mode == "local_size":
        struct.pack_into("<I", raw, 22, 1)
    else:
        # A trailing NUL is stripped by ZipInfo.filename but retained in orig_filename.
        members = read_members(archive)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive_file:
            for name, data in members:
                info = zipfile.ZipInfo(name)
                if name.endswith(".mp4"):
                    info.filename = name + "\x00"
                archive_file.writestr(info, data)
        raw = bytearray(output.getvalue())
    reject(tmp_path, manifest, bytes(raw))


def test_streamed_archive_with_data_descriptors(tmp_path):
    class NonSeekable(io.BytesIO):
        def seek(self, *args):
            raise io.UnsupportedOperation("stream-only")
    manifest, archive = build_capture(tmp_path)
    sink = NonSeekable()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, data in read_members(archive):
            output.writestr(name, data)
    validate(tmp_path, manifest, sink.getvalue())


@pytest.mark.parametrize("payload", [b"bad", struct.pack("<HH", 1, 0)])
def test_malformed_or_zip64_extra_fields(tmp_path, payload):
    manifest, archive = build_capture(tmp_path)
    members = read_members(archive)
    name, data = members[0]
    info = zipfile.ZipInfo(name)
    info.extra = payload
    reject(tmp_path, manifest, zip_members([(info, data), members[1]]))


def test_corrupted_member_is_rejected_by_checksum(tmp_path):
    manifest, archive = build_capture(tmp_path)
    raw = bytearray(archive)
    data_offset = 30 + struct.unpack_from("<H", raw, 26)[0]
    raw[data_offset + 20] ^= 1
    reject(tmp_path, manifest, bytes(raw))


def test_invalid_deflate_data_is_sanitized(tmp_path):
    manifest, archive = build_capture(tmp_path, compression=zipfile.ZIP_DEFLATED)
    raw = bytearray(archive)
    data_offset = 30 + struct.unpack_from("<H", raw, 26)[0]
    raw[data_offset] = 0xFF
    reject(tmp_path, manifest, bytes(raw))


def test_extended_mp4_box_is_supported(tmp_path):
    manifest, archive = build_capture(tmp_path)
    members = read_members(archive)
    name, _ = members[0]
    data = struct.pack(">I4sQ4sI4s", 1, b"ftyp", 28, b"isom", 0, b"mp42")
    manifest["takes"][0]["video"] = file_reference(name, data)
    validate(tmp_path, manifest, zip_members([(name, data), members[1]]))


def test_non_ascii_utf8_filename_failure_is_sanitized(tmp_path):
    manifest, archive = build_capture(tmp_path)
    raw = bytearray(archive)
    central = raw.find(b"PK\x01\x02")
    struct.pack_into("<H", raw, central + 8, 0x800)
    raw[central + 46] = 0xFF
    reject(tmp_path, manifest, bytes(raw))


@pytest.mark.parametrize("size,padding", [(65536, b"x"), (65537, b"x"), (131073, b"x"), (65559, b" ")])
def test_deflate_drains_buffered_output_after_input_is_consumed(tmp_path, size, padding):
    manifest, archive = build_capture(tmp_path)
    members = read_members(archive)
    name, original = members[0]
    payload = original + padding * (size - len(original))
    manifest["takes"][0]["video"] = file_reference(name, payload)
    large_archive = zip_members([(name, payload), members[1]], compression=zipfile.ZIP_DEFLATED)
    (_, _), destination = validate(tmp_path, manifest, large_archive)
    assert (destination / "files" / name).read_bytes() == payload


def test_deflate_decoder_drains_output_with_no_unconsumed_input():
    from processing.uploads import _expanded_chunks
    payload = b"x" * 65537
    encoder = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    compressed = encoder.compress(payload) + encoder.flush()
    info = zipfile.ZipInfo("decoder-regression")
    info.compress_type = zipfile.ZIP_DEFLATED
    info.compress_size = len(compressed)
    assert b"".join(_expanded_chunks(io.BytesIO(compressed), info)) == payload


@pytest.mark.parametrize("change", [
    lambda manifest: manifest.pop("replay_take_id"),
    lambda manifest: manifest["takes"][0].update(condition="standing"),
    lambda manifest: manifest["takes"][0].update(kind="foot_closeup"),
    lambda manifest: manifest["takes"][0].update(side="left"),
])
def test_walking_requires_full_body_exercise_source(tmp_path, change):
    manifest, archive = build_capture(tmp_path, test_type="walking")
    change(manifest)
    from processing.api_contract import validate_schema
    with pytest.raises(ValueError):
        validate_schema("CaptureManifest", manifest)
    reject(tmp_path, manifest, archive)


def test_walking_retains_separate_steady_hold_microscope_capture(tmp_path):
    manifest, archive = build_capture(tmp_path, test_type="walking", take_count=2)
    manifest["replay_take_id"] = manifest["takes"][1]["take_id"]
    manifest["takes"][0].update(kind="microscope", condition="steady_hold")
    manifest, archive = mutate_sidecar(manifest, archive, lambda sidecar: sidecar["capture"].update(condition="steady_hold"))
    validate(tmp_path, manifest, archive)
