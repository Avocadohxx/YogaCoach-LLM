"""B: independently known pixel geometry and robust JSONL export checks."""
import csv
import json
import math
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from backend.pose_features_133 import (
    FEATURE_UNITS, Frame133, extract_features_133,
)
from experiments.detection.extract_features_133 import export_features


def skeleton():
    p = [[0.0, 0.0] for _ in range(133)]
    for i, xy in {
        5: (60, 30), 6: (40, 30), 7: (60, 45), 8: (40, 45),
        9: (60, 60), 10: (40, 60), 11: (55, 60), 12: (45, 60),
        15: (60, 100), 16: (40, 100),
    }.items():
        p[i] = list(xy)
    return dict(timestamp_ms=0, keypoints=p, scores=[0.9] * 133)


def feature_values(raw):
    return {k: v["value"] for k, v in extract_features_133(raw)["features"].items()}


class Feature133Tests(unittest.TestCase):
    def test_known_upright_geometry_and_units(self):
        out = extract_features_133(skeleton())
        values = feature_values(skeleton())
        self.assertEqual(len(out["features"]), 8)
        self.assertEqual(out["measurement_status"], "all_valid")
        self.assertFalse(out["feedback_allowed"])
        self.assertEqual(values["shoulder_height_diff_px"], 0)
        self.assertEqual(values["shoulder_height_diff"], 0)
        self.assertEqual(values["torso_tilt_deg"], 0)
        for side in ("left", "right"):
            self.assertAlmostEqual(values[f"{side}_elbow_angle_deg"], 180)
            self.assertAlmostEqual(values[f"{side}_arm_torso_angle_deg"], 0)
        self.assertAlmostEqual(values["ankle_spacing_shoulder_ratio"], 1)
        for name, unit in FEATURE_UNITS.items():
            self.assertEqual(out["features"][name]["unit"], unit)

    def test_elbow_right_angle_independent_of_body(self):
        raw = skeleton()
        raw["keypoints"][9] = [75, 45]
        self.assertAlmostEqual(feature_values(raw)["left_elbow_angle_deg"], 90)

    def test_arm_90_and_180_use_upper_arm_not_wrist(self):
        raw = skeleton()
        raw["keypoints"][7] = [75, 30]
        raw["keypoints"][9] = [75, 45]  # bent elbow does not change upper-arm direction
        self.assertAlmostEqual(feature_values(raw)["left_arm_torso_angle_deg"], 90)
        self.assertAlmostEqual(feature_values(raw)["left_elbow_angle_deg"], 90)
        raw["keypoints"][7] = [60, 15]
        raw["keypoints"][9] = [60, 0]
        self.assertAlmostEqual(feature_values(raw)["left_arm_torso_angle_deg"], 180)

    def test_torso_45_and_mirror_sign(self):
        raw = skeleton()
        for i in (5, 6):
            raw["keypoints"][i][0] += 30
        self.assertAlmostEqual(feature_values(raw)["torso_tilt_deg"], 45)
        for p in raw["keypoints"]:
            p[0] = 200 - p[0]
        self.assertAlmostEqual(feature_values(raw)["torso_tilt_deg"], -45)

    def test_shoulder_difference_and_ratio_known_values(self):
        raw = skeleton()
        raw["keypoints"][5][1] = 24
        vals = feature_values(raw)
        self.assertAlmostEqual(vals["shoulder_height_diff_px"], 6)
        self.assertAlmostEqual(vals["shoulder_height_diff"], 6 / 33)
        # The denominator is EUCLIDEAN shoulder width, not horizontal span.
        self.assertAlmostEqual(vals["ankle_spacing_shoulder_ratio"], 20 / math.hypot(20, 6))

    def test_ankle_horizontal_span_ignores_ankle_height_difference(self):
        raw = skeleton()
        raw["keypoints"][15][1] += 50
        self.assertAlmostEqual(feature_values(raw)["ankle_spacing_shoulder_ratio"], 1)

    def test_translation_and_scale(self):
        raw = skeleton()
        raw["keypoints"][5][1] = 24
        expected = feature_values(raw)
        translated = deepcopy(raw)
        for p in translated["keypoints"]:
            p[0] += 234
            p[1] += 500
        scaled = deepcopy(raw)
        for p in scaled["keypoints"]:
            p[0] *= 3
            p[1] *= 3
        for key, value in expected.items():
            self.assertAlmostEqual(feature_values(translated)[key], value)
            factor = 3 if key == "shoulder_height_diff_px" else 1
            self.assertAlmostEqual(feature_values(scaled)[key], value * factor)

    def test_raw_scores_above_one_are_preserved(self):
        raw = skeleton()
        raw["scores"] = [1.05] * 133
        out = extract_features_133(raw)
        self.assertEqual(out["measurement_status"], "all_valid")
        self.assertAlmostEqual(out["features"]["left_elbow_angle_deg"]["min_keypoint_score"], 1.05)

    def test_wrist_low_score_only_disables_its_elbow(self):
        raw = skeleton()
        raw["scores"][9] = 0.1
        f = extract_features_133(raw)["features"]
        self.assertIsNone(f["left_elbow_angle_deg"]["value"])
        self.assertEqual(f["left_elbow_angle_deg"]["reason"], "low_keypoint_score")
        self.assertTrue(f["left_arm_torso_angle_deg"]["valid"])
        self.assertTrue(f["torso_tilt_deg"]["valid"])
        self.assertTrue(f["right_elbow_angle_deg"]["valid"])

    def test_invalid_coordinate_or_score_is_feature_local(self):
        for container, value in (("keypoints", [None, 60]), ("keypoints", [math.nan, 60]),
                                 ("scores", math.inf), ("scores", -0.1)):
            with self.subTest(container=container, value=value):
                raw = skeleton()
                raw[container][9] = value
                out = extract_features_133(raw)
                self.assertFalse(out["features"]["left_elbow_angle_deg"]["valid"])
                self.assertTrue(out["features"]["right_elbow_angle_deg"]["valid"])
                json.dumps(out, allow_nan=False)

    def test_degenerate_torso_and_shoulder_width(self):
        raw = skeleton()
        raw["keypoints"][11] = [55, 30]
        raw["keypoints"][12] = [45, 30]
        f = extract_features_133(raw)["features"]
        self.assertEqual(f["torso_tilt_deg"]["reason"], "degenerate_torso")
        self.assertTrue(f["left_elbow_angle_deg"]["valid"])
        raw = skeleton()
        raw["keypoints"][6] = raw["keypoints"][5][:]
        f = extract_features_133(raw)["features"]
        self.assertEqual(f["ankle_spacing_shoulder_ratio"]["reason"], "degenerate_shoulder_width")

    def test_no_scores_pass_and_threshold_is_configurable(self):
        raw = skeleton()
        raw["scores"] = [0.2] * 133
        self.assertEqual(extract_features_133(raw)["measurement_status"], "not_assessable")
        self.assertEqual(extract_features_133(raw, min_score=0.1)["measurement_status"], "all_valid")
        for threshold in (math.nan, math.inf, -0.5, True):
            with self.assertRaises(ValueError):
                extract_features_133(raw, min_score=threshold)

    def test_structure_checks_do_not_accept_mediapipe_33(self):
        for field, value in (("keypoints", [[0, 0]] * 33), ("scores", [0.9] * 132),
                             ("timestamp_ms", True), ("timestamp_ms", -1),
                             ("timestamp_ms", "33")):
            with self.subTest(field=field, value=str(value)[:50]):
                raw = skeleton()
                raw[field] = value
                with self.assertRaises(ValueError):
                    Frame133.from_mapping(raw)


class Export133Tests(unittest.TestCase):
    def test_full_export_keeps_rows_and_blanks_invalid_values(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "input/keypoints_133.jsonl"
            path.parent.mkdir()
            normal, low = skeleton(), skeleton()
            low["timestamp_ms"] = 33
            low["scores"][9] = 0.1
            path.write_text(json.dumps(normal) + "\n\n" + json.dumps(low) + "\n")
            output = root / "output"
            summary = export_features(path, output)
            self.assertEqual(summary["frames"], 2)
            self.assertFalse(summary["hold_segments_selected"])
            self.assertEqual(summary["feature_statistics"]["left_elbow_angle_deg"]["invalid_frames"], 1)
            rows = list(csv.DictReader((output / "features.csv").open()))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["left_elbow_angle_deg"], "")
            self.assertEqual(rows[1]["left_elbow_angle_deg__reason"], "low_keypoint_score")
            self.assertEqual(len((output / "features.jsonl").read_text().splitlines()), 2)

    def test_corrupt_line_does_not_replace_previous_exports(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path, output = root / "input.jsonl", root / "out"
            path.write_text(json.dumps(skeleton()) + "\n")
            export_features(path, output)
            before = (output / "features.csv").read_bytes()
            path.write_text(json.dumps(skeleton()) + "\n{not json}\n")
            with self.assertRaisesRegex(ValueError, "line 2"):
                export_features(path, output)
            self.assertEqual((output / "features.csv").read_bytes(), before)

    def test_metadata_layout_is_checked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "input/keypoints.jsonl"
            path.parent.mkdir()
            path.write_text(json.dumps(skeleton()) + "\n")
            (path.parent / "metadata.json").write_text(json.dumps({"layout": "MediaPipe 33"}))
            with self.assertRaisesRegex(ValueError, "metadata layout"):
                export_features(path, root / "output")

    def test_refuses_outputs_in_source_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "input.jsonl"
            path.write_text(json.dumps(skeleton()) + "\n")
            with self.assertRaises(ValueError):
                export_features(path, root)


if __name__ == "__main__":
    unittest.main()
