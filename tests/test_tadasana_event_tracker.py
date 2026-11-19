"""Temporal behavior tests use synthetic rule results, never clinical labels."""

from copy import deepcopy
import unittest

from backend.tadasana_event_tracker import TadasanaEventTracker


def rule(status="deviation", rule_id="shoulder_height", **overrides):
    result = {
        "rule_id": rule_id,
        "event_type": "shoulder_asymmetry",
        "target": "shoulders",
        "feature_name": "shoulder_height_diff",
        "status": status,
        "observed_value": 0.15,
        "comparison_value": 0.15,
        "unit": "torso_ratio",
        "reference_range": [0.0, 0.06],
        "temporal": {
            "min_duration_ms": 300,
            "clear_duration_ms": 200,
            "max_gap_ms": 100,
        },
        "evidence": {"required_keypoint_ids": [5, 6, 11, 12]},
    }
    result.update(overrides)
    return result


def frame(timestamp_ms, status="deviation", *, results=None, **overrides):
    evaluation = {
        "timestamp_ms": timestamp_ms,
        "rule_version": "test-only-v1",
        "phase": "arms_down_hold",
        "rules_reviewed": False,
        "execution_mode": "exploratory_preview",
        "source_model": "RTMW-x",
        "phase_source": "manual",
        "feedback_allowed": False,
        "rule_results": [rule(status)] if results is None else results,
    }
    evaluation.update(overrides)
    return evaluation


class TadasanaEventTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = TadasanaEventTracker()

    def activate(self, tracker=None):
        tracker = tracker or self.tracker
        for timestamp in (0, 100, 200, 300):
            output = tracker.update(frame(timestamp))
        self.assertEqual([x["status"] for x in output["new_events"]], ["started"])
        return output

    def test_threshold_is_inclusive_and_duration_is_computed(self):
        for timestamp in (0, 100, 200):
            output = self.tracker.update(frame(timestamp, results=[rule(duration_ms=99999)]))
            self.assertFalse(output["feedback_allowed"])
            self.assertEqual(output["new_events"], [])
        output = self.tracker.update(frame(300, results=[rule(duration_ms=99999, event_id="spoofed")]))
        event = output["new_events"][0]
        self.assertEqual(event["duration_ms"], 300)
        self.assertEqual(event["duration_semantics"], "episode_elapsed")
        self.assertEqual(event["start_timestamp_ms"], 0)
        self.assertEqual(event["confirmed_timestamp_ms"], 300)
        self.assertNotEqual(event["event_id"], "spoofed")
        self.assertTrue(output["feedback_allowed"])
        self.assertFalse(event["rules_reviewed"])
        self.assertEqual(event["execution_mode"], "exploratory_preview")
        self.assertEqual(event["source_model"], "RTMW-x")
        self.assertNotIn("confidence", event)

    def test_short_spike_does_not_start(self):
        self.tracker.update(frame(0))
        self.tracker.update(frame(100))
        output = self.tracker.update(frame(200, "within_reference"))
        self.assertEqual(output["new_events"], [])
        self.assertEqual(output["pending_events"], [])

    def test_pending_gray_zone_restarts_confirmation(self):
        self.tracker.update(frame(0))
        self.tracker.update(frame(100))
        self.tracker.update(frame(200, "gray_zone"))
        self.tracker.update(frame(300))
        self.tracker.update(frame(400))
        output = self.tracker.update(frame(500))
        self.assertFalse(output["feedback_allowed"])
        output = self.tracker.update(frame(600))
        self.assertEqual(output["new_events"][0]["start_timestamp_ms"], 300)

    def test_active_updates_keep_identity_and_never_repeat_feedback(self):
        first = self.activate()["new_events"][0]
        output = self.tracker.update(frame(400))
        self.assertEqual(output["new_events"], [])
        self.assertFalse(output["feedback_allowed"])
        self.assertEqual(output["active_events"][0]["event_id"], first["event_id"])
        self.assertEqual(output["active_events"][0]["duration_ms"], 400)

    def test_stable_clear_condition_recovers_at_exact_duration(self):
        first = self.activate()["new_events"][0]
        self.tracker.update(frame(400, "within_reference"))
        output = self.tracker.update(frame(500, "within_reference"))
        self.assertEqual(output["active_events"][0]["tracking_state"], "clearing")
        output = self.tracker.update(frame(600, "within_reference"))
        recovered = output["new_events"][0]
        self.assertEqual(recovered["status"], "recovered")
        self.assertEqual(recovered["event_id"], first["event_id"])
        self.assertFalse(output["feedback_allowed"])
        self.assertEqual(output["active_events"], [])

    def test_gray_zone_keeps_active_and_cancels_clear_countdown(self):
        self.activate()
        self.tracker.update(frame(400, "within_reference"))
        output = self.tracker.update(frame(500, "gray_zone"))
        self.assertEqual(output["new_events"], [])
        self.assertEqual(output["active_events"][0]["tracking_state"], "active")
        self.tracker.update(frame(600, "within_reference"))
        output = self.tracker.update(frame(700, "within_reference"))
        self.assertEqual(output["new_events"], [])
        output = self.tracker.update(frame(800, "within_reference"))
        self.assertEqual(output["new_events"][0]["status"], "recovered")

    def test_deviation_cancels_recovery_without_new_identity(self):
        first = self.activate()["new_events"][0]
        self.tracker.update(frame(400, "within_reference"))
        output = self.tracker.update(frame(500, "deviation"))
        self.assertEqual(output["new_events"], [])
        self.assertEqual(output["active_events"][0]["event_id"], first["event_id"])

    def test_invalid_or_inapplicable_evidence_interrupts_instead_of_recovers(self):
        for status in ("not_assessable", "not_applicable", "disabled"):
            with self.subTest(status=status):
                tracker = TadasanaEventTracker()
                self.activate(tracker)
                output = tracker.update(frame(400, status))
                event = output["new_events"][0]
                self.assertEqual(event["status"], "interrupted")
                self.assertEqual(event["interruption_reason"], status)
                self.assertEqual(event["duration_ms"], 300)
                self.assertEqual(event["end_timestamp_ms"], 300)
                self.assertFalse(output["feedback_allowed"])
                self.assertEqual(output["active_events"], [])

    def test_occlusion_resets_pending(self):
        self.tracker.update(frame(0))
        self.tracker.update(frame(100))
        self.tracker.update(frame(200, "not_assessable"))
        output = self.tracker.update(frame(300))
        self.assertEqual(output["pending_events"][0]["duration_ms"], 0)
        self.assertEqual(output["new_events"], [])

    def test_gap_interrupts_and_does_not_count_missing_time(self):
        self.activate()
        output = self.tracker.update(frame(501))
        event = output["new_events"][0]
        self.assertEqual(event["status"], "interrupted")
        self.assertEqual(event["interruption_reason"], "frame_gap")
        self.assertEqual(event["duration_ms"], 300)
        self.assertEqual(output["pending_events"][0]["start_timestamp_ms"], 501)
        self.assertFalse(output["feedback_allowed"])

    def test_pending_gap_restarts_without_lifecycle_event(self):
        self.tracker.update(frame(0))
        output = self.tracker.update(frame(101))
        self.assertEqual(output["pending_events"][0]["start_timestamp_ms"], 101)
        self.assertEqual(output["new_events"], [])

    def test_duplicate_and_out_of_order_frames_do_not_mutate_any_state(self):
        first = self.activate()["new_events"][0]
        duplicate = self.tracker.update(frame(300, results=[], phase="arms_up_hold"))
        self.assertTrue(duplicate["ignored"])
        self.assertEqual(duplicate["ignored_reason"], "duplicate_timestamp")
        old = self.tracker.update(frame(250, "not_assessable", rule_version="other"))
        self.assertTrue(old["ignored"])
        self.assertEqual(old["ignored_reason"], "out_of_order_timestamp")
        output = self.tracker.update(frame(400))
        self.assertEqual(output["new_events"], [])
        self.assertEqual(output["active_events"][0]["event_id"], first["event_id"])

    def test_phase_change_interrupts_old_event_and_resets_confirmation(self):
        self.activate()
        output = self.tracker.update(frame(400, phase="arms_up_hold"))
        self.assertEqual(output["new_events"][0]["interruption_reason"], "phase_changed")
        self.assertEqual(output["new_events"][0]["phase"], "arms_down_hold")
        self.assertEqual(output["pending_events"][0]["start_timestamp_ms"], 400)
        self.assertFalse(output["feedback_allowed"])

    def test_version_change_interrupts_old_event_and_resets_confirmation(self):
        self.activate()
        output = self.tracker.update(frame(400, rule_version="test-only-v2"))
        self.assertEqual(output["new_events"][0]["interruption_reason"], "rule_version_changed")
        self.assertEqual(output["new_events"][0]["rule_version"], "test-only-v1")
        self.assertEqual(output["pending_events"][0]["rule_version"], "test-only-v2")

    def test_prepare_and_transition_phases_are_accepted(self):
        for phase in ("prepare", "transition"):
            with self.subTest(phase=phase):
                tracker = TadasanaEventTracker()
                self.activate(tracker)
                output = tracker.update(frame(400, "not_applicable", phase=phase))
                self.assertEqual(output["new_events"][0]["status"], "interrupted")
                self.assertEqual(output["new_events"][0]["interruption_reason"], "phase_changed")
                self.assertEqual(output["active_events"], [])
                self.assertFalse(output["feedback_allowed"])

    def test_context_changes_interrupt_with_original_provenance(self):
        replacements = {
            "source_model": "different-model",
            "feature_version": "new-formula",
            "rules_reviewed": True,
            "execution_mode": "reviewed_rules",
            "phase_source": "automatic",
            "reference_status": "reviewed_reference",
        }
        for key, replacement in replacements.items():
            with self.subTest(key=key):
                tracker = TadasanaEventTracker()
                first = self.activate(tracker)["new_events"][0]
                output = tracker.update(frame(400, **{key: replacement}))
                interrupted = output["new_events"][0]
                self.assertEqual(interrupted["status"], "interrupted")
                self.assertEqual(interrupted["interruption_reason"], "context_changed")
                self.assertEqual(interrupted.get(key), first.get(key))
                self.assertEqual(output["pending_events"][0].get(key), replacement)
                self.assertEqual(output["pending_events"][0]["start_timestamp_ms"], 400)
                self.assertFalse(output["feedback_allowed"])

    def test_missing_and_null_context_are_equivalent(self):
        self.tracker.update(frame(0))
        self.tracker.update(frame(100, feature_version=None))
        self.tracker.update(frame(200))
        output = self.tracker.update(frame(300, feature_version=None))
        self.assertTrue(output["feedback_allowed"])
        self.assertEqual(output["new_events"][0]["start_timestamp_ms"], 0)

    def test_removing_context_field_interrupts(self):
        self.activate()
        next_frame = frame(400)
        del next_frame["source_model"]
        output = self.tracker.update(next_frame)
        self.assertEqual(output["new_events"][0]["interruption_reason"], "context_changed")
        self.assertEqual(output["new_events"][0]["source_model"], "RTMW-x")
        self.assertNotIn("source_model", output["pending_events"][0])

    def test_elapsed_duration_explicitly_includes_gray_and_recovery_time(self):
        self.activate()
        output = self.tracker.update(frame(400, "gray_zone"))
        self.assertEqual(output["active_events"][0]["duration_ms"], 400)
        self.assertEqual(output["active_events"][0]["duration_semantics"], "episode_elapsed")
        self.tracker.update(frame(500, "within_reference"))
        self.tracker.update(frame(600, "within_reference"))
        output = self.tracker.update(frame(700, "within_reference"))
        self.assertEqual(output["new_events"][0]["duration_ms"], 700)
        self.assertEqual(output["new_events"][0]["duration_semantics"], "episode_elapsed")

    def test_missing_rule_interrupts_without_claiming_recovery(self):
        self.activate()
        output = self.tracker.update(frame(400, results=[]))
        self.assertEqual(output["new_events"][0]["status"], "interrupted")
        self.assertEqual(output["new_events"][0]["interruption_reason"], "rule_missing")

    def test_multiple_rules_are_independent(self):
        for timestamp in (0, 100, 200, 300):
            output = self.tracker.update(frame(timestamp, results=[
                rule(), rule("within_reference", rule_id="elbow"),
            ]))
        self.assertEqual(len(output["new_events"]), 1)
        self.assertEqual(output["new_events"][0]["rule_id"], "shoulder_height")
        output = self.tracker.update(frame(400, results=[rule("not_assessable"), rule(rule_id="elbow")]))
        self.assertEqual(output["new_events"][0]["rule_id"], "shoulder_height")
        self.assertEqual(output["pending_events"][0]["rule_id"], "elbow")

    def test_two_instances_do_not_share_state_or_event_identity(self):
        other = TadasanaEventTracker()
        first = self.activate()["new_events"][0]
        output = other.update(frame(300))
        self.assertEqual(output["new_events"], [])
        for timestamp in (400, 500, 600):
            output = other.update(frame(timestamp))
        self.assertNotEqual(output["new_events"][0]["event_id"], first["event_id"])

    def test_reset_allows_timestamp_restart_without_reusing_event_id(self):
        first = self.activate()["new_events"][0]
        self.tracker.reset()
        second = self.activate()["new_events"][0]
        self.assertNotEqual(first["event_id"], second["event_id"])
        self.assertTrue(second["event_id"].endswith("000002"))

    def test_after_recovery_new_event_gets_new_id(self):
        first = self.activate()["new_events"][0]
        for timestamp in (400, 500, 600):
            output = self.tracker.update(frame(timestamp, "within_reference"))
        for timestamp in (700, 800, 900, 1000):
            output = self.tracker.update(frame(timestamp))
        self.assertNotEqual(output["new_events"][0]["event_id"], first["event_id"])

    def test_input_and_output_mutations_do_not_change_tracker_state(self):
        input_frame = frame(0)
        original = deepcopy(input_frame)
        output = self.tracker.update(input_frame)
        self.assertEqual(input_frame, original)
        output["pending_events"][0]["evidence"]["required_keypoint_ids"].clear()
        input_frame["rule_results"][0]["evidence"]["required_keypoint_ids"].clear()
        output = self.tracker.update(frame(100))
        self.assertEqual(output["pending_events"][0]["evidence"]["required_keypoint_ids"], [5, 6, 11, 12])

    def test_invalid_batch_is_rejected_before_state_mutation(self):
        self.tracker.update(frame(0))
        self.tracker.update(frame(100))
        with self.assertRaises(ValueError):
            self.tracker.update(frame(200, results=[rule(), rule(rule_id="bad", temporal={"max_gap_ms": 0})]))
        self.tracker.update(frame(200))
        output = self.tracker.update(frame(300))
        self.assertTrue(output["feedback_allowed"])

    def test_invalid_timestamps_and_temporal_values(self):
        for value in (True, -1, 0.5, float("nan"), float("inf"), "100", None):
            with self.subTest(timestamp=value), self.assertRaises(ValueError):
                self.tracker.update(frame(value))
        for key in ("min_duration_ms", "clear_duration_ms", "max_gap_ms"):
            for value in (True, 0, -1, 1.5, float("nan"), "100"):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.tracker.update(frame(0, results=[rule(temporal={key: value})]))

    def test_nan_evidence_and_invalid_rule_contracts(self):
        variants = [
            frame(0, results=[rule(observed_value=float("nan"))]),
            frame(0, results=[rule(observed_value=True)]),
            frame(0, results=[rule(reference_range=[1, 0])]),
            frame(0, results=[rule(), rule()]),
            frame(0, results=[rule("unknown")]),
            frame(0, results=[rule(["deviation"])]),
            frame(0, results=[rule(temporal={"unexpected": 100})]),
            frame(0, rules_reviewed="false"),
            frame(0, phase="walking"),
            frame(0, phase=["arms_down_hold"]),
            frame(0, rule_version=" "),
        ]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                self.tracker.update(variant)

    def test_temporal_configuration_change_interrupts(self):
        self.activate()
        output = self.tracker.update(frame(400, results=[rule(temporal={
            "min_duration_ms": 400, "clear_duration_ms": 200, "max_gap_ms": 100,
        })]))
        self.assertEqual(output["new_events"][0]["interruption_reason"], "temporal_parameters_changed")
        self.assertEqual(output["pending_events"][0]["duration_ms"], 0)


if __name__ == "__main__":
    unittest.main()
