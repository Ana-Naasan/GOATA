"""Private service settings; model environments are configured separately."""

import json
import math
import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    max_zip_bytes: int = 512 * 1024**2
    max_manifest_bytes: int = 1024**2
    max_expanded_bytes: int = 1024**3
    max_entries: int = 64
    max_takes: int = 8
    max_metadata_bytes: int = 16 * 1024**2
    max_storage_bytes: int = 8 * 1024**3
    max_output_bytes: int = 1024**3
    max_upload_seconds: float = 120.0

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "max_upload_seconds":
                if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                    raise ValueError("Upload deadline must be finite and positive")
            elif type(value) is not int or value <= 0:
                raise ValueError("Resource limits must be positive integers")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    token: str
    limits: Limits = Limits()
    inference_command: tuple[str, ...] = ()
    inference_cwd: Path | None = None
    inference_timeout_seconds: float = 900.0
    inference_workspace_bytes: int = 768 * 1024**2
    allow_estimated_intrinsics: bool = False
    allow_unverified_pinhole: bool = False
    resident_command: tuple[str, ...] = ()

    def __post_init__(self):
        if len(self.token) < 32 or not all(33 <= ord(char) <= 126 for char in self.token):
            raise ValueError("PROCESSING_TOKEN must contain at least 32 printable ASCII characters without spaces")
        for command in (self.inference_command, self.resident_command):
            if (type(command) is not tuple or len(command) > 64
                    or any(type(item) is not str or not item or "\0" in item or len(item) > 4096 for item in command)):
                raise ValueError("Inference command must be a bounded tuple of nonempty arguments")
        if self.inference_command and self.resident_command:
            raise ValueError("Resident and legacy inference commands are mutually exclusive")
        if self.inference_cwd is not None and (not self.inference_cwd.is_absolute() or not self.inference_cwd.is_dir()):
            raise ValueError("Inference working directory must be an existing absolute directory")
        if (self.inference_command or self.resident_command) and self.inference_cwd is None:
            raise ValueError("Configured inference requires PROCESSING_INFERENCE_CWD")
        if (type(self.inference_timeout_seconds) not in (int, float)
                or not math.isfinite(self.inference_timeout_seconds) or self.inference_timeout_seconds <= 0):
            raise ValueError("Inference timeout must be finite and positive")
        if type(self.inference_workspace_bytes) is not int or self.inference_workspace_bytes <= 0:
            raise ValueError("Inference workspace budget must be a positive integer")
        if type(self.allow_unverified_pinhole) is not bool:
            raise ValueError("Unverified pinhole setting must be boolean")
        if type(self.allow_estimated_intrinsics) is not bool:
            raise ValueError("Estimated intrinsics setting must be boolean")

    @classmethod
    def from_env(cls):
        command = json.loads(os.environ.get("PROCESSING_INFERENCE_COMMAND", "[]"))
        if type(command) is not list:
            raise ValueError("PROCESSING_INFERENCE_COMMAND must be a JSON array of arguments")
        resident = json.loads(os.environ.get("PROCESSING_RESIDENT_COMMAND", "[]"))
        if type(resident) is not list:
            raise ValueError("PROCESSING_RESIDENT_COMMAND must be a JSON array of arguments")
        cwd = os.environ.get("PROCESSING_INFERENCE_CWD")
        estimated = os.environ.get("PROCESSING_ALLOW_ESTIMATED_INTRINSICS", "false")
        if estimated not in {"true", "false"}:
            raise ValueError("PROCESSING_ALLOW_ESTIMATED_INTRINSICS must be true or false")
        pinhole = os.environ.get("PROCESSING_ALLOW_UNVERIFIED_PINHOLE", "false")
        if pinhole not in {"true", "false"}:
            raise ValueError("PROCESSING_ALLOW_UNVERIFIED_PINHOLE must be true or false")
        return cls(Path(os.environ.get("PROCESSING_DATA_DIR", "var/processing")),
                   os.environ.get("PROCESSING_TOKEN", ""), inference_command=tuple(command),
                   resident_command=tuple(resident),
                   inference_cwd=Path(cwd) if cwd else None,
                   inference_timeout_seconds=float(os.environ.get("PROCESSING_INFERENCE_TIMEOUT_SECONDS", "900")),
                   inference_workspace_bytes=int(os.environ.get("PROCESSING_INFERENCE_WORKSPACE_BYTES", str(768 * 1024**2))),
                   allow_estimated_intrinsics=estimated == "true",
                   allow_unverified_pinhole=pinhole == "true")
