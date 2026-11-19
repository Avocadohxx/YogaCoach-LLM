"""Replay a feature directory through single-frame rules and one fresh tracker.

Default: review guard + unknown phase => no correction. Geometric preview is
explicitly exploratory and must never be reported as validated action labels.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.pose_rules_tadasana import compare_tadasana_frame, load_rules
from backend.tadasana_event_tracker import TadasanaEventTracker


def _segments(path, source_hash, allow_unreviewed):
    if path is None:
        return []
    config = json.loads(Path(path).read_text())
    if config.get("source_features_sha256") != source_hash:
        raise ValueError("segment file must match this features.jsonl SHA256")
    if type(config.get("reviewed")) is not bool:
        raise ValueError("segment reviewed must be boolean")
    if not config["reviewed"] and not allow_unreviewed:
        raise ValueError("unreviewed segments require explicit exploratory flag")
    segments = config.get("segments")
    if not isinstance(segments, list):
        raise ValueError("segments must be a list")
    previous_end = -1
    for seg in segments:
        if not isinstance(seg, dict):
            raise ValueError("segment must be an object")
        start, end = seg.get("start_ms"), seg.get("end_ms")
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("segment requires nonnegative start_ms < end_ms")
        if start < previous_end:
            raise ValueError("segments must be ordered and non-overlapping")
        if seg.get("phase") not in ("arms_down_hold", "arms_up_hold", "prepare", "transition"):
            raise ValueError("segment phase unsupported")
        previous_end = end
    return segments


def geometric_phase_preview(frame):
    """A bucket only; not a posture recognizer or proof of stable hold."""
    f = frame.get("features", {})
    angles = []
    for name in ("left_arm_torso_angle_deg", "right_arm_torso_angle_deg"):
        item = f.get(name, {})
        if item.get("valid") is not True or not isinstance(item.get("value"), (int, float)):
            return "unknown"
        angles.append(item["value"])
    if all(v > 150 for v in angles):
        return "arms_up_hold"
    if all(v < 30 for v in angles):
        return "arms_down_hold"
    return "transition"


def replay(input_dir: Path, output_dir: Path, *, rules_path=None, segments_path=None,
           allow_unreviewed=False, preview_geometric_phases=False):
    input_dir, output_dir = Path(input_dir).resolve(), Path(output_dir).resolve()
    if input_dir == output_dir or input_dir.is_relative_to(output_dir):
        raise ValueError("output must not overwrite or contain the input directory")
    if preview_geometric_phases and not allow_unreviewed:
        raise ValueError("geometric phase preview requires allow_unreviewed=True")
    if preview_geometric_phases and segments_path is not None:
        raise ValueError("choose explicit segments or geometric preview, not both")
    source = input_dir / "features.jsonl"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    metadata = json.loads((input_dir / "summary.json").read_text())
    source_model = metadata.get("source_metadata", {}).get("model_label")
    camera = metadata.get("source_selection", {}).get("camera_view", "unknown")
    rules = load_rules() if rules_path is None else load_rules(rules_path)
    segments = _segments(segments_path, source_hash, allow_unreviewed)
    phase_reviewed = (json.loads(Path(segments_path).read_text())["reviewed"]
                      if segments_path else False)
    phase_source = ("geometry_preview_NOT_HOLD_GROUND_TRUTH" if preview_geometric_phases
                    else "explicit_segments" if segments_path else "unknown")
    tracker = TadasanaEventTracker()
    frames = 0
    last_accepted = None
    statuses, phases, event_counts = Counter(), Counter(), Counter()
    all_events = []
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".rules-preview-", dir=output_dir) as temp_name:
        temp = Path(temp_name)
        with source.open() as src, (temp / "rule_frames.jsonl").open("w") as trace:
            for line_number, line in enumerate(src, 1):
                if not line.strip():
                    continue
                try:
                    frame = json.loads(line)
                    t = frame["timestamp_ms"]
                    phase = geometric_phase_preview(frame) if preview_geometric_phases else "unknown"
                    if not preview_geometric_phases:
                        for seg in segments:
                            if seg["start_ms"] <= t < seg["end_ms"]:
                                phase = seg["phase"]
                                break
                    result = compare_tadasana_frame(
                        frame, phase=phase, camera_view=camera, source_model=source_model,
                        phase_source=phase_source, ruleset=rules,
                        phase_reviewed=phase_reviewed,
                        allow_unreviewed=allow_unreviewed,
                    )
                    tracked = tracker.update(result)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"features.jsonl line {line_number}: {exc}") from exc
                statuses[result["assessment_status"]] += 1
                if not tracked["ignored"]:
                    last_accepted = tracked
                phases[phase] += 1
                for event in tracked["new_events"]:
                    all_events.append(event)
                    event_counts[event["status"]] += 1
                # Full feature records remain in the source; avoid duplicating them in trace.
                trace_row = {key: val for key, val in tracked.items() if key != "features"}
                trace.write(json.dumps(trace_row, ensure_ascii=False, allow_nan=False) + "\n")
                frames += 1
        summary = {
            "input_dir": str(input_dir), "features_sha256": source_hash,
            "source_video_label": metadata.get("source_selection", {}).get("source_label"),
            "label_is_not_frame_ground_truth": True, "frames": frames,
            "rule_version": rules["version"], "rules_reviewed": rules["reviewed"],
            "phase_source": phase_source, "allow_unreviewed": allow_unreviewed,
            "phase_counts": dict(phases), "assessment_counts": dict(statuses),
            "lifecycle_counts": dict(event_counts), "events": all_events,
            "not_accuracy_evaluation": True, "hold_phases_manually_reviewed": phase_reviewed,
            "end_of_input": {
                "policy": "report_open_events_do_not_invent_recovery",
                "active_events": last_accepted["active_events"] if last_accepted else [],
                "pending_events": last_accepted["pending_events"] if last_accepted else [],
            },
        }
        (temp / "rule_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
        for name in ("rule_frames.jsonl", "rule_summary.json"):
            (temp / name).replace(output_dir / name)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--segments", type=Path)
    parser.add_argument("--allow-unreviewed", action="store_true")
    parser.add_argument("--preview-geometric-phases", action="store_true")
    args = parser.parse_args()
    result = replay(args.input_dir, args.output_dir, rules_path=args.rules,
                    segments_path=args.segments, allow_unreviewed=args.allow_unreviewed,
                    preview_geometric_phases=args.preview_geometric_phases)
    print(json.dumps({key: result[key] for key in (
        "frames", "phase_source", "rules_reviewed", "assessment_counts", "lifecycle_counts"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
