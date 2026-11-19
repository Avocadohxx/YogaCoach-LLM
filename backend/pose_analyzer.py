"""Owner B: Day-1 pure 2D measurements; no reference or temporal claims.

No MediaPipe, NumPy, DB, network or LLM dependency. All thresholds below are
measurement gates for development, NOT exercise/safety standards.
"""
from dataclasses import dataclass
from math import acos, atan2, degrees, hypot

from backend.schemas import AnalysisResult, Observation, PoseFrame


@dataclass(frozen=True)
class Point2D:
    x: float
    y: float


class MeasurementUnavailable(ValueError):
    pass


MIN_LENGTH_PX = 1.0  # numerical degeneracy guard, not a validated camera-distance gate
DEFAULT_MIN_VISIBILITY = 0.75  # provisional; must be calibrated on real videos


def to_pixel_coordinates(frame: PoseFrame) -> list[Point2D]:
    """Use actual inference input dimensions, not CSS/Canvas display dimensions."""
    return [
        Point2D(p.x * frame.image_width, p.y * frame.image_height)
        for p in frame.landmarks
    ]


def _midpoint(a: Point2D, b: Point2D) -> Point2D:
    return Point2D((a.x + b.x) / 2, (a.y + b.y) / 2)


def _torso(points: list[Point2D]) -> tuple[Point2D, Point2D, float]:
    shoulder = _midpoint(points[11], points[12])
    hip = _midpoint(points[23], points[24])
    scale = hypot(shoulder.x - hip.x, shoulder.y - hip.y)
    if scale <= MIN_LENGTH_PX:
        raise MeasurementUnavailable("degenerate_torso")
    if shoulder.y >= hip.y:
        raise MeasurementUnavailable("unsupported_body_orientation")
    return shoulder, hip, scale


def compute_shoulder_height_diff(points: list[Point2D]) -> float:
    _, _, scale = _torso(points)
    return abs(points[11].y - points[12].y) / scale


def compute_torso_angle(points: list[Point2D]) -> float:
    """Signed IMAGE-plane angle; + toward image right, NOT anatomical right."""
    shoulder, hip, _ = _torso(points)
    return degrees(atan2(shoulder.x - hip.x, hip.y - shoulder.y))


def compute_elbow_angle(shoulder: Point2D, elbow: Point2D, wrist: Point2D) -> float:
    ux, uy = shoulder.x - elbow.x, shoulder.y - elbow.y
    vx, vy = wrist.x - elbow.x, wrist.y - elbow.y
    lu, lv = hypot(ux, uy), hypot(vx, vy)
    if min(lu, lv) <= MIN_LENGTH_PX:
        raise MeasurementUnavailable("degenerate_arm")
    cosine = max(-1.0, min(1.0, (ux * vx + uy * vy) / (lu * lv)))
    return degrees(acos(cosine))


def _quality_reason(frame: PoseFrame, ids: tuple[int, ...], minimum: float):
    for i in ids:
        p = frame.landmarks[i]
        if p.visibility < minimum:
            return "low_visibility"
        if not (0.0 <= p.x <= 1.0 and 0.0 <= p.y <= 1.0):
            return "required_landmark_out_of_frame"
    return None


def analyze_frame(
    frame: PoseFrame, *, min_visibility: float = DEFAULT_MIN_VISIBILITY
) -> AnalysisResult:
    """Measure each feature independently; no 'normal posture' classification.

    camera_view is a user/upstream declaration, not automatically verified.
    Both elbow angles are observations only; raised arm and form rules await A/C.
    """
    if not 0.0 <= min_visibility <= 1.0:
        raise ValueError("min_visibility must be between 0 and 1")
    points = to_pixel_coordinates(frame)
    specs = [
        ("shoulder_height_diff", "torso_ratio", (11, 12, 23, 24),
         lambda: compute_shoulder_height_diff(points)),
        ("torso_tilt_deg", "deg", (11, 12, 23, 24),
         lambda: compute_torso_angle(points)),
        ("left_elbow_angle_deg", "deg", (11, 13, 15),
         lambda: compute_elbow_angle(points[11], points[13], points[15])),
        ("right_elbow_angle_deg", "deg", (12, 14, 16),
         lambda: compute_elbow_angle(points[12], points[14], points[16])),
    ]
    observations = []
    for name, unit, ids, measure in specs:
        reason = (
            "unsupported_camera_view" if frame.camera_view != "front"
            else _quality_reason(frame, ids, min_visibility)
        )
        value = None
        if reason is None:
            try:
                value = measure()
            except MeasurementUnavailable as exc:
                reason = str(exc)
        observations.append(Observation(
            name=name, value=value, unit=unit, valid=reason is None, reason=reason
        ))
    valid_count = sum(o.valid for o in observations)
    reasons = sorted({o.reason for o in observations if o.reason is not None})
    if frame.phase != "hold":
        reasons.append("not_in_hold_phase")
    assessable = valid_count > 0 and frame.phase == "hold"
    return AnalysisResult(
        session_id=frame.session_id, pose_id=frame.pose_id,
        frame_seq=frame.frame_seq, timestamp_ms=frame.timestamp_ms,
        tracking_quality=("good" if valid_count == len(specs) else
                          "partial" if valid_count else "poor"),
        assessment_status="uncalibrated" if assessable else "not_assessable",
        analysis_mode="measurements_only", reference_status="not_loaded",
        feedback_allowed=False, observations=observations, deviations=[],
        reason_codes=reasons,
    )
