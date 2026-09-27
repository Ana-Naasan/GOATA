"""Synthetic upload builders; MP4 bytes are signature-only, never real footage."""

import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path
from uuid import uuid4

FIXTURE = Path(__file__).parents[1] / "contracts/fixtures/capture_sidecar.json"
SYNTHETIC_MP4 = (
    struct.pack(">I4s4sI4s4s", 24, b"ftyp", b"isom", 0, b"isom", b"mp42")
    + struct.pack(">I4s", 32, b"mdat") + b"SYNTHETIC SIGNATURE ONLY!"
)


def zip_members(members, *, compression=zipfile.ZIP_STORED):
    """Return archive bytes, retaining list order and deliberate duplicate names."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, value in members:
            archive.writestr(name, value)
    return output.getvalue()


def read_members(archive_bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        return [(info.filename, archive.read(info)) for info in archive.infolist()]


def file_reference(name, data):
    return {"member": name, "byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build_capture(tmp_path, *, patient_id=None, session_id=None, test_type="elk",
                  take_count=1, compression=zipfile.ZIP_STORED):
    """Build test-only capture metadata and a signature-only synthetic MP4 ZIP.

    ``tmp_path`` keeps the interface convenient for service tests; the builder
    returns bytes and does not write participant-like media to the repository.
    """
    takes, members = [], []
    for _ in range(take_count):
        take_id = str(uuid4())
        sidecar = json.loads(FIXTURE.read_bytes())
        sidecar["take_id"] = take_id
        sidecar["adapter"]["name"] = "synthetic_service_test_signature_only"
        if test_type == "walking":
            sidecar["capture"] = {**sidecar["capture"], "condition": "exercise", "view": "right",
                                  "side": "not_applicable"}
        if test_type == "barefoot":
            sidecar["capture"] = {**sidecar["capture"], "side": "left", "view": "medial"}
        metadata = json.dumps(sidecar).encode()
        video_name, metadata_name = f"{uuid4()}.mp4", f"{uuid4()}.json"
        takes.append({
            "take_id": take_id, "kind": "foot_closeup" if test_type == "barefoot" else "full_body",
            **{key: sidecar["capture"][key] for key in ("view", "condition", "side")},
            "duration_s": 0.2, "video": file_reference(video_name, SYNTHETIC_MP4),
            "frame_metadata": file_reference(metadata_name, metadata),
        })
        members.extend([(video_name, SYNTHETIC_MP4), (metadata_name, metadata)])
    manifest = {
        "schema_version": "1.0", "patient_id": patient_id or str(uuid4()),
        "session_id": session_id or str(uuid4()), "test_type": test_type,
        "protocol_id": test_type, "protocol_version": "1.0",
        "capture_completed_at": "2026-09-26T17:00:00Z", "takes": takes,
    }
    if test_type != "barefoot":
        manifest["replay_take_id"] = takes[0]["take_id"]
    return manifest, zip_members(members, compression=compression)
