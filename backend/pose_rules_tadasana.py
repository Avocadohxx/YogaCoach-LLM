"""B: single-frame Tadasana comparison for existing RTMW feature records.

No session_id/pose_id is needed: this module is exclusively for Tadasana.
It compares measurements, not images, and never asserts sustained deviation.
Default-unreviewed rules are disabled unless explicitly previewed.
"""
from copy import deepcopy
import json
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Mapping


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "knowledge/tadasana_rules.json"
PHASES = {"unknown", "prepare", "transition", "arms_down_hold", "arms_up_hold"}
KNOWN_UNITS = {
    "shoulder_height_diff_px": "px", "shoulder_height_diff": "torso_ratio",
    "torso_tilt_deg": "deg", "left_elbow_angle_deg": "deg",
    "right_elbow_angle_deg": "deg", "left_arm_torso_angle_deg": "deg",
    "right_arm_torso_angle_deg": "deg", "ankle_spacing_shoulder_ratio": "shoulder_width_ratio",
}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _finite_json(value):
    """Retain missing evidence as null so a bad measurement cannot break tracking."""
    if isinstance(value, Real) and not isinstance(value, bool) and not _number(value):
        return None
    if isinstance(value, Mapping):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item) for item in value]
    return deepcopy(value)


def _interval(value, field):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} must be [lower,upper], allowing null open bounds")
    if any(v is not None and not _number(v) for v in value):
        raise ValueError(f"{field} needs finite numeric bounds or null")
    if value[0] is not None and value[1] is not None and value[0] > value[1]:
        raise ValueError(f"{field} is reversed")


def validate_ruleset(raw: Mapping) -> dict:
    """Validate all configuration before processing; return a defensive copy."""
    if not isinstance(raw, Mapping):
        raise ValueError("ruleset must be an object")
    config = deepcopy(dict(raw))
    if not isinstance(config.get("version"), str) or not config["version"].strip():
        raise ValueError("ruleset needs version")
    if type(config.get("reviewed")) is not bool:
        raise ValueError("reviewed must be boolean")
    if config["reviewed"] and not config.get("review_record"):
        raise ValueError("reviewed rules need a non-empty review_record")
    if not isinstance(config.get("expected_layout"), str):
        raise ValueError("expected_layout is required")
    for field in ("allowed_feature_versions", "allowed_source_models"):
        if (not isinstance(config.get(field), list) or not config[field]
                or not all(isinstance(v, str) and v for v in config[field])):
            raise ValueError(f"{field} must be a nonempty string list")
    minimum = config.get("min_keypoint_score")
    if not _number(minimum) or minimum < 0:
        raise ValueError("min_keypoint_score must be finite and nonnegative")
    if not isinstance(config.get("rules"), list) or not config["rules"]:
        raise ValueError("rules must be a nonempty list")
    seen = set()
    for rule in config["rules"]:
        if not isinstance(rule, Mapping):
            raise ValueError("each rule must be an object")
        for field in ("rule_id", "event_type", "target", "feature_name"):
            if not isinstance(rule.get(field), str) or not rule[field].strip():
                raise ValueError(f"rule needs {field}")
        if rule["rule_id"] in seen:
            raise ValueError("duplicate rule_id")
        seen.add(rule["rule_id"])
        if rule["feature_name"] not in KNOWN_UNITS:
            raise ValueError("unknown feature_name")
        if rule.get("unit") != KNOWN_UNITS[rule["feature_name"]]:
            raise ValueError("rule unit does not match feature")
        if type(rule.get("enabled")) is not bool:
            raise ValueError("enabled must be boolean")
        if rule.get("mode") not in ("candidate", "monitor_only"):
            raise ValueError("mode must be candidate or monitor_only")
        if rule.get("transform") not in ("identity", "abs"):
            raise ValueError("unsupported transform")
        phases = rule.get("applicable_phases")
        if (not isinstance(phases, list) or not phases
                or any(p not in {"arms_up_hold", "arms_down_hold"} for p in phases)):
            raise ValueError("rules must explicitly target supported hold phases")
        for field in ("reference_range", "trigger_range", "clear_range"):
            _interval(rule.get(field), field)
        trigger, clear = rule["trigger_range"], rule["clear_range"]
        if (trigger[0] is not None and (clear[0] is None or clear[0] < trigger[0])
                or trigger[1] is not None and (clear[1] is None or clear[1] > trigger[1])):
            raise ValueError("clear_range must lie inside trigger_range")
        temporal = rule.get("temporal")
        if not isinstance(temporal, Mapping):
            raise ValueError("temporal settings are required")
        if set(temporal) != {"min_duration_ms", "clear_duration_ms", "max_gap_ms"}:
            raise ValueError("temporal settings have unexpected or missing fields")
        if any(type(v) is not int or v <= 0 for v in temporal.values()):
            raise ValueError("temporal settings must be positive integers")
    return config


def load_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict:
    return validate_ruleset(json.loads(Path(path).read_text()))


def _inside(value, interval):
    low, high = interval
    return (low is None or value >= low) and (high is None or value <= high)


def compare_tadasana_frame(
    frame: Mapping, *, phase: str = "unknown", camera_view: str = "unknown",
    source_model: str | None = None, phase_source: str = "caller_declared",
    phase_reviewed: bool = False,
    allow_unreviewed: bool = False, ruleset: Mapping | None = None,
) -> dict:
    """Compare an extract_features_133()/features.jsonl record, NOT raw keypoints.

    Pass explicit context, e.g. phase='arms_up_hold', camera_view='front',
    source_model='RTMW-x'. Unknown phase/model never creates a candidate.
    allow_unreviewed=True is an explicit exploratory opt-in, NOT rule approval.
    No prior-frame state is stored here; feedback_allowed is ALWAYS False.
    """
    if not isinstance(frame, Mapping):
        raise ValueError("frame must be a feature object")
    timestamp = frame.get("timestamp_ms")
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError("timestamp_ms must be a nonnegative integer")
    if phase not in PHASES:
        raise ValueError("unsupported phase")
    if camera_view not in {"unknown", "front", "side", "back"}:
        raise ValueError("unsupported camera_view")
    if type(allow_unreviewed) is not bool:
        raise ValueError("allow_unreviewed must be boolean")
    if type(phase_reviewed) is not bool:
        raise ValueError("phase_reviewed must be boolean")
    if not isinstance(phase_source, str) or not phase_source:
        raise ValueError("phase_source must be a nonempty string")
    rules = load_rules() if ruleset is None else validate_ruleset(ruleset)
    blockers = []
    if frame.get("layout") != rules["expected_layout"]:
        blockers.append("layout_mismatch")
    if frame.get("coordinate_space") != "image_pixels":
        blockers.append("coordinate_space_mismatch")
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
    for rule in rules["rules"]:
        name = rule["feature_name"]
        item = features.get(name)
        item = item if isinstance(item, Mapping) else {}
        result = {
            "rule_id": rule["rule_id"], "event_type": rule["event_type"],
            "target": rule["target"], "feature_name": name,
            "unit": rule["unit"], "transform": rule["transform"],
            "observed_value": item.get("value") if _number(item.get("value")) else None,
            "comparison_value": None, "reference_range": rule["reference_range"],
            "trigger_range": rule["trigger_range"], "clear_range": rule["clear_range"],
            "temporal": rule["temporal"], "mode": rule["mode"],
            "min_keypoint_score": item.get("min_keypoint_score")
                if _number(item.get("min_keypoint_score")) else None,
            "status": "not_assessable", "reason": None,
        }
        if blockers:
            result["reason"] = blockers[0]
        elif not rule["enabled"] or rule["mode"] == "monitor_only":
            result.update(status="disabled", reason="monitor_only" if rule["mode"] == "monitor_only"
                          else "rule_disabled")
        elif not rules["reviewed"] and not allow_unreviewed:
            result.update(status="disabled", reason="rules_require_manual_review")
        elif phase not in rule["applicable_phases"]:
            result.update(status="not_applicable", reason="explicit_hold_phase_required")
        elif item.get("valid") is not True or not _number(item.get("value")):
            result["reason"] = item.get("reason") or "feature_invalid_or_missing"
        elif item.get("unit") != rule["unit"]:
            result["reason"] = "feature_unit_mismatch"
        elif (result["min_keypoint_score"] is None
              or result["min_keypoint_score"] < rules["min_keypoint_score"]):
            result["reason"] = "insufficient_keypoint_score"
        else:
            observed = float(item["value"])
            if (rule["unit"] in ("torso_ratio", "shoulder_width_ratio", "px") and observed < 0
                    or rule["unit"] == "deg" and abs(observed) > 180
                    or rule["unit"] == "deg" and name != "torso_tilt_deg" and observed < 0):
                result["reason"] = "feature_outside_geometric_domain"
            else:
                value = abs(observed) if rule["transform"] == "abs" else observed
                result["comparison_value"] = value
                if not _inside(value, rule["trigger_range"]):
                    result.update(status="deviation", reason="outside_trigger_range")
                elif _inside(value, rule["clear_range"]):
                    result.update(status="within_reference", reason=None)
                else:
                    result.update(status="gray_zone", reason="between_start_and_clear_thresholds")
        results.append(result)
    candidates = [deepcopy(r) for r in results if r["status"] == "deviation"]
    assessable_statuses = {"deviation", "gray_zone", "within_reference"}
    eligible = [r for r, config in zip(results, rules["rules"])
                if config["enabled"] and config["mode"] == "candidate"
                and phase in config["applicable_phases"]]
    assessed_ids = [r["rule_id"] for r in eligible if r["status"] in assessable_statuses]
    unassessed_ids = [r["rule_id"] for r in eligible if r["status"] not in assessable_statuses]
    states = {r["status"] for r in results}
    status = (
        "not_assessable" if blockers else
        "candidate_deviation" if candidates else
        "gray_zone" if "gray_zone" in states else
        "within_reference" if "within_reference" in states else
        "not_assessable" if "not_assessable" in states else "not_evaluated"
    )
    return {
        "schema_version": "tadasana-comparison-v1", "timestamp_ms": timestamp,
        "frame_index": frame.get("frame_index"), "rule_version": rules["version"],
        "feature_version": frame.get("feature_version"), "source_model": source_model,
        "phase": phase, "phase_source": phase_source, "phase_reviewed": phase_reviewed,
        "camera_view": camera_view,
        "camera_view_verified": False, "rules_reviewed": rules["reviewed"],
        "execution_mode": "reviewed_rules" if rules["reviewed"] else
                          "exploratory_preview" if allow_unreviewed else "review_guard",
        "reference_status": "reviewed_rule_config" if rules["reviewed"] else "draft_unreviewed",
        "assessment_status": status, "reason_codes": blockers,
        "assessment_coverage": {
            "eligible_rule_ids": [r["rule_id"] for r in eligible],
            "assessed_rule_ids": assessed_ids, "unassessed_rule_ids": unassessed_ids,
            "complete_for_enabled_phase_rules": bool(eligible) and not unassessed_ids,
            "scope": "enabled_phase_rules_only_not_full_posture",
        },
        "features": _finite_json(dict(features)), "rule_results": results,
        "candidates": candidates, "deviations": [], "feedback_allowed": False,
        "limitations": ["single_frame_has_no_verified_duration", "no_medical_or_full_posture_judgement"],
    }
