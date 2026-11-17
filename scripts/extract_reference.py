"""A: extract contract-compatible landmarks and a reference from a front-view clip."""
import argparse
import json
import math
from pathlib import Path

POSES = ('tadasana', 'ardhakati_chakrasana')
REQUIRED = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)


def acceptable(points, threshold):
    return (len(points) == 33
            and all(math.isfinite(p[k]) for p in points for k in ('x', 'y', 'z', 'visibility'))
            and all(points[i]['visibility'] >= threshold
                    and 0 <= points[i]['x'] <= 1 and 0 <= points[i]['y'] <= 1
                    for i in REQUIRED))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--pose', choices=POSES, required=True)
    parser.add_argument('--model', type=Path, required=True, help='Local MediaPipe pose_landmarker.task')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--visibility', type=float, default=0.6)
    args = parser.parse_args()
    if not 0 <= args.visibility <= 1:
        parser.error('--visibility must be in [0, 1]')
    if not args.video.is_file() or not args.model.is_file():
        parser.error('Video and model must be existing local files')
    import cv2
    import numpy as np
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    cap = cv2.VideoCapture(str(args.video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not cap.isOpened() or not math.isfinite(fps) or fps <= 0 or fps > 1000:
        cap.release()
        parser.error('Cannot open video or unsupported FPS')
    options = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(args.model)),
        running_mode=vision.RunningMode.VIDEO, num_poses=1)
    args.output.mkdir(parents=True, exist_ok=True)
    frames_path = args.output / f'{args.pose}_frames.jsonl'
    reference_path = args.output / f'{args.pose}_reference.json'
    if frames_path.exists() or reference_path.exists():
        cap.release()
        parser.error('Output already exists; choose a new output directory')
    accepted = []
    total = 0
    preview_saved = False
    try:
        with vision.PoseLandmarker.create_from_options(options) as detector, frames_path.open('w') as stream, (args.output / 'all_frames.jsonl').open('w') as raw_stream:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                timestamp = round(total * 1000 / fps)
                total += 1
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp)
                if not result.pose_landmarks:
                    raw_stream.write(json.dumps(dict(timestamp_ms=timestamp, landmarks=None, quality_status='no_detection')) + '\n')
                    continue
                points = [{k: float(getattr(p, k)) for k in ('x', 'y', 'z', 'visibility')}
                          for p in result.pose_landmarks[0]]
                usable = acceptable(points, args.visibility)
                raw_stream.write(json.dumps(dict(pose_id=args.pose, timestamp_ms=timestamp, camera_view='front', landmarks=points, quality_status='accepted' if usable else 'rejected_quality'), allow_nan=False) + '\n')
                if not usable:
                    continue
                record = dict(pose_id=args.pose, timestamp_ms=timestamp, camera_view='front', landmarks=points)
                stream.write(json.dumps(record, allow_nan=False) + '\n')
                accepted.append(record)
                if not preview_saved:
                    h, w = frame.shape[:2]
                    for connection in vision.PoseLandmarksConnections.POSE_LANDMARKS:
                        a, b = points[connection.start], points[connection.end]
                        if min(a['visibility'], b['visibility']) >= args.visibility:
                            cv2.line(frame, (round(a['x']*w), round(a['y']*h)),
                                     (round(b['x']*w), round(b['y']*h)), (0, 255, 0), 2)
                    preview_saved = cv2.imwrite(str(args.output / f'{args.pose}_skeleton.jpg'), frame)
    finally:
        cap.release()
    if not accepted:
        raise SystemExit('No usable frames: check viewpoint, full-body framing, and visibility. No reference generated.')
    # Select an actual observed frame nearest the median, avoiding a synthetic pose.
    values = np.array([[[p[k] for k in ('x', 'y', 'z')] for p in r['landmarks']] for r in accepted])
    distances = np.mean((values - np.median(values, axis=0)) ** 2, axis=(1, 2))
    representative = accepted[int(np.argmin(distances))]
    reference = dict(representative, metadata=dict(
        source_video=args.video.name, model_file=args.model.name,
        total_frames=total, accepted_frames=len(accepted),
        visibility_threshold=args.visibility, selection='observed_frame_nearest_coordinate_median',
        review_status='requires_manual_review', fps=fps))
    reference_path.write_text(json.dumps(reference, indent=2, allow_nan=False) + '\n')
    print(f'Accepted {len(accepted)}/{total} frames. Reference: {reference_path}')


if __name__ == '__main__':
    main()
