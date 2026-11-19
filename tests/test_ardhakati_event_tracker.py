"""Synthetic continuity tests; these do not validate yoga teaching thresholds."""

from copy import deepcopy
import unittest

from backend.ardhakati_event_tracker import ArdhakatiEventTracker
from backend.tadasana_event_tracker import TadasanaEventTracker


def rule(status="deviation", rule_id="left_elbow_bend_sidebend", **overrides):
    result = {
        "rule_id": rule_id,
        "event_type": "elbow_bend",
        "target": "left_elbow",
        "feature_name": "left_elbow_angle_deg",
        "status": status,
        "observed_value": 150.0,
        "comparison_value": 150.0,
        "unit": "deg",
        "reference_range": [165.0, 180.0],
        "trigger_range": [160.0, 180.0],
        "clear_range": [165.0, 180.0],
        "temporal": {
            "min_duration_ms": 1500,
            "clear_duration_ms": 700,
            "max_gap_ms": 500,
        },
    }
    result.update(overrides)
    return result


def frame(timestamp_ms, status="deviation", *, results=None, **overrides):
    evaluation = {
        "timestamp_ms": timestamp_ms,
        "rule_version": "ardhakati-synthetic-v1",
        "feature_version": "synthetic-feature-v1",
        "exercise": "ardhakati_chakrasana",
        "phase": "side_bend_hold",
        "phase_source": "manual",
        "phase_reviewed": True,
        "bend_direction": "image_right",
        "direction_source": "manual",
        "direction_reviewed": True,
        "camera_view": "front",
        "camera_view_verified": False,
        "camera_view_source": "caller_declared",
        "movement_variant": "both_arms_overhead",
        "variant_source": "caller_declared",
        "variant_reviewed": False,
        "raised_arm_side": "unknown",
        "raised_arm_source": "not_applicable",
        "raised_arm_reviewed": False,
        "source_model": "RTMW-x",
        "rules_reviewed": False,
        "execution_mode": "exploratory_preview",
        "reference_status": "draft_unreviewed",
        "feedback_allowed": False,
        "rule_results": [rule(status)] if results is None else results,
    }
    evaluation.update(overrides)
    return evaluation


class ArdhakatiEventTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = ArdhakatiEventTracker()

    def activate(self, tracker=None, **overrides):
        tracker = tracker or self.tracker
        for timestamp in (0, 500, 1000, 1500):
            output = tracker.update(frame(timestamp, **overrides))
        self.assertEqual([x["status"] for x in output["new_events"]], ["started"])
        return output

    def test_shared_engine_and_tadasana_contract_remain_separate(self):
        self.assertIsInstance(self.tracker, TadasanaEventTracker)
        self.assertEqual(TadasanaEventTracker.EVENT_PREFIX, "tadasana")
        self.assertNotIn("side_bend_hold", TadasanaEventTracker.ALLOWED_PHASES)
        with self.assertRaises(ValueError):
            TadasanaEventTracker().update(frame(0))

    def test_all_declared_phases_are_accepted(self):
        for phase in (
            "unknown", "prepare", "transition", "arms_down_hold", "arms_up_hold",
            "side_bend_hold", "return_upright",
        ):
            with self.subTest(phase=phase):
                output = ArdhakatiEventTracker().update(frame(0, "not_applicable", phase=phase))
                self.assertEqual(output["new_events"], [])
        with self.assertRaises(ValueError):
            self.tracker.update(frame(0, phase="undefined_phase"))

    def test_confirmation_1500_ms_inclusive_and_gap_500_ms_continuous(self):
        for timestamp in (0, 500, 1000):
            output = self.tracker.update(frame(timestamp))
            self.assertFalse(output["feedback_allowed"])
            self.assertEqual(output["new_events"], [])
        output = self.tracker.update(frame(1500))
        event = output["new_events"][0]
        self.assertEqual(event["duration_ms"], 1500)
        self.assertEqual(event["start_timestamp_ms"], 0)
        self.assertEqual(event["confirmed_timestamp_ms"], 1500)
        self.assertEqual(event["duration_semantics"], "episode_elapsed")
        self.assertTrue(output["feedback_allowed"])

    def test_finite_duration_not_frame_count_is_used(self):
        self.tracker.update(frame(0))
        for timestamp in range(1, 100):
            output = self.tracker.update(frame(timestamp))
        self.assertFalse(output["feedback_allowed"])
        self.assertEqual(output["pending_events"][0]["duration_ms"], 99)

    def test_short_deviation_and_pending_gray_reset_confirmation(self):
        for status in ("gray_zone", "within_reference", "not_assessable"):
            with self.subTest(status=status):
                tracker = ArdhakatiEventTracker()
                tracker.update(frame(0))
                tracker.update(frame(500))
                output = tracker.update(frame(1000, status))
                self.assertEqual(output["pending_events"], [])
                output = tracker.update(frame(1500))
                self.assertEqual(output["pending_events"][0]["start_timestamp_ms"], 1500)
                self.assertFalse(output["feedback_allowed"])

    def test_active_event_does_not_repeat_feedback(self):
        first = self.activate()["new_events"][0]
        output = self.tracker.update(frame(2000))
        self.assertFalse(output["feedback_allowed"])
        self.assertEqual(output["new_events"], [])
        self.assertEqual(output["active_events"][0]["event_id"], first["event_id"])

    def test_clear_700_ms_recovers_same_event_and_no_new_feedback(self):
        first = self.activate()["new_events"][0]
        self.tracker.update(frame(1600, "within_reference"))
        self.tracker.update(frame(2000, "within_reference"))
        output = self.tracker.update(frame(2299, "within_reference"))
        self.assertEqual(output["new_events"], [])
        self.assertEqual(output["active_events"][0]["tracking_state"], "clearing")
        output = self.tracker.update(frame(2300, "within_reference"))
        event = output["new_events"][0]
        self.assertEqual(event["status"], "recovered")
        self.assertEqual(event["event_id"], first["event_id"])
        self.assertEqual(event["duration_ms"], 2300)
        self.assertFalse(output["feedback_allowed"])
        self.assertEqual(output["active_events"], [])

    def test_active_gray_preserves_episode_and_cancels_recovery(self):
        first = self.activate()["new_events"][0]
        self.tracker.update(frame(1600, "within_reference"))
        output = self.tracker.update(frame(2000, "gray_zone"))
        self.assertEqual(output["active_events"][0]["event_id"], first["event_id"])
        self.assertEqual(output["active_events"][0]["tracking_state"], "active")
        self.tracker.update(frame(2100, "within_reference"))
        self.tracker.update(frame(2500, "within_reference"))
        output = self.tracker.update(frame(2800, "within_reference"))
        self.assertEqual(output["new_events"][0]["status"], "recovered")

    def test_side_change_interrupts_instead_of_claiming_recovery(self):
        self.activate()
        output = self.tracker.update(frame(2000, bend_direction="image_left"))
        interrupted = output["new_events"][0]
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(interrupted["interruption_reason"], "context_changed")
        self.assertEqual(interrupted["bend_direction"], "image_right")
        self.assertEqual(output["pending_events"][0]["bend_direction"], "image_left")
        self.assertEqual(output["pending_events"][0]["duration_ms"], 0)
        self.assertFalse(output["feedback_allowed"])

    def test_all_extra_context_changes_protect_original_provenance(self):
        replacements = {
            "exercise": "another_exercise",
            "bend_direction": "unknown",
            "direction_source": "geometry_preview",
            "direction_reviewed": False,
            "camera_view": "unknown",
            "camera_view_verified": True,
            "camera_view_source": "manual",
            "movement_variant": "single_arm_overhead",
            "variant_reviewed": True,
            "variant_source": "manual",
            "raised_arm_side": "left",
            "raised_arm_source": "manual",
            "raised_arm_reviewed": True,
        }
        for key, replacement in replacements.items():
            with self.subTest(key=key):
                tracker = ArdhakatiEventTracker()
                original = self.activate(tracker)["new_events"][0]
                output = tracker.update(frame(2000, **{key: replacement}))
                interrupted = output["new_events"][0]
                self.assertEqual(interrupted["status"], "interrupted")
                self.assertEqual(interrupted["interruption_reason"], "context_changed")
                self.assertEqual(interrupted[key], original[key])
                self.assertEqual(output["pending_events"][0][key], replacement)

    def test_base_context_changes_still_interrupt(self):
        for key, value in {
            "source_model": "other-model", "feature_version": "v2",
            "phase_source": "automatic", "phase_reviewed": False,
            "rules_reviewed": True, "execution_mode": "reviewed_rules",
            "reference_status": "reviewed_reference",
        }.items():
            with self.subTest(key=key):
                tracker = ArdhakatiEventTracker()
                original = self.activate(tracker)["new_events"][0]
                output = tracker.update(frame(2000, **{key: value}))
                self.assertEqual(output["new_events"][0][key], original[key])
                self.assertEqual(output["new_events"][0]["status"], "interrupted")

    def test_return_upright_phase_interrupts_and_does_not_recover(self):
        self.activate()
        output = self.tracker.update(frame(2000, "not_applicable", phase="return_upright"))
        self.assertEqual(output["new_events"][0]["status"], "interrupted")
        self.assertEqual(output["new_events"][0]["interruption_reason"], "phase_changed")
        self.assertEqual(output["new_events"][0]["phase"], "side_bend_hold")
        self.assertEqual(output["pending_events"], [])
        self.assertFalse(output["feedback_allowed"])

    def test_rule_version_change_restarts_confirmation(self):
        self.activate()
        output = self.tracker.update(frame(2000, rule_version="ardhakati-synthetic-v2"))
        self.assertEqual(output["new_events"][0]["interruption_reason"], "rule_version_changed")
        self.assertEqual(output["new_events"][0]["rule_version"], "ardhakati-synthetic-v1")
        self.assertEqual(output["pending_events"][0]["rule_version"], "ardhakati-synthetic-v2")

    def test_review_guard_disabled_frames_never_start(self):
        # Policy is applied by the comparator.  Review metadata by itself is
        # intentionally not interpreted as a second, conflicting policy gate.
        for timestamp in (0, 500, 1000, 1500, 2000):
            output = self.tracker.update(frame(
                timestamp, "disabled", execution_mode="review_guard",
            ))
            self.assertFalse(output["feedback_allowed"])
            self.assertEqual(output["pending_events"], [])
            self.assertEqual(output["new_events"], [])
        preview = self.activate(ArdhakatiEventTracker())
        self.assertTrue(preview["feedback_allowed"])
        self.assertFalse(preview["new_events"][0]["rules_reviewed"])

    def test_gap_over_500_ms_interrupts_and_does_not_count_missing_time(self):
        self.activate()
        output = self.tracker.update(frame(2001))
        event = output["new_events"][0]
        self.assertEqual(event["status"], "interrupted")
        self.assertEqual(event["interruption_reason"], "frame_gap")
        self.assertEqual(event["end_timestamp_ms"], 1500)
        self.assertEqual(event["duration_ms"], 1500)
        self.assertEqual(output["pending_events"][0]["start_timestamp_ms"], 2001)

    def test_duplicate_and_old_frames_do_not_mutate_direction_or_state(self):
        first = self.activate()["new_events"][0]
        output = self.tracker.update(frame(1500, bend_direction="image_left"))
        self.assertTrue(output["ignored"])
        self.assertEqual(output["ignored_reason"], "duplicate_timestamp")
        output = self.tracker.update(frame(1000, results=[], phase="return_upright"))
        self.assertEqual(output["ignored_reason"], "out_of_order_timestamp")
        output = self.tracker.update(frame(2000))
        self.assertEqual(output["active_events"][0]["event_id"], first["event_id"])
        self.assertEqual(output["new_events"], [])

    def test_reset_ids_unique_streams_independent_and_no_session_ids_needed(self):
        first = self.activate()["new_events"][0]
        self.assertTrue(first["event_id"].startswith("ardhakati-"))
        self.assertNotIn("session_id", first)
        self.assertNotIn("pose_id", first)
        self.tracker.reset()
        second = self.activate()["new_events"][0]
        third = self.activate(ArdhakatiEventTracker())["new_events"][0]
        self.assertEqual(len({first["event_id"], second["event_id"], third["event_id"]}), 3)

    def test_missing_disabled_or_low_quality_rule_interrupts_not_recovers(self):
        for results in ([], [rule("disabled")], [rule("not_assessable")], [rule("not_applicable")]):
            with self.subTest(results=results):
                tracker = ArdhakatiEventTracker()
                self.activate(tracker)
                output = tracker.update(frame(2000, results=results))
                self.assertEqual(output["new_events"][0]["status"], "interrupted")
                self.assertEqual(output["active_events"], [])
                self.assertFalse(output["feedback_allowed"])

    def test_temporal_change_interrupts_old_rule(self):
        self.activate()
        changed = rule(temporal={"min_duration_ms": 1200, "clear_duration_ms": 700, "max_gap_ms": 500})
        output = self.tracker.update(frame(2000, results=[changed]))
        self.assertEqual(output["new_events"][0]["interruption_reason"], "temporal_parameters_changed")
        self.assertEqual(output["pending_events"][0]["start_timestamp_ms"], 2000)

    def test_input_is_copied_and_lifecycle_identity_cannot_be_spoofed(self):
        incoming = frame(0, results=[rule(event_id="spoofed", duration_ms=999999)])
        original = deepcopy(incoming)
        self.tracker.update(incoming)
        self.assertEqual(incoming, original)
        for timestamp in (500, 1000, 1500):
            output = self.tracker.update(frame(timestamp, results=[rule(event_id="spoofed", duration_ms=999999)]))
        self.assertNotEqual(output["new_events"][0]["event_id"], "spoofed")
        self.assertEqual(output["new_events"][0]["duration_ms"], 1500)
        self.assertNotIn("confidence", output["new_events"][0])

    def test_invalid_batch_does_not_mutate_active_state(self):
        first = self.activate()["new_events"][0]
        with self.assertRaises(ValueError):
            self.tracker.update(frame(2000, results=[rule(), rule()]))
        with self.assertRaises(ValueError):
            self.tracker.update(frame(2000, results=[rule(observed_value=float("nan"))]))
        output = self.tracker.update(frame(2000))
        self.assertEqual(output["active_events"][0]["event_id"], first["event_id"])
        self.assertEqual(output["new_events"], [])


if __name__ == "__main__":
    unittest.main()
