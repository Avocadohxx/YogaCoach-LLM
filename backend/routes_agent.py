"""LangGraph feedback endpoint; calibrated corrections remain disabled."""
from fastapi import APIRouter
from backend.agent import feedback_for
from backend.prompts import Feedback
from backend.schemas import AnalysisResult

router = APIRouter()


@router.post("/api/agent/feedback", response_model=Feedback, tags=["agent"])
def feedback(event: AnalysisResult) -> Feedback:
    return feedback_for(event)
