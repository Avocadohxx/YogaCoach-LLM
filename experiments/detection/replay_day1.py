"""Owner B: print raw measurements for a saved PoseFrame, without a camera."""
import argparse
import json
from pathlib import Path

from backend.pose_analyzer import analyze_frame
from backend.schemas import PoseFrame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frame", type=Path)
    args = parser.parse_args()
    frame = PoseFrame.model_validate(json.loads(args.frame.read_text()))
    print(analyze_frame(frame).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
