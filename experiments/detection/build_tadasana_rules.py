"""Rebuild the UNREVIEWED rule draft from the saved two-video audit.

Manual design choices (160/165 degrees and timing) are explicit engineering
choices, not optimized estimates or externally validated teaching standards.
"""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def build():
    audit = json.loads((ROOT / "experiments/detection/tadasana_rule_audit.json").read_text())
    correct = audit["sources"]["tadasana_rtmw_correct_2"]
    wrong = audit["sources"]["tadasana_rtmw_incorrect_2"]
    config = {
        "version": "tadasana-rtmw-draft-v1", "reviewed": False, "review_record": None,
        "expected_layout": "COCO-WholeBody 133",
        "allowed_feature_versions": ["dwpose133-geometry-v1"],
        "allowed_source_models": ["RTMW-x", "rtmw_x_384.onnx"],
        "min_keypoint_score": 0.5,
        "evidence_status": "two_source_videos_no_frame_ground_truth_no_hold_review",
        "scope": "front-view 2D geometric observations; raised-arm variant needs explicit phase",
        "provenance": {}, "rules": [],
    }
    for label, source in (("correct", correct), ("incorrect", wrong)):
        config["provenance"][label] = {
            "source_file": source["metadata"]["source_file"],
            "source_sha256": source["consistency"]["source_hash_recorded"],
            "features_jsonl_sha256": source["consistency"]["jsonl_sha256"],
            "frames": source["consistency"]["jsonl_rows"],
            "label_scope": "filename only; not per-frame correctness",
        }

    def rule(rule_id, event, target, feature, unit, phases, reference, trigger,
             clear, mode="monitor_only", transform="identity", evidence=""):
        return dict(
            rule_id=rule_id, event_type=event, target=target, feature_name=feature,
            unit=unit, enabled=True, mode=mode, transform=transform,
            applicable_phases=phases, reference_range=reference,
            trigger_range=trigger, clear_range=clear,
            temporal=dict(min_duration_ms=1500, clear_duration_ms=700, max_gap_ms=500),
            evidence=evidence,
        )

    for side in ("left", "right"):
        name = f"{side}_elbow_angle_deg"
        c = correct["buckets"]["arms_overhead_geometry"]["features"][name]
        w = wrong["buckets"]["arms_overhead_geometry"]["features"][name]
        r = rule(
            f"{side}_elbow_bend_overhead", "elbow_bend", f"{side}_elbow", name,
            "deg", ["arms_up_hold"], [165.0, 180.0], [160.0, 180.0], [165.0, 180.0],
            mode="candidate",
            evidence="Two-arm>150deg geometric bucket only; NOT a verified hold label. "
                     "160deg trigger and 165deg clear are conservative demo choices."
        )
        r["descriptive_reference"] = {
            "group": "arms_overhead_geometry", "group_is_not_ground_truth": True,
            "correct_p05": c["p05"], "correct_median": c["median"],
            "incorrect_p05": w["p05"], "incorrect_median": w["median"],
        }
        config["rules"].append(r)

    config["rules"].extend([
        rule("shoulder_height_monitor", "shoulder_asymmetry", "shoulders",
             "shoulder_height_diff", "torso_ratio", ["arms_down_hold", "arms_up_hold"],
             [0.0, 0.04], [0.0, 0.06], [0.0, 0.04],
             evidence="Highly overlapping distributions; rounded descriptive range only. No events, even in preview."),
        rule("torso_tilt_monitor", "torso_tilt", "torso", "torso_tilt_deg", "deg",
             ["arms_down_hold", "arms_up_hold"], [0.0, 3.0], [0.0, 5.0], [0.0, 3.0],
             transform="abs", evidence="Both sources mostly near upright; abs tilt overlaps, camera roll unverified. No events."),
        rule("stance_monitor", "stance_difference", "ankles", "ankle_spacing_shoulder_ratio",
             "shoulder_width_ratio", ["arms_down_hold", "arms_up_hold"], [0.25, 0.33],
             [0.20, 0.40], [0.25, 0.35],
             evidence="Rounded raised-arm reference bucket only, not a universal stance. Correct video starts wide. No events."),
    ])
    for side in ("left", "right"):
        config["rules"].append(rule(
            f"{side}_upper_arm_monitor", "upper_arm_alignment", f"{side}_upper_arm",
            f"{side}_arm_torso_angle_deg", "deg", ["arms_up_hold"],
            [170.0, 180.0], [160.0, 180.0], [170.0, 180.0],
            evidence="Geometric bucket already selected by arm angle; cannot validate this threshold on the same bucket. No events.",
        ))
    from backend.pose_rules_tadasana import validate_ruleset
    validate_ruleset(config)
    output = ROOT / "knowledge/tadasana_rules.json"
    output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {len(config['rules'])} draft rules; reviewed=False; default feedback guarded.")
    return config


if __name__ == "__main__":
    build()
