"""Offline integration: single-frame evidence -> lifecycle -> C packets."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.ardhakati_event_tracker import ArdhakatiEventTracker
from backend.pose_rules_ardhakati import compare_ardhakati_frame
from experiments.detection.replay_ardhakati_rules import (
    geometric_context_preview, load_segments, replay,
)


def feature_frame(timestamp_ms, left_elbow=140.0, left_arm=175.0,
                  right_arm=175.0, tilt=25.0):
    values = {
        "left_elbow_angle_deg": left_elbow, "right_elbow_angle_deg": 175.0,
        "left_arm_torso_angle_deg": left_arm,
        "right_arm_torso_angle_deg": right_arm, "torso_tilt_deg": tilt,
    }
    return {
        "timestamp_ms": timestamp_ms, "layout": "COCO-WholeBody 133",
        "feature_version": "dwpose133-geometry-v1", "coordinate_space": "image_pixels",
        "features": {name: {"value": value, "unit": "deg", "valid": True,
                            "min_keypoint_score": 0.8} for name, value in values.items()},
    }


def evaluation(frame, **overrides):
    context = {
        "phase": "side_bend_hold", "movement_variant": "both_arms_overhead",
        "bend_direction": "image_right", "direction_source": "manual_instruction",
        "source_model": "RTMW-x", "camera_view": "front", "allow_unreviewed": True,
    }
    context.update(overrides)
    return compare_ardhakati_frame(frame, **context)


def write_source(root, frames, camera="front"):
    source = root / "source"
    source.mkdir()
    path = source / "features.jsonl"
    path.write_text("".join(json.dumps(frame) + "\n" for frame in frames))
    (source / "summary.json").write_text(json.dumps({
        "source_metadata": {"model_label": "RTMW-x"},
        "source_selection": {"camera_view": camera, "source_label": "synthetic"},
    }))
    return source, hashlib.sha256(path.read_bytes()).hexdigest()


def segment(start=0, end=10000, **overrides):
    context = {
        "start_ms": start, "end_ms": end, "phase": "side_bend_hold",
        "movement_variant": "both_arms_overhead", "bend_direction": "image_right",
    }
    context.update(overrides)
    return context


def write_segments(root, source_hash, *, reviewed=True, segments=None):
    path = root / "segments.json"
    path.write_text(json.dumps({
        "source_features_sha256": source_hash, "reviewed": reviewed,
        "segments": [segment()] if segments is None else segments,
    }))
    return path


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class ArdhakatiIntegrationTests(unittest.TestCase):
    def test_comparator_tracker_confirms_once_and_recovers_after_stable_700_ms(self):
        tracker = ArdhakatiEventTracker()
        for timestamp in (0, 500, 1000, 1500):
            comparison = evaluation(feature_frame(timestamp))
            self.assertFalse(comparison["feedback_allowed"])
            output = tracker.update(comparison)
        self.assertEqual([e["rule_id"] for e in output["new_events"]], ["left_raised_elbow_bend"])
        event_id = output["new_events"][0]["event_id"]
        self.assertTrue(output["feedback_allowed"])
        for timestamp in (1600, 2000, 2300):
            output = tracker.update(evaluation(feature_frame(timestamp, left_elbow=160)))
        self.assertEqual(output["new_events"][0]["status"], "recovered")
        self.assertEqual(output["new_events"][0]["event_id"], event_id)
        self.assertFalse(output["feedback_allowed"])

    def test_ending_hold_or_changing_side_interrupts_original_evidence(self):
        for overrides in ({"phase": "return_upright"}, {"bend_direction": "image_left"}):
            with self.subTest(overrides=overrides):
                tracker = ArdhakatiEventTracker()
                for timestamp in (0, 500, 1000, 1500):
                    tracker.update(evaluation(feature_frame(timestamp)))
                output = tracker.update(evaluation(feature_frame(2000), **overrides))
                self.assertEqual(output["new_events"][0]["status"], "interrupted")
                self.assertEqual(output["new_events"][0]["bend_direction"], "image_right")

    def test_default_replay_is_silent_and_retains_unverified_camera(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            source, _ = write_source(root, [feature_frame(t) for t in (0, 500, 1000, 1500)], camera="angle_1_unverified")
            output = root / "out"
            summary = replay(source, output)
            self.assertEqual(summary["lifecycle_counts"], {})
            self.assertEqual(summary["agent_packets"], 0)
            self.assertEqual(summary["camera_view"], "angle_1_unverified")
            self.assertEqual((output / "agent_events.jsonl").read_text(), "")
            trace = read_jsonl(output / "rule_frames.jsonl")
            self.assertTrue(all(not f["feedback_allowed"] for f in trace))
            self.assertTrue(all(f["execution_mode"] == "review_guard" for f in trace))

    def test_reviewed_segments_do_not_bypass_unreviewed_rule_guard(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            source, source_hash = write_source(root, [feature_frame(t) for t in (0, 500, 1000, 1500)])
            segments = write_segments(root, source_hash)
            summary = replay(source, root / "out", segments_path=segments)
            self.assertEqual(summary["lifecycle_counts"], {})
            self.assertTrue(summary["segments_reviewed"])
            self.assertFalse(summary["rules_reviewed"])

    def test_manual_replay_agent_packets_only_started_with_context_and_provenance(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            frames = ([feature_frame(t) for t in (0, 500, 1000, 1500)]
                      + [feature_frame(t, left_elbow=160) for t in (1600, 2000, 2300)])
            source, source_hash = write_source(root, frames)
            segments = write_segments(root, source_hash)
            output = root / "out"
            summary = replay(source, output, segments_path=segments, allow_unreviewed=True)
            self.assertEqual(summary["lifecycle_counts"], {"started": 1, "recovered": 1})
            packets = read_jsonl(output / "agent_events.jsonl")
            self.assertEqual(len(packets), 1)
            packet = packets[0]
            self.assertEqual(packet["schema_version"], "ardhakati-bc-demo-v1")
            self.assertEqual(packet["phase_source"], "explicit_segments")
            self.assertEqual(packet["direction_source"], "explicit_segments")
            self.assertEqual(packet["camera_view_source"], "source_metadata")
            self.assertTrue(packet["phase_reviewed"])
            self.assertFalse(packet["rules_reviewed"])
            self.assertEqual(packet["execution_mode"], "exploratory_preview")
            self.assertTrue(packet["feedback_allowed"])
            self.assertEqual([e["status"] for e in packet["new_events"]], ["started"])
            self.assertNotIn("features", read_jsonl(output / "rule_frames.jsonl")[0])

    def test_eof_duplicate_keeps_last_accepted_active_event_snapshot(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            frames = [feature_frame(t) for t in (0, 500, 1000, 1500)]
            frames.append(feature_frame(1500, left_elbow=175))
            source, source_hash = write_source(root, frames)
            segments = write_segments(root, source_hash)
            output = root / "out"
            summary = replay(source, output, segments_path=segments, allow_unreviewed=True)
            self.assertEqual(summary["lifecycle_counts"], {"started": 1})
            self.assertEqual(summary["end_of_input"]["policy"], "report_open_events_do_not_invent_recovery")
            self.assertEqual(len(summary["end_of_input"]["active_events"]), 1)
            self.assertEqual(summary["end_of_input"]["active_events"][0]["duration_ms"], 1500)
            self.assertTrue(read_jsonl(output / "rule_frames.jsonl")[-1]["ignored"])

    def test_preview_requires_two_explicit_optins_and_conflicts_are_rejected(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            source, source_hash = write_source(root, [feature_frame(0)])
            segments = write_segments(root, source_hash)
            for kwargs in (
                {"preview_geometric_context": True},
                {"preview_geometric_context": True, "allow_unreviewed": True},
                {"preview_geometric_context": True, "movement_variant": "both_arms_overhead"},
                {"preview_geometric_context": True, "allow_unreviewed": True,
                 "movement_variant": "both_arms_overhead", "segments_path": segments},
                {"movement_variant": "both_arms_overhead", "segments_path": segments},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    replay(source, root / "out", **kwargs)

    def test_geometry_preview_does_not_self_validate_bend_direction(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            source, _ = write_source(root, [feature_frame(t) for t in (0, 500, 1000, 1500)])
            output = root / "out"
            summary = replay(source, output, preview_geometric_context=True,
                             allow_unreviewed=True, movement_variant="both_arms_overhead")
            self.assertEqual(summary["started_by_rule"], {"left_raised_elbow_bend": 1})
            trace = read_jsonl(output / "rule_frames.jsonl")
            rule = next(r for r in trace[-1]["rule_results"] if r["rule_id"] == "bend_direction_mismatch")
            self.assertEqual(rule["status"], "not_assessable")
            self.assertEqual(rule["reason"], "independent_intended_direction_required")
            packet = read_jsonl(output / "agent_events.jsonl")[0]
            self.assertEqual(packet["direction_source"], "geometry_preview_NOT_HOLD_GROUND_TRUTH")
            self.assertFalse(packet["phase_reviewed"])
            self.assertFalse(packet["direction_reviewed"])

    def test_camera_override_is_explicit_and_retains_unverified_provenance(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            source, source_hash = write_source(root, [feature_frame(t) for t in (0, 500, 1000, 1500)], camera="angle_1_unverified")
            segments = write_segments(root, source_hash)
            blocked = replay(source, root / "blocked", segments_path=segments, allow_unreviewed=True)
            self.assertEqual(blocked["agent_packets"], 0)
            allowed = replay(source, root / "override", segments_path=segments,
                             allow_unreviewed=True, camera_view="front")
            self.assertEqual(allowed["agent_packets"], 1)
            self.assertEqual(allowed["source_camera_view"], "angle_1_unverified")
            self.assertEqual(allowed["camera_view_source"], "caller_override_unverified")
            self.assertFalse(allowed["camera_view_verified"])

    def test_segment_hash_order_overlap_and_boundary_validation(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            source_hash = "test-sha256"
            path = write_segments(root, source_hash, segments=[segment(0, 1000), segment(1000, 2000)])
            loaded, reviewed = load_segments(path, source_hash, False)
            self.assertEqual(len(loaded), 2)
            self.assertTrue(reviewed)
            with self.assertRaises(ValueError):
                load_segments(path, "different-sha256", False)
            for segments in ([segment(0, 1000), segment(999, 2000)],
                             [segment(1000, 2000), segment(0, 1000)],
                             [segment(1000, 1000)], [segment(True, 1000)],
                             [segment(movement_variant="unknown")],
                             [segment(raised_arm_side="left")]):
                with self.subTest(segments=segments):
                    path = write_segments(root, source_hash, segments=segments)
                    with self.assertRaises(ValueError):
                        load_segments(path, source_hash, False)

    def test_unreviewed_segments_require_explicit_optin(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            path = write_segments(root, "sha", reviewed=False)
            with self.assertRaises(ValueError):
                load_segments(path, "sha", False)
            _, reviewed = load_segments(path, "sha", True)
            self.assertFalse(reviewed)

    def test_geometry_preview_declares_single_arm_and_rejects_invalid_scores(self):
        context = geometric_context_preview(feature_frame(0, left_arm=140, right_arm=20), "single_arm_overhead")
        self.assertEqual(context["raised_arm_side"], "left")
        self.assertEqual(context["bend_direction"], "image_right")
        invalid = feature_frame(0)
        invalid["features"]["torso_tilt_deg"]["min_keypoint_score"] = float("nan")
        self.assertEqual(geometric_context_preview(invalid, "both_arms_overhead")["phase"], "unknown")

    def test_segments_use_half_open_end_boundary(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            source, source_hash = write_source(root, [feature_frame(0), feature_frame(500)])
            segments = write_segments(root, source_hash, segments=[segment(0, 500)])
            output = root / "out"
            replay(source, output, segments_path=segments, allow_unreviewed=True)
            trace = read_jsonl(output / "rule_frames.jsonl")
            self.assertEqual(trace[0]["phase"], "side_bend_hold")
            self.assertEqual(trace[1]["phase"], "unknown")
            self.assertFalse(trace[1]["phase_reviewed"])


if __name__ == "__main__":
    unittest.main()
