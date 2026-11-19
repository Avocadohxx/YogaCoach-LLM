"""Canonical 133-point measurements; no conversion to MediaPipe semantics."""
from backend.pose_features_133 import extract_features_133
from backend.schemas import AnalysisResult, Observation, PoseFrame133


def analyze_frame_133(frame: PoseFrame133) -> AnalysisResult:
    result = extract_features_133(frame.model_dump())
    observations = []
    for name, feature in result['features'].items():
        in_frame = all((frame.image_width is None or 0 <= frame.keypoints[i][0] < frame.image_width)
            and (frame.image_height is None or 0 <= frame.keypoints[i][1] < frame.image_height)
            for i in feature['required_keypoint_ids']) if feature['valid'] else True
        valid = feature['valid'] and frame.camera_view == 'front' and in_frame
        reason = None if valid else ('unsupported_camera_view' if frame.camera_view != 'front' else 'required_landmark_out_of_frame' if not in_frame else feature['reason'])
        observations.append(Observation(name=name, value=feature['value'] if valid else None,
            unit=feature['unit'], valid=valid, reason=reason))
    count = sum(o.valid for o in observations)
    reasons = sorted({o.reason for o in observations if o.reason})
    if frame.phase not in {'hold', 'arms_down_hold', 'arms_up_hold', 'side_bend_hold'}:
        reasons.append('not_in_hold_phase')
    return AnalysisResult(session_id=frame.session_id, pose_id=frame.pose_id,
        frame_seq=frame.frame_seq, timestamp_ms=frame.timestamp_ms,
        tracking_quality='good' if count == len(observations) else 'partial' if count else 'poor',
        assessment_status='uncalibrated' if count and frame.phase in {'hold', 'arms_down_hold', 'arms_up_hold', 'side_bend_hold'} else 'not_assessable',
        analysis_mode='measurements_only', reference_status='not_loaded', feedback_allowed=False,
        observations=observations, deviations=[], reason_codes=reasons)
