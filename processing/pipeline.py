"""One local GPU subprocess, verified native export and honest feature status."""

import os
import shutil
import signal
import stat
import struct
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from processing.contracts import read_json_file
from processing.export import artifact, export_native, write_json
from processing.media_timing import validate_media_mapping
from processing.storage import now


class PipelineError(RuntimeError):
    """Only static, safe messages from this module may cross the worker boundary."""


def _workspace_budget(path, limit):
    if not path.exists() and not path.is_symlink():
        return
    pending, total, entries = [path], 0, 0
    while pending:
        current = pending.pop()
        details = current.lstat()
        entries += 1
        if entries > 128:
            raise PipelineError("Inference output exceeds its file-count budget.")
        if stat.S_ISLNK(details.st_mode):
            raise PipelineError("Inference produced linked output; it cannot be published.")
        if stat.S_ISDIR(details.st_mode):
            pending.extend(current.iterdir())
        elif stat.S_ISREG(details.st_mode):
            total += details.st_size
        else:
            raise PipelineError("Inference produced an unsupported output file.")
        if total > limit:
            raise PipelineError("Inference output exceeds its storage budget.")


def _stop(process):
    # The worker owns the new process group, including decoder/model children.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _validate_capture_encoding(metadata):
    if metadata.get("adapter") == {
        "name": "Meta.MRUK.PassthroughCameraAccess/HTH.AndroidMediaCodec", "version": "85.0.0/1"
    }:
        raise PipelineError("This recording was saved upside down by an earlier app version. "
                            "Update the app and record a new test. The original recordings are retained.")


def run_inference(video, sidecar, destination, settings):
    """Run an operator-configured local CLI, never a shell or remote transport."""
    if not settings.inference_command:
        raise PipelineError("Real inference is not configured; the original capture has been retained.")
    metadata = read_json_file(sidecar, max_bytes=settings.limits.max_metadata_bytes)
    _validate_capture_encoding(metadata)
    media = metadata.get("media")
    if media is None:
        raise PipelineError("Capture has no verified media timestamp mapping; inference cannot bind source evidence.")
    validate_media_mapping(media, len(metadata.get("frames", media["presentation_time_us"])))
    args = [*settings.inference_command, "--video", str(video.resolve()), "--sidecar", str(sidecar.resolve()),
            "--output", str(destination.resolve()), "--pts-offset-ns", "0"]
    if settings.allow_estimated_intrinsics:
        args.append("--allow-estimated-intrinsics")
    if settings.allow_unverified_pinhole:
        args.append("--allow-unverified-pinhole")
    environment = {key: value for key, value in os.environ.items() if key != "PROCESSING_TOKEN"}
    root = str(Path(__file__).resolve().parent.parent)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (root, environment.get("PYTHONPATH"))))
    started = time.monotonic()
    # DEVNULL prevents a faulty decoder from filling memory/disk with logs.
    with subprocess.Popen(args, cwd=settings.inference_cwd, env=environment, start_new_session=True,
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
        try:
            while process.poll() is None:
                _workspace_budget(destination, settings.inference_workspace_bytes)
                if time.monotonic() - started > settings.inference_timeout_seconds:
                    raise PipelineError("Inference exceeded its processing deadline; retain the capture and retry after investigation.")
                time.sleep(.05)
            _workspace_budget(destination, settings.inference_workspace_bytes)
            if process.returncode:
                raise PipelineError("Inference failed; the original capture has been retained.")
        finally:
            _stop(process)


def _unavailable(test_type):
    if test_type == "barefoot":
        return {"name": "foot", "status": "unavailable", "detail":
                "Automated foot assessment is incomplete. Manual standing dorsal-height geometry requires verified anatomical annotations, loading and calibration; none are supplied by this capture."}
    if test_type == "walking":
        return {"name": "movement", "status": "unavailable", "detail":
                "Clinical gait assessment is unavailable: walking observations describe estimated geometry only. No validated gait classifier, step timing or calibrated distance measurements are installed."}
    return {"name": "movement", "status": "unavailable", "detail":
            "Exercise assessment is incomplete: no held-out evaluated Quest-compatible ELK/RTK classifier is installed. A reconstructed body and an empty findings list do not establish a correct repetition."}


def _observations(replay, output, test_type, sidecar, limits):
    feature = {"name": "observations", "status": "unavailable",
               "detail": "Estimated movement observations require a supported full-body replay."}
    if replay is None or test_type == "barefoot":
        return {"observations": [], "methods": [], "artifacts": [], "feature": feature}
    from processing.analysis.observations import (
        METHOD_ID,
        METHOD_VERSION,
        generate_observations,
    )

    binary = replay["artifacts"]["skeleton_joints"]
    path = output / binary["filename"]
    expected = replay["frame_count"] * replay["joint_count"] * 12
    if path.is_symlink() or path.stat().st_size != expected or expected > limits.max_output_bytes:
        raise PipelineError("Observation geometry exceeds validated bounds.")
    with path.open("rb") as stream:
        raw = stream.read(expected + 1)
    if len(raw) != expected:
        raise PipelineError("Observation geometry changed after export.")
    points = list(struct.iter_unpack("<3f", raw))
    width = replay["joint_count"]
    rows = [points[index:index + width] for index in range(0, len(points), width)]
    observations, settings = generate_observations(replay, rows, test_type, sidecar)
    settings_id = str(uuid4())
    write_json(output / settings_id, settings, limits.max_metadata_bytes)
    reasons = list(dict.fromkeys(item["reason"] for item in settings["unavailable_quantities"]))
    detail = ("Estimated angles from the selected recording are available. These are model estimates, not clinical findings."
              if observations else "No eligible pose geometry. " + " ".join(reasons))
    return {"observations": observations,
            "feature": {**feature, "status": "available" if observations else "unavailable", "detail": detail[:500]},
            "methods": [{"method_id": METHOD_ID, "name": "Estimated pose geometry", "version": METHOD_VERSION,
                         "settings_artifact_id": settings_id}],
            "artifacts": [artifact(output / settings_id, "processing_settings", "application/json")]}


class Pipeline:
    """The service's single worker owns invocation, result identity and cleanup."""

    def __init__(self, settings, microscope=None):
        self.settings = settings
        self.microscope = microscope

    def __call__(self, inputs, output, capture, job, stage):
        started = time.monotonic()
        stage("preparing_recording")
        sources = {take["take_id"]: (take, read_json_file(inputs / "files" / take["frame_metadata"]["member"],
                                                        max_bytes=self.settings.limits.max_metadata_bytes))
                   for take in capture["takes"]}
        for _take, sidecar in sources.values():
            _validate_capture_encoding(sidecar)
        result_id, settings_id = str(uuid4()), str(uuid4())
        native = output / "native.tmp"
        replay_take = capture.get("replay_take_id")
        try:
            if replay_take:
                take, _sidecar = sources[replay_take]
                if take["kind"] != "full_body":
                    raise PipelineError("Replay requires a full-body source take.")
                stage("estimating_movement")
                run_inference(inputs / "files" / take["video"]["member"],
                              inputs / "files" / take["frame_metadata"]["member"], native, self.settings)
            stage("analysing_test")
            microscopes = self._microscopes(inputs, output, sources)
            stage("preparing_replay")
            replay, artifacts, provenance = None, [], {}
            if replay_take:
                replay, artifacts, provenance = export_native(native, output, *sources[replay_take],
                                                              result_id, self.settings.limits,
                                                              allow_unverified_pinhole=self.settings.allow_unverified_pinhole)
            observations = _observations(replay, output, capture["test_type"],
                                         sources[replay_take][1] if replay_take else None, self.settings.limits)
            record = {"pipeline_version": "gvhmr-unity-2", "capture_to_loaded_latency": "Not measured by the service.",
                      "processing_elapsed_seconds": time.monotonic() - started, "reconstruction": provenance,
                      "assessment": _unavailable(capture["test_type"])}
            write_json(output / settings_id, record, self.settings.limits.max_metadata_bytes)
            methods = [{"method_id": "capture_processing", "name": "GVHMR native export and capture evidence",
                        "version": "1", "settings_artifact_id": settings_id}]
            features = [_unavailable(capture["test_type"]), microscopes["feature"], observations["feature"]]
            if replay_take:
                features = [{"name": "replay", "status": "available", "detail":
                             "Estimated body and skeleton from the selected source take. Model scale and world orientation are uncalibrated; clinical accuracy is unvalidated."}, *features]
            result = {
                "schema_version": "1.1", "result_id": result_id,
                **{key: job[key] for key in ("job_id", "session_id", "patient_id", "test_type", "input_digest")},
                **{key: capture[key] for key in ("protocol_id", "protocol_version")},
                "created_at": now(), "pipeline_version": "gvhmr-unity-2", "validation_status": "research_demo_unvalidated",
                "methods": methods + microscopes["methods"] + observations["methods"],
                "features": features, "findings": [], "observations": observations["observations"],
                "microscopes": microscopes["microscopes"],
                "artifacts": artifacts + microscopes["artifacts"] + observations["artifacts"] + [artifact(output / settings_id, "processing_settings", "application/json")],
            }
            if replay is not None:
                result["replay"] = {"source_take_id": replay_take, "manifest_artifact_id": artifacts[0]["artifact_id"]}
            return result
        finally:
            shutil.rmtree(native, ignore_errors=True)

    def _microscopes(self, inputs, output, sources):
        if self.microscope is None:
            from processing.microscope import process_microscope
            processor = process_microscope
        else:
            processor = self.microscope
        outputs = []
        for take, sidecar in sources.values():
            used = sum(item["byte_size"] for result in outputs for item in result["artifacts"])
            outputs.append(processor(inputs / "files" / take["video"]["member"], sidecar, output,
                                     max_output_bytes=self.settings.limits.max_output_bytes - used))
        available = any(result["feature"]["status"] == "available" for result in outputs)
        return {"feature": {"name": "microscope", "status": "available" if available else "unavailable",
                            "detail": "Source-labelled original and amplified recording regions are available; magnification can amplify artifacts."
                            if available else outputs[0]["feature"]["detail"]},
                **{key: [item for result in outputs for item in result[key]] for key in ("methods", "microscopes", "artifacts")}}
