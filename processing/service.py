"""Authenticated local processing API with an explicitly configured GPU adapter."""

import asyncio
import copy
import hmac
import logging
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.responses import FileResponse, JSONResponse

from processing.errors import ServiceError
from processing.pipeline import Pipeline, PipelineError
from processing.publication import validate_result
from processing.settings import Settings
from processing.storage import Store, private_directory
from processing.uploads import validate_upload

LOG = logging.getLogger(__name__)


def error_response(error, request_id):
    headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else {}
    if error.status_code == 429:
        headers["Retry-After"] = "2"
    return JSONResponse({"error": error.detail(), "request_id": request_id}, error.status_code, headers=headers)


class Authenticate:
    """Reject unauthorized requests before any body parser or route executes."""

    def __init__(self, app, token):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        authorization = Headers(scope=scope).getlist("authorization")
        if len(authorization) != 1 or not hmac.compare_digest(authorization[0].encode("utf-8"), self.expected):
            response = error_response(ServiceError("UNAUTHORIZED", "A valid bearer token is required.", 401), request_id)
            await response(scope, receive, send)
            return
        started = False

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception:  # noqa: BLE001 - do not let ASGI server logs expose raw exception contents.
            LOG.error("Internal error for request %s", request_id)
            if started:
                raise RuntimeError("The service response was interrupted.") from None
            response = error_response(ServiceError("INTERNAL_ERROR", "The service could not complete this request.", 500, True), request_id)
            await response(scope, receive, send)


class CaptureMultipartParser(MultiPartParser):
    """Bound multipart headers and reject Starlette's lossy Latin-1 fallback."""

    def on_part_begin(self):
        self.header_bytes = 0
        super().on_part_begin()

    def _check_header(self, size):
        self.header_bytes += size
        if self.header_bytes > 16 * 1024:
            raise MultiPartException("Multipart headers exceed their limit.")

    def on_header_field(self, data, start, end):
        self._check_header(end - start)
        super().on_header_field(data, start, end)

    def on_header_value(self, data, start, end):
        self._check_header(end - start)
        super().on_header_value(data, start, end)

    def on_part_end(self):
        if self._current_part.file is None:
            self.items.append((self._current_part.field_name, self._current_part.data.decode("utf-8")))
        else:
            super().on_part_end()


@asynccontextmanager
async def capture_form(request, limits):
    parser = CaptureMultipartParser(request.headers, request.stream(), max_files=1,
                                    max_fields=1, max_part_size=limits.max_manifest_bytes)
    form = await parser.parse()
    try:
        yield form
    finally:
        await form.close()


def _process(store, processor, job_id):
    output = store.jobs_dir / job_id / "output.tmp"
    try:
        record = store.start(job_id)
        private_directory(output)
        input_dir = store.jobs_dir / job_id / "input"
        context = {**record["job"], "input_digest": record["input_digest"]}
        result = processor(input_dir, output, copy.deepcopy(record["manifest"]), context, lambda stage: store.stage(job_id, stage))
        artifact_files = validate_result(result, record, input_dir, output, store.settings.limits)
        store.publish(job_id, result, artifact_files)
    except Exception as exc:  # noqa: BLE001 - worker boundary persists failure without exposing arbitrary exception text.
        # Log only an opaque job reference; exceptions may contain source paths,
        # media metadata or credentials supplied by a future model adapter.
        LOG.error("Processing failed for job %s", job_id)
        try:
            message = str(exc) if isinstance(exc, PipelineError) else "Processing failed; the original capture has been retained."
            store.fail(job_id, "PROCESSING_FAILED", message)
        except Exception:  # noqa: BLE001 - report storage failure while preserving its pending/running record.
            LOG.error("Could not persist processing failure for job %s", job_id)
    finally:
        shutil.rmtree(output, ignore_errors=True)


def _validate(staging, raw_manifest, limits):
    private_directory(staging / "input")
    result = validate_upload(raw_manifest, staging / "upload.zip", staging / "input", limits)
    (staging / "upload.zip").unlink()
    return result


async def _receive_upload(request, staging, limits):
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;"):
        raise ServiceError("VALIDATION_ERROR", "Expected multipart form fields manifest and media.")
    body_limit = limits.max_zip_bytes + limits.max_manifest_bytes + 64 * 1024
    received = 0
    original_receive = request.receive

    async def bounded_receive():
        nonlocal received
        message = await original_receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > body_limit:
                raise ServiceError("UPLOAD_TOO_LARGE", "The request exceeds the upload limit.", 413)
        return message

    bounded_request = Request(request.scope, receive=bounded_receive)
    try:
        async with asyncio.timeout(limits.max_upload_seconds):
            async with capture_form(bounded_request, limits) as form:
                entries = form.multi_items()
                if len(entries) != 2 or {name for name, _ in entries} != {"manifest", "media"}:
                    raise ServiceError("VALIDATION_ERROR", "Exactly one manifest and one media field are required.")
                manifest, media = form["manifest"], form["media"]
                if not isinstance(manifest, str) or not isinstance(media, UploadFile):
                    raise ServiceError("VALIDATION_ERROR", "Manifest must be JSON text and media must be a ZIP file.")
                raw_manifest = manifest.encode("utf-8")
                if len(raw_manifest) > limits.max_manifest_bytes:
                    raise ServiceError("UPLOAD_TOO_LARGE", "The manifest exceeds its size limit.", 413)
                if media.size is not None and media.size > limits.max_zip_bytes:
                    raise ServiceError("UPLOAD_TOO_LARGE", "The ZIP exceeds its size limit.", 413)
                descriptor = os.open(staging / "upload.zip", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as destination:
                    total = 0
                    while chunk := await media.read(1024 * 1024):
                        total += len(chunk)
                        if total > limits.max_zip_bytes:
                            raise ServiceError("UPLOAD_TOO_LARGE", "The ZIP exceeds its size limit.", 413)
                        await run_in_threadpool(destination.write, chunk)
                return raw_manifest
    except TimeoutError as exc:
        raise ServiceError("VALIDATION_ERROR", "The upload deadline was exceeded; retry with the retained capture.", 422, True) from exc
    except MultiPartException as exc:
        if "Part exceeded maximum size" in exc.message:
            raise ServiceError("UPLOAD_TOO_LARGE", "A multipart field exceeds its size limit.", 413) from exc
        raise ServiceError("VALIDATION_ERROR", "Malformed multipart form data.") from exc
    except UnicodeError as exc:
        raise ServiceError("VALIDATION_ERROR", "Manifest must contain valid UTF-8 JSON.") from exc


def create_app(settings: Settings | None = None, processor=None):
    """Use the configured local pipeline; retain injection for boundary tests."""
    settings = settings or Settings.from_env()
    processor = processor if processor is not None else Pipeline(settings)
    store = Store(settings)
    upload_slot = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(store.open)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="processing")
        app.state.executor = executor
        try:
            yield
        finally:
            await run_in_threadpool(lambda: executor.shutdown(wait=True, cancel_futures=False))
            store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.add_middleware(Authenticate, token=settings.token)

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return error_response(exc, request.state.request_id)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = "NOT_FOUND" if exc.status_code == 404 else "VALIDATION_ERROR"
        status = 404 if exc.status_code == 404 else 422
        return error_response(ServiceError(code, "Endpoint was not found." if status == 404 else "Invalid request.", status), request.state.request_id)

    @app.post("/v1/jobs")
    async def create_job(request: Request):
        keys = request.headers.getlist("idempotency-key")
        key = keys[0] if len(keys) == 1 else ""
        try:
            key = str(UUID(key))
        except (ValueError, AttributeError) as exc:
            raise ServiceError("VALIDATION_ERROR", "A UUID Idempotency-Key header is required.") from exc
        if not upload_slot.acquire(blocking=False):
            raise ServiceError("CAPACITY_EXCEEDED", "Another upload is being validated; retry shortly.", 429, True)
        staging = None
        try:
            staging = await run_in_threadpool(store.staging)
            raw_manifest = await _receive_upload(request, staging, settings.limits)
            manifest, digest = await run_in_threadpool(_validate, staging, raw_manifest, settings.limits)
            record, is_new = await run_in_threadpool(store.accept, staging, manifest, digest, key)
            job = record["job"]
            if is_new:
                try:
                    app.state.executor.submit(_process, store, processor, job["job_id"])
                except RuntimeError:
                    await run_in_threadpool(store.fail, job["job_id"], "WORKER_INTERRUPTED", "The worker could not start; retain the capture and retry.", True)
                    job = (await run_in_threadpool(store.read, job["job_id"]))["job"]
            headers = {"Location": f"/v1/jobs/{job['job_id']}"}
            if job["status"] in {"pending", "running"}:
                headers["Retry-After"] = "2"
            return JSONResponse(job, 202, headers=headers)
        finally:
            if staging is not None:
                await run_in_threadpool(shutil.rmtree, staging, True)
            upload_slot.release()

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str):
        job = (await run_in_threadpool(store.read, job_id))["job"]
        headers = {"Retry-After": "2"} if job["status"] in {"pending", "running"} else {}
        return JSONResponse(job, headers=headers)

    @app.get("/v1/jobs/{job_id}/result")
    async def get_result(job_id: str):
        return JSONResponse(await run_in_threadpool(store.result, job_id))

    @app.get("/v1/jobs/{job_id}/artifacts/{artifact_id}")
    async def get_artifact(job_id: str, artifact_id: str):
        path, artifact = await run_in_threadpool(store.artifact, job_id, artifact_id)
        return FileResponse(path, media_type=artifact["media_type"],
                            headers={"X-Content-SHA256": artifact["sha256"], "Content-Length": str(artifact["byte_size"])})

    return app
