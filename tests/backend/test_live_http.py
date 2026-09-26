"""Backend end-to-end check over a real loopback socket; all inputs are synthetic."""

import hashlib
import json
import socket
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx
import uvicorn

from processing.api_contract import validate_schema
from processing.service import create_app
from processing.settings import Settings
from tests.backend.helpers import build_capture
from tests.backend.test_service import AUTH, TOKEN, synthetic_processor


@contextmanager
def live_server(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, ws="none"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started, "Loopback server did not start"
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive(), "Loopback server did not shut down"


def test_upload_poll_download_and_restart_over_tcp(tmp_path):
    settings = Settings(tmp_path / "store", TOKEN)
    manifest, bundle = build_capture(tmp_path)
    key = str(uuid4())
    with live_server(create_app(settings, synthetic_processor)) as client:
        assert client.get("/v1/jobs/unknown").status_code == 401
        accepted = client.post("/v1/jobs", headers={**AUTH, "Idempotency-Key": key},
                               data={"manifest": json.dumps(manifest)},
                               files={"media": ("synthetic.zip", bundle, "application/zip")})
        assert accepted.status_code == 202, accepted.text
        validate_schema("Job", accepted.json())
        location = accepted.headers["location"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = client.get(location, headers=AUTH).json()
            if status["status"] in {"succeeded", "failed"}:
                break
            time.sleep(.01)
        assert status["status"] == "succeeded", status
        result = client.get(f"{location}/result", headers=AUTH).json()
        validate_schema("ResultManifest", result)
        item = result["artifacts"][0]
        downloaded = client.get(f"{location}/artifacts/{item['artifact_id']}", headers=AUTH)
        assert downloaded.status_code == 200
        assert hashlib.sha256(downloaded.content).hexdigest() == item["sha256"]
        assert downloaded.headers["x-content-sha256"] == item["sha256"]
    with live_server(create_app(settings)) as client:
        assert client.get(f"{location}/result", headers=AUTH).json() == result
        retried = client.post("/v1/jobs", headers={**AUTH, "Idempotency-Key": key},
                              data={"manifest": json.dumps(manifest)},
                              files={"media": ("synthetic.zip", bundle, "application/zip")})
        assert retried.status_code == 202 and retried.json() == status
