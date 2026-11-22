"""Read-only tools. Knowledge files retain their explicit review status."""
import json
from pathlib import Path
from backend import memory


def reference_for(pose_id: str) -> dict:
    if pose_id not in {"tadasana", "ardhakati_chakrasana"}:
        raise ValueError("unsupported pose")
    path = Path(__file__).resolve().parents[1] / "knowledge" / f"{pose_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def context_for(session_id: str, pose_id: str) -> dict:
    session = memory.get_session(session_id)
    if session is None or session["pose_id"] != pose_id or session["ended_at"] is not None:
        raise ValueError("Unknown session or pose mismatch")
    context = memory.get_memory_context(pose_id, session_id, session["user_id"])
    # Only server rule episodes from completed matching practices are eligible.
    # User-written summaries never become evidence of a measured deviation.
    context['prior_focus'] = []
    for previous in context['recent_sessions']:
        for event in memory.get_pose_events(previous['session_id']):
            payload=event.get('payload') or {}
            if payload.get('server_generated') is True and payload.get('rule_version') and payload.get('source_model'):
                context['prior_focus'].append({'type':event['event_type'],'side':event['side']})
    return context
