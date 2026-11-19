"""Measurement endpoint with short-lived server evidence snapshots; no LLM/DB call."""
from fastapi import APIRouter

from backend.evidence import store
from backend.pose_analyzer_133 import analyze_frame_133
from backend.pose_analyzer import analyze_frame
from backend.schemas import AnalysisResult, PoseFrame, PoseFrame133

router = APIRouter()


@router.post("/api/analyze", response_model=AnalysisResult, tags=["pose"])
def analyze(frame: PoseFrame | PoseFrame133) -> AnalysisResult:
    event = analyze_frame_133(frame) if isinstance(frame, PoseFrame133) else analyze_frame(frame)
    store.record(event)
    return event
