"""Private, atomic job storage for one local processing worker."""

import copy
import fcntl
import json
import os
import shutil
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from processing.api_contract import validate_schema
from processing.errors import ServiceError
from processing.settings import Settings

ACTIVE = {"pending", "running"}
STAGES = ("queued", "preparing_recording", "estimating_movement", "analysing_test", "preparing_replay")


def now():
    return datetime.now(UTC).isoformat()


def identifier(value):
    """Normalize UUIDs without allowing a path component through."""
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ServiceError("NOT_FOUND", "Job or artifact was not found.", 404) from exc


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path, value, max_bytes):
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            written = 0
            encoder = json.JSONEncoder(allow_nan=False, ensure_ascii=False, separators=(",", ":"))
            for chunk in encoder.iterencode(value):
                written += len(chunk.encode())
                if written > max_bytes:
                    raise ValueError("Persisted metadata exceeds its configured size limit.")
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def private_directory(path):
    if path.is_symlink():
        raise RuntimeError("Processing storage must not use symbolic links.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


class Store:
    """No queue: the on-disk pending state belongs to the single worker slot."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir
        self.jobs_dir = self.root / "jobs"
        self.staging_dir = self.root / "staging"
        # An internal record combines the capture manifest, artifact index and
        # state. Reserve fixed overhead for terminal errors and identity fields.
        self.record_limit = settings.limits.max_manifest_bytes + settings.limits.max_metadata_bytes + 4096
        self.lock = threading.RLock()
        self.records = {}
        self.idempotency = {}
        self._lock_stream = None

    def open(self):
        private_directory(self.root)
        descriptor = os.open(self.root / ".worker.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self._lock_stream = os.fdopen(descriptor, "a+")
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("This processing store already has an active service.") from exc
            private_directory(self.jobs_dir)
            private_directory(self.staging_dir)
            self.records = {}
            self.idempotency = {}
            self._recover()
        except BaseException:
            self.close()
            raise
        return self

    def _recover(self):
        for path in self.jobs_dir.iterdir():
            if path.is_symlink() or not path.is_dir() or identifier(path.name) != path.name:
                raise RuntimeError("Processing storage contains an invalid job directory.")
            record_path = path / "record.json"
            if record_path.is_symlink() or record_path.stat().st_size > self.record_limit:
                raise RuntimeError("Processing storage contains invalid job metadata.")
            record = json.loads(record_path.read_text(encoding="utf-8"))
            validate_schema("Job", record["job"])
            if record["job"]["job_id"] != path.name or record["idempotency_key"] in self.idempotency:
                raise RuntimeError("Processing storage contains inconsistent job metadata.")
            self.records[path.name] = record
            self.idempotency[record["idempotency_key"]] = path.name
            if record["job"]["status"] in ACTIVE:
                self.fail(path.name, "WORKER_INTERRUPTED", "Processing stopped when the service restarted.", True)
            # Incomplete output is never published or resumed, including after a
            # crash between the artifacts rename and terminal-state persistence.
            shutil.rmtree(path / "output.tmp", ignore_errors=True)
            if self.records[path.name]["job"]["status"] != "succeeded":
                shutil.rmtree(path / "artifacts", ignore_errors=True)
        for path in self.staging_dir.iterdir():
            if path.is_symlink() or not path.is_dir():
                path.unlink()
            else:
                shutil.rmtree(path)

    def close(self):
        if self._lock_stream is not None:
            self._lock_stream.close()
            self._lock_stream = None

    def read(self, job_id):
        with self.lock:
            record = self.records.get(identifier(job_id))
            if record is None:
                raise ServiceError("NOT_FOUND", "Job or artifact was not found.", 404)
            return copy.deepcopy(record)

    def ensure_capacity(self, reserve):
        # ponytail: O(n) disk accounting; use a persisted byte counter if saved
        # job volume makes upload admission slow. There is one validation slot.
        used = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        if used + reserve > self.settings.limits.max_storage_bytes:
            raise ServiceError("CAPACITY_EXCEEDED", "Storage capacity is exhausted; retain the capture and retry later.", 429, True)
        if shutil.disk_usage(self.root).free < reserve:
            raise ServiceError("CAPACITY_EXCEEDED", "Available disk space is insufficient.", 429, True)

    def staging(self):
        with self.lock:
            limits = self.settings.limits
            # Budget the simultaneous ZIP, extracted files, metadata and output
            # of the worker already running while this request is validated.
            reserve = (max(2 * limits.max_zip_bytes, limits.max_zip_bytes + limits.max_expanded_bytes)
                       + self.record_limit + limits.max_manifest_bytes)
            if any(record["job"]["status"] in ACTIVE for record in self.records.values()):
                reserve += limits.max_output_bytes + limits.max_metadata_bytes + self.record_limit
            self.ensure_capacity(reserve)
            return Path(tempfile.mkdtemp(prefix="upload-", dir=self.staging_dir))

    def accept(self, staging, manifest, digest, key):
        with self.lock:
            previous_id = self.idempotency.get(key)
            if previous_id is not None:
                record = self.records[previous_id]
                if record["input_digest"] != digest:
                    raise ServiceError("IDEMPOTENCY_CONFLICT", "This idempotency key belongs to different capture contents.", 409)
                return copy.deepcopy(record), False
            if any(record["job"]["status"] in ACTIVE for record in self.records.values()):
                raise ServiceError("CAPACITY_EXCEEDED", "Another capture is processing; retry after it finishes.", 429, True)
            self.ensure_capacity(self.settings.limits.max_output_bytes + self.settings.limits.max_metadata_bytes + self.record_limit)
            job_id = str(uuid4())
            timestamp = now()
            job = {"job_id": job_id, "session_id": manifest["session_id"],
                   "patient_id": manifest["patient_id"], "test_type": manifest["test_type"],
                   "status": "pending", "stage": "queued", "created_at": timestamp, "updated_at": timestamp}
            record = {"job": job, "manifest": manifest, "input_digest": digest, "idempotency_key": key}
            validate_schema("Job", job)
            atomic_json(staging / "record.json", record, self.record_limit)
            atomic_json(staging / "input" / "capture_manifest.json", manifest, self.settings.limits.max_manifest_bytes)
            for path in (staging / "input").rglob("*"):
                if path.is_file():
                    path.chmod(0o600)
                    with path.open("rb") as stream:
                        os.fsync(stream.fileno())
                elif path.is_dir():
                    path.chmod(0o700)
                    sync_directory(path)
            sync_directory(staging / "input")
            os.replace(staging, self.jobs_dir / job_id)
            self.records = {**self.records, job_id: record}
            self.idempotency = {**self.idempotency, key: job_id}
            try:
                sync_directory(self.jobs_dir)
            except OSError:
                self.fail(job_id, "WORKER_INTERRUPTED", "Job acceptance was interrupted; the original capture has been retained.", True)
                raise
            return copy.deepcopy(record), True

    def _write(self, job_id, record):
        validate_schema("Job", record["job"])
        atomic_json(self.jobs_dir / job_id / "record.json", record, self.record_limit)
        self.records = {**self.records, job_id: record}

    def start(self, job_id):
        with self.lock:
            record = self.read(job_id)
            if record["job"]["status"] != "pending":
                raise RuntimeError("Only a pending job may start.")
            updated = {**record, "job": {**record["job"], "status": "running", "stage": "preparing_recording", "updated_at": now()}}
            self._write(job_id, updated)
            return copy.deepcopy(updated)

    def stage(self, job_id, stage):
        with self.lock:
            record = self.read(job_id)
            job = record["job"]
            if job["status"] != "running" or stage not in STAGES or STAGES.index(stage) < STAGES.index(job["stage"]):
                raise RuntimeError("Worker reported an invalid processing stage.")
            self._write(job_id, {**record, "job": {**job, "stage": stage, "updated_at": now()}})

    def fail(self, job_id, code, message, retryable=False):
        with self.lock:
            record = self.read(job_id)
            if record["job"]["status"] not in ACTIVE:
                return
            error = {"code": code, "message": message, "retryable": retryable}
            self._write(job_id, {**record, "job": {**record["job"], "status": "failed", "updated_at": now(), "error": error}})

    def publish(self, job_id, result, artifact_files):
        with self.lock:
            record = self.read(job_id)
            if record["job"]["status"] != "running":
                raise RuntimeError("Only a running job may publish results.")
            job_dir = self.jobs_dir / job_id
            output = job_dir / "output.tmp"
            atomic_json(output / "result.json", result, self.settings.limits.max_metadata_bytes)
            for path in output.iterdir():
                path.chmod(0o600)
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            sync_directory(output)
            os.replace(output, job_dir / "artifacts")
            sync_directory(job_dir)
            updated = {**record, "artifact_files": artifact_files,
                       "job": {**record["job"], "status": "succeeded", "stage": "complete",
                               "result_id": result["result_id"], "updated_at": now()}}
            self._write(job_id, updated)

    def result(self, job_id):
        record = self.read(job_id)
        status = record["job"]["status"]
        if status != "succeeded":
            code = "PROCESSING_FAILED" if status == "failed" else "NOT_READY"
            raise ServiceError(code, "Processing failed." if status == "failed" else "Result is not ready.", 409, status != "failed")
        path = self.jobs_dir / record["job"]["job_id"] / "artifacts" / "result.json"
        if path.is_symlink() or path.stat().st_size > self.settings.limits.max_metadata_bytes:
            raise RuntimeError("Invalid persisted result metadata.")
        return json.loads(path.read_text(encoding="utf-8"))

    def artifact(self, job_id, artifact_id):
        artifact_id = identifier(artifact_id)
        result = self.result(job_id)
        record = self.read(job_id)
        filename = record.get("artifact_files", {}).get(artifact_id)
        artifact = next((item for item in result["artifacts"] if item["artifact_id"] == artifact_id), None)
        if filename is None or artifact is None:
            raise ServiceError("NOT_FOUND", "Job or artifact was not found.", 404)
        if Path(filename).name != filename:
            raise RuntimeError("Invalid persisted artifact index.")
        path = self.jobs_dir / record["job"]["job_id"] / "artifacts" / filename
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Published artifact is unavailable.")
        if path.stat().st_size != artifact["byte_size"]:
            raise RuntimeError("Published artifact has an unexpected size.")
        return path, artifact
