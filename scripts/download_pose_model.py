"""Download pinned Google Pose Landmarker asset without committing binaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.request
import zipfile

URL = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task'
TARGET = Path(__file__).resolve().parents[1] / 'frontend/public/models/pose_landmarker_lite.task'


def validate(path, expected=None):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected and digest != expected.lower():
        raise ValueError('SHA256 does not match expected value')
    with zipfile.ZipFile(path) as bundle:
        if bundle.testzip() is not None or len([n for n in bundle.namelist() if n.endswith('.tflite')]) < 2:
            raise ValueError('Invalid Pose Landmarker task bundle')
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha256', help='Optional externally verified digest')
    args = parser.parse_args()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        digest = validate(TARGET, args.sha256)
    else:
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=TARGET.parent, delete=False) as out:
                name = Path(out.name)
                with urllib.request.urlopen(URL, timeout=45) as source:
                    while chunk := source.read(65536):
                        out.write(chunk)
                        if out.tell() > 32 * 1024 * 1024:
                            raise ValueError('Unexpected model size')
            digest = validate(name, args.sha256)
            os.replace(name, TARGET)
        finally:
            if name is not None:
                name.unlink(missing_ok=True)
    print(json.dumps({'path': str(TARGET), 'source': URL, 'sha256': digest}, indent=2))


if __name__ == '__main__':
    main()
