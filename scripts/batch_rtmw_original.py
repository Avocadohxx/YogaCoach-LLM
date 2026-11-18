"""Run remaining Original Angle 1 clips; checkpoint each verified result for resuming."""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    import cv2
    import numpy as np
    jobs=[]
    for folder in sorted(args.dataset.iterdir()):
        if not folder.is_dir() or folder.name=='Tadasana':continue
        for label,kind in [('correct','Right'),('incorrect','Wrong')]:
            files=[f for f in folder.rglob('*.mp4') if f'{kind} Steps' in str(f.parent) and 'Angle 1.' in f.name]
            if len(files)!=1:raise ValueError(f'Expected one Angle 1: {folder.name} {label}: {files}')
            pose=folder.name.lower().replace(' ','_');out=args.output/pose/f'{pose}_rtmw_original_{label}_full'
            jobs.append((pose,label,files[0],out))
    args.output.mkdir(parents=True,exist_ok=True)
    progress=args.output/'rtmw_original_batch_status.json'
    status=[]
    for pose,label,video,out in jobs:
        entry=dict(pose_id=pose,source_label=label,source_video=str(video.resolve()),output=str(out.resolve()),status='running')
        status.append(entry);progress.write_text(json.dumps(status,indent=2)+'\n')
        marker=out/'verified.json'
        if not marker.exists():
            if out.exists():raise RuntimeError(f'Incomplete output exists; inspect before resuming: {out}')
            print(f'START {pose} {label}',flush=True)
            subprocess.run([sys.executable,str(Path(__file__).with_name('compare_rtmpose.py')),'--video',str(video),'--model',str(args.model),'--model-label','RTMW-x','--output',str(out)],check=True)
            rows=[json.loads(s) for s in (out/'keypoints_133.jsonl').read_text().splitlines()]
            source=cv2.VideoCapture(str(video));expected=int(source.get(cv2.CAP_PROP_FRAME_COUNT));source.release()
            assert rows and len(rows)==expected
            assert all(np.asarray(r['keypoints']).shape==(133,2) and len(r['scores'])==133 and np.isfinite(r['keypoints']).all() and np.isfinite(r['scores']).all() for r in rows)
            assert all(a['timestamp_ms']<b['timestamp_ms'] for a,b in zip(rows,rows[1:]))
            cap=cv2.VideoCapture(str(out/'skeleton_review.mp4'));assert cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT))==expected;cap.release()
            (out/'selection.json').write_text(json.dumps(dict(pose_id=pose,source_video=str(video.resolve()),source_label=label,label_scope='filename only, not per-frame ground truth',dataset_variant='original',camera_view='angle_1_unverified',view_review='Angle 1 selected by filename; anatomical view needs manual verification',source_timestamp_offset_ms=0,segments=[],review_status='requires_manual_review'),indent=2)+'\n')
            marker.write_text(json.dumps(dict(frames=expected,checks=['frame count','133 keypoints','finite values','increasing timestamps','video frame count']),indent=2)+'\n')
        entry.update(status='complete',frames=json.loads(marker.read_text())['frames']);progress.write_text(json.dumps(status,indent=2)+'\n')
        print(f'DONE {pose} {label}: {entry["frames"]} frames',flush=True)
    print(f'COMPLETE {len(jobs)} clips',flush=True)


if __name__=='__main__':main()
