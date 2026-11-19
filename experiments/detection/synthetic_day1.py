"""Owner B: reproducible SYNTHETIC geometry, never real posture evaluation.

Run from repository root: python -m experiments.detection.synthetic_day1
This only updates B's fixtures and B's analysis mocks; A's mock stays untouched.
"""
import json
from copy import deepcopy
from pathlib import Path

from backend.pose_analyzer import analyze_frame
from backend.schemas import AnalysisResult, PoseFrame


def make_frame(kind: str = "normal") -> dict:
    # Minimal illustrative person; unused joints have visibility 0.
    landmarks = [dict(x=0.5, y=0.5, z=0.0, visibility=0.0) for _ in range(33)]
    positions = {
        0: (0.5, 0.12), 1: (0.515, 0.11), 2: (0.525, 0.11),
        3: (0.535, 0.11), 4: (0.485, 0.11), 5: (0.475, 0.11),
        6: (0.465, 0.11), 7: (0.55, 0.12), 8: (0.45, 0.12),
        9: (0.52, 0.15), 10: (0.48, 0.15),
        11: (0.6, 0.3), 12: (0.4, 0.3),
        13: (0.6, 0.43), 14: (0.4, 0.43),
        15: (0.6, 0.56), 16: (0.4, 0.56),
        23: (0.56, 0.6), 24: (0.44, 0.6),
        25: (0.56, 0.75), 26: (0.44, 0.75),
        27: (0.56, 0.9), 28: (0.44, 0.9),
        29: (0.57, 0.92), 30: (0.43, 0.92),
        31: (0.59, 0.93), 32: (0.41, 0.93),
    }
    for i, (x, y) in positions.items():
        landmarks[i].update(x=x, y=y, visibility=0.99)
    frame = dict(
        session_id="synthetic-day1", pose_id="tadasana", frame_seq=0,
        timestamp_ms=0, image_width=1280, image_height=720,
        camera_view="front", coordinate_space="normalized_image",
        phase="hold", side=None, landmarks=landmarks,
    )
    if kind == "shoulder_difference":
        landmarks[11]["y"] = 0.24
    elif kind == "occluded":
        for p in landmarks:
            p["visibility"] = 0.0
    elif kind == "side_bend":
        frame.update(pose_id="ardhakati_chakrasana", side="left")
        # Illustrates a tilted torso, NOT a validated yoga demonstration.
        for i in range(23):
            landmarks[i]["x"] += 0.08
    elif kind != "normal":
        raise ValueError(f"Unknown fixture kind: {kind}")
    return frame


def make_mocks() -> dict[str, dict]:
    normal = analyze_frame(PoseFrame.model_validate(make_frame())).model_dump()
    normal.update(
        analysis_mode="synthetic_mock", reference_status="unvalidated_synthetic",
        assessment_status="within_reference",
    )
    deviation = analyze_frame(PoseFrame.model_validate(
        make_frame("shoulder_difference")
    )).model_dump()
    value = next(o["value"] for o in deviation["observations"]
                 if o["name"] == "shoulder_height_diff")
    deviation.update(
        analysis_mode="synthetic_mock", reference_status="unvalidated_synthetic",
        assessment_status="deviation", timestamp_ms=1800, frame_seq=9,
        feedback_allowed=True,
        deviations=[dict(
            event_id="synthetic-shoulder-01", type="shoulder_asymmetry",
            side="left_higher", severity="mild", confidence=0.99,
            duration_ms=1800, feature_name="shoulder_height_diff",
            observed_value=value, reference_range=[0.0, 0.1],
        )],
    )
    invalid = analyze_frame(PoseFrame.model_validate(make_frame("occluded"))).model_dump()
    invalid.update(analysis_mode="synthetic_mock", reference_status="unvalidated_synthetic")
    mocks = {"normal": normal, "deviation": deviation, "not_assessable": invalid}
    for mock in mocks.values():
        AnalysisResult.model_validate(mock)
    return mocks


def generate(root: Path):
    def write(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")

    fixtures = root / "experiments/detection/fixtures"
    for kind in ("normal", "shoulder_difference", "occluded", "side_bend"):
        write(fixtures / f"{kind}.json", make_frame(kind))
    mocks = make_mocks()
    for kind, payload in mocks.items():
        write(root / f"contracts/mock/b_day1/analysis_{kind}.json", payload)
    write(root / "contracts/mock/analysis_event.json", deepcopy(mocks["deviation"]))
    write(fixtures / "manifest.json", dict(
        source="synthetic_python_generator", real_people=False,
        validated_reference=False, review_status="TEAM_REVIEW_REQUIRED",
        note="合成联调数据；持续1800ms、参考范围及事件均为手工设定，不是检测结果。"
             "confidence仅示意关键点质量，不是错误概率。normal也不代表真实动作标准。",
    ))
    print("Generated 4 synthetic frames + 3 analysis mocks (NOT real evaluation).")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[2])
