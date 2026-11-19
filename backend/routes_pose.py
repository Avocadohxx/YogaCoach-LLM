"""Owner B: stateless Day-1 measurement endpoint; no LLM or DB call."""
from fastapi import APIRouter

from backend.pose_analyzer import analyze_frame
from backend.schemas import AnalysisResult, PoseFrame

router = APIRouter()


@router.post("/api/analyze", response_model=AnalysisResult, tags=["pose"])
def analyze(frame: PoseFrame) -> AnalysisResult:
    return analyze_frame(frame)
