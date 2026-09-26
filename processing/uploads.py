"""Bounded capture validation and allowlisted extraction before job acceptance.

MP4 validation here checks the ISO BMFF signature only. Real decoder probing and
resource limits belong to the future inference adapter; these checks do not
establish that a movie is decodable or that its metadata matches decoded frames.
"""

import hashlib
import json
import math
import stat
import struct
import zipfile
import zlib
from pathlib import Path

from processing.api_contract import validate_schema
from processing.contracts import load_json, validate_sidecar
from processing.errors import ServiceError
from processing.settings import Limits

_CHUNK_BYTES = 64 * 1024
_SUPPORTED_COMPRESSION = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


def _invalid(message="Invalid capture bundle."):
    return ServiceError("VALIDATION_ERROR", message, status_code=422)


def _bounded(actual, maximum):
    if actual > maximum:
        raise ServiceError("UPLOAD_TOO_LARGE", "Capture exceeds a configured upload limit.", status_code=413)


def _require(condition, message="Invalid capture bundle."):
    if not condition:
        raise _invalid(message)


def _parse_manifest(raw, limits):
    _bounded(len(raw), limits.max_manifest_bytes)
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8")
        except UnicodeError as exc:
            raise _invalid("Manifest must be valid UTF-8 JSON.") from exc
    _bounded(len(raw), limits.max_manifest_bytes)
    try:
        manifest = load_json(raw, max_bytes=limits.max_manifest_bytes)
        if isinstance(manifest, dict) and isinstance(manifest.get("takes"), list):
            _bounded(len(manifest["takes"]), limits.max_takes)
        validate_schema("CaptureManifest", manifest)
    except ValueError as exc:
        raise _invalid("Invalid capture manifest.") from exc
    _require(manifest["protocol_id"] == manifest["test_type"] and manifest["protocol_version"] == "1.0",
             "Unknown provisional test protocol.")
    return manifest


def _references(manifest, limits):
    takes = {take["take_id"]: take for take in manifest["takes"]}
    _require(len(takes) == len(manifest["takes"]), "Duplicate capture take.")
    replay_id = manifest.get("replay_take_id")
    if replay_id is not None:
        _require(replay_id in takes and takes[replay_id]["kind"] == "full_body", "Invalid replay source take.")
    references = {}
    for take in takes.values():
        for role, suffix in (("video", ".mp4"), ("frame_metadata", ".json")):
            item = take[role]
            _require(item["member"].endswith(suffix), "Capture member has an incorrect extension.")
            _require(item["member"] not in references, "Duplicate capture member reference.")
            if role == "frame_metadata":
                _bounded(item["byte_size"], limits.max_metadata_bytes)
            references[item["member"]] = item
    _bounded(len(references), limits.max_entries)
    _bounded(sum(item["byte_size"] for item in references.values()), limits.max_expanded_bytes)
    return references


def _central_directory(source, offset, size, count):
    """Bound the records themselves before ZipFile allocates its central table."""
    source.seek(offset)
    end = offset + size
    for _ in range(count):
        header = source.read(46)
        _require(len(header) == 46 and header[:4] == b"PK\x01\x02", "Invalid ZIP central directory.")
        fields = struct.unpack("<4s6H3I5H2I", header)
        name_size, extra_size, comment_size, disk = fields[10:14]
        _require(0 < name_size <= 41 and disk == 0, "Invalid ZIP member header.")
        _require(fields[8] != 0xFFFFFFFF and fields[9] != 0xFFFFFFFF and fields[-1] != 0xFFFFFFFF,
                 "ZIP64 archives are unsupported.")
        next_offset = source.tell() + name_size + extra_size + comment_size
        _require(next_offset <= end, "Invalid ZIP central directory length.")
        source.seek(next_offset)
    _require(source.tell() == end, "ZIP member count does not match central directory.")


def _preflight_zip(path, limits):
    size = path.stat().st_size
    _bounded(size, limits.max_zip_bytes)
    with path.open("rb") as source:
        source.seek(max(0, size - 65557))
        tail = source.read(65557)
        position = tail.rfind(b"PK\x05\x06")
        _require(position >= 0 and len(tail) - position >= 22, "Missing ZIP end record.")
        record = struct.unpack("<4s4H2IH", tail[position:position + 22])
        _, disk, central_disk, disk_count, count, central_size, offset, comment_size = record
        _require(position + 22 + comment_size == len(tail), "Invalid ZIP end record length.")
        _require(disk == central_disk == 0 and disk_count == count, "Multidisk ZIP archives are unsupported.")
        _require(count != 0xFFFF and central_size != 0xFFFFFFFF and offset != 0xFFFFFFFF,
                 "ZIP64 archives are unsupported.")
        _bounded(count, limits.max_entries)
        absolute_end = size - len(tail) + position
        _require(count > 0 and offset + central_size == absolute_end, "Invalid ZIP central directory bounds.")
        _require(central_size <= count * (46 + 41 + 2 * 65535), "Invalid ZIP central directory size.")
        source.seek(0)
        _require(source.read(4) == b"PK\x03\x04", "Invalid ZIP local header.")
        _central_directory(source, offset, central_size, count)
    return offset


def _check_extra(extra):
    offset = 0
    while offset < len(extra):
        _require(offset + 4 <= len(extra), "Invalid ZIP extra data.")
        tag, size = struct.unpack_from("<HH", extra, offset)
        _require(tag != 1, "ZIP64 archives are unsupported.")
        offset += 4 + size
        _require(offset <= len(extra), "Invalid ZIP extra data length.")


def _check_members(archive, references, limits):
    members = archive.infolist()
    _bounded(len(members), limits.max_entries)
    names = [info.filename for info in members]
    _require(len(set(names)) == len(names), "Duplicate ZIP member.")
    _require(set(names) == set(references), "ZIP members do not match the capture manifest.")
    _bounded(sum(info.file_size for info in members), limits.max_expanded_bytes)
    for info in members:
        mode = info.external_attr >> 16
        _require(info.orig_filename == info.filename, "Invalid original ZIP member name.")
        _require(not info.is_dir() and not (info.external_attr & 0x10), "ZIP directories are unsupported.")
        _require(stat.S_IFMT(mode) in (0, stat.S_IFREG), "ZIP links and special files are unsupported.")
        _require(info.flag_bits & ~0x80E == 0, "Unsupported or encrypted ZIP member flags.")
        _require(info.compress_type in _SUPPORTED_COMPRESSION, "Unsupported ZIP compression.")
        _require(info.volume == 0, "Multidisk ZIP archives are unsupported.")
        _require(info.file_size == references[info.filename]["byte_size"], "ZIP member byte count mismatch.")
        _check_extra(info.extra)
    return members


def _local_header(source, info, central_offset):
    source.seek(info.header_offset)
    raw = source.read(30)
    _require(len(raw) == 30 and raw[:4] == b"PK\x03\x04", "Invalid ZIP local header.")
    fields = struct.unpack("<4s5H3I2H", raw)
    _, _, flags, compression, _, _, crc, compressed, size, name_size, extra_size = fields
    _require(flags == info.flag_bits and compression == info.compress_type, "ZIP headers disagree.")
    _require(compressed != 0xFFFFFFFF and size != 0xFFFFFFFF, "ZIP64 archives are unsupported.")
    expected = (info.CRC, info.compress_size, info.file_size)
    _require(all(value == actual or (flags & 8 and value == 0)
                 for value, actual in zip((crc, compressed, size), expected)), "ZIP headers disagree.")
    _require(name_size == len(info.filename) and source.read(name_size) == info.filename.encode("ascii"),
             "ZIP member names disagree.")
    extra = source.read(extra_size)
    _require(len(extra) == extra_size, "Truncated ZIP extra data.")
    _check_extra(extra)
    end = source.tell() + info.compress_size
    _require(end <= central_offset, "ZIP member overlaps central directory.")
    return end


def _expanded_chunks(source, info):
    """Do not use ZipExtFile: it truncates output to the untrusted file_size."""
    remaining = info.compress_size
    decoder = zlib.decompressobj(-zlib.MAX_WBITS) if info.compress_type == zipfile.ZIP_DEFLATED else None
    while remaining:
        chunk = source.read(min(_CHUNK_BYTES, remaining))
        _require(bool(chunk), "Truncated compressed ZIP member.")
        remaining -= len(chunk)
        if decoder is None:
            yield chunk
        else:
            while True:
                decoded = decoder.decompress(chunk, _CHUNK_BYTES)
                chunk = decoder.unconsumed_tail
                _require(not decoder.unused_data, "Unexpected bytes after compressed ZIP member.")
                if decoded:
                    yield decoded
                # zlib can buffer output after consuming the last input byte.
                if not chunk and len(decoded) < _CHUNK_BYTES:
                    break
    _require(decoder is None or decoder.eof, "Incomplete compressed ZIP member.")


def _copy_member(archive_path, info, target, reference, remaining, central_offset):
    actual, crc, digest = 0, 0, hashlib.sha256()
    with archive_path.open("rb") as source, target.open("xb") as output:
        target.chmod(0o600)
        end = _local_header(source, info, central_offset)
        for chunk in _expanded_chunks(source, info):
            actual += len(chunk)
            _bounded(actual, remaining)
            _require(actual <= reference["byte_size"], "Expanded member exceeds declared byte count.")
            digest.update(chunk)
            crc = zlib.crc32(chunk, crc)
            output.write(chunk)
    _require(actual == reference["byte_size"], "Expanded member byte count mismatch.")
    _require(crc == info.CRC, "ZIP member checksum mismatch.")
    _require(digest.hexdigest() == reference["sha256"], "Capture member hash mismatch.")
    return actual, end


def validate_mp4_signature(path: Path, size: int) -> None:
    """Check the bounded file-type signature; this does not validate decoding."""
    with path.open("rb") as source:
        header = source.read(32)
    _require(len(header) >= 16 and header[4:8] == b"ftyp", "Video lacks an MP4 file-type box.")
    box_size = struct.unpack_from(">I", header)[0]
    minimum, brand_offset = 16, 8
    if box_size == 1:
        _require(len(header) >= 24, "Truncated MP4 extended file-type box.")
        box_size = struct.unpack_from(">Q", header, 8)[0]
        minimum, brand_offset = 24, 16
    _require(minimum <= box_size <= size and (box_size - minimum) % 4 == 0,
             "Invalid MP4 file-type box size.")
    _require(all(32 <= value <= 126 for value in header[brand_offset:brand_offset + 4]),
             "Invalid MP4 file-type brand.")


def _check_sidecar(take, directory, limits):
    path = directory / take["frame_metadata"]["member"]
    with path.open("rb") as source:
        raw = source.read(limits.max_metadata_bytes + 1)
    _bounded(len(raw), limits.max_metadata_bytes)
    try:
        sidecar = load_json(raw, max_bytes=limits.max_metadata_bytes)
        validate_sidecar(sidecar)
    except ValueError as exc:
        raise _invalid("Invalid capture sidecar.") from exc
    _require(sidecar["take_id"] == take["take_id"], "Sidecar take does not match manifest.")
    _require(all(sidecar["capture"][key] == take[key] for key in ("view", "condition", "side")),
             "Sidecar capture does not match manifest.")
    span = (int(sidecar["frames"][-1]["pts_ns"]) - int(sidecar["clock"]["origin_pts_ns"])) / 1e9
    _require(span <= take["duration_s"] or math.isclose(span, take["duration_s"], abs_tol=1e-9, rel_tol=0),
             "Source timestamps exceed capture duration.")


def validate_upload(manifest_raw: bytes | str, archive_path: Path, destination: Path,
                    limits: Limits) -> tuple[dict, str]:
    """Verify original inputs, extract private files, and compute a canonical digest.

    The caller owns the private fresh destination and removes it if validation
    fails. Filesystem errors propagate so storage failures remain server errors.
    """
    manifest = _parse_manifest(manifest_raw, limits)
    references = _references(manifest, limits)
    central_offset = _preflight_zip(archive_path, limits)
    directory = destination / "files"
    directory.mkdir(mode=0o700)
    expanded = 0
    try:
        with zipfile.ZipFile(archive_path, "r", allowZip64=False) as archive:
            previous_end = 0
            for info in sorted(_check_members(archive, references, limits), key=lambda item: item.header_offset):
                _require(info.header_offset >= previous_end, "ZIP members overlap.")
                size, previous_end = _copy_member(archive_path, info, directory / info.filename,
                                                 references[info.filename], limits.max_expanded_bytes - expanded,
                                                 central_offset)
                expanded += size
    except (zipfile.BadZipFile, zlib.error, EOFError, UnicodeError, NotImplementedError) as exc:
        raise _invalid("Malformed or damaged ZIP archive.") from exc
    for take in manifest["takes"]:
        validate_mp4_signature(directory / take["video"]["member"], take["video"]["byte_size"])
        _check_sidecar(take, directory, limits)
    canonical = {"manifest": manifest, "members": [references[name] for name in sorted(references)]}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    return manifest, digest
