"""B: end-to-end rule→tracker and replay guard tests without source video labels."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from backend.pose_rules_tadasana import compare_tadasana_frame, load_rules
from backend.tadasana_event_tracker import TadasanaEventTracker
from experiments.detection.replay_tadasana_rules import replay
from tests.test_pose_rules_tadasana import frame


class RulesIntegrationTests(unittest.TestCase):
    def test_one_continuous_candidate_produces_one_started(self):
        tracker = TadasanaEventTracker()
        events = []
        for t in range(0, 2401, 100):
            evaluation = compare_tadasana_frame(
                frame(150, timestamp_ms=t), phase="arms_up_hold", camera_view="front",
                source_model="RTMW-x", allow_unreviewed=True,
            )
            out = tracker.update(evaluation)
            events.extend(out["new_events"])
        started = [e for e in events if e["status"] == "started"]
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["duration_ms"], 1500)
        self.assertFalse(started[0]["rules_reviewed"])
        self.assertEqual(started[0]["execution_mode"], "exploratory_preview")

    def test_default_guard_remains_silent(self):
        tracker = TadasanaEventTracker()
        for t in range(0, 3001, 100):
            out = tracker.update(compare_tadasana_frame(
                frame(140, timestamp_ms=t), phase="arms_up_hold", camera_view="front",
                source_model="RTMW-x",
            ))
            self.assertFalse(out["feedback_allowed"])
            self.assertEqual(out["new_events"], [])

    def test_open_reference_bound_is_compatible_with_tracker(self):
        rules = load_rules()
        rules["rules"][0]["reference_range"] = [None, 180.0]
        out = TadasanaEventTracker().update(compare_tadasana_frame(
            frame(150), phase="arms_up_hold", camera_view="front",
            source_model="RTMW-x", allow_unreviewed=True, ruleset=rules,
        ))
        self.assertEqual(out["pending_events"][0]["reference_range"], [None, 180.0])

    def test_transition_interrupts_instead_of_recovering(self):
        tracker = TadasanaEventTracker()
        for t in range(0, 1501, 100):
            tracker.update(compare_tadasana_frame(
                frame(150, timestamp_ms=t), phase="arms_up_hold", camera_view="front",
                source_model="RTMW-x", allow_unreviewed=True,
            ))
        out = tracker.update(compare_tadasana_frame(
            frame(150, timestamp_ms=1600), phase="transition", camera_view="front",
            source_model="RTMW-x", allow_unreviewed=True,
        ))
        self.assertEqual([e["status"] for e in out["new_events"]], ["interrupted"])
        self.assertFalse(out["feedback_allowed"])

    def test_replay_defaults_and_explicit_preview(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source"
            source.mkdir()
            rows = [frame(150, timestamp_ms=t) for t in range(0, 2001, 100)]
            (source / "features.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            (source / "summary.json").write_text(json.dumps({
                "source_metadata": {"model_label": "RTMW-x"},
                "source_selection": {"camera_view": "front", "source_label": "synthetic"},
            }))
            out = replay(source, root / "guard")
            self.assertEqual(out["lifecycle_counts"], {})
            out = replay(source, root / "preview", allow_unreviewed=True,
                         preview_geometric_phases=True)
            self.assertEqual(out["lifecycle_counts"].get("started"), 1)
            self.assertFalse(out["hold_phases_manually_reviewed"])
            # An ignored duplicate/out-of-order tail must not erase open events.
            with (source / "features.jsonl").open("a") as f:
                f.write(json.dumps(rows[-1]) + "\n")
                f.write(json.dumps(rows[-2]) + "\n")
            out = replay(source, root / "duplicate_tail", allow_unreviewed=True,
                         preview_geometric_phases=True)
            self.assertEqual(len(out["end_of_input"]["active_events"]), 1)
            with self.assertRaises(ValueError):
                replay(source, root / "bad", preview_geometric_phases=True)
            segment_file = root / "segments.json"
            segment_file.write_text(json.dumps({
                "source_features_sha256": hashlib.sha256((source / "features.jsonl").read_bytes()).hexdigest(),
                "reviewed": False,
                "segments": [{"start_ms": 0, "end_ms": 2100, "phase": "arms_up_hold"}],
            }))
            with self.assertRaises(ValueError):
                replay(source, root / "unreviewed", segments_path=segment_file)
            out = replay(source, root / "explicit", allow_unreviewed=True,
                         segments_path=segment_file)
            self.assertEqual(out["lifecycle_counts"].get("started"), 1)


if __name__ == "__main__":
    unittest.main()
