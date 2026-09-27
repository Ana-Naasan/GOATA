"""Run: python3 -m unittest discover -s tests/ml -v"""
import unittest
from copy import deepcopy

from processing.reconstruction.timing import map_selected_frames


class TimingTests(unittest.TestCase):
    def test_malformed_timing_and_selections_rejected(self):
        good = {"frame_id": 7, "pts_ns": "100", "image_valid": True}
        cases = [
            ([], []), ([good], [-1]), ([good], [True]), ([good], [1]),
            ([good], [0.0]), ([good, good], [0]),
            ([good, dict(good, frame_id=8, pts_ns="99")], [0]),
            ([good, dict(good, frame_id=8, pts_ns="101")], [1, 0]),
        ]
        for key, value in [("frame_id", True), ("frame_id", -1),
                           ("pts_ns", "1.0"), ("pts_ns", 100),
                           ("pts_ns", " 100"), ("pts_ns", "١٠٠"),
                           ("image_valid", 1)]:
            cases.append(([dict(good, **{key: value})], [0]))
        cases.extend([([{}], [0]), ([None], [0]), ([good], [] )])
        for frames, indices in cases:
            with self.subTest(frames=frames, indices=indices), self.assertRaises(ValueError):
                map_selected_frames(frames, indices)

    def test_invalid_containers_fields_and_unselected_frames(self):
        good = {"frame_id": 7, "pts_ns": "100", "image_valid": True}
        cases = []
        for invalid in (None, {}, "0", 0, {0}):
            cases.extend([(invalid, [0]), ([good], invalid)])
        for invalid in (False, None, "0", [], float("nan")):
            cases.append(([good], [invalid]))
        for field in good:
            incomplete = dict(good)
            del incomplete[field]
            cases.append(([incomplete], [0]))
        for field, values in {
            "frame_id": [None, "7", 7.0, []],
            "pts_ns": [None, True, "", "+100", "100\n", "1e2", "NaN", "--1"],
            "image_valid": [None, "false", 0],
        }.items():
            for value in values:
                cases.append(([dict(good, **{field: value})], [0]))
        cases.extend([
            ([good, dict(good, pts_ns="101")], [0]),  # Duplicate ID, new PTS.
            ([good, dict(good, frame_id=8)], [0]),  # Equal PTS, distinct ID.
            ([good, {}], [0]),  # Skipping a frame does not bypass validation.
            ([good, dict(good, frame_id=8, pts_ns="9" * 400)], [1]),
            ([good, dict(good, frame_id=8, pts_ns="9" * 400)], [0]),
        ])
        for frames, indices in cases:
            with self.subTest(frames=frames, indices=indices), self.assertRaises(ValueError):
                map_selected_frames(frames, indices)

    def test_exact_pts_and_origin_survive_skipping_first_invalid_frame(self):
        frames = [
            {"frame_id": 20, "pts_ns": "90071992547409930", "image_valid": False},
            {"frame_id": 3, "pts_ns": "90071992547409931", "image_valid": True},
            {"frame_id": 99, "pts_ns": "90071992547409937", "image_valid": False},
        ]
        original = deepcopy(frames)
        indices = [1, 2, 2]
        result = map_selected_frames(frames, indices)
        self.assertEqual(result, [
            {"inference_index": 0, "source_frame_id": 3,
             "source_pts_ns": "90071992547409931", "source_time_s": 1e-9,
             "image_valid": True},
            {"inference_index": 1, "source_frame_id": 99,
             "source_pts_ns": "90071992547409937", "source_time_s": 7e-9,
             "image_valid": False},
            {"inference_index": 2, "source_frame_id": 99,
             "source_pts_ns": "90071992547409937", "source_time_s": 7e-9,
             "image_valid": False},
        ])
        self.assertEqual(frames, original)
        self.assertEqual(indices, [1, 2, 2])
        result[1]["image_valid"] = True
        self.assertFalse(result[2]["image_valid"])
        self.assertEqual(frames, original)

    def test_signed_pts_and_tuple_inputs(self):
        frames = (
            {"frame_id": 0, "pts_ns": "-0002", "image_valid": False},
            {"frame_id": 1, "pts_ns": "0", "image_valid": True},
        )
        result = map_selected_frames(frames, (0, 1))
        self.assertEqual(result[0]["source_pts_ns"], "-0002")
        self.assertEqual(result[1]["source_time_s"], 2e-9)

    def test_single_frame_repetition(self):
        frame = {"frame_id": 42, "pts_ns": "00100", "image_valid": False}
        result = map_selected_frames([frame], [0, 0])
        self.assertEqual([row["inference_index"] for row in result], [0, 1])
        self.assertTrue(all(row["source_pts_ns"] == "00100" for row in result))
        self.assertTrue(all(row["source_time_s"] == 0 for row in result))
        self.assertTrue(all(row["image_valid"] is False for row in result))

    def test_irregular_pts_repetition_and_rejection_preserve_source(self):
        frames = [
            {"frame_id": 10, "pts_ns": "90071992547409930", "image_valid": True},
            {"frame_id": 12, "pts_ns": "90071992567409930", "image_valid": False},
            {"frame_id": 15, "pts_ns": "90071992637409930", "image_valid": True},
        ]
        result = map_selected_frames(frames, [0, 0, 2])
        self.assertEqual([r["source_frame_id"] for r in result], [10, 10, 15])
        self.assertEqual([r["source_time_s"] for r in result], [0.0, 0.0, 0.09])
        self.assertEqual(result[2]["source_pts_ns"], frames[2]["pts_ns"])
        self.assertEqual(result[2]["inference_index"], 2)
        self.assertEqual(map_selected_frames(frames, [1])[0]["image_valid"], False)
        self.assertEqual(frames[0]["frame_id"], 10)
