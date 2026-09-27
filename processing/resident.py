"""One local JSONL child, full warmup before admission, and one recovery attempt.

Stdlib only: this module also runs in the separate Python 3.10 model environment.
The supervisor thread owns all pipe I/O and process cleanup. There is no queue.
"""

import json
import math
import os
import select
import shutil
import signal
import stat
import subprocess
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

PROTOCOL = "gvhmr-resident-1"
MAX_LINE = 16 * 1024
POLL_SECONDS = .05


class ResidentError(RuntimeError):
    """Static, safe messages only; never include child output or exception text."""


class ResidentCleanupError(ResidentError):
    """Fatal: callers must retain output; no automatic recovery is safe."""

    def __init__(self):
        super().__init__("Inference cleanup could not be confirmed; service is unavailable and temporary output has been retained.")


def remove_workspace(path):
    """Only for scratch whose worker has stopped or whose Store lease is held."""
    try:
        if path.is_symlink():
            path.unlink()
        else:
            shutil.rmtree(path)
    except FileNotFoundError:
        pass


def workspace_budget(path, limit):
    """Bound scratch bytes and entries without following links, even during cleanup."""
    pending, total, entries = [path], 0, 0
    while pending:
        current = pending.pop()
        try:
            details = current.lstat()
            if stat.S_ISLNK(details.st_mode):
                raise ResidentError("Inference produced linked output; it cannot be published.")
            if stat.S_ISDIR(details.st_mode):
                for child in current.iterdir():
                    entries += 1
                    if entries >= 128:
                        raise ResidentError("Inference output exceeds its file-count budget.")
                    pending.append(child)
            elif stat.S_ISREG(details.st_mode):
                total += details.st_size
            else:
                raise ResidentError("Inference produced an unsupported output file.")
        except FileNotFoundError:
            # Warmup removes its files before readiness. Do not follow replacements.
            continue
        if total > limit:
            raise ResidentError("Inference output exceeds its storage budget.")
    return total


def stop_process(process):
    """Kill the whole session, including descendants of an already exited child."""
    try:
        try:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except PermissionError:
                # Darwin can report EPERM for a group whose leader just became a
                # zombie. Reap it and retry; EPERM alone never proves it dead.
                process.wait(timeout=2)
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        raise ResidentCleanupError() from None


def child_environment():
    environment = {key: value for key, value in os.environ.items() if key != "PROCESSING_TOKEN"}
    root = str(Path(__file__).resolve().parent.parent)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (root, environment.get("PYTHONPATH"))))
    return environment


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate protocol key")
        result[key] = value
    return result


def _nonfinite(_):
    raise ValueError("Nonfinite protocol number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        _nonfinite(value)
    return number


@dataclass
class _Job:
    request: bytes
    output: Path
    deadline: float
    done: threading.Event = field(default_factory=threading.Event)
    error: ResidentError | None = None
    pid: int | None = None


class Resident:
    def __init__(self, settings, store=None):
        self.settings = settings
        self.store = store  # Standalone supervisors do not own global scratch.
        self.root = settings.data_dir.resolve()
        self.warmup = self.root / "resident.tmp"
        self._condition = threading.Condition()
        self._stopping = threading.Event()
        self._thread = None
        self._process = None
        self._job = None
        self._state = "stopped"
        self._invalidated = False
        self._cleanup_error = None

    def start(self):
        """Start asynchronously, once per service lifespan, including on failure."""
        with self._condition:
            if self._thread is not None or self._stopping.is_set():
                return
            if not self.settings.resident_command:
                raise ResidentError("Resident inference is not configured.")
            self._state = "warming"
            self._thread = threading.Thread(target=self._supervise, name="resident", daemon=True)
            self._thread.start()

    def snapshot(self):
        """A cheap liveness check, never a model call or a wait for a busy job."""
        with self._condition:
            state = self._state
            if state in {"ready", "busy"} and (self._process is None or self._process.poll() is not None):
                state = "failed"
            return {"state": state, "ready": state in {"ready", "busy"}}

    def run(self, job_id, video, sidecar, output):
        """Return after success/reaping, or raise a fatal cleanup safety status."""
        try:
            if str(UUID(job_id)) != job_id:
                raise ValueError
            job_root = self.root / "jobs" / job_id
            paths = [Path(path).resolve() for path in (video, sidecar, output)]
            if any(not path.is_relative_to(job_root) or path == job_root for path in paths):
                raise ValueError
            payload = {"id": job_id, **dict(zip(("video", "sidecar", "output"), map(str, paths))),
                       "allow_estimated_intrinsics": self.settings.allow_estimated_intrinsics,
                       "allow_unverified_pinhole": self.settings.allow_unverified_pinhole}
            request = (json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n").encode()
            if len(request) > MAX_LINE:
                raise ValueError
        except (ValueError, TypeError, OSError, AttributeError):
            raise ResidentError("Invalid resident inference request.") from None
        with self._condition:
            if self._job is not None:
                raise ResidentError("Resident inference is busy; retry after it finishes.")
            if not self.snapshot()["ready"]:
                raise ResidentError("Resident inference is not ready; retry shortly.")
            job = _Job(request, paths[2], time.monotonic() + self.settings.inference_timeout_seconds)
            self._job = job
            self._state = "busy"
            self._condition.notify_all()
        job.done.wait()  # Fatal cleanup also releases callers, forbidding output deletion.
        if job.error is not None:
            raise job.error
        return job.pid

    def invalidate(self, pid):
        """Retire an invalid handoff's worker before Pipeline deletes its scratch."""
        with self._condition:
            if self._cleanup_error is not None:
                raise self._cleanup_error
            process = self._process
            if process is None or process.pid != pid:
                return  # Already reaped, possibly replaced by the recovery worker.
            self._invalidated = True
            self._state = "failed"
            self._condition.notify_all()
            while self._process is process and self._cleanup_error is None:
                self._condition.wait(POLL_SECONDS)
            if self._cleanup_error is not None:
                raise self._cleanup_error

    def close(self):
        with self._condition:
            self._stopping.set()
            self._state = "failed" if self._cleanup_error is not None else "stopped"
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=3)
            if thread.is_alive():
                self._fatal_cleanup()
        if self._cleanup_error is not None:
            raise self._cleanup_error

    def _fatal_cleanup(self):
        # Even a failed kill/reap or cleanup must release run()/invalidate().
        # Keep the process handle: no assertion that the worker has been killed.
        with self._condition:
            self._cleanup_error = ResidentCleanupError()
            self._state = "failed"
            if self._job is not None:
                self._job.error = self._cleanup_error
                self._job.done.set()
                self._job = None
            self._condition.notify_all()

    def _check(self, process, deadline=None, output=None):
        if self._stopping.is_set():
            raise ResidentError("Resident inference stopped; the original capture has been retained.")
        if self._invalidated:
            raise ResidentError("Resident inference produced an invalid handoff.")
        if deadline is not None and time.monotonic() >= deadline:
            raise ResidentError("Inference exceeded its processing deadline; retain the capture and retry after investigation.")
        used = workspace_budget(self.warmup, self.settings.inference_workspace_bytes)
        if output is not None:
            workspace_budget(output, self.settings.inference_workspace_bytes - used)
        if process.poll() is not None:
            raise ResidentError("Resident inference exited; the original capture has been retained.")

    def _read(self, process, deadline, output=None):
        data = bytearray()
        descriptor = process.stdout.fileno()
        while True:
            self._check(process, deadline, output)
            if not select.select([descriptor], [], [], POLL_SECONDS)[0]:
                continue
            chunk = os.read(descriptor, MAX_LINE + 1 - len(data))
            if not chunk:
                raise ResidentError("Resident inference closed its protocol stream.")
            data.extend(chunk)
            if len(data) > MAX_LINE:
                raise ResidentError("Resident inference exceeded its protocol message limit.")
            if b"\n" in data:
                if data.index(b"\n") != len(data) - 1:
                    raise ResidentError("Resident inference sent unexpected protocol output.")
                try:
                    message = json.loads(data.decode("utf-8"), object_pairs_hook=_object,
                                         parse_constant=_nonfinite, parse_float=_finite_float)
                except (ValueError, RecursionError):
                    raise ResidentError("Resident inference sent an invalid protocol message.") from None
                if type(message) is not dict or message.get("protocol") != PROTOCOL:
                    raise ResidentError("Resident inference sent an invalid protocol message.")
                self._check(process, deadline, output)
                return message

    def _write(self, process, job):
        remaining = memoryview(job.request)
        descriptor = process.stdin.fileno()
        while remaining:
            self._check(process, job.deadline, job.output)
            if select.select([], [descriptor], [], POLL_SECONDS)[1]:
                try:
                    remaining = remaining[os.write(descriptor, remaining):]
                except BlockingIOError:
                    continue

    def _serve(self, process):
        while True:
            self._check(process)
            # Any unsolicited stdout, including a partial line, is a protocol fault.
            if select.select([process.stdout], [], [], 0)[0]:
                raise ResidentError("Resident inference sent unexpected protocol output.")
            with self._condition:
                job = self._job
                if job is None:
                    self._condition.wait(POLL_SECONDS)
                    continue
            self._write(process, job)
            response = self._read(process, job.deadline, job.output)
            if (response.get("event") != "result" or response.get("id") != json.loads(job.request)["id"]
                    or type(response.get("ok")) is not bool
                    or set(response) - {"protocol", "event", "id", "ok", "constructors", "job_index", "resident_pid"}):
                raise ResidentError("Resident inference sent an invalid job response.")
            if not response["ok"]:
                raise ResidentError("Inference failed; the original capture has been retained.")
            with self._condition:
                self._job = None
                self._state = "stopped" if self._stopping.is_set() else "ready"
                job.pid = process.pid
                job.done.set()

    def _supervise(self):
        recovered = False
        while not self._stopping.is_set():
            process, warmed = None, False
            error = ResidentError("Resident inference failed; the original capture has been retained.")
            try:
                args = [*self.settings.resident_command, "--data-root", str(self.root)]
                if self.settings.allow_estimated_intrinsics:
                    args.append("--allow-estimated-intrinsics")
                if self.settings.allow_unverified_pinhole:
                    args.append("--allow-unverified-pinhole")
                deadline = time.monotonic() + self.settings.inference_timeout_seconds
                with self.store.lock if self.store is not None else nullcontext():
                    descriptors = self.store.resident_fds() if self.store is not None else ()
                    # Only Store.open(), after acquiring the inherited lease,
                    # may reconcile scratch from a previous service lifetime.
                    if self.warmup.exists() or self.warmup.is_symlink():
                        raise ResidentError("Resident warmup scratch is not owned by this worker.")
                    process = subprocess.Popen(args, cwd=self.settings.inference_cwd, env=child_environment(),
                                               start_new_session=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                               stderr=subprocess.DEVNULL, bufsize=0, pass_fds=descriptors)
                with self._condition:
                    self._process = process
                    self._invalidated = False
                os.set_blocking(process.stdin.fileno(), False)
                os.set_blocking(process.stdout.fileno(), False)
                message = self._read(process, deadline)
                if (message.get("event") != "ready" or message.get("warmup_complete") is not True
                        or set(message) - {"protocol", "event", "warmup_complete", "pid", "constructors", "warmup_seconds"}):
                    raise ResidentError("Resident inference did not complete warmup.")
                warmed = True
                with self._condition:
                    self._state = "stopped" if self._stopping.is_set() else "ready"
                self._serve(process)
            except Exception as exc:  # noqa: BLE001 - arbitrary child/OS errors stay private.
                if isinstance(exc, ResidentError):
                    error = exc
            finally:
                with self._condition:
                    self._state = "stopped" if self._stopping.is_set() else "failed"
                reaped = False
                try:
                    if process is not None:
                        stop_process(process)
                        reaped = True
                        for stream in (process.stdin, process.stdout):
                            try:
                                stream.close()
                            except Exception:  # noqa: BLE001 - static fatal cleanup status.
                                self._fatal_cleanup()
                        # Standalone test supervisors have no global lease;
                        # even an absent path at launch does not confer ownership.
                        if self.store is not None and self._cleanup_error is None:
                            remove_workspace(self.warmup)
                except Exception:  # noqa: BLE001 - never strand a caller on OS/cleanup failure.
                    self._fatal_cleanup()
                finally:
                    with self._condition:
                        if reaped:
                            self._process = None
                        if self._cleanup_error is not None:
                            self._state = "failed"
                        if self._job is not None:
                            self._job.error = self._cleanup_error or error
                            self._job.done.set()
                            self._job = None
                        self._condition.notify_all()
            if self._cleanup_error is not None or not warmed or recovered or self._stopping.is_set():
                break
            recovered = True
            with self._condition:
                self._state = "warming"
