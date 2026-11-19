"""B: COCO-WholeBody 133 / DWPose image-pixel geometry (not MediaPipe).

Pure standard-library functions. A score is a model response, not a probability
or visibility; values above 1 are preserved. No exercise correction thresholds.
"""
from dataclasses import dataclass
from math import acos, atan2, degrees, hypot, isfinite
from numbers import Real
from typing import Any, Mapping


LAYOUT = "COCO-WholeBody 133"
FEATURE_VERSION = "dwpose133-geometry-v1"
DEFAULT_MIN_SCORE = 0.5  # development gate only; not calibrated on people
MIN_SEGMENT_PX = 1.0  # numerical degeneracy guard, not a safety/distance standard

# Zero-based COCO-WholeBody order, independently checked against MMPose metadata.
JOINTS = {
    "left_shoulder": 5, "right_shoulder": 6,
    "left_elbow": 7, "right_elbow": 8,
    "left_wrist": 9, "right_wrist": 10,
    "left_hip": 11, "right_hip": 12,
    "left_ankle": 15, "right_ankle": 16,
}

FEATURE_UNITS = {
    "shoulder_height_diff_px": "px",
    "shoulder_height_diff": "torso_ratio",
    "torso_tilt_deg": "deg",
    "left_elbow_angle_deg": "deg",
    "right_elbow_angle_deg": "deg",
    "left_arm_torso_angle_deg": "deg",
    "right_arm_torso_angle_deg": "deg",
    "ankle_spacing_shoulder_ratio": "shoulder_width_ratio",
}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        out = float(value)
    except (ValueError, OverflowError):
        return None
    return out if isfinite(out) else None


@dataclass(frozen=True)
class Frame133:
    timestamp_ms: int
    points: tuple[tuple[float | None, float | None], ...]
    scores: tuple[float | None, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Frame133":
        if not isinstance(raw, Mapping):
            raise ValueError("frame must be a JSON object")
        timestamp = raw.get("timestamp_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ValueError("timestamp_ms must be a non-negative integer")
        points, scores = raw.get("keypoints"), raw.get("scores")
        if not isinstance(points, (list, tuple)) or len(points) != 133:
            raise ValueError("keypoints must contain exactly 133 [x,y] pixel pairs")
        if not isinstance(scores, (list, tuple)) or len(scores) != 133:
            raise ValueError("scores must contain exactly 133 entries")
        parsed_points = []
        for i, p in enumerate(points):
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                raise ValueError(f"keypoints[{i}] must be an [x,y] pair")
            # Null/nonfinite values invalidate only dependent features, not others.
            parsed_points.append((_finite_number(p[0]), _finite_number(p[1])))
        return cls(timestamp, tuple(parsed_points), tuple(_finite_number(s) for s in scores))


class GeometryUnavailable(ValueError):
    pass


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def _mid(a, b):
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def _length(v, name):
    out = hypot(v[0], v[1])
    if not isfinite(out) or out <= MIN_SEGMENT_PX:
        raise GeometryUnavailable(f"degenerate_{name}")
    return out


def angle_between(u, v, segment_name="segment") -> float:
    """Numerically stable unsigned 2D included angle, in [0,180] degrees."""
    lu, lv = _length(u, segment_name), _length(v, segment_name)
    ux, uy = u[0] / lu, u[1] / lu
    vx, vy = v[0] / lv, v[1] / lv
    cosine = max(-1.0, min(1.0, ux * vx + uy * vy))
    return degrees(acos(cosine))


def _torso(points):
    shoulder = _mid(points[5], points[6])
    hip = _mid(points[11], points[12])
    down = _sub(hip, shoulder)
    return shoulder, hip, down, _length(down, "torso")


def _quality(frame, ids, min_score):
    relevant = [frame.scores[i] for i in ids]
    score_min = min(relevant) if all(s is not None and s >= 0 for s in relevant) else None
    if score_min is None:
        return "invalid_keypoint_score", None
    for i in ids:
        if None in frame.points[i]:
            return "invalid_keypoint_coordinate", score_min
    if score_min < min_score:
        return "low_keypoint_score", score_min
    return None, score_min


def extract_features_133(
    frame: Frame133 | Mapping[str, Any], *, min_score: float = DEFAULT_MIN_SCORE
) -> dict:
    """Eight measurements representing the seven requested positional features.

    Shoulder difference is provided in pixels AND normalized by torso scale.
    Body tilt is the shoulder-midpoint/hip-midpoint axis, signed in IMAGE space.
    Arm/trunk angle uses upper arm (elbow-shoulder) vs CENTRAL downward trunk
    (hip midpoint-shoulder midpoint): hanging along trunk≈0°, perpendicular≈90°,
    opposite to downward trunk≈180°. It is not a clinical shoulder joint angle.
    Stance ratio = abs(left_ankle.x-right_ankle.x) / 2D shoulder Euclidean width.
    No width/height multiplication: input coordinates are already image pixels.
    """
    if not isinstance(frame, Frame133):
        frame = Frame133.from_mapping(frame)
    minimum = _finite_number(min_score)
    if minimum is None or minimum < 0:
        raise ValueError("min_score must be finite and non-negative")
    p = frame.points

    def shoulder_diff():
        return abs(p[5][1] - p[6][1])

    def torso_tilt():
        shoulder, hip, _, _ = _torso(p)
        return degrees(atan2(shoulder[0] - hip[0], hip[1] - shoulder[1]))

    def elbow(s, e, w):
        return angle_between(_sub(p[s], p[e]), _sub(p[w], p[e]), "arm")

    def upper_arm(s, e):
        _, _, down, _ = _torso(p)
        return angle_between(_sub(p[e], p[s]), down, "arm_or_torso")

    def stance():
        shoulder_width = _length(_sub(p[5], p[6]), "shoulder_width")
        return abs(p[15][0] - p[16][0]) / shoulder_width

    specs = (
        ("shoulder_height_diff_px", (5, 6), shoulder_diff),
        ("shoulder_height_diff", (5, 6, 11, 12), lambda: shoulder_diff() / _torso(p)[3]),
        ("torso_tilt_deg", (5, 6, 11, 12), torso_tilt),
        ("left_elbow_angle_deg", (5, 7, 9), lambda: elbow(5, 7, 9)),
        ("right_elbow_angle_deg", (6, 8, 10), lambda: elbow(6, 8, 10)),
        ("left_arm_torso_angle_deg", (5, 6, 7, 11, 12), lambda: upper_arm(5, 7)),
        ("right_arm_torso_angle_deg", (5, 6, 8, 11, 12), lambda: upper_arm(6, 8)),
        ("ankle_spacing_shoulder_ratio", (5, 6, 15, 16), stance),
    )
    features = {}
    for name, ids, measure in specs:
        reason, score_min = _quality(frame, ids, minimum)
        value = None
        if reason is None:
            try:
                value = measure()
                if not isfinite(value):
                    raise GeometryUnavailable("nonfinite_geometry")
            except GeometryUnavailable as exc:
                reason = str(exc)
                value = None
        features[name] = dict(
            value=value, unit=FEATURE_UNITS[name], valid=reason is None,
            reason=reason, required_keypoint_ids=list(ids), min_keypoint_score=score_min,
        )
    count = sum(f["valid"] for f in features.values())
    return dict(
        timestamp_ms=frame.timestamp_ms, feature_version=FEATURE_VERSION,
        layout=LAYOUT, coordinate_space="image_pixels",
        analysis_mode="measurements_only", reference_status="not_loaded",
        feedback_allowed=False, min_score=minimum,
        measurement_status="all_valid" if count == len(features) else
                           "partial" if count else "not_assessable",
        features=features,
    )
