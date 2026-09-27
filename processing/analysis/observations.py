"""Source-linked geometric pose estimates, without clinical classification.

Call only after validating the exported replay and its skeleton binary. Geometry
is the original Unity-converted model output; never pass display-scaled or
amplified coordinates. These checks establish numerical consistency, not joint
visibility, anatomical accuracy, normal movement or clinical validity.
"""

import math
from copy import deepcopy
from uuid import uuid4

from processing.contracts import (
    _require,
    _schema_validate,
    _validate_parents,
    _validate_replay_timing,
    validate_sidecar,
)
from processing.reconstruction.native import MAX_FRAMES
from processing.reconstruction.runtime import MAX_INFERENCE_FRAMES

METHOD_ID = "pose-geometry-v1"
METHOD_VERSION = "1.0.0"
_TORSO = ("left_hip", "right_hip", "left_shoulder", "right_shoulder")
_QUALITY = "Joint visibility and anatomical accuracy are unvalidated; finite fitted joints are not visibility scores."
_LIMITATIONS = (
    _QUALITY,
    "Gravity, camera motion and body fitting are model estimates; no clinical reference comparison was performed.",
    "The peak covers eligible reconstructed source frames only. Missing frames are excluded and never interpolated.",
)


def _specifications(test_type):
    # Each tuple fixes the quantity, side, required joints, operation and meaning.
    if test_type == "elk":
        return [("elk.lateral_torso_lean", "not_applicable", _TORSO, "lateral",
                 "Estimated lateral torso lean",
                 ("Signed torso lean at the greatest absolute lateral lean, positive toward anatomical left. "
                  "Hip-to-shoulder midpoint direction is projected onto estimated upright and the horizontal hip axis. "
                  "This describes fitted torso orientation, not lumbar or vertebral motion."))]
    if test_type == "rtk":
        return [("rtk.shoulder_pelvis_rotation", "not_applicable", _TORSO, "rotation",
                 "Estimated shoulder-to-pelvis rotation",
                 ("Largest absolute shortest angle (0 to 180 degrees) between horizontal shoulder and hip axes. "
                  "This is fitted relative orientation at one frame, not accumulated rotation or lumbar motion."))]
    _require(test_type == "walking", "Unsupported observation test type")
    knees = [("walking.knee_flexion", side,
              (f"{side}_hip", f"{side}_knee", f"{side}_ankle"), "knee",
              f"Estimated {side} knee bending",
              ("Largest geometric 3D hip-knee-ankle bending angle: 180 degrees minus the included angle, "
               "with a straight leg at zero. This is a model-joint estimate, not a clinical anatomical knee measurement."))
             for side in ("left", "right")]
    return knees + [("walking.trunk_lean", "not_applicable", _TORSO, "inclination",
                     "Estimated trunk inclination",
                     ("Largest unsigned angle between the hip-to-shoulder midpoint direction and estimated upright. "
                      "This describes fitted torso inclination and does not establish walking direction or lumbar motion."))]


def _sequence(value, count, message):
    _require(type(value) in (list, tuple) and len(value) == count, message)


def _bounded_inputs(manifest, joint_rows, sidecar):
    _require(type(manifest) is dict and type(sidecar) is dict, "Expected replay and sidecar objects")
    count, joints = manifest.get("frame_count"), manifest.get("joint_count")
    _require(type(count) is int and 1 <= count <= MAX_INFERENCE_FRAMES, "Observation frame count exceeds bounds")
    _require(type(joints) is int and 1 <= joints <= 256, "Observation joint count exceeds bounds")
    _sequence(joint_rows, count, "Joint frame count mismatch")
    for row in joint_rows:
        _sequence(row, joints, "Joint row width mismatch")
        for point in row:
            _sequence(point, 3, "Joint coordinate width mismatch")
            for value in point:
                try:
                    valid = type(value) in (int, float) and math.isfinite(value)
                except OverflowError:
                    valid = False
                _require(valid, "Joint coordinates must be finite numbers, not booleans")
    for key in ("frame_times_s", "source_frame_ids", "source_pts_ns", "frame_valid", "joint_valid"):
        _sequence(manifest.get(key), count, "Replay frame metadata count mismatch")
    for key in ("joint_names", "joint_parents"):
        _sequence(manifest.get(key), joints, "Replay joint metadata count mismatch")
    for row in manifest["joint_valid"]:
        _sequence(row, joints, "Replay joint validity width mismatch")
    for key, limit in (("gaps", count), ("resampling_map", MAX_INFERENCE_FRAMES)):
        value = manifest.get(key)
        _require(type(value) is list and len(value) <= limit, "Replay timing metadata exceeds bounds")
    frames = sidecar.get("frames")
    _require(type(frames) is list and 1 <= len(frames) <= MAX_FRAMES, "Source frames exceed bounds")
    capture = sidecar.get("capture")
    _require(type(capture) is dict and type(capture.get("gaps")) is list
             and len(capture["gaps"]) <= MAX_FRAMES, "Capture gaps exceed bounds")


def _source_frames(manifest, joint_rows, sidecar):
    _bounded_inputs(manifest, joint_rows, sidecar)
    _schema_validate(manifest, "replay_manifest.schema.json")
    _validate_parents(manifest)
    _validate_replay_timing(manifest)
    validate_sidecar(sidecar)
    _require(manifest["source_take_id"] == sidecar["take_id"], "Observation source take mismatch")
    _require(manifest["source_clock"] == sidecar["clock"], "Observation source clock mismatch")
    source = {frame["frame_id"]: frame for frame in sidecar["frames"]}
    frames = []
    for frame_id, pts in zip(manifest["source_frame_ids"], manifest["source_pts_ns"]):
        original = source.get(frame_id)
        _require(original is not None and original["pts_ns"] == pts, "Observation source frame binding mismatch")
        frames.append(original)
    return frames


def _unit(vector):
    length = math.hypot(*vector)
    return tuple(value / length for value in vector) if math.isfinite(length) and length > 0 else None


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _mid(a, b):
    return tuple(x / 2 + y / 2 for x, y in zip(a, b))


def _horizontal(vector):
    unit = _unit(vector)
    if unit is None or math.hypot(unit[0], unit[2]) < 1e-6:
        return None
    return _unit((unit[0], 0, unit[2]))


def _measure(operation, points):
    if operation == "knee":
        hip, knee, ankle = points
        a, b = _unit(_sub(hip, knee)), _unit(_sub(ankle, knee))
        if a is None or b is None:
            return None
        cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
        return 180 - math.degrees(math.atan2(math.hypot(*cross), _dot(a, b)))
    left_hip, right_hip, left_shoulder, right_shoulder = points
    torso = _unit(_sub(_mid(left_shoulder, right_shoulder), _mid(left_hip, right_hip)))
    if torso is None:
        return None
    if operation == "inclination":
        return math.degrees(math.atan2(math.hypot(torso[0], torso[2]), torso[1]))
    hip_axis = _horizontal(_sub(left_hip, right_hip))
    if hip_axis is None:
        return None
    if operation == "lateral":
        lateral, upright = _dot(torso, hip_axis), torso[1]
        return math.degrees(math.atan2(lateral, upright)) if math.hypot(lateral, upright) >= 1e-6 else None
    shoulder_axis = _horizontal(_sub(left_shoulder, right_shoulder))
    if shoulder_axis is None:
        return None
    # Absolute shortest yaw is invariant to the exporter's Z reflection. Do not
    # interpret the Unity cross-product sign as anatomical rotation direction.
    cross = hip_axis[0] * shoulder_axis[2] - hip_axis[2] * shoulder_axis[0]
    return math.degrees(math.atan2(abs(cross), _dot(hip_axis, shoulder_axis)))


def _quantity(spec, manifest, joint_rows, frames, sidecar):
    code, side, required, operation, label, explanation = spec
    info = {"quantity_code": code, "side": side, "definition": explanation,
            "statistic": "signed value at maximum absolute sample" if operation == "lateral" else "maximum sample",
            "valid_sample_count": 0, "rejected_sample_count": manifest["frame_count"]}
    names = manifest["joint_names"]
    if not set(required) <= set(names):
        return None, info, "Required named joints are missing from the replay."
    if sidecar["capture"]["interrupted"]:
        return None, info, "The source capture was interrupted."
    allowed = ("exercise",) if code.startswith("walking.") else ("seated", "exercise")
    if sidecar["capture"]["condition"] not in allowed:
        return None, info, "Source capture condition does not support this test."
    indices = [names.index(name) for name in required]
    samples = []
    for index, (row, original) in enumerate(zip(joint_rows, frames)):
        if (not original["image_valid"] or not manifest["frame_valid"][index]
                or not all(manifest["joint_valid"][index][joint] for joint in indices)):
            continue
        value = _measure(operation, [row[joint] for joint in indices])
        if value is not None and math.isfinite(value):
            samples.append((index, value))
    info = {**info, "valid_sample_count": len(samples), "rejected_sample_count": len(frames) - len(samples)}
    if not samples:
        return None, info, "No original valid frame has all required joints and nondegenerate geometry."
    index, value = max(samples, key=lambda item: abs(item[1]))  # First source frame wins equal peaks.
    timestamp, frame_id = manifest["frame_times_s"][index], manifest["source_frame_ids"][index]
    limitations = list(_LIMITATIONS)
    if manifest["synthetic"]:
        limitations.append("Synthetic mechanics fixture; this is not a participant measurement.")
    observation = {
        "observation_id": str(uuid4()), "method_id": METHOD_ID, "quantity_code": code,
        "label": label, "explanation": explanation, "region": "knee" if operation == "knee" else "torso",
        "side": side, "limitations": limitations, "highlight_joint_names": list(required),
        "evidence": {"take_id": sidecar["take_id"], "start_s": timestamp, "end_s": timestamp,
                     "first_frame_id": frame_id, "last_frame_id": frame_id,
                     "condition": sidecar["capture"]["condition"], "quality": "limited", "quality_reason": _QUALITY},
        "metrics": [{"name": info["statistic"], "value": value, "unit": "deg", "basis": "pose_estimate",
                     "scale_status": "not_required"}],
    }
    return observation, {**info, "peak_source_frame_id": frame_id}, None


def generate_observations(manifest, joint_rows, test_type, sidecar):
    """Return (observations, method settings) from one validated exported take.

    Inputs are never modified. joint_rows is a bounded frame-major sequence of
    joint XYZ triples, already converted once into Unity coordinates. Peak
    evidence is one exact valid source frame. There is no temporal interpolation,
    gap bridging, threshold classification, calibrated confidence or diagnosis.
    Malformed/badly bound input raises ValueError; missing support gives explicit
    unavailable quantity reasons. The caller publishes settings as an artifact.
    """
    specs = _specifications(test_type)
    frames = _source_frames(manifest, joint_rows, sidecar)
    observations, quantities, unavailable = [], [], []
    for spec in specs:
        observation, info, reason = _quantity(spec, manifest, joint_rows, frames, sidecar)
        quantities.append(info)
        if observation is not None:
            observations.append(observation)
        else:
            unavailable.append({"quantity_code": spec[0], "side": spec[1], "reason": reason})
    settings = {
        "method_id": METHOD_ID, "method_version": METHOD_VERSION,
        "validation_status": "research_demo_unvalidated", "test_type": test_type,
        "source_take_id": sidecar["take_id"], "source_view": sidecar["capture"]["view"],
        "source_model": deepcopy(manifest["model"]), "synthetic": manifest["synthetic"],
        "coordinate_system": manifest["coordinate_system"],
        "input": "Original exported model joints; no display transform, smoothing or magnification.",
        "quality": _QUALITY, "quantities": quantities, "unavailable_quantities": unavailable,
        "peak_policy": "Greatest absolute eligible sample; ties keep first source frame. No temporal interpolation.",
        "projection_minimum_norm": 1e-6,
    }
    return observations, settings
