"""Offline side-bend rules -> continuous events -> draft B-to-C packets.

Default retains source view (angle_1_unverified), unknown phase and rule guard.
Geometry preview needs explicit variant and opt-in; it is not a hold classifier.
"""
import argparse
from collections import Counter
import hashlib
import json
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.ardhakati_event_tracker import ArdhakatiEventTracker
from backend.pose_rules_ardhakati import (
    DIRECTIONS, PHASES, VARIANTS, compare_ardhakati_frame, load_rules,
)


def _value(frame, name):
    item = frame.get("features", {}).get(name, {})
    value = item.get("value")
    if (item.get("valid") is not True or type(value) not in (int, float)
            or not isfinite(value) or item.get("unit") != "deg"
            or type(item.get("min_keypoint_score")) not in (int, float)
            or not isfinite(item["min_keypoint_score"]) or item["min_keypoint_score"] < 0.5
            or abs(value) > 180 or (name != "torso_tilt_deg" and value < 0)):
        return None
    return value


def geometric_context_preview(frame, variant):
    """Buckets may contain transitions; no stable-hold inference is claimed.

    Torso-based buckets do not require the candidate arm alignment to be good.
    Raised-arm inference in single-arm mode is only a debug convenience and is
    marked as geometry-derived. Resulting arm-dependent candidates are only a
    debug replay, not an independent validation or an accuracy measurement.
    """
    tilt = _value(frame, "torso_tilt_deg")
    left = _value(frame, "left_arm_torso_angle_deg")
    right = _value(frame, "right_arm_torso_angle_deg")
    direction = "unknown"
    arm = "unknown"
    phase = "unknown"
    if variant == "single_arm_overhead" and left is not None and right is not None:
        if left > 60 and right < 60:
            arm = "left"
        elif right > 60 and left < 60:
            arm = "right"
    if tilt is not None and abs(tilt) > 15:
        phase = "side_bend_hold"
        direction = "image_right" if tilt > 0 else "image_left"
    elif tilt is not None and abs(tilt) <= 5 and left is not None and right is not None:
        if left < 30 and right < 30:
            phase = "prepare"
        else:
            phase = "transition"
    elif tilt is not None:
        phase = "transition"
    return dict(phase=phase, movement_variant=variant, raised_arm_side=arm,
                bend_direction=direction)


def load_segments(path, source_hash, allow_unreviewed):
    if path is None:
        return [], False
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict) or raw.get("source_features_sha256") != source_hash:
        raise ValueError("segment configuration must match source features SHA256")
    if type(raw.get("reviewed")) is not bool:
        raise ValueError("segment reviewed must be boolean")
    if not raw["reviewed"] and not allow_unreviewed:
        raise ValueError("unreviewed segments need explicit exploratory opt-in")
    segments = raw.get("segments")
    if not isinstance(segments, list):
        raise ValueError("segments must be a list")
    previous_end = -1
    for seg in segments:
        if not isinstance(seg, dict):
            raise ValueError("segment must be an object")
        start, end = seg.get("start_ms"), seg.get("end_ms")
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("segment needs nonnegative start_ms < end_ms")
        if start < previous_end:
            raise ValueError("segments must be ordered and non-overlapping")
        if seg.get("phase") not in PHASES - {"unknown"}:
            raise ValueError("unsupported phase in segment")
        if seg.get("movement_variant") not in VARIANTS - {"unknown"}:
            raise ValueError("segment must explicitly specify movement_variant")
        if seg.get("bend_direction", "unknown") not in DIRECTIONS:
            raise ValueError("unsupported segment direction")
        if seg.get("raised_arm_side", "unknown") not in {"unknown", "left", "right"}:
            raise ValueError("unsupported raised_arm_side")
        if seg["movement_variant"] == "both_arms_overhead" and seg.get("raised_arm_side", "unknown") != "unknown":
            raise ValueError("both-arm segment cannot declare one raised arm")
        previous_end = end
    return segments, raw["reviewed"]


def replay(input_dir, output_dir, *, rules_path=None, segments_path=None,
           allow_unreviewed=False, preview_geometric_context=False,
           movement_variant="unknown", camera_view=None):
    source_dir, output_dir = Path(input_dir).resolve(), Path(output_dir).resolve()
    if source_dir == output_dir or source_dir.is_relative_to(output_dir):
        raise ValueError("output must not overwrite or contain input directory")
    if movement_variant not in VARIANTS:
        raise ValueError("unsupported movement_variant")
    if preview_geometric_context and (not allow_unreviewed or movement_variant == "unknown"):
        raise ValueError("geometry preview needs allow_unreviewed and an explicit movement_variant")
    if preview_geometric_context and segments_path is not None:
        raise ValueError("choose geometric preview or explicit segments")
    if segments_path is not None and movement_variant != "unknown":
        raise ValueError("with segments, specify movement_variant inside each segment")
    source = source_dir / "features.jsonl"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    metadata = json.loads((source_dir / "summary.json").read_text())
    source_camera = metadata.get("source_selection", {}).get("camera_view", "unknown")
    camera = source_camera if camera_view is None else camera_view
    camera_source = "source_metadata" if camera_view is None else "caller_override_unverified"
    model = metadata.get("source_metadata", {}).get("model_label")
    segments, segments_reviewed = load_segments(segments_path, source_hash, allow_unreviewed)
    rules = load_rules() if rules_path is None else load_rules(rules_path)
    tracker = ArdhakatiEventTracker()
    frames = packets = 0
    last_accepted = None
    statuses, phases, lifecycle = Counter(), Counter(), Counter()
    per_rule, directions, arms = Counter(), Counter(), Counter()
    events = []
    source_tag = ("geometry_preview_NOT_HOLD_GROUND_TRUTH" if preview_geometric_context
                  else "explicit_segments" if segments_path else "unknown")
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ardhakati-replay-", dir=output_dir) as temp_name:
        temp = Path(temp_name)
        with source.open() as src, (temp / "rule_frames.jsonl").open("w") as trace, (temp / "agent_events.jsonl").open("w") as handoff:
            for line_number, line in enumerate(src, 1):
                if not line.strip():
                    continue
                try:
                    frame = json.loads(line)
                    context = dict(phase="unknown", movement_variant=movement_variant,
                                   bend_direction="unknown", raised_arm_side="unknown")
                    in_segment = False
                    if preview_geometric_context:
                        context = geometric_context_preview(frame, movement_variant)
                    else:
                        for seg in segments:
                            if seg["start_ms"] <= frame["timestamp_ms"] < seg["end_ms"]:
                                context = {key: seg.get(key, "unknown") for key in context}
                                in_segment = True
                                break
                    reviewed = segments_reviewed and in_segment
                    evaluation = compare_ardhakati_frame(
                        frame, **context, source_model=model, camera_view=camera,
                        camera_view_source=camera_source, camera_view_verified=False,
                        phase_source=source_tag, phase_reviewed=reviewed,
                        direction_source=source_tag, direction_reviewed=reviewed,
                        variant_source=source_tag if in_segment else "caller_declared",
                        variant_reviewed=reviewed,
                        raised_arm_source=source_tag, raised_arm_reviewed=reviewed,
                        ruleset=rules, allow_unreviewed=allow_unreviewed,
                    )
                    tracked = tracker.update(evaluation)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"features.jsonl line {line_number}: {exc}") from exc
                if not tracked["ignored"]:
                    last_accepted = tracked
                statuses[evaluation["assessment_status"]] += 1
                phases[evaluation["phase"]] += 1
                directions[evaluation["bend_direction"]] += 1
                arms[evaluation["raised_arm_side"]] += 1
                for event in tracked["new_events"]:
                    events.append(event)
                    lifecycle[event["status"]] += 1
                    if event["status"] == "started":
                        per_rule[event["rule_id"]] += 1
                trace.write(json.dumps({k: v for k, v in tracked.items() if k != "features"}, ensure_ascii=False, allow_nan=False) + "\n")
                started = [e for e in tracked["new_events"] if e["status"] == "started"]
                if tracked["feedback_allowed"] and started:
                    packet = {k: tracked[k] for k in (
                        "exercise", "timestamp_ms", "rule_version", "feature_version", "source_model",
                        "phase", "phase_source", "phase_reviewed", "movement_variant", "variant_source", "variant_reviewed",
                        "bend_direction", "direction_source", "direction_reviewed", "raised_arm_side", "raised_arm_source", "raised_arm_reviewed",
                        "camera_view", "camera_view_source", "camera_view_verified", "rules_reviewed",
                        "execution_mode", "reference_status", "assessment_coverage", "unsupported_checks",
                    )}
                    packet.update(schema_version="ardhakati-bc-demo-v1", feedback_allowed=True, new_events=started)
                    handoff.write(json.dumps(packet, ensure_ascii=False, allow_nan=False) + "\n")
                    packets += 1
                frames += 1
        summary = dict(
            input_dir=str(source_dir), features_sha256=source_hash,
            source_video_label=metadata.get("source_selection", {}).get("source_label"),
            label_is_not_frame_ground_truth=True, frames=frames,
            rule_version=rules["version"], rules_reviewed=rules["reviewed"],
            allow_unreviewed=allow_unreviewed, context_source=source_tag,
            segments_reviewed=segments_reviewed, camera_view=camera,
            source_camera_view=source_camera, camera_view_source=camera_source, camera_view_verified=False,
            requested_movement_variant=movement_variant,
            source_variant_evidence=rules["source_variant_evidence"],
            phase_counts=dict(phases), direction_counts=dict(directions), raised_arm_counts=dict(arms),
            assessment_counts=dict(statuses), lifecycle_counts=dict(lifecycle),
            started_by_rule=dict(per_rule), agent_packets=packets, events=events,
            not_accuracy_evaluation=True,
            end_of_input=dict(policy="report_open_events_do_not_invent_recovery",
                              active_events=last_accepted["active_events"] if last_accepted else [],
                              pending_events=last_accepted["pending_events"] if last_accepted else []),
        )
        (temp / "rule_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        for name in ("rule_frames.jsonl", "rule_summary.json", "agent_events.jsonl"):
            (temp / name).replace(output_dir / name)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--segments", type=Path)
    parser.add_argument("--allow-unreviewed", action="store_true")
    parser.add_argument("--preview-geometric-context", action="store_true")
    parser.add_argument("--movement-variant", choices=sorted(VARIANTS), default="unknown")
    parser.add_argument("--camera-view", choices=["unknown", "front", "side", "back", "angle_1_unverified"])
    args = parser.parse_args()
    result = replay(args.input_dir, args.output_dir, rules_path=args.rules, segments_path=args.segments,
                    allow_unreviewed=args.allow_unreviewed, preview_geometric_context=args.preview_geometric_context,
                    movement_variant=args.movement_variant, camera_view=args.camera_view)
    print(json.dumps({key: result[key] for key in (
        "frames", "camera_view", "requested_movement_variant", "rules_reviewed",
        "assessment_counts", "lifecycle_counts", "agent_packets"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
