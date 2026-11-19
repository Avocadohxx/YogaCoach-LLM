"""Render review artifacts from the exact video used for extraction (no inference)."""
import argparse
import json
import math
from pathlib import Path

# MediaPipe body connections; facial details are omitted for review readability.
EDGES = [(11,12),(11,13),(13,15),(12,14),(14,16),(11,23),(12,24),
         (23,24),(23,25),(25,27),(24,26),(26,28),(27,29),(29,31),
         (27,31),(28,30),(30,32),(28,32),(15,17),(15,19),(15,21),
         (16,18),(16,20),(16,22)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video', type=Path, required=True, help='Exact extraction clip, not the full source')
    p.add_argument('--frames', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--all-frames', type=Path, help='Optional raw audit JSONL; show rejected detections for review only')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    import cv2
    records = [json.loads(line) for line in args.frames.read_text().splitlines() if line.strip()]
    accepted_times = {r['timestamp_ms'] for r in records}
    if args.all_frames:
        records = [r for r in map(json.loads, args.all_frames.read_text().splitlines()) if r.get('landmarks')]
    reference = json.loads(args.reference.read_text())
    if not records:
        p.error('No accepted frames')
    lookup = {r['timestamp_ms']: r for r in records}
    if reference['timestamp_ms'] not in lookup:
        p.error('Reference timestamp absent from frames')
    for r in records:
        if len(r['landmarks']) != 33 or r['pose_id'] != reference['pose_id']:
            p.error('Inconsistent pose or landmark count')
    cap = cv2.VideoCapture(str(args.video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not cap.isOpened() or not math.isfinite(fps) or fps <= 0:
        p.error('Cannot open video or invalid FPS')
    args.output.mkdir(parents=True, exist_ok=True)
    video_path = args.output / 'skeleton_review.mp4'
    image_path = args.output / 'reference_frame.jpg'
    if video_path.exists() or image_path.exists():
        cap.release()
        p.error('Review artifacts already exist; choose a new output directory')
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*'mp4v'), fps,
                            (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))))
    if not writer.isOpened():
        cap.release()
        p.error('Video writer failed')
    threshold = reference.get('metadata', {}).get('visibility_threshold', .6)
    count = matched = 0
    saved = False
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ts = round(count * 1000 / fps)
            count += 1
            record = lookup.get(ts)
            if record:
                matched += 1
                points = record['landmarks']
                h, w = frame.shape[:2]
                def visible(i):
                    q = points[i]
                    return q['visibility'] >= threshold and 0 <= q['x'] <= 1 and 0 <= q['y'] <= 1
                def xy(i):
                    return round(points[i]['x'] * (w-1)), round(points[i]['y'] * (h-1))
                for a, b in EDGES:
                    if visible(a) and visible(b):
                        cv2.line(frame, xy(a), xy(b), (0,255,0), 2)
                for i in range(11,33):
                    if visible(i):
                        cv2.circle(frame, xy(i), 4, (0,200,255), -1)
                        cv2.putText(frame, str(i), xy(i), cv2.FONT_HERSHEY_SIMPLEX, .4, (0,0,255), 1)
            status = 'accepted' if ts in accepted_times else ('REJECTED QUALITY: partial overlay' if record else 'NO ACCEPTED DATA')
            label = f'{ts} ms | {status}'
            if ts == reference['timestamp_ms']:
                label += ' | REFERENCE'
            cv2.putText(frame, label, (12,30), cv2.FONT_HERSHEY_SIMPLEX, .6, (0,0,255), 2)
            writer.write(frame)
            if ts == reference['timestamp_ms']:
                saved = cv2.imwrite(str(image_path), frame)
    finally:
        cap.release()
        writer.release()
    if matched != len(records) or not saved:
        raise SystemExit('Timestamp mismatch: use the exact original extraction clip. Artifacts are incomplete.')
    print(f'Rendered {count} frames; matched {matched}; reference {reference["timestamp_ms"]} ms')


if __name__ == '__main__':
    main()
