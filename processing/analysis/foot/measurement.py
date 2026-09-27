"""Manual standing dorsal-height geometry; no image inference or diagnosis.

Adapted from McPoil et al., 2008, doi:10.1186/1757-1146-1-3,
Methods / Procedures. This computes one annotation, not their three-reading
average or sit-to-stand protocol. See method.json for evidence and restrictions.
The caller must verify annotations, rectification, loading and calibration.
Metadata assertions do not establish those physical facts.
"""
import math
import re
from copy import deepcopy
from uuid import UUID

_FIELDS = {"patient_id", "session_id", "take_id", "frame_id", "pts_ns", "image_sha256", "image_size_px", "side", "view", "condition", "loading", "loading_record", "annotation_method", "annotator_id", "geometry", "geometry_record", "unamplified", "image_valid", "interrupted", "landmarks_px", "support_y_px", "calibration", "reference_comparison"}


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("Missing or unknown fields")


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError("Expected nonempty text of at most 1000 characters")


def _number(value):
    if type(value) not in (int, float):
        raise ValueError("Expected a finite number, not a boolean")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("Expected a finite number")
    return value


def measure_standing(data):
    """Return a manual measurement and its complete input provenance.

    Coordinates are pixels in an unamplified, rectified medial image, x right,
    y down, with a horizontal support line. Supply actual visible anatomical
    points, not model joints. Only scalar, same-plane calibration is supported.
    UUID/time/hash references must also be checked against the owning session
    and original frame sidecar by the caller. No files or patient store accessed.
    """
    _keys(data, _FIELDS)
    for key in ("patient_id", "session_id", "take_id"):
        if not isinstance(data[key], str):
            raise ValueError("Expected UUID string")  # noqa: TRY004 - malformed external metadata uses ValueError
        try:
            valid = str(UUID(data[key])) == data[key]
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Expected canonical UUID")
    if type(data["frame_id"]) is not int or data["frame_id"] < 0:
        raise ValueError("Expected original nonnegative frame ID")
    if not isinstance(data["pts_ns"], str) or not re.fullmatch(r"[0-9]{1,30}", data["pts_ns"]):
        raise ValueError("Expected original PTS as decimal nanosecond string")
    if not isinstance(data["image_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", data["image_sha256"]):
        raise ValueError("Expected source image SHA-256")
    size = data["image_size_px"]
    if not isinstance(size, (list, tuple)) or len(size) != 2 or any(
        type(v) is not int or not 0 < v <= 32768 for v in size
    ):
        raise ValueError("Expected image dimensions within 32768 pixels per axis")
    width, height = size

    def point(value):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("Expected two pixel coordinates")
        x, y = map(_number, value)
        if not 0 <= x < width or not 0 <= y < height:
            raise ValueError("Point outside image")
        return x, y

    if data["side"] not in ("left", "right"):
        raise ValueError("Expected one identified foot")
    for key, required in {
        "view": "medial", "condition": "standing",
        "loading": "verified_50_percent_body_weight", "annotation_method": "manual",
        "geometry": "rectified_medial_plane_horizontal_support",
    }.items():
        if data[key] != required:
            raise ValueError(f"Unsupported {key}")
    for key, required in (("unamplified", True), ("image_valid", True), ("interrupted", False)):
        if data[key] is not required:
            raise ValueError(f"Ineligible {key}")
    for key in ("loading_record", "annotator_id", "geometry_record"):
        _text(data[key])

    landmarks = data["landmarks_px"]
    _keys(landmarks, ("posterior_heel", "hallux_tip", "dorsum_at_half_length"))
    heel, hallux, dorsum = (point(landmarks[k]) for k in
                           ("posterior_heel", "hallux_tip", "dorsum_at_half_length"))
    support = _number(data["support_y_px"])
    if not 0 <= support < height or any(p[1] > support for p in (heel, hallux, dorsum)):
        raise ValueError("Invalid support line or point below support")
    if heel[0] == hallux[0] or dorsum[1] >= support:
        raise ValueError("Degenerate foot length or dorsal height")
    # Numerical consistency only, not an anatomical tolerance or quality score.
    if not math.isclose(dorsum[0], (heel[0] + hallux[0]) / 2, rel_tol=0, abs_tol=1e-9):
        raise ValueError("Dorsum must be annotated at half projected heel-to-hallux length")

    calibration = data["calibration"]
    _keys(calibration, ("status", "start_px", "end_px", "length_mm", "same_plane_verified", "record"))
    if calibration["status"] != "calibrated" or calibration["same_plane_verified"] is not True:
        raise ValueError("Measured same-plane calibration required")
    _text(calibration["record"])
    if len(calibration["record"]) > 500:
        raise ValueError("Calibration provenance must be at most 500 characters")
    length = _number(calibration["length_mm"])
    pixels = math.dist(point(calibration["start_px"]), point(calibration["end_px"]))
    if length <= 0 or pixels <= 0:
        raise ValueError("Calibration length must be positive")
    value = _number((support - dorsum[1]) * (length / pixels))
    if value <= 0:
        raise ValueError("Unrepresentable height")

    comparison = data["reference_comparison"]
    if not isinstance(comparison, dict):
        raise ValueError("Explicit reference comparison status required")  # noqa: TRY004 - malformed external metadata uses ValueError
    difference = None
    if comparison.get("status") == "not_performed":
        _keys(comparison, ("status",))
    else:
        _keys(comparison, ("status", "method", "value_mm", "record"))
        if comparison["status"] != "provided":
            raise ValueError("Unsupported reference comparison status")
        _text(comparison["method"])
        _text(comparison["record"])
        reference = _number(comparison["value_mm"])
        if reference <= 0:
            raise ValueError("Reference height must be positive")
        difference = _number(value - reference)

    result = {
        "method_id": "manual_standing_dorsal_height", "method_version": "0.1.0",
        "measurement_origin": "manual_landmarks",
        "validation_status": "research_demo_unvalidated",
        "input": deepcopy(data),
        "metric": {
            "name": "standing_dorsal_height_at_half_foot_length", "value": value,
            "unit": "mm", "basis": "image_measurement", "scale_status": "calibrated",
            "scale_provenance": calibration["record"],
        },
        "feature": {
            "name": "foot", "status": "unavailable",
            "detail": "Automated foot assessment incomplete. Only geometry from manually supplied anatomical points is implemented; Quest capture and reference validation remain unverified.",
        },
        "limitations": [
            "One static standing annotation, not gait, navicular height or plantar arch clearance.",
            "No automatic landmark extraction, classification, confidence or treatment advice.",
            "Calibration, rectification, anatomy and loading are caller-verified assertions.",
            "Not the study's repeated-reading average or complete sit-to-stand protocol.",
            "Study validity and numerical unit tests do not validate this Quest adaptation.",
        ],
    }
    if difference is not None:
        result["reference_difference_mm"] = difference
    return result
