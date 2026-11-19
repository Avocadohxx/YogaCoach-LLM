"""B: compare a frame without claiming a verified hold or persistent event."""
from copy import deepcopy
import math
import unittest

from backend.pose_rules_tadasana import compare_tadasana_frame, load_rules, validate_ruleset


def frame(left=175.0, right=175.0, timestamp_ms=0):
    features = {}
    for name, unit, value in (
        ("left_elbow_angle_deg", "deg", left),
        ("right_elbow_angle_deg", "deg", right),
        ("shoulder_height_diff", "torso_ratio", 0.01),
        ("torso_tilt_deg", "deg", 0.0),
        ("ankle_spacing_shoulder_ratio", "shoulder_width_ratio", 0.28),
        ("left_arm_torso_angle_deg", "deg", 175.0),
        ("right_arm_torso_angle_deg", "deg", 175.0),
    ):
        features[name] = dict(value=value, valid=True, reason=None, unit=unit,
                              min_keypoint_score=0.9)
    return dict(timestamp_ms=timestamp_ms, feature_version="dwpose133-geometry-v1",
                layout="COCO-WholeBody 133", coordinate_space="image_pixels", features=features)


def compare(raw, **kw):
    defaults = dict(phase="arms_up_hold", camera_view="front", source_model="RTMW-x",
                    allow_unreviewed=True)
    defaults.update(kw)
    return compare_tadasana_frame(raw, **defaults)


def left_rule(out):
    return next(r for r in out["rule_results"] if r["rule_id"] == "left_elbow_bend_overhead")


class ComparisonTests(unittest.TestCase):
    def test_draft_is_guarded_by_default(self):
        out = compare(frame(140), allow_unreviewed=False)
        self.assertFalse(out["feedback_allowed"])
        self.assertEqual(out["candidates"], [])
        self.assertEqual(left_rule(out)["status"], "disabled")
        self.assertFalse(out["rules_reviewed"])

    def test_explicit_preview_only_creates_single_frame_candidate(self):
        out = compare(frame(150))
        self.assertEqual(left_rule(out)["status"], "deviation")
        self.assertEqual(len(out["candidates"]), 1)
        self.assertEqual(out["assessment_status"], "candidate_deviation")
        self.assertEqual(out["execution_mode"], "exploratory_preview")
        self.assertFalse(out["feedback_allowed"])
        self.assertEqual(out["deviations"], [])
        self.assertNotIn("duration_ms", out["candidates"][0])

    def test_boundary_and_hysteresis(self):
        for angle, expected in ((159.999, "deviation"), (160, "gray_zone"),
                                (164.999, "gray_zone"), (165, "within_reference"),
                                (180, "within_reference")):
            with self.subTest(angle=angle):
                self.assertEqual(left_rule(compare(frame(angle)))["status"], expected)

    def test_each_side_is_independent(self):
        out = compare(frame(175, 150))
        self.assertEqual(left_rule(out)["status"], "within_reference")
        self.assertEqual(out["candidates"][0]["target"], "right_elbow")

    def test_unknown_and_down_phase_do_not_claim_overhead_error(self):
        for phase in ("unknown", "prepare", "transition", "arms_down_hold"):
            out = compare(frame(90), phase=phase)
            self.assertEqual(out["candidates"], [])
            self.assertEqual(left_rule(out)["status"], "not_applicable")

    def test_monitors_never_become_events_in_preview(self):
        raw = frame()
        raw["features"]["shoulder_height_diff"]["value"] = 0.9
        raw["features"]["torso_tilt_deg"]["value"] = -80.0
        raw["features"]["ankle_spacing_shoulder_ratio"]["value"] = 1.5
        out = compare(raw)
        self.assertEqual(out["candidates"], [])
        for r in out["rule_results"]:
            if r["mode"] == "monitor_only":
                self.assertEqual(r["status"], "disabled")

    def test_feature_validity_unit_and_score_gates(self):
        for change in ({"valid": False, "reason": "occluded"}, {"value": None},
                       {"value": math.nan}, {"value": True}, {"unit": "rad"},
                       {"min_keypoint_score": 0.1}, {"min_keypoint_score": None},
                       {"value": 181.0}, {"value": -1.0}):
            raw = frame(150)
            raw["features"]["left_elbow_angle_deg"].update(change)
            with self.subTest(change=change):
                self.assertEqual(left_rule(compare(raw))["status"], "not_assessable")

    def test_source_compatibility(self):
        for change, kw in (({"layout": "MediaPipe 33"}, {}),
                           ({"coordinate_space": "normalized_image"}, {}),
                           ({"feature_version": "new-version"}, {}),
                           ({}, {"source_model": None}), ({}, {"camera_view": "side"})):
            raw = frame(150)
            raw.update(change)
            out = compare(raw, **kw)
            self.assertEqual(out["assessment_status"], "not_assessable")
            self.assertEqual(out["candidates"], [])

    def test_missing_feature_is_local(self):
        raw = frame()
        del raw["features"]["left_elbow_angle_deg"]
        out = compare(raw)
        self.assertEqual(left_rule(out)["status"], "not_assessable")
        self.assertEqual(next(r for r in out["rule_results"]
                              if r["rule_id"] == "right_elbow_bend_overhead")["status"],
                         "within_reference")
        self.assertFalse(out["assessment_coverage"]["complete_for_enabled_phase_rules"])
        self.assertEqual(out["assessment_coverage"]["unassessed_rule_ids"],
                         ["left_elbow_bend_overhead"])

    def test_nonfinite_measurement_is_json_safe_and_interrupts_tracking(self):
        import json
        from backend.tadasana_event_tracker import TadasanaEventTracker
        tracker = TadasanaEventTracker()
        for t in range(0, 1501, 100):
            result = tracker.update(compare(frame(150, timestamp_ms=t)))
        self.assertTrue(result["feedback_allowed"])
        raw = frame(math.nan, timestamp_ms=1600)
        result = tracker.update(compare(raw))
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["new_events"][0]["status"], "interrupted")
        self.assertIsNone(result["features"]["left_elbow_angle_deg"]["value"])
        self.assertFalse(result["assessment_coverage"]["complete_for_enabled_phase_rules"])

    def test_cannot_approve_rules_without_record(self):
        config = load_rules()
        config["reviewed"] = True
        with self.assertRaises(ValueError):
            validate_ruleset(config)
        config["review_record"] = {"reviewer": "unit-test-only", "scope": "synthetic"}
        out = compare(frame(150), allow_unreviewed=False, ruleset=config)
        self.assertTrue(out["rules_reviewed"])
        self.assertEqual(out["execution_mode"], "reviewed_rules")
        self.assertEqual(len(out["candidates"]), 1)

    def test_bad_rules_are_rejected(self):
        for field, value in (("unit", "rad"), ("feature_name", "unknown"),
                             ("transform", "square"), ("trigger_range", [180, 160]),
                             ("clear_range", [150, 180]),
                             ("temporal", {"min_duration_ms": True}),
                             ("applicable_phases", ["unknown"])):
            config = load_rules()
            config["rules"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_ruleset(config)

    def test_no_input_mutation_and_no_synthetic_event_id(self):
        raw = frame(150)
        raw["duration_ms"] = 999999
        before = deepcopy(raw)
        out = compare(raw)
        self.assertEqual(raw, before)
        self.assertNotIn("event_id", out["candidates"][0])
        self.assertNotIn("duration_ms", out["candidates"][0])

    def test_abs_transform_for_explicit_test_rule(self):
        config = load_rules()
        rule = next(r for r in config["rules"] if r["rule_id"] == "torso_tilt_monitor")
        rule["mode"] = "candidate"  # synthetic test only; original config is unchanged
        raw = frame()
        raw["features"]["torso_tilt_deg"]["value"] = -7.0
        out = compare(raw, ruleset=config)
        r = next(r for r in out["rule_results"] if r["rule_id"] == "torso_tilt_monitor")
        self.assertEqual(r["observed_value"], -7)
        self.assertEqual(r["comparison_value"], 7)
        self.assertEqual(r["status"], "deviation")


if __name__ == "__main__":
    unittest.main()
