"""Build an explicitly unreviewed side-bend rule draft from the saved audit."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build():
    audit = json.loads((ROOT / "experiments/detection/ardhakati_rule_audit.json").read_text())
    variants = ["both_arms_overhead", "single_arm_overhead"]
    holds = ["arms_up_hold", "side_bend_hold"]
    config = dict(
        version="ardhakati-rtmw-draft-v1", exercise="ardhakati_chakrasana",
        reviewed=False, review_record=None, expected_layout="COCO-WholeBody 133",
        allowed_feature_versions=["dwpose133-geometry-v1"],
        allowed_source_models=["RTMW-x", "rtmw_x_384.onnx"], min_keypoint_score=0.5,
        primary_requested_variant="both_arms_overhead",
        source_variant_evidence="geometry_suggests_single_arm_only_not_manually_verified",
        rules=[], provenance={},
        unsupported_checks=[
            "hip_translation_or_fixed_pelvis", "shoulder_depression", "palms_together",
            "head_neutral_or_forward_gaze", "3D_coplanarity_or_rotation",
            "weight_distribution_or_plantar_pressure", "lateral_stretch_sensation",
        ],
        limitations=["two_source_clips_only", "unverified_camera_angle",
                     "no_frame_error_labels_or_hold_annotations", "both_arm_variant_has_no_reference_samples"],
    )
    for label, clip in audit["clips"].items():
        config["provenance"][label] = dict(
            source_directory=clip["source_directory"], files_sha256=clip["files_sha256"],
            frames=clip["frames"], source_label_is_not_frame_ground_truth=True,
            camera_view=clip["camera_view"],
        )

    def rule(identifier, event_type, target, feature, unit, reference, trigger, clear,
             *, mode="candidate", transform="identity", arm="none", phases=None,
             applicable_variants=None, evidence=""):
        return dict(
            rule_id=identifier, event_type=event_type, target=target, feature_name=feature,
            unit=unit, enabled=True, mode=mode, transform=transform, required_arm=arm,
            applicable_phases=holds if phases is None else phases,
            applicable_variants=variants if applicable_variants is None else applicable_variants,
            reference_range=reference, trigger_range=trigger, clear_range=clear,
            temporal=dict(min_duration_ms=1500, clear_duration_ms=700, max_gap_ms=500),
            evidence=evidence,
        )

    for side in ("left", "right"):
        config["rules"].append(rule(
            f"{side}_raised_elbow_bend", "elbow_bend", f"{side}_elbow",
            f"{side}_elbow_angle_deg", "deg", [160.0, 180.0], [150.0, 180.0], [160.0, 180.0],
            arm=side,
            evidence="150deg is below both correct-source whole-video minima (155.71/158.17). "
                     "160deg clear is an engineering hysteresis choice. Both-arm transfer is unvalidated. "
                     "Single-arm mode checks only the explicitly raised arm; not a taught universal limit.",
        ))
        config["rules"].append(rule(
            f"{side}_upper_arm_alignment_both", "upper_arm_alignment", f"{side}_upper_arm",
            f"{side}_arm_torso_angle_deg", "deg", [160.0, 180.0], [150.0, 180.0], [160.0, 180.0],
            arm=side, applicable_variants=["both_arms_overhead"],
            evidence="Requested both-arm version only: large arm-to-central-trunk deviation is a demo candidate. "
                     "No both-arm reference frame exists in the attached clips; 150/160 are unvalidated design values.",
        ))
        config["rules"].append(rule(
            f"{side}_upper_arm_single_monitor", "upper_arm_alignment", f"{side}_upper_arm",
            f"{side}_arm_torso_angle_deg", "deg", [130.0, 180.0], [120.0, 180.0], [130.0, 180.0],
            mode="monitor_only", arm=side, applicable_variants=["single_arm_overhead"],
            evidence="Correct-source bent torso has raised-arm medians about139-144deg. "
                     "Range is an illustrative monitor band, not an active judgement or validated standard.",
        ))
    config["rules"].extend([
        rule("bend_direction_mismatch", "bend_direction_mismatch", "torso", "torso_tilt_deg", "deg",
             [5.0, None], [-5.0, None], [5.0, None], transform="expected_direction",
             phases=["side_bend_hold"],
             evidence="Tilt is multiplied by the independently declared intended image direction. "
                      "Only opposite tilt beyond5deg is a candidate, not insufficient bend. "
                      "Disabled as not_assessable when intended direction comes from this same geometry."),
        rule("lateral_bend_magnitude_monitor", "lateral_bend_magnitude", "torso", "torso_tilt_deg", "deg",
             [15.0, 40.0], [5.0, 50.0], [15.0, 40.0], mode="monitor_only", transform="abs",
             phases=["side_bend_hold"],
             evidence="Both source directions and durations differ; no minimum/maximum teaching angle inferred. "
                      "Monitor bounds are placeholders only; do not coach deeper bending from this value."),
        rule("shoulder_height_monitor", "shoulder_asymmetry", "shoulders", "shoulder_height_diff", "torso_ratio",
             [0.0, 0.8], [0.0, 1.0], [0.0, 0.8], mode="monitor_only",
             phases=["side_bend_hold"],
             evidence="Shoulder-height difference is expected in lateral bending. Never apply Tadasana level-shoulder alarms. "
                      "Bounds are illustrative only."),
        rule("stance_monitor", "stance_difference", "ankles", "ankle_spacing_shoulder_ratio", "shoulder_width_ratio",
             [0.18, 0.30], [0.15, 0.40], [0.18, 0.35], mode="monitor_only",
             phases=["side_bend_hold"],
             evidence="Source ratios vary with projection and preparation. Illustrative monitoring range only; "
                      "cannot measure plantar load or fixed pelvis."),
    ])
    from backend.pose_rules_ardhakati import validate_ruleset
    config = validate_ruleset(config)
    path = ROOT / "knowledge/ardhakati_chakrasana_rules.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {len(config['rules'])} unreviewed side-bend rules.")
    return config


if __name__ == "__main__":
    build()
