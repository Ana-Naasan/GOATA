"""HTTP mechanics only: the injected processor is explicitly synthetic."""

import asyncio
import hashlib
import json
import secrets
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from processing.api_contract import validate_schema
from processing.service import create_app
from processing.settings import Limits, Settings
from tests.backend.helpers import build_capture

TOKEN = secrets.token_urlsafe(32)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def synthetic_processor(input_dir, output_dir, capture, job, stage):
    """Produce no clinical observations and a labelled settings artifact."""
    stage("analysing_test")
    artifact_id = str(uuid4())
    content = b'{"synthetic_test_worker":true}'
    (output_dir / artifact_id).write_bytes(content)
    return {
        "schema_version": "1.0", "result_id": str(uuid4()),
        "job_id": job["job_id"], "patient_id": capture["patient_id"],
        "session_id": capture["session_id"], "test_type": capture["test_type"],
        "created_at": datetime.now(UTC).isoformat(),
        "pipeline_version": "synthetic-test-only", "protocol_id": capture["protocol_id"],
        "protocol_version": capture["protocol_version"], "input_digest": job["input_digest"],
        "validation_status": "research_demo_unvalidated",
        "methods": [{"method_id": "synthetic", "name": "Synthetic test worker",
                     "version": "1", "settings_artifact_id": artifact_id}],
        "features": [{"name": name, "status": "unavailable", "detail": "Synthetic HTTP test only."}
                     for name in (("foot", "microscope") if capture["test_type"] == "barefoot"
                                  else ("replay", "movement", "microscope"))],
        "findings": [], "microscopes": [],
        "artifacts": [{"artifact_id": artifact_id, "role": "processing_settings",
                       "media_type": "application/json", "byte_size": len(content),
                       "sha256": hashlib.sha256(content).hexdigest()}],
    }


def submit(client, capture, key=None):
    manifest, archive = capture
    return client.post("/v1/jobs", headers={**AUTH, "Idempotency-Key": key or str(uuid4())},
                       data={"manifest": json.dumps(manifest)},
                       files={"media": ("ignored.zip", archive, "application/zip")})


def terminal(client, job_id):
    for _ in range(200):
        response = client.get(f"/v1/jobs/{job_id}", headers=AUTH)
        validate_schema("Job", response.json())
        if response.json()["status"] in {"succeeded", "failed"}:
            return response
        time.sleep(0.01)
    pytest.fail("Worker failed to reach a terminal state")


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "store", token=TOKEN)


def test_authentication_before_body_and_private_docs(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/jobs", content=b"not multipart")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"
        validate_schema("ErrorEnvelope", response.json())
        assert response.headers["www-authenticate"] == "Bearer"
        for path in ("/docs", "/openapi.json", "/v1/jobs/bad"):
            assert client.get(path).status_code == 401
            assert client.get(path, headers=AUTH).status_code == 404


@pytest.mark.parametrize("test_type", ["elk", "rtk", "barefoot"])
def test_published_result_idempotency_restart_and_artifact_isolation(settings, tmp_path, test_type):
    capture = build_capture(tmp_path, test_type=test_type)
    key = str(uuid4())
    with TestClient(create_app(settings, synthetic_processor)) as client:
        accepted = submit(client, capture, key)
        assert accepted.status_code == 202, accepted.text
        validate_schema("Job", accepted.json())
        job_id = accepted.json()["job_id"]
        assert accepted.headers["location"] == f"/v1/jobs/{job_id}"
        final = terminal(client, job_id)
        assert final.json()["status"] == "succeeded", final.text
        assert "retry-after" not in final.headers
        result = client.get(f"/v1/jobs/{job_id}/result", headers=AUTH)
        assert result.status_code == 200, result.text
        saved = result.json()
        validate_schema("ResultManifest", saved)
        assert "replay" not in saved
        assert all(feature["status"] == "unavailable" for feature in saved["features"])
        artifact = saved["artifacts"][0]
        content = client.get(f"/v1/jobs/{job_id}/artifacts/{artifact['artifact_id']}", headers=AUTH)
        assert content.status_code == 200
        assert content.headers["x-content-sha256"] == hashlib.sha256(content.content).hexdigest()
        assert int(content.headers["content-length"]) == len(content.content)
        assert submit(client, capture, key).json() == final.json()
        second = submit(client, capture).json()["job_id"]
        terminal(client, second)
        assert client.get(f"/v1/jobs/{second}/artifacts/{artifact['artifact_id']}", headers=AUTH).status_code == 404
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/v1/jobs/{job_id}", headers=AUTH).json() == final.json()
        assert client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).json() == saved


def test_default_worker_fails_honestly(settings, tmp_path):
    with TestClient(create_app(settings)) as client:
        response = submit(client, build_capture(tmp_path))
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]
        final = terminal(client, job_id).json()
        assert final["status"] == "failed"
        assert final["error"]["code"] == "PROCESSING_FAILED"
        assert "inference" in final["error"]["message"].lower()
        for suffix in ("result", f"artifacts/{uuid4()}"):
            failed = client.get(f"/v1/jobs/{job_id}/{suffix}", headers=AUTH)
            assert failed.status_code == 409
            assert failed.json()["error"]["code"] == "PROCESSING_FAILED"


def test_capacity_and_idempotency_precedence(settings, tmp_path):
    release = threading.Event()
    started = threading.Event()

    def blocked(*args):
        started.set()
        assert release.wait(10)
        return synthetic_processor(*args)

    capture = build_capture(tmp_path)
    key = str(uuid4())
    with TestClient(create_app(settings, blocked)) as client:
        try:
            accepted = submit(client, capture, key)
            assert accepted.status_code == 202, accepted.text
            assert started.wait(2)
            job_id = accepted.json()["job_id"]
            running = client.get(f"/v1/jobs/{job_id}", headers=AUTH)
            assert running.json()["status"] == "running"
            assert running.headers["retry-after"] == "2"
            assert client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).json()["error"]["code"] == "NOT_READY"
            assert submit(client, capture, key).json()["job_id"] == job_id
            overloaded = submit(client, capture)
            assert overloaded.status_code == 429
            changed = {**capture[0], "session_id": str(uuid4())}
            conflict = submit(client, (changed, capture[1]), key)
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        finally:
            release.set()
        assert terminal(client, job_id).json()["status"] == "succeeded"


def test_invalid_multipart_and_unknown_ids(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/jobs", headers=AUTH, content=b"bad").status_code == 422
        headers = {**AUTH, "Idempotency-Key": str(uuid4())}
        assert client.post("/v1/jobs", headers=headers, content=b"bad").status_code == 422
        duplicate = client.post("/v1/jobs", headers=headers,
                                files=[("manifest", (None, "{}")), ("manifest", (None, "{}")),
                                       ("media", ("x.zip", b"x"))])
        assert duplicate.status_code == 422
        for suffix in ("", "/result", f"/artifacts/{uuid4()}"):
            missing = client.get(f"/v1/jobs/{uuid4()}{suffix}", headers=AUTH)
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "NOT_FOUND"
            validate_schema("ErrorEnvelope", missing.json())


def test_stream_limits_and_storage_capacity(settings, tmp_path):
    small = replace(settings, limits=replace(Limits(), max_zip_bytes=64))
    with TestClient(create_app(small)) as client:
        response = submit(client, build_capture(tmp_path))
        assert response.status_code == 413
    exhausted = replace(settings, limits=replace(Limits(), max_storage_bytes=1))
    with TestClient(create_app(exhausted)) as client:
        assert submit(client, build_capture(tmp_path)).status_code == 429


def test_failed_worker_never_publishes_partial_output(settings, tmp_path):
    def broken(input_dir, output_dir, capture, job, stage):
        (output_dir / "partial.txt").write_text("private evidence")
        raise RuntimeError("Do not expose secret /private/path")

    with TestClient(create_app(settings, broken)) as client:
        accepted = submit(client, build_capture(tmp_path))
        final = terminal(client, accepted.json()["job_id"])
        assert final.json()["status"] == "failed"
        assert "secret" not in final.text
        assert "private/path" not in final.text


def test_recovery_and_single_store_lock(settings, tmp_path):
    with TestClient(create_app(settings)) as client:
        accepted = submit(client, build_capture(tmp_path))
        job_id = accepted.json()["job_id"]
        terminal(client, job_id)
        with pytest.raises(RuntimeError, match="already"), TestClient(create_app(settings)):
            pass
    record_path = settings.data_dir / "jobs" / job_id / "record.json"
    record = json.loads(record_path.read_text())
    record["job"] = {key: value for key, value in record["job"].items() if key != "error"}
    record["job"]["status"] = "running"
    record_path.write_text(json.dumps(record))
    with TestClient(create_app(settings)) as client:
        recovered = client.get(f"/v1/jobs/{job_id}", headers=AUTH).json()
        assert recovered["status"] == "failed"
        assert recovered["error"]["code"] == "WORKER_INTERRUPTED"


def raw_request(app, body, *, delay=0, content_length=None):
    """Send real ASGI chunks; no client-created Content-Length can mask a bug."""
    async def run():
        response = []
        chunks = iter([body[index:index + 1024] for index in range(0, len(body), 1024)])

        async def receive():
            if delay:
                await asyncio.sleep(delay)
            chunk = next(chunks, None)
            return {"type": "http.request", "body": chunk or b"", "more_body": chunk is not None}

        async def send(message):
            response.append(message)

        headers = [(b"authorization", AUTH["Authorization"].encode()),
                   (b"content-type", b"multipart/form-data; boundary=bound"),
                   (b"idempotency-key", str(uuid4()).encode())]
        if content_length is not None:
            headers.append((b"content-length", str(content_length).encode()))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/v1/jobs", "raw_path": b"/v1/jobs",
                 "query_string": b"", "root_path": "", "headers": headers,
                 "server": ("localhost", 80), "client": ("localhost", 12345)}
        await app(scope, receive, send)
        return response[0]["status"], json.loads(b"".join(item.get("body", b"") for item in response[1:]))

    return asyncio.run(run())


@pytest.mark.parametrize("content_length", [None, 1])
def test_stream_count_does_not_trust_content_length(settings, content_length):
    small = replace(settings, limits=replace(Limits(), max_zip_bytes=64, max_manifest_bytes=64))
    app = create_app(small)
    body = (b'--bound\r\nContent-Disposition: form-data; name="media"; filename="x.zip"\r\n\r\n'
            + b"x" * (70 * 1024) + b"\r\n--bound--\r\n")
    with TestClient(app):
        status, response = raw_request(app, body, content_length=content_length)
        assert status == 413
        assert response["error"]["code"] == "UPLOAD_TOO_LARGE"
        assert not list(app.state.store.staging_dir.iterdir())


@pytest.mark.parametrize("payload", [
    b'--bound\r\nContent-Disposition: form-data; name="manifest"\r\n\r\n{"bad":"\xff"}\r\n--bound--\r\n',
    b'--bound\r\nContent-Disposition: form-data; name="' + b"x" * 17000 + b'"\r\n\r\n{}\r\n--bound--\r\n',
    b'--bound\r\nContent-Disposition: form-data; name="other"\r\n\r\n{}\r\n--bound--\r\n',
])
def test_malformed_multipart_cleans_staging(settings, payload):
    app = create_app(settings)
    with TestClient(app):
        status, response = raw_request(app, payload)
        assert status == 422
        assert response["error"]["code"] == "VALIDATION_ERROR"
        assert not list(app.state.store.staging_dir.iterdir())


def test_upload_deadline_and_validation_slot_release(settings):
    quick = replace(settings, limits=replace(Limits(), max_upload_seconds=0.001))
    app = create_app(quick)
    with TestClient(app):
        status, response = raw_request(app, b"--bound--\r\n", delay=0.01)
        assert status == 422
        assert response["error"]["retryable"] is True
        assert not list(app.state.store.staging_dir.iterdir())
        assert raw_request(app, b"--bound--\r\n")[0] == 422


def test_small_manifest_limit(settings):
    small = replace(settings, limits=replace(Limits(), max_manifest_bytes=16))
    app = create_app(small)
    body = b'--bound\r\nContent-Disposition: form-data; name="manifest"\r\n\r\n' + b"x" * 32 + b"\r\n--bound--\r\n"
    with TestClient(app):
        assert raw_request(app, body)[0] == 413


def test_corrupt_startup_releases_store_lock(settings):
    job_dir = settings.data_dir / "jobs" / str(uuid4())
    job_dir.mkdir(parents=True)
    (job_dir / "record.json").write_text("not JSON")
    with pytest.raises(ValueError), TestClient(create_app(settings)):
        pass
    (job_dir / "record.json").unlink()
    job_dir.rmdir()
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/v1/jobs/{uuid4()}", headers=AUTH).status_code == 404


def test_cli_requires_tls_and_single_worker(monkeypatch, tmp_path):
    from processing import __main__ as cli

    monkeypatch.setenv("PROCESSING_TOKEN", TOKEN)
    monkeypatch.setenv("PROCESSING_DATA_DIR", str(tmp_path / "cli"))
    called = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: called.append(kwargs))
    monkeypatch.setattr("sys.argv", ["processing"])
    cli.main()
    assert called[0]["host"] == "127.0.0.1"
    assert called[0]["workers"] == 1
    monkeypatch.setattr("sys.argv", ["processing", "--host", "0.0.0.0"])
    with pytest.raises(SystemExit):
        cli.main()
    monkeypatch.setattr("sys.argv", ["processing", "--host", "0.0.0.0", "--ssl-certfile", "cert.pem", "--ssl-keyfile", "key.pem"])
    cli.main()
    assert called[-1]["ssl_certfile"] == "cert.pem"


def test_upload_validation_slot_is_bounded(settings, tmp_path, monkeypatch):
    from processing import service

    release = threading.Event()
    started = threading.Event()
    original = service.validate_upload

    def slow_validation(*args):
        started.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(service, "validate_upload", slow_validation)
    app = create_app(settings)
    capture = build_capture(tmp_path)
    responses = []
    with TestClient(app) as client:
        first = threading.Thread(target=lambda: responses.append(submit(client, capture)))
        first.start()
        try:
            assert started.wait(2)
            second = submit(client, capture)
            assert second.status_code == 429
            assert second.headers["retry-after"] == "2"
            assert len(list(app.state.store.staging_dir.iterdir())) == 1
        finally:
            release.set()
            first.join(3)
        assert responses[0].status_code == 202


def test_acceptance_write_failure_never_acknowledges_job(settings, tmp_path, monkeypatch):
    from processing import storage

    def fail_write(*args):
        raise OSError("private disk path and token must not leak")

    app = create_app(settings)
    with TestClient(app) as client:
        monkeypatch.setattr(storage, "atomic_json", fail_write)
        response = submit(client, build_capture(tmp_path))
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "private disk" not in response.text
        assert not list(app.state.store.jobs_dir.iterdir())
        assert not list(app.state.store.staging_dir.iterdir())


def test_wrong_patient_output_fails_before_publication(settings, tmp_path):
    def wrong_patient(*args):
        return {**synthetic_processor(*args), "patient_id": str(uuid4())}

    app = create_app(settings, wrong_patient)
    with TestClient(app) as client:
        job_id = submit(client, build_capture(tmp_path)).json()["job_id"]
        assert terminal(client, job_id).json()["status"] == "failed"
        assert not (app.state.store.jobs_dir / job_id / "artifacts").exists()


def test_auth_does_not_consume_request_body(settings):
    async def run():
        response = []

        async def receive():
            pytest.fail("Unauthorized upload consumed its body")

        async def send(message):
            response.append(message)

        scope = {"type": "http", "method": "POST", "path": "/v1/jobs", "headers": []}
        await create_app(settings)(scope, receive, send)
        assert response[0]["status"] == 401

    asyncio.run(run())


def test_oversized_result_metadata_never_reaches_succeeded(settings, tmp_path):
    small = replace(settings, limits=replace(Limits(), max_metadata_bytes=10000))

    def oversized_result(*args):
        result = synthetic_processor(*args)
        method = result["methods"][0]
        return {**result, "methods": [{**method, "method_id": f"synthetic-{index}"} for index in range(200)]}

    app = create_app(small, oversized_result)
    with TestClient(app) as client:
        job_id = submit(client, build_capture(tmp_path)).json()["job_id"]
        final = terminal(client, job_id)
        assert final.json()["status"] == "failed"
        assert client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).status_code == 409
        assert not (app.state.store.jobs_dir / job_id / "artifacts").exists()


def test_internal_record_budget_includes_capture_and_terminal_error(settings, tmp_path):
    small = replace(settings, limits=replace(Limits(), max_metadata_bytes=4500))
    with TestClient(create_app(small)) as client:
        accepted = submit(client, build_capture(tmp_path, take_count=8))
        assert accepted.status_code == 202, accepted.text
        job_id = accepted.json()["job_id"]
        final = terminal(client, job_id).json()
        assert final["status"] == "failed"
    with TestClient(create_app(small)) as client:
        assert client.get(f"/v1/jobs/{job_id}", headers=AUTH).json() == final


def test_truncated_saved_artifact_returns_safe_error(settings, tmp_path):
    app = create_app(settings, synthetic_processor)
    with TestClient(app) as client:
        job_id = submit(client, build_capture(tmp_path)).json()["job_id"]
        assert terminal(client, job_id).json()["status"] == "succeeded"
        result = client.get(f"/v1/jobs/{job_id}/result", headers=AUTH).json()
        artifact_id = result["artifacts"][0]["artifact_id"]
        (app.state.store.jobs_dir / job_id / "artifacts" / artifact_id).write_bytes(b"truncated")
        response = client.get(f"/v1/jobs/{job_id}/artifacts/{artifact_id}", headers=AUTH)
        assert response.status_code == 500
        validate_schema("ErrorEnvelope", response.json())


def test_acceptance_directory_sync_failure_retains_idempotency(settings, tmp_path, monkeypatch):
    from processing import storage

    original_sync = storage.sync_directory
    should_fail = True

    def fail_first_job_directory_sync(path):
        nonlocal should_fail
        if path == settings.data_dir / "jobs" and should_fail:
            should_fail = False
            raise OSError("Simulated post-rename directory sync failure")
        original_sync(path)

    capture = build_capture(tmp_path)
    key = str(uuid4())
    app = create_app(settings)
    with TestClient(app) as client:
        monkeypatch.setattr(storage, "sync_directory", fail_first_job_directory_sync)
        assert submit(client, capture, key).status_code == 500
        saved_directories = list(app.state.store.jobs_dir.iterdir())
        assert len(saved_directories) == 1
        retry = submit(client, capture, key)
        assert retry.status_code == 202, retry.text
        assert retry.json()["job_id"] == saved_directories[0].name
        assert len(list(app.state.store.jobs_dir.iterdir())) == 1
    with TestClient(create_app(settings)) as client:
        assert submit(client, capture, key).json()["job_id"] == saved_directories[0].name


@pytest.mark.parametrize("field,value", [("patient_id", str(uuid4())), ("protocol_version", "mutated")])
def test_processor_cannot_mutate_accepted_identity_or_validation_baseline(settings, tmp_path, field, value):
    capture = build_capture(tmp_path)

    def mutating_processor(input_dir, output_dir, manifest, job, stage):
        manifest[field] = value
        return synthetic_processor(input_dir, output_dir, manifest, job, stage)

    app = create_app(settings, mutating_processor)
    with TestClient(app) as client:
        job_id = submit(client, capture).json()["job_id"]
        assert terminal(client, job_id).json()["status"] == "failed"
        assert app.state.store.read(job_id)["manifest"] == capture[0]
        saved = json.loads((app.state.store.jobs_dir / job_id / "record.json").read_text())
        assert saved["manifest"] == capture[0]
        assert not (app.state.store.jobs_dir / job_id / "artifacts").exists()
