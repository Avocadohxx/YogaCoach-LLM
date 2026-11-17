"""Add independent hand detections to an existing Heavy pose review; never replace pose points."""
import argparse
import json
from pathlib import Path
from collections import Counter
from render_pose_review import EDGES


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('video','pose-frames','model','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    if args.output.exists(): p.error('Choose a new output directory')
    poses={r['timestamp_ms']:r for r in map(json.loads,args.pose_frames.read_text().splitlines())}
    cap=cv2.VideoCapture(str(args.video));fps=cap.get(cv2.CAP_PROP_FPS)
    if not cap.isOpened() or fps<=0: p.error('Cannot open video')
    w,h=int(cap.get(3)),int(cap.get(4));args.output.mkdir(parents=True)
    writer=cv2.VideoWriter(str(args.output/'skeleton_review.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),fps,(w,h))
    if not writer.isOpened(): cap.release();p.error('Cannot create video')
    options=vision.HandLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(args.model)),running_mode=vision.RunningMode.VIDEO,num_hands=2)
    counts=Counter();index=matched=0
    try:
        with vision.HandLandmarker.create_from_options(options) as detector,(args.output/'hands.jsonl').open('w') as stream:
            while True:
                ok,frame=cap.read()
                if not ok: break
                ts=round(index*1000/fps);pose=poses.get(ts);hands=[]
                result=detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)),ts)
                for points,categories in zip(result.hand_landmarks,result.handedness):
                    hands.append(dict(handedness_label=categories[0].category_name,handedness_score=categories[0].score,landmarks=[dict(x=q.x,y=q.y,z=q.z) for q in points]))
                counts[len(hands)]+=1
                stream.write(json.dumps(dict(timestamp_ms=ts,hands=hands),allow_nan=False)+'\n')
                def xy(q): return round(q['x']*(w-1)),round(q['y']*(h-1))
                # Keep original coarse pose hand points visible in green for comparison.
                if pose:
                    matched+=1;points=pose['landmarks']
                    for a,b in EDGES:
                        if min(points[a]['visibility'],points[b]['visibility'])>=.6:cv2.line(frame,xy(points[a]),xy(points[b]),(0,180,0),2)
                for hand in hands:
                    points=hand['landmarks']
                    for edge in vision.HandLandmarksConnections.HAND_CONNECTIONS:
                        cv2.line(frame,xy(points[edge.start]),xy(points[edge.end]),(255,0,255),2)
                    for q in points:cv2.circle(frame,xy(q),2,(0,255,255),-1)
                cv2.putText(frame,f'{ts} ms | hands={len(hands)} | green=Pose pink=Hands',(12,30),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,255),2)
                writer.write(frame)
                if index==round(2067*fps/1000):cv2.imwrite(str(args.output/'comparison_frame_2067ms.jpg'),frame)
                index+=1
    finally:
        cap.release();writer.release()
    if matched!=len(poses):raise SystemExit('Pose/video timestamp mismatch')
    metadata=dict(frames=index,frames_by_detected_hands=dict(counts),model_file=args.model.name,pose_source=str(args.pose_frames),pose_33_points='unchanged',hand_xy='normalized image coordinates',hand_z='relative to hand wrist; not comparable to pose z',handedness='raw model classification, not anatomical side verified',review_status='requires_manual_review')
    (args.output/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(metadata))


if __name__=='__main__':main()
