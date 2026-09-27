"""Authored geometry checks; these are not clinical or camera accuracy tests."""

import copy
import math
import unittest
from uuid import UUID

from processing.analysis.observations import METHOD_ID, generate_observations


def sample():
    names = ["left_hip", "right_hip", "left_shoulder", "right_shoulder",
             "left_knee", "right_knee", "left_ankle", "right_ankle"]
    pose = [[-.2, 1, 0], [.2, 1, 0], [-.3, 2, 0], [.3, 2, 0],
            [-.2, .5, 0], [.2, .5, 0], [-.2, 0, 0], [.2, 0, 0]]
    ids, pts = [11, 17, 21], ["1000000000", "1100000000", "1200000000"]
    clock = {"id": "authored", "unit": "nanoseconds", "origin_pts_ns": pts[0]}
    take = "00000000-0000-0000-0000-000000000001"
    sidecar = {
        "schema_version": "1.0", "take_id": take,
        "adapter": {"name": "synthetic", "version": "1"},
        "image": {"width_px": 640, "height_px": 480, "rotation_degrees": 0, "mirrored": False},
        "camera": {"id": "synthetic", "calibration_status": "unavailable"},
        "clock": clock, "frames": [{"frame_id": i, "pts_ns": p, "image_valid": True}
                                  for i, p in zip(ids, pts)],
        "capture": {"view": "right", "condition": "exercise", "side": "bilateral",
                    "interrupted": False, "gaps": []},
    }
    manifest = {
        "schema_version": "1.0", "result_id": take, "source_take_id": take, "synthetic": True,
        "model": {"name": "authored", "revision": "1", "topology_revision": "1"},
        "frame_count": 3, "vertex_count": 3, "triangle_count": 1, "joint_count": len(names),
        "joint_names": names, "joint_parents": [-1] + [0] * (len(names) - 1),
        "joint_regions": {"body": names}, "frame_times_s": [0, .1, .2],
        "source_frame_ids": ids, "source_pts_ns": pts, "source_clock": clock,
        "frame_valid": [True] * 3, "joint_valid": [[True] * len(names) for _ in ids], "gaps": [],
        "coordinate_system": "unity_left_handed_y_up_z_forward", "units": "metres",
        "scale_status": "estimated", "scale_provenance": "Authored; not physical calibration",
        "source_coordinate_system": "gvhmr_global_ay",
        "source_to_replay": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1],
        "resampling_map": [],
        "artifacts": {role: {"artifact_id": take, "filename": filename, "byte_size": 1,
                             "sha256": "a" * 64, "encoding": encoding}
                      for role, filename, encoding in (
                          ("mesh_triangles", "mesh_triangles.u32", "uint32_le"),
                          ("mesh_vertices", "mesh_vertices.f32", "float32_le_frame_major_xyz"),
                          ("skeleton_joints", "skeleton_joints.f32", "float32_le_frame_major_xyz"))},
    }
    return manifest, [copy.deepcopy(pose) for _ in ids], sidecar


def run(data, test="walking"):
    manifest, rows, sidecar = data
    return generate_observations(manifest, rows, test, sidecar)


def values(observations):
    return {(o["quantity_code"], o["side"]): o["metrics"][0]["value"] for o in observations}


class ObservationTests(unittest.TestCase):
    def test_straight_walking_pose_and_limited_provenance(self):
        observations, settings = run(sample())
        self.assertEqual(values(observations), {
            ("walking.knee_flexion", "left"): 0,
            ("walking.knee_flexion", "right"): 0,
            ("walking.trunk_lean", "not_applicable"): 0})
        for observation in observations:
            UUID(observation["observation_id"])
            self.assertEqual(observation["method_id"], METHOD_ID)
            self.assertEqual(observation["evidence"]["quality"], "limited")
            self.assertIn("visibility", observation["evidence"]["quality_reason"])
            self.assertEqual(observation["metrics"][0]["basis"], "pose_estimate")
            self.assertEqual(observation["metrics"][0]["scale_status"], "not_required")
            self.assertEqual(observation["metrics"][0]["unit"], "deg")
            self.assertNotIn("confidence", observation)
        self.assertTrue(settings["synthetic"])
        self.assertEqual(settings["unavailable_quantities"], [])

    def test_knees_have_independent_peaks_and_original_frames(self):
        data = sample()
        data[1][1][6] = [-.2, .5, -.5]  # 90-degree left knee, original frame 17.
        data[1][2][7] = [.2, .5 - math.sqrt(3) / 4, .25]  # 30-degree right knee.
        observations, _ = run(data)
        knees = {o["side"]: o for o in observations if o["quantity_code"] == "walking.knee_flexion"}
        for side, value, frame, time in (("left", 90, 17, .1), ("right", 30, 21, .2)):
            self.assertAlmostEqual(knees[side]["metrics"][0]["value"], value)
            evidence = knees[side]["evidence"]
            self.assertEqual(evidence["first_frame_id"], frame)
            self.assertEqual(evidence["last_frame_id"], frame)
            self.assertEqual((evidence["start_s"], evidence["end_s"]), (time, time))

    def test_trunk_inclination_is_unsigned_and_does_not_claim_forward(self):
        data = sample()
        for shoulder in (2, 3):
            data[1][1][shoulder][2] = -1
        observations, _ = run(data)
        trunk = next(o for o in observations if o["quantity_code"] == "walking.trunk_lean")
        self.assertAlmostEqual(trunk["metrics"][0]["value"], 45)
        self.assertNotIn("forward", trunk["explanation"])

    def test_elk_sign_is_anatomical_and_peak_is_absolute(self):
        data = sample()
        for shoulder in (2, 3):
            data[1][1][shoulder][0] -= .5
            data[1][2][shoulder][0] += 1
        observation = run(data, "elk")[0][0]
        self.assertAlmostEqual(observation["metrics"][0]["value"], -45)
        self.assertEqual(observation["evidence"]["first_frame_id"], 21)
        self.assertIn("positive toward anatomical left", observation["explanation"])

    def test_rtk_shortest_projected_angle_handles_wrap_and_reflection(self):
        data = sample()
        for frame, angle in zip(data[1], (0, 179, -170)):
            angle = math.radians(angle)
            frame[2] = [-.3 * math.cos(angle), 2, -.3 * math.sin(angle)]
            frame[3] = [.3 * math.cos(angle), 2, .3 * math.sin(angle)]
        observation = run(data, "rtk")[0][0]
        self.assertAlmostEqual(observation["metrics"][0]["value"], 179)
        self.assertEqual(observation["evidence"]["first_frame_id"], 17)
        for frame in data[1]:
            for point in frame:
                point[2] *= -1
        self.assertEqual(values(run(data, "rtk")[0]), values([observation]))

    def test_translation_scale_heading_and_reflection_invariance(self):
        data = sample()
        for frame in data[1]:
            frame[2][0] -= .4
            frame[3][0] -= .4
            frame[2][2] += .3
            frame[6] = [-.2, .5, -.5]
        for test in ("elk", "rtk", "walking"):
            expected = values(run(data, test)[0])
            for scale in (1e-5, .5, 20):
                transformed = copy.deepcopy(data)
                angle = .83
                for frame in transformed[1]:
                    for point in frame:
                        x, y, z = point
                        z = -z
                        point[:] = [scale * (math.cos(angle) * x + math.sin(angle) * z) + 3,
                                    scale * y - 2,
                                    scale * (-math.sin(angle) * x + math.cos(angle) * z) + 4]
                actual = values(run(transformed, test)[0])
                for key in expected:
                    self.assertAlmostEqual(actual[key], expected[key], places=6)

    def test_missing_landmarks_and_degenerate_geometry_do_not_become_zero(self):
        data = sample()
        for row in data[1]:
            row[6] = row[4][:]
            row[7] = row[5][:]
            row[2], row[3] = row[0][:], row[1][:]
        observations, settings = run(data)
        self.assertEqual(observations, [])
        self.assertEqual(len(settings["unavailable_quantities"]), 3)
        missing = sample()
        missing[0]["joint_names"][6] = "unavailable_ankle"
        self.assertNotIn(("walking.knee_flexion", "left"), values(run(missing)[0]))

    def test_collapsed_projected_axes_are_unavailable(self):
        data = sample()
        for row in data[1]:
            row[0], row[1] = [0, 1, 0], [0, 1.4, 0]
        self.assertEqual(run(data, "elk")[0], [])
        self.assertEqual(run(data, "rtk")[0], [])

    def test_invalid_original_image_or_joint_cannot_supply_peak(self):
        for invalid in ("image", "joint", "frame"):
            data = sample()
            data[1][1][6] = [-.2, .5, -.5]
            if invalid == "image":
                data[2]["frames"][1]["image_valid"] = False
            elif invalid == "joint":
                data[0]["joint_valid"][1][6] = False
            else:
                data[0]["frame_valid"][1] = False
                data[0]["joint_valid"][1] = [False] * 8
            observations, _ = run(data)
            knee = next(o for o in observations if o["side"] == "left")
            self.assertEqual(knee["metrics"][0]["value"], 0)
            self.assertEqual(knee["evidence"]["first_frame_id"], 11)

    def test_gaps_are_not_interpolated_and_peak_evidence_is_a_single_valid_frame(self):
        data = sample()
        data[0]["frame_valid"][1] = False
        data[0]["joint_valid"][1] = [False] * 8
        data[0]["gaps"] = [{"start_s": .08, "end_s": .12, "reason": "authored dropout"}]
        data[2]["frames"][1]["image_valid"] = False
        data[2]["capture"]["gaps"] = [{"start_pts_ns": "1080000000", "end_pts_ns": "1120000000",
                                          "reason": "authored dropout"}]
        data[1][1][6] = [-.2, .5, -.5]
        self.assertTrue(all(o["evidence"]["start_s"] == o["evidence"]["end_s"] == 0
                            for o in run(data)[0]))

    def test_repeated_inference_mapping_does_not_duplicate_observations(self):
        data = sample()
        data[0]["resampling_map"] = [{"inference_frame_id": index, "source_frame_id": 17,
                                     "source_pts_ns": "1100000000"} for index in range(7)]
        self.assertEqual(len(run(data)[0]), 3)

    def test_interrupted_or_wrong_condition_produces_unavailable_reasons(self):
        for field, value in (("interrupted", True), ("condition", "standing")):
            data = sample()
            data[2]["capture"][field] = value
            observations, settings = run(data)
            self.assertEqual(observations, [])
            self.assertEqual(len(settings["unavailable_quantities"]), 3)

    def test_source_mismatch_and_duplicate_mapping_fail(self):
        changes = [("source_take_id", "00000000-0000-0000-0000-000000000009"),
                   ("source_frame_ids", [11, 17, 17]), ("source_frame_ids", [11, 17, 22]),
                   ("frame_times_s", [0, .11, .2]), ("source_pts_ns", ["1000000000", "1100000001", "1200000000"])]
        for field, value in changes:
            data = sample()
            data[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                run(data)

    def test_malformed_shapes_bounds_nonfinite_and_boolean_coordinates_fail(self):
        for bad in (None, [], [1, 2], True, float("inf"), float("nan"), 10**1000):
            data = sample()
            data[1][0][0][0] = bad
            with self.subTest(bad=str(bad)[:30]), self.assertRaises(ValueError):
                run(data)
        for field, value in (("frame_count", 601), ("joint_count", 257), ("frame_count", True)):
            data = sample()
            data[0][field] = value
            with self.assertRaises(ValueError):
                run(data)
        data = sample()
        data[1][0].pop()
        with self.assertRaises(ValueError):
            run(data)

    def test_unsupported_test_or_coordinate_system_fail(self):
        with self.assertRaises(ValueError):
            run(sample(), "barefoot")
        data = sample()
        data[0]["coordinate_system"] = "native_right_handed"
        with self.assertRaises(ValueError):
            run(data)

    def test_input_is_unchanged_and_results_are_independent(self):
        data = sample()
        before = copy.deepcopy(data)
        observations, _ = run(data)
        self.assertEqual(data, before)
        observations[0]["limitations"].append("modified")
        self.assertNotIn("modified", run(data)[0][0]["limitations"])


if __name__ == "__main__":
    unittest.main()
