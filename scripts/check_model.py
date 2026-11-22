"""Explicit heavy-model smoke check; fast CI does not need LFS downloads."""
from pathlib import Path
import argparse,json
from backend.readiness import readiness
from backend.inference_133 import infer
import cv2
p=argparse.ArgumentParser();p.add_argument('--image',type=Path,required=True);args=p.parse_args()
state=readiness()
if not state['model']['available']:raise SystemExit('Model unavailable: '+state['model']['reason'])
image=cv2.imread(str(args.image))
if image is None:raise SystemExit('Cannot read image')
points,scores=infer(image)
print(json.dumps({'model':state['model']['name'],'points':len(points),'scores':len(scores)}))
