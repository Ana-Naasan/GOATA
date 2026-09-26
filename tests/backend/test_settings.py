from pathlib import Path

import pytest

from processing.settings import Limits, Settings


def test_settings_require_private_runtime_token(monkeypatch):
    monkeypatch.delenv("PROCESSING_TOKEN", raising=False)
    with pytest.raises(ValueError):
        Settings.from_env()
    monkeypatch.setenv("PROCESSING_TOKEN", "x" * 32)
    monkeypatch.setenv("PROCESSING_DATA_DIR", "/tmp/physio-test-data")
    assert Settings.from_env().data_dir == Path("/tmp/physio-test-data")


@pytest.mark.parametrize("token", ["", "short", "x" * 31, "é" * 32, " " * 32, "x" * 32 + "\n"])
def test_bad_tokens_rejected(tmp_path, token):
    with pytest.raises(ValueError):
        Settings(tmp_path, token)


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_byte_limits_rejected(value):
    with pytest.raises(ValueError):
        Limits(max_zip_bytes=value)


@pytest.mark.parametrize("value", [0, float("inf"), float("nan")])
def test_invalid_upload_deadlines_rejected(value):
    with pytest.raises(ValueError):
        Limits(max_upload_seconds=value)
