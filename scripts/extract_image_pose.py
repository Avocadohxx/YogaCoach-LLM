"""Run a local MediaPipe Pose model on a still image, without quality filtering."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('image','model','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    frame=cv2.imread(str(args.image))
    if frame is None:parser.error('Cannot read image')
    if args.output.exists():parser.error('Choose a new output directory')
    options=vision.PoseLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(args.model)),running_mode=vision.RunningMode.IMAGE,num_poses=1)
    with vision.PoseLandmarker.create_from_options(options) as detector:
        result=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)))
    if not result.pose_landmarks:raise SystemExit('No person detected')
    points=[{k:float(getattr(q,k)) for k in ('x','y','z','visibility')} for q in result.pose_landmarks[0]]
    args.output.mkdir(parents=True)
    (args.output/'landmarks.json').write_text(json.dumps(dict(source_image=args.image.name,model_file=args.model.name,landmarks=points,metadata=dict(running_mode='IMAGE',quality_filter_applied=False,pose_id=None,camera_view='unverified',review_status='requires_manual_review')),indent=2,allow_nan=False)+'\n')
    h,w=frame.shape[:2]
    def xy(i):return round(points[i]['x']*(w-1)),round(points[i]['y']*(h-1))
    for edge in vision.PoseLandmarksConnections.POSE_LANDMARKS:
        cv2.line(frame,xy(edge.start),xy(edge.end),(0,200,0),2)
    for i,q in enumerate(points):
        color=(0,200,255) if q['visibility']>=.6 else (0,0,255)
        cv2.circle(frame,xy(i),3,color,-1)
        cv2.putText(frame,str(i),xy(i),cv2.FONT_HERSHEY_SIMPLEX,.32,(180,0,180),1)
    if not cv2.imwrite(str(args.output/'heavy_skeleton.jpg'),frame):raise SystemExit('Failed saving image')
    print('33 points saved. Red dots indicate visibility < 0.6.')


if __name__=='__main__':main()
