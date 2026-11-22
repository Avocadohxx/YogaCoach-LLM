"""Get the production RTMW weight via Git LFS and verify its recorded SHA256."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/'data/models/rtmw_x_384.onnx'
EXPECTED='b2dd00cce207d3c1503e35cc77a82ecd7092dcbdfe4a3c692ec4cdc3cf40c804'

def valid():
    if not MODEL.is_file() or MODEL.stat().st_size<1024:return False
    h=hashlib.sha256()
    with MODEL.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()==EXPECTED

if not valid():
    subprocess.run(['git','lfs','pull','--include=data/models/rtmw_x_384.onnx','--exclude='],cwd=ROOT,check=True)
if not valid():raise SystemExit('Model missing or SHA256 mismatch; no alternate weight was silently substituted.')
print(json.dumps({'model':MODEL.name,'sha256':EXPECTED,'bytes':MODEL.stat().st_size}))
