"""Private service settings; model environments are configured separately."""

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

    def __post_init__(self):
        if len(self.token) < 32 or not all(33 <= ord(char) <= 126 for char in self.token):
            raise ValueError("PROCESSING_TOKEN must contain at least 32 printable ASCII characters without spaces")

    @classmethod
    def from_env(cls):
        return cls(Path(os.environ.get("PROCESSING_DATA_DIR", "var/processing")),
                   os.environ.get("PROCESSING_TOKEN", ""))
