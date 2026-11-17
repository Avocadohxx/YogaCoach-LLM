"""Single-person, fixed full-frame ROI experiment; separate from the 33-point contract."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    import cv2
    import numpy as np
    from rtmlib import RTMPose, draw_skeleton
    if args.output.exists():
        p.error('Use a new output directory')
    model = RTMPose(str(args.model), model_input_size=(288,384), backend='onnxruntime', device='cpu', to_openpose=False)
    cap = cv2.VideoCapture(str(args.video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not cap.isOpened() or fps <= 0:
        p.error('Cannot read video')
    w,h = int(cap.get(3)),int(cap.get(4))
    args.output.mkdir(parents=True)
    writer=cv2.VideoWriter(str(args.output/'skeleton_review.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),fps,(w,h))
    if not writer.isOpened():
        cap.release()
        p.error('Cannot create video')
    count=0
    try:
        with (args.output/'keypoints_133.jsonl').open('w') as stream:
            while True:
                ok,frame=cap.read()
                if not ok: break
                ts=round(count*1000/fps)
                keypoints,scores=model(frame,bboxes=np.array([[0,0,w,h]],dtype=np.float32))
                if keypoints.shape != (1,133,2): raise ValueError(f'Unexpected shape: {keypoints.shape}')
                stream.write(json.dumps(dict(timestamp_ms=ts,keypoints=keypoints[0].tolist(),scores=scores[0].tolist()),allow_nan=False)+'\n')
                rendered=draw_skeleton(frame.copy(),keypoints,scores,openpose_skeleton=False,kpt_thr=.3)
                cv2.putText(rendered,f'DWPose-L (RTMPose) | {ts} ms',(12,30),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,255),2)
                writer.write(rendered)
                if count==round(2067*fps/1000): cv2.imwrite(str(args.output/'comparison_frame_2067ms.jpg'),rendered)
                count+=1
    finally:
        cap.release();writer.release()
    (args.output/'metadata.json').write_text(json.dumps(dict(model=args.model.name,fps=fps,frames=count,layout='COCO-WholeBody 133',coordinates='image pixels; scores are not MediaPipe visibility',roi='fixed full image; one person only; no detector',review_status='requires_manual_review'),indent=2)+'\n')
    print(f'Rendered {count} frames')


if __name__=='__main__': main()
