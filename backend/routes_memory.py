# Owner: D —— 会话、总结、偏好相关接口（前缀 /api/memory）
"""FastAPI routes for the D-owned memory subsystem.

main.py 已经挂载本 router，D 不需要也不应修改 main.py。
session_id 由 E 的前端生成（crypto.randomUUID），B 的 /api/analyze 也使用同一个 ID。
接口约定详见 docs/memory_design.md 第 10 节。
"""
from typing import Any, Optional, Union

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from . import memory
import os
from backend.evidence import store
from backend.schemas import AnalysisResult
from backend.session_activity import touch, incomplete
from .online_rules_133 import online_rules

router = APIRouter(prefix="/api/memory", tags=["memory"])


class SessionBody(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    pose_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(default="default", min_length=1, max_length=100)
    started_at: Optional[str] = None


class FinishBody(BaseModel):
    ended_at: Optional[str] = None
    auto_summary: bool = True


class PreferenceBody(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=100)
    preference_key: str = Field(min_length=1, max_length=64)
    preference_value: Union[bool, str, int, float]


class SummaryBody(BaseModel):
    summary: str = Field(min_length=1, max_length=10000)


class FeedbackBody(BaseModel):
    event_type: Optional[str] = None
    feedback_text: str = Field(min_length=1, max_length=3000)


class PoseEventBody(BaseModel):
    event: dict


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _not_found_or_bad(exc: Exception) -> HTTPException:
    code = 404 if "Unknown session_id" in str(exc) else 400
    return HTTPException(status_code=code, detail=str(exc))


def require_test_write():
    if os.getenv('YOGACOACH_ALLOW_TEST_WRITES') != '1':
        raise HTTPException(403, '正式事件与反馈仅由服务端写入。')


@router.get('/incomplete-sessions')
def incomplete_sessions():
    return {'items': incomplete()}


@router.post('/sessions/{session_id}/heartbeat')
def heartbeat(session_id: str):
    try: touch(session_id)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    return {'ok':True}


# ---- sessions -------------------------------------------------------------
@router.post("/sessions")
def post_session(body: SessionBody):
    try:
        memory.create_session(
            session_id=body.session_id,
            pose_id=body.pose_id,
            user_id=body.user_id,
            started_at=body.started_at,
        )
    except (ValueError, TypeError) as exc:
        raise _bad_request(exc) from exc
    try: touch(body.session_id)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    return {"ok": True, "session_id": body.session_id}


@router.get("/sessions")
def list_sessions(user_id: str = "default", pose_id: Optional[str] = None, limit: int = 5):
    try:
        return {"items": memory.get_recent_sessions(pose_id=pose_id, user_id=user_id, limit=limit)}
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    session = memory.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
    return session


@router.delete("/sessions/{session_id}")
def remove_session(session_id: str):
    if not memory.delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
    return {"ok": True, "deleted": session_id}


@router.post("/sessions/{session_id}/finish")
def post_finish_session(session_id: str, body: Optional[FinishBody] = None):
    body = body or FinishBody()
    try:
        online_rules.reset(session_id)
        summary = memory.finish_session(
            session_id, ended_at=body.ended_at, auto_summary=body.auto_summary
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "session_id": session_id, "summary": summary}


@router.post("/sessions/{session_id}/summary")
def put_summary(session_id: str, body: SummaryBody):
    try:
        memory.save_session_summary(session_id, body.summary)
    except ValueError as exc:
        raise _not_found_or_bad(exc) from exc
    return {"ok": True, "session_id": session_id}


# ---- L1 events ------------------------------------------------------------
@router.get("/sessions/{session_id}/events")
def list_pose_events(session_id: str):
    if memory.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
    return {"items": memory.get_pose_events(session_id)}


@router.post("/sessions/{session_id}/events")
def post_pose_event(session_id: str, body: PoseEventBody):
    """Test-only import; real events are written by the inference service."""
    require_test_write()
    try:
        event_id = memory.save_pose_event(session_id, body.event)
    except (ValueError, TypeError) as exc:
        raise _not_found_or_bad(exc) from exc
    return {"ok": True, "event_id": event_id}


@router.post("/sessions/{session_id}/analysis")
def post_analysis_event(session_id: str, event: dict[str, Any] = Body(...)):
    """Store a whole B→C analysis event (``deviations`` array is fanned out,
    untrusted events skipped, repeated deviations merged)."""
    require_test_write()
    if event.get("session_id") not in (None, session_id):
        raise HTTPException(status_code=400, detail="session_id in body does not match the path")
    try:
        result = memory.save_analysis_event(event, session_id=session_id)
    except (ValueError, TypeError) as exc:
        raise _bad_request(exc) from exc
    return {"ok": True, **result}


# ---- feedback log ---------------------------------------------------------
@router.get("/sessions/{session_id}/feedback")
def list_feedback(session_id: str, n: int = 5):
    try:
        return {"items": memory.get_recent_feedback(session_id, n)}
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/sessions/{session_id}/feedback")
def put_feedback(session_id: str, body: FeedbackBody):
    require_test_write()
    try:
        feedback_id = memory.log_feedback(session_id, body.event_type, body.feedback_text)
    except ValueError as exc:
        raise _not_found_or_bad(exc) from exc
    return {"ok": True, "feedback_id": feedback_id}


# ---- L3 preferences -------------------------------------------------------
@router.get("/preferences")
def list_preferences(user_id: str = "default"):
    return {"user_id": user_id, "preferences": memory.get_user_preferences(user_id)}


@router.put("/preferences")
def put_preference(body: PreferenceBody):
    try:
        pref_id = memory.set_user_preference(
            body.preference_key, body.preference_value, body.user_id
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return {"ok": True, "preference_id": pref_id}


@router.delete("/preferences/{preference_key}")
def remove_preference(preference_key: str, user_id: str = "default"):
    if not memory.delete_user_preference(preference_key, user_id):
        raise HTTPException(status_code=404, detail="Preference not found")
    return {"ok": True, "deleted": preference_key}


# ---- D → C context & privacy ----------------------------------------------
@router.get("/context")
def get_context(
    pose_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: str = "default",
    n_sessions: int = 3,
    n_feedback: int = 5,
):
    """Memory context in the shape of ``contracts/mock/memory_sample.json``."""
    try:
        return memory.get_memory_context(
            pose_id=pose_id, session_id=session_id, user_id=user_id,
            n_sessions=n_sessions, n_feedback=n_feedback,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete("/user-data")
def remove_user_data(user_id: str = "default"):
    """Erase all stored practice records and preferences of a user."""
    return {"ok": True, "deleted": memory.delete_user_data(user_id)}
