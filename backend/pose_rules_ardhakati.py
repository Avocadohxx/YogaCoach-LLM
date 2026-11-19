"""Single-frame, phase/variant-aware 2D Ardhakati Chakrasana evidence.

Consumes the existing features.jsonl schema, not images or raw keypoints.
No session/pose ID is required; this module is specific to this exercise.
"""
from copy import deepcopy
import json
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Mapping


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "knowledge/ardhakati_chakrasana_rules.json"
PHASES = {"unknown", "prepare", "arms_down_hold", "arms_up_hold", "transition",
          "side_bend_hold", "return_upright"}
VARIANTS = {"unknown", "both_arms_overhead", "single_arm_overhead"}
DIRECTIONS = {"unknown", "image_left", "image_right"}
UNITS = {
    "shoulder_height_diff": "torso_ratio", "torso_tilt_deg": "deg",
    "left_elbow_angle_deg": "deg", "right_elbow_angle_deg": "deg",
    "left_arm_torso_angle_deg": "deg", "right_arm_torso_angle_deg": "deg",
    "ankle_spacing_shoulder_ratio": "shoulder_width_ratio",
}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _safe(value):
    if isinstance(value, Real) and not isinstance(value, bool) and not _number(value):
        return None
    if isinstance(value, Mapping):
        return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    return deepcopy(value)


def _interval(bounds, field):
    if (not isinstance(bounds, list) or len(bounds) != 2
            or any(v is not None and not _number(v) for v in bounds)
            or (all(v is not None for v in bounds) and bounds[0] > bounds[1])):
        raise ValueError(f"{field} must be [lower, upper], with null open bounds allowed")


def _inside(value, bounds):
    return ((bounds[0] is None or value >= bounds[0])
            and (bounds[1] is None or value <= bounds[1]))


def validate_ruleset(raw):
    if not isinstance(raw, Mapping):
        raise ValueError("ruleset must be an object")
    config = deepcopy(dict(raw))
    if not isinstance(config.get("version"), str) or not config["version"].strip():
        raise ValueError("version is required")
    if type(config.get("reviewed")) is not bool:
        raise ValueError("reviewed must be boolean")
    if config["reviewed"] and not config.get("review_record"):
        raise ValueError("reviewed rules need a non-empty review_record")
    if config.get("exercise") != "ardhakati_chakrasana":
        raise ValueError("wrong exercise configuration")
    if config.get("expected_layout") != "COCO-WholeBody 133":
        raise ValueError("unsupported layout")
    for field in ("allowed_source_models", "allowed_feature_versions"):
        values = config.get(field)
        if (not isinstance(values, list) or not values
                or not all(isinstance(v, str) and v for v in values)):
            raise ValueError(f"{field} must be a nonempty string list")
    if not _number(config.get("min_keypoint_score")) or config["min_keypoint_score"] < 0:
        raise ValueError("min_keypoint_score must be finite and nonnegative")
    if not isinstance(config.get("rules"), list) or not config["rules"]:
        raise ValueError("rules must be a nonempty list")
    seen = set()
    for rule in config["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("rule must be an object")
        for key in ("rule_id", "event_type", "target", "feature_name"):
            if not isinstance(rule.get(key), str) or not rule[key].strip():
                raise ValueError(f"rule requires {key}")
        if rule["rule_id"] in seen:
            raise ValueError("duplicate rule_id")
        seen.add(rule["rule_id"])
        if rule["feature_name"] not in UNITS or rule.get("unit") != UNITS[rule["feature_name"]]:
            raise ValueError("unsupported feature or mismatched unit")
        if type(rule.get("enabled")) is not bool or rule.get("mode") not in {"candidate", "monitor_only"}:
            raise ValueError("enabled/mode invalid")
        if rule.get("transform") not in {"identity", "abs", "expected_direction"}:
            raise ValueError("unsupported transform")
        if rule["transform"] == "expected_direction" and rule["feature_name"] != "torso_tilt_deg":
            raise ValueError("expected_direction requires signed torso tilt")
        if rule.get("required_arm") not in {"none", "left", "right"}:
            raise ValueError("required_arm must be none/left/right")
        for key, choices in (("applicable_phases", PHASES - {"unknown", "prepare", "transition", "return_upright"}),
                             ("applicable_variants", VARIANTS - {"unknown"})):
            values = rule.get(key)
            if not isinstance(values, list) or not values or any(v not in choices for v in values):
                raise ValueError(f"invalid {key}")
        for key in ("reference_range", "trigger_range", "clear_range"):
            _interval(rule.get(key), key)
        trigger, clear = rule["trigger_range"], rule["clear_range"]
        if (trigger[0] is not None and (clear[0] is None or clear[0] < trigger[0])
                or trigger[1] is not None and (clear[1] is None or clear[1] > trigger[1])):
            raise ValueError("clear_range must be inside trigger_range")
        temporal = rule.get("temporal")
        if (not isinstance(temporal, dict)
                or set(temporal) != {"min_duration_ms", "clear_duration_ms", "max_gap_ms"}
                or any(type(v) is not int or v <= 0 for v in temporal.values())):
            raise ValueError("temporal needs three positive integer millisecond settings")
    return config


def load_rules(path=DEFAULT_RULES_PATH):
    return validate_ruleset(json.loads(Path(path).read_text()))


def compare_ardhakati_frame(
    frame, *, phase="unknown", movement_variant="unknown", raised_arm_side="unknown",
    bend_direction="unknown", camera_view="unknown", source_model=None,
    phase_source="caller_declared", phase_reviewed=False,
    direction_source="caller_declared", direction_reviewed=False,
    variant_source="caller_declared", variant_reviewed=False,
    raised_arm_source="caller_declared", raised_arm_reviewed=False,
    camera_view_source="caller_declared", camera_view_verified=False,
    allow_unreviewed=False, ruleset=None,
):
    """Return instantaneous evidence; feedback_allowed is ALWAYS False.

    bend_direction is the INTENDED image-space direction, not anatomy. A
    direction guessed from this same tilt cannot test direction mismatch.
    single_arm_overhead additionally needs explicit raised_arm_side.
    """
    if not isinstance(frame, Mapping):
        raise ValueError("frame must be a feature object")
    t = frame.get("timestamp_ms")
    if type(t) is not int or t < 0:
        raise ValueError("timestamp_ms must be a nonnegative integer")
    if phase not in PHASES or movement_variant not in VARIANTS or bend_direction not in DIRECTIONS:
        raise ValueError("unsupported phase, movement_variant, or bend_direction")
    if raised_arm_side not in {"unknown", "left", "right"}:
        raise ValueError("raised_arm_side must be unknown/left/right")
    if movement_variant == "both_arms_overhead" and raised_arm_side != "unknown":
        raise ValueError("both-arm variant does not accept a single raised_arm_side")
    if camera_view not in {"unknown", "front", "side", "back", "angle_1_unverified"}:
        raise ValueError("unsupported camera_view")
    provenance = dict(
        phase_source=phase_source, direction_source=direction_source,
        variant_source=variant_source, raised_arm_source=raised_arm_source,
        camera_view_source=camera_view_source,
    )
    if any(not isinstance(v, str) or not v.strip() for v in provenance.values()):
        raise ValueError("provenance sources must be nonempty strings")
    for value in (phase_reviewed, direction_reviewed, variant_reviewed,
                  raised_arm_reviewed, camera_view_verified, allow_unreviewed):
        if type(value) is not bool:
            raise ValueError("review/preview flags must be boolean")
    rules = load_rules() if ruleset is None else validate_ruleset(ruleset)
    blockers = []
    for key, value, reason in (
        ("layout", rules["expected_layout"], "layout_mismatch"),
        ("coordinate_space", "image_pixels", "coordinate_space_mismatch"),
    ):
        if frame.get(key) != value:
            blockers.append(reason)
    if frame.get("feature_version") not in rules["allowed_feature_versions"]:
        blockers.append("feature_version_mismatch")
    if source_model not in rules["allowed_source_models"]:
        blockers.append("source_model_missing_or_mismatch")
    if camera_view != "front":
        blockers.append("front_view_required")
    features = frame.get("features")
    if not isinstance(features, Mapping):
        blockers.append("features_missing")
        features = {}
    results = []
    eligible_ids = []
    for rule in rules["rules"]:
        item = features.get(rule["feature_name"], {})
        if not isinstance(item, Mapping):
            item = {}
        arm = rule["required_arm"]
        phase_ok = phase in rule["applicable_phases"]
        variant_ok = movement_variant in rule["applicable_variants"]
        arm_ok = (arm == "none" or movement_variant == "both_arms_overhead"
                  or raised_arm_side == arm)
        arm_unknown = (arm != "none" and movement_variant == "single_arm_overhead"
                       and raised_arm_side == "unknown")
        if rule["enabled"] and rule["mode"] == "candidate" and phase_ok and variant_ok and (arm_ok or arm_unknown):
            eligible_ids.append(rule["rule_id"])
        result = {k: deepcopy(rule[k]) for k in (
            "rule_id", "event_type", "target", "feature_name", "unit", "mode", "transform",
            "reference_range", "trigger_range", "clear_range", "temporal", "required_arm",
        )}
        result.update(
            observed_value=item.get("value") if _number(item.get("value")) else None,
            comparison_value=None,
            min_keypoint_score=item.get("min_keypoint_score")
                if _number(item.get("min_keypoint_score")) else None,
            status="not_assessable", reason=None,
        )
        if blockers:
            result["reason"] = blockers[0]
        elif not rule["enabled"] or rule["mode"] == "monitor_only":
            result.update(status="disabled", reason="monitor_only" if rule["mode"] == "monitor_only" else "rule_disabled")
        elif not rules["reviewed"] and not allow_unreviewed:
            result.update(status="disabled", reason="rules_require_manual_review")
        elif not phase_ok:
            result.update(status="not_applicable", reason="explicit_hold_phase_required")
        elif movement_variant == "unknown":
            result["reason"] = "movement_variant_required"
        elif not variant_ok:
            result.update(status="not_applicable", reason="movement_variant_not_applicable")
        elif arm != "none" and movement_variant == "single_arm_overhead" and raised_arm_side == "unknown":
            result["reason"] = "raised_arm_side_required"
        elif not arm_ok:
            result.update(status="not_applicable", reason="non_raised_arm")
        elif rule["transform"] == "expected_direction" and (
                bend_direction == "unknown" or direction_source.startswith("geometry_preview")):
            result["reason"] = "independent_intended_direction_required"
        elif item.get("valid") is not True or not _number(item.get("value")):
            result["reason"] = item.get("reason") if isinstance(item.get("reason"), str) else "feature_invalid_or_missing"
        elif item.get("unit") != rule["unit"]:
            result["reason"] = "feature_unit_mismatch"
        elif result["min_keypoint_score"] is None or result["min_keypoint_score"] < rules["min_keypoint_score"]:
            result["reason"] = "insufficient_keypoint_score"
        else:
            value = float(item["value"])
            signed = rule["feature_name"] == "torso_tilt_deg"
            if ((rule["unit"] == "deg" and (abs(value) > 180 or (not signed and value < 0)))
                    or (rule["unit"] != "deg" and value < 0)):
                result["reason"] = "feature_outside_geometric_domain"
            else:
                if rule["transform"] == "abs":
                    value = abs(value)
                elif rule["transform"] == "expected_direction":
                    value *= 1 if bend_direction == "image_right" else -1
                result["comparison_value"] = value
                if not _inside(value, rule["trigger_range"]):
                    result.update(status="deviation", reason="outside_trigger_range")
                elif _inside(value, rule["clear_range"]):
                    result.update(status="within_reference", reason=None)
                else:
                    result.update(status="gray_zone", reason="between_start_and_clear_thresholds")
        results.append(result)
    assessed = [r["rule_id"] for r in results if r["rule_id"] in eligible_ids
                and r["status"] in {"deviation", "within_reference", "gray_zone"}]
    unassessed = [r["rule_id"] for r in results if r["rule_id"] in eligible_ids and r["rule_id"] not in assessed]
    candidates = [deepcopy(r) for r in results if r["status"] == "deviation"]
    statuses = {r["status"] for r in results}
    status = ("not_assessable" if blockers else "candidate_deviation" if candidates
              else "gray_zone" if "gray_zone" in statuses else "within_reference" if "within_reference" in statuses
              else "not_assessable" if "not_assessable" in statuses else "not_evaluated")
    return dict(
        schema_version="ardhakati-comparison-v1", exercise="ardhakati_chakrasana",
        timestamp_ms=t, frame_index=_safe(frame.get("frame_index")),
        rule_version=rules["version"], feature_version=frame.get("feature_version"),
        source_model=source_model, phase=phase, movement_variant=movement_variant,
        raised_arm_side=raised_arm_side, bend_direction=bend_direction,
        camera_view=camera_view, camera_view_verified=camera_view_verified,
        phase_reviewed=phase_reviewed, direction_reviewed=direction_reviewed,
        variant_reviewed=variant_reviewed, raised_arm_reviewed=raised_arm_reviewed,
        **provenance,
        rules_reviewed=rules["reviewed"],
        execution_mode="reviewed_rules" if rules["reviewed"] else "exploratory_preview" if allow_unreviewed else "review_guard",
        reference_status="reviewed_rule_config" if rules["reviewed"] else "draft_unreviewed",
        assessment_status=status, reason_codes=blockers,
        assessment_coverage=dict(
            eligible_rule_ids=eligible_ids, assessed_rule_ids=assessed,
            unassessed_rule_ids=unassessed,
            complete_for_enabled_phase_rules=bool(eligible_ids) and not unassessed,
            scope="enabled_phase_variant_rules_only_not_full_posture",
        ),
        features=_safe(features), rule_results=results, candidates=candidates,
        deviations=[], feedback_allowed=False,
        unsupported_checks=deepcopy(rules.get("unsupported_checks", [])),
        limitations=["2D_projection_only", "single_frame_has_no_verified_duration",
                     "source_variant_differs_from_requested_both_arm_variant"],
    )
