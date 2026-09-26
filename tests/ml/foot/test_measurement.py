"""Synthetic geometry tests, not participant or Quest validation."""
import copy
import math
import json
from pathlib import Path
import unittest

from processing.analysis.foot.measurement import measure_standing


def sample():
    return {
        "patient_id": "00000000-0000-0000-0000-000000000001",
        "session_id": "00000000-0000-0000-0000-000000000002",
        "take_id": "00000000-0000-0000-0000-000000000003",
        "frame_id": 19,
        "pts_ns": "1000030001",
        "image_sha256": "a" * 64,
        "image_size_px": [640, 480],
        "side": "left",
        "view": "medial",
        "condition": "standing",
        "loading": "verified_50_percent_body_weight",
        "loading_record": "Synthetic fixture only: scale reading recorded separately.",
        "annotation_method": "manual",
        "annotator_id": "synthetic-rater",
        "geometry": "rectified_medial_plane_horizontal_support",
        "geometry_record": "Synthetic orthographic fixture; no camera validation.",
        "unamplified": True,
        "image_valid": True,
        "interrupted": False,
        "landmarks_px": {
            "posterior_heel": [100, 300],
            "hallux_tip": [500, 350],
            "dorsum_at_half_length": [300, 280],
        },
        "support_y_px": 400,
        "calibration": {
            "status": "calibrated",
            "start_px": [100, 420],
            "end_px": [300, 420],
            "length_mm": 100,
            "same_plane_verified": True,
            "record": "Synthetic 100 mm reference, not measured participant evidence.",
        },
        "reference_comparison": {"status": "not_performed"},
    }


class StandingMeasurementTests(unittest.TestCase):
    def test_known_height_and_provenance(self):
        data = sample()
        result = measure_standing(data)
        self.assertEqual(result["metric"]["value"], 60)
        self.assertEqual(result["metric"]["unit"], "mm")
        self.assertEqual(result["input"], data)
        self.assertEqual(result["feature"]["status"], "unavailable")
        self.assertEqual(result["validation_status"], "research_demo_unvalidated")
        self.assertEqual(result["measurement_origin"], "manual_landmarks")
        self.assertNotIn("confidence", result)
        self.assertNotIn("classification", result)
        data["landmarks_px"]["dorsum_at_half_length"][1] = 0
        self.assertEqual(result["input"]["landmarks_px"]["dorsum_at_half_length"][1], 280)

    def test_input_not_modified(self):
        data = sample()
        before = copy.deepcopy(data)
        measure_standing(data)
        self.assertEqual(data, before)

    def test_right_foot_and_mirrored_direction(self):
        data = sample()
        data["side"] = "right"
        points = data["landmarks_px"]
        points["posterior_heel"][0], points["hallux_tip"][0] = 500, 100
        self.assertEqual(measure_standing(data)["metric"]["value"], 60)

    def test_uniform_image_scaling_does_not_change_mm(self):
        data = sample()
        data["image_size_px"] = [1280, 960]
        for p in data["landmarks_px"].values():
            p[:] = [v * 2 for v in p]
        for key in ("start_px", "end_px"):
            data["calibration"][key] = [v * 2 for v in data["calibration"][key]]
        data["support_y_px"] *= 2
        self.assertEqual(measure_standing(data)["metric"]["value"], 60)

    def test_reference_comparison_is_not_invented(self):
        data = sample()
        data["reference_comparison"] = {
            "status": "provided", "method": "independent manual image measurement",
            "value_mm": 59, "record": "Synthetic comparison fixture only",
        }
        result = measure_standing(data)
        self.assertEqual(result["reference_difference_mm"], 1)
        self.assertNotIn("reference_difference_mm", measure_standing(sample()))

    def test_capture_gates(self):
        for key, value in {
            "side": "bilateral", "view": "front", "condition": "seated",
            "loading": "assumed_equal", "annotation_method": "body_pose",
            "geometry": "raw_headset_image", "unamplified": False,
            "image_valid": False, "interrupted": True,
        }.items():
            with self.subTest(key=key):
                data = sample()
                data[key] = value
                with self.assertRaises(ValueError):
                    measure_standing(data)

    def test_missing_fields(self):
        for key in sample():
            with self.subTest(key=key):
                data = sample()
                del data[key]
                with self.assertRaises(ValueError):
                    measure_standing(data)

    def test_unknown_fields_rejected(self):
        data = sample()
        data["display_scale"] = 2
        with self.assertRaises(ValueError):
            measure_standing(data)

    def test_bad_numeric_values(self):
        for value in (None, True, "120", math.nan, math.inf, -1, 480):
            with self.subTest(value=value):
                data = sample()
                data["support_y_px"] = value
                with self.assertRaises(ValueError):
                    measure_standing(data)

    def test_bad_landmarks(self):
        for points in (None, {}, {"ankle": [0, 0]}):
            data = sample()
            data["landmarks_px"] = points
            with self.assertRaises(ValueError):
                measure_standing(data)
        for point in (None, [1], [1, 2, 3], [True, 2], [math.nan, 2], [-1, 2], [640, 2]):
            data = sample()
            data["landmarks_px"]["posterior_heel"] = point
            with self.assertRaises(ValueError):
                measure_standing(data)

    def test_bad_geometry(self):
        for name, point in (("dorsum_at_half_length", [301, 280]),
                            ("dorsum_at_half_length", [300, 401]),
                            ("dorsum_at_half_length", [300, 400]),
                            ("posterior_heel", [500, 300]),
                            ("hallux_tip", [500, 401])):
            data = sample()
            data["landmarks_px"][name] = point
            with self.assertRaises(ValueError):
                measure_standing(data)

    def test_calibration_provenance_length_boundary(self):
        data = sample()
        data["calibration"]["record"] = "x" * 500
        self.assertEqual(
            measure_standing(data)["metric"]["scale_provenance"],
            data["calibration"]["record"],
        )
        data["calibration"]["record"] += "x"
        with self.assertRaises(ValueError):
            measure_standing(data)

    def test_calibration_gates(self):
        for key, value in (("status", "estimated"), ("same_plane_verified", False),
                           ("length_mm", 0), ("length_mm", math.inf),
                           ("length_mm", True), ("record", ""),
                           ("end_px", [100, 420])):
            data = sample()
            data["calibration"][key] = value
            with self.assertRaises(ValueError):
                measure_standing(data)

    def test_invalid_identity_time_image_metadata(self):
        for key, value in (("patient_id", "patient-name"), ("take_id", "../file"),
                           ("frame_id", True), ("frame_id", -1),
                           ("pts_ns", "1.5"), ("pts_ns", 123),
                           ("image_sha256", "unknown"), ("image_size_px", [0, 480]),
                           ("annotator_id", ""), ("geometry_record", ""),
                           ("loading_record", "")):
            data = sample()
            data[key] = value
            with self.assertRaises(ValueError):
                measure_standing(data)

    def test_serialization_preserves_large_pts_and_patient_separation(self):
        first = sample()
        first["pts_ns"] = "12345678901234567890"
        second = sample()
        second["patient_id"] = "00000000-0000-0000-0000-000000000004"
        a, b = measure_standing(first), measure_standing(second)
        self.assertEqual(json.loads(json.dumps(a, allow_nan=False)), a)
        self.assertNotEqual(a["input"]["patient_id"], b["input"]["patient_id"])
        b["input"]["calibration"]["record"] = "changed"
        self.assertNotEqual(a["input"]["calibration"], b["input"]["calibration"])

    def test_malformed_nested_metadata_and_overflow(self):
        for key, value in (("patient_id", 1), ("image_size_px", None),
                           ("calibration", None), ("reference_comparison", None),
                           ("support_y_px", 10 ** 1000)):
            data = sample()
            data[key] = value
            with self.assertRaises(ValueError):
                measure_standing(data)
        data = sample()
        data["calibration"]["length_mm"] = 1e308
        data["calibration"]["start_px"] = [0, 0]
        data["calibration"]["end_px"] = [1e-300, 0]
        with self.assertRaises(ValueError):
            measure_standing(data)
        for key, value in (("method", ""), ("value_mm", math.nan)):
            data = sample()
            data["reference_comparison"] = {
                "status": "provided", "method": "ruler", "value_mm": 60, "record": "fixture",
            }
            data["reference_comparison"][key] = value
            with self.assertRaises(ValueError):
                measure_standing(data)

    def test_method_artifact_matches_result_and_marks_automation_incomplete(self):
        path = Path(__file__).resolve().parents[3] / "processing/analysis/foot/method.json"
        method = json.loads(path.read_text())
        result = measure_standing(sample())
        self.assertEqual(method["method_id"], result["method_id"])
        self.assertEqual(method["version"], result["method_version"])
        self.assertEqual(method["automated_feature"], result["feature"])
        self.assertTrue(method["sources"])
        self.assertTrue(method["capture_requirements"])
        self.assertEqual(method["quest_validation"], "not_performed")

    def test_invalid_reference(self):
        for reference in ({}, {"status": "passed"},
                          {"status": "not_performed", "value_mm": 0},
                          {"status": "provided", "method": "ruler", "value_mm": -1, "record": "x"}):
            data = sample()
            data["reference_comparison"] = reference
            with self.assertRaises(ValueError):
                measure_standing(data)


if __name__ == "__main__":
    unittest.main()
