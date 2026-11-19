"""Synthetic single-frame contracts; no clinical or dataset-accuracy claims."""

from copy import deepcopy
import json
import unittest

from backend.pose_rules_ardhakati import (
    compare_ardhakati_frame, load_rules, validate_ruleset,
)


def feature_frame(timestamp_ms=0, **values):
    specs = {
        "shoulder_height_diff": (0.3, "torso_ratio"),
        "torso_tilt_deg": (25.0, "deg"),
        "left_elbow_angle_deg": (175.0, "deg"),
        "right_elbow_angle_deg": (175.0, "deg"),
        "left_arm_torso_angle_deg": (175.0, "deg"),
        "right_arm_torso_angle_deg": (175.0, "deg"),
        "ankle_spacing_shoulder_ratio": (0.25, "shoulder_width_ratio"),
    }
    return {
        "timestamp_ms": timestamp_ms,
        "feature_version": "dwpose133-geometry-v1",
        "layout": "COCO-WholeBody 133", "coordinate_space": "image_pixels",
        "features": {
            name: {"value": values.get(name, value), "unit": unit,
                   "valid": True, "reason": None, "min_keypoint_score": 0.8}
            for name, (value, unit) in specs.items()
        },
    }


def compare(frame=None, **overrides):
    context = {
        "phase": "side_bend_hold", "movement_variant": "both_arms_overhead",
        "bend_direction": "image_right", "direction_source": "manual_instruction",
        "camera_view": "front", "source_model": "RTMW-x",
        "allow_unreviewed": True,
    }
    context.update(overrides)
    return compare_ardhakati_frame(frame or feature_frame(), **context)


def rule_result(output, rule_id):
    return next(rule for rule in output["rule_results"] if rule["rule_id"] == rule_id)


class ArdhakatiSingleFrameTests(unittest.TestCase):
    def test_default_guard_disables_candidates_and_never_feedbacks(self):
        output = compare(feature_frame(left_elbow_angle_deg=120), allow_unreviewed=False)
        self.assertEqual(output["execution_mode"], "review_guard")
        self.assertFalse(output["rules_reviewed"])
        self.assertEqual(output["candidates"], [])
        self.assertFalse(output["feedback_allowed"])
        self.assertEqual(rule_result(output, "left_raised_elbow_bend")["reason"], "rules_require_manual_review")

    def test_single_frame_only_generates_candidate_without_duration(self):
        output = compare(feature_frame(left_elbow_angle_deg=140))
        self.assertEqual([r["rule_id"] for r in output["candidates"]], ["left_raised_elbow_bend"])
        self.assertEqual(output["assessment_status"], "candidate_deviation")
        self.assertFalse(output["feedback_allowed"])
        self.assertEqual(output["deviations"], [])
        self.assertNotIn("duration_ms", output["candidates"][0])

    def test_elbow_trigger_gray_and_clear_boundaries(self):
        for angle, status in ((149.99, "deviation"), (150.0, "gray_zone"),
                              (159.99, "gray_zone"), (160.0, "within_reference"),
                              (180.0, "within_reference"), (181.0, "not_assessable")):
            with self.subTest(angle=angle):
                output = compare(feature_frame(left_elbow_angle_deg=angle))
                self.assertEqual(rule_result(output, "left_raised_elbow_bend")["status"], status)

    def test_both_upper_arm_trigger_and_clear_boundaries(self):
        for angle, status in ((149.9, "deviation"), (150.0, "gray_zone"), (160.0, "within_reference")):
            with self.subTest(angle=angle):
                output = compare(feature_frame(left_arm_torso_angle_deg=angle))
                self.assertEqual(rule_result(output, "left_upper_arm_alignment_both")["status"], status)

    def test_both_arms_are_independently_assessed(self):
        output = compare(feature_frame(left_elbow_angle_deg=140, right_arm_torso_angle_deg=140))
        self.assertEqual({r["rule_id"] for r in output["candidates"]}, {
            "left_raised_elbow_bend", "right_upper_arm_alignment_both",
        })
        self.assertEqual(len(output["assessment_coverage"]["eligible_rule_ids"]), 5)
        self.assertTrue(output["assessment_coverage"]["complete_for_enabled_phase_rules"])

    def test_single_arm_only_assesses_explicitly_raised_elbow(self):
        for raised, other in (("left", "right"), ("right", "left")):
            with self.subTest(raised=raised):
                output = compare(feature_frame(left_elbow_angle_deg=100, right_elbow_angle_deg=100),
                                 movement_variant="single_arm_overhead", raised_arm_side=raised)
                self.assertEqual(rule_result(output, f"{raised}_raised_elbow_bend")["status"], "deviation")
                self.assertEqual(rule_result(output, f"{other}_raised_elbow_bend")["reason"], "non_raised_arm")
                self.assertEqual(rule_result(output, f"{other}_raised_elbow_bend")["status"], "not_applicable")
                self.assertEqual(rule_result(output, f"{raised}_upper_arm_alignment_both")["status"], "not_applicable")
                self.assertEqual(rule_result(output, f"{raised}_upper_arm_single_monitor")["status"], "disabled")
                self.assertEqual(len(output["assessment_coverage"]["eligible_rule_ids"]), 2)

    def test_unknown_variant_or_single_arm_side_cannot_be_complete(self):
        output = compare(movement_variant="unknown")
        self.assertEqual(output["candidates"], [])
        self.assertFalse(output["assessment_coverage"]["complete_for_enabled_phase_rules"])
        self.assertEqual(rule_result(output, "left_raised_elbow_bend")["reason"], "movement_variant_required")
        output = compare(movement_variant="single_arm_overhead", raised_arm_side="unknown")
        self.assertEqual(rule_result(output, "left_raised_elbow_bend")["reason"], "raised_arm_side_required")
        self.assertFalse(output["assessment_coverage"]["complete_for_enabled_phase_rules"])

    def test_transitions_preparation_and_return_never_generate_candidates(self):
        for phase in ("unknown", "prepare", "transition", "return_upright", "arms_down_hold"):
            with self.subTest(phase=phase):
                output = compare(feature_frame(left_elbow_angle_deg=100, torso_tilt_deg=-30), phase=phase)
                self.assertEqual(output["candidates"], [])
                self.assertFalse(output["feedback_allowed"])
                self.assertFalse(output["assessment_coverage"]["complete_for_enabled_phase_rules"])

    def test_arms_up_hold_checks_arms_but_not_bend_direction(self):
        output = compare(feature_frame(left_elbow_angle_deg=100, torso_tilt_deg=-30), phase="arms_up_hold")
        self.assertEqual(rule_result(output, "bend_direction_mismatch")["status"], "not_applicable")
        self.assertEqual([r["rule_id"] for r in output["candidates"]], ["left_raised_elbow_bend"])

    def test_expected_direction_uses_signed_projection_not_absolute_tilt(self):
        for direction, tilt, comparison, status in (
            ("image_right", -20, -20, "deviation"),
            ("image_right", 20, 20, "within_reference"),
            ("image_left", -20, 20, "within_reference"),
            ("image_left", 20, -20, "deviation"),
            ("image_right", -5, -5, "gray_zone"),
            ("image_right", 5, 5, "within_reference"),
        ):
            with self.subTest(direction=direction, tilt=tilt):
                result = rule_result(compare(feature_frame(torso_tilt_deg=tilt), bend_direction=direction), "bend_direction_mismatch")
                self.assertEqual(result["transform"], "expected_direction")
                self.assertEqual(result["comparison_value"], comparison)
                self.assertEqual(result["status"], status)

    def test_missing_or_geometry_derived_direction_is_unassessed(self):
        for direction, source in (("unknown", "manual_instruction"),
                                  ("image_left", "geometry_preview_NOT_HOLD_GROUND_TRUTH")):
            with self.subTest(source=source):
                output = compare(bend_direction=direction, direction_source=source)
                self.assertEqual(rule_result(output, "bend_direction_mismatch")["reason"], "independent_intended_direction_required")
                self.assertIn("bend_direction_mismatch", output["assessment_coverage"]["unassessed_rule_ids"])
                self.assertFalse(output["assessment_coverage"]["complete_for_enabled_phase_rules"])

    def test_front_view_and_matching_source_are_required(self):
        for camera in ("unknown", "angle_1_unverified", "side", "back"):
            with self.subTest(camera=camera):
                output = compare(feature_frame(left_elbow_angle_deg=100), camera_view=camera)
                self.assertEqual(output["assessment_status"], "not_assessable")
                self.assertIn("front_view_required", output["reason_codes"])
                self.assertEqual(output["candidates"], [])
                self.assertFalse(output["assessment_coverage"]["complete_for_enabled_phase_rules"])
        self.assertIn("source_model_missing_or_mismatch", compare(source_model=None)["reason_codes"])

    def test_layout_coordinate_and_version_mismatch_block_all_candidates(self):
        for key, value, reason in (("layout", "mediapipe33", "layout_mismatch"),
                                   ("coordinate_space", "normalized", "coordinate_space_mismatch"),
                                   ("feature_version", "v2", "feature_version_mismatch")):
            with self.subTest(key=key):
                incoming = feature_frame(left_elbow_angle_deg=100)
                incoming[key] = value
                output = compare(incoming)
                self.assertIn(reason, output["reason_codes"])
                self.assertEqual(output["candidates"], [])

    def test_invalid_missing_unit_score_and_nonfinite_are_json_safe(self):
        modifications = (
            {"valid": False}, {"value": None}, {"value": True},
            {"value": -1}, {"value": float("nan")}, {"value": float("inf")},
            {"unit": "radian"}, {"min_keypoint_score": None},
            {"min_keypoint_score": 0.49}, {"min_keypoint_score": float("nan")},
        )
        for replacement in modifications:
            with self.subTest(replacement=replacement):
                incoming = feature_frame()
                incoming["features"]["left_elbow_angle_deg"].update(replacement)
                output = compare(incoming)
                self.assertEqual(rule_result(output, "left_raised_elbow_bend")["status"], "not_assessable")
                self.assertIn("left_raised_elbow_bend", output["assessment_coverage"]["unassessed_rule_ids"])
                self.assertFalse(output["assessment_coverage"]["complete_for_enabled_phase_rules"])
                json.dumps(output, allow_nan=False)
        incoming = feature_frame()
        del incoming["features"]["left_elbow_angle_deg"]
        self.assertEqual(rule_result(compare(incoming), "left_raised_elbow_bend")["status"], "not_assessable")

    def test_raw_score_above_one_is_not_clamped_or_rejected(self):
        incoming = feature_frame()
        incoming["features"]["left_elbow_angle_deg"]["min_keypoint_score"] = 1.02
        result = rule_result(compare(incoming), "left_raised_elbow_bend")
        self.assertEqual(result["status"], "within_reference")
        self.assertEqual(result["min_keypoint_score"], 1.02)

    def test_monitor_rules_do_not_judge_expected_shoulder_height_or_depth(self):
        output = compare(feature_frame(shoulder_height_diff=9, torso_tilt_deg=80,
                                       ankle_spacing_shoulder_ratio=8))
        for name in ("shoulder_height_monitor", "lateral_bend_magnitude_monitor", "stance_monitor"):
            self.assertEqual(rule_result(output, name)["status"], "disabled")
        self.assertEqual(output["candidates"], [])

    def test_pure_function_and_defensive_config_copy(self):
        incoming, rules = feature_frame(), load_rules()
        original_frame, original_rules = deepcopy(incoming), deepcopy(rules)
        output = compare(incoming, ruleset=rules)
        output["features"]["left_elbow_angle_deg"]["value"] = -999
        self.assertEqual(incoming, original_frame)
        self.assertEqual(rules, original_rules)

    def test_config_review_record_is_required_for_reviewed_rules(self):
        rules = load_rules()
        rules["reviewed"] = True
        with self.assertRaises(ValueError):
            validate_ruleset(rules)
        rules["review_record"] = {"reviewer": "synthetic-test-only"}
        output = compare(ruleset=rules, allow_unreviewed=False)
        self.assertEqual(output["execution_mode"], "reviewed_rules")

    def test_config_rejects_duplicate_rule_ids_and_wrong_hysteresis(self):
        rules = load_rules()
        rules["rules"].append(deepcopy(rules["rules"][0]))
        with self.assertRaises(ValueError):
            validate_ruleset(rules)
        rules = load_rules()
        rules["rules"][0]["clear_range"] = [140, 180]
        with self.assertRaises(ValueError):
            validate_ruleset(rules)

    def test_invalid_context_and_timestamp_values_raise(self):
        for options in ({"phase": "unlisted"}, {"movement_variant": "unlisted"},
                        {"raised_arm_side": "left"}, {"bend_direction": "anatomical_left"},
                        {"phase_reviewed": "yes"}, {"direction_source": ""}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                compare(**options)
        incoming = feature_frame()
        incoming["timestamp_ms"] = True
        with self.assertRaises(ValueError):
            compare(incoming)


if __name__ == "__main__":
    unittest.main()
