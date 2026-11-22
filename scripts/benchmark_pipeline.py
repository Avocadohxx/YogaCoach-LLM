"""Measure actual local pipeline latency; not a detection-accuracy evaluation."""
import argparse,json,statistics,tempfile,os,time
from pathlib import Path
import cv2
from fastapi.testclient import TestClient
from backend.main import app

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',type=Path,required=True);p.add_argument('--frames',type=int,default=20)
    p.add_argument('--output',type=Path);args=p.parse_args()
    if args.frames<2:raise SystemExit('Use at least 2 frames')
    image=cv2.imread(str(args.image))
    if image is None:raise SystemExit('Cannot read image')
    payload=cv2.imencode('.jpg',image)[1].tobytes()
    elapsed=[]
    with tempfile.TemporaryDirectory() as d:
        previous=os.environ.get('YOGACOACH_DB_PATH');os.environ['YOGACOACH_DB_PATH']=str(Path(d)/'bench.db')
        try:
            with TestClient(app) as client:
                client.post('/api/memory/sessions',json={'session_id':'benchmark','pose_id':'tadasana'}).raise_for_status()
                for n in range(args.frames):
                    start=time.perf_counter()
                    r=client.post(f'/api/pose/frame?session_id=benchmark&frame_seq={n}&timestamp_ms={n*100}&phase=prepare&camera_view=front',content=payload,headers={'Content-Type':'image/jpeg'})
                    r.raise_for_status();elapsed.append((time.perf_counter()-start)*1000)
                    assert len(r.json()['keypoints'])==133
        finally:
            if previous is None:os.environ.pop('YOGACOACH_DB_PATH',None)
            else:os.environ['YOGACOACH_DB_PATH']=previous
    warm=sorted(elapsed[1:]);percent=lambda q:warm[int((len(warm)-1)*q)]
    result={'scope':'local_testclient_repeated_image_prepare_phase_not_browser_fps_or_accuracy','samples':args.frames,
        'cold_ms':elapsed[0],'warm_p50_ms':percent(.5),'warm_p95_ms':percent(.95),'warm_p99_ms':percent(.99)}
    print(json.dumps(result,indent=2))
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
