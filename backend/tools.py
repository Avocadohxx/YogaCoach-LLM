"""Read-only tools. Knowledge files retain their explicit review status."""
import json
import os
from pathlib import Path
from backend import memory


def reference_for(pose_id: str) -> dict:
    if pose_id not in {"tadasana", "ardhakati_chakrasana"}:
        raise ValueError("unsupported pose")
    root = Path(__file__).resolve().parents[1] / "knowledge"
    path = root / f"{pose_id}.json"
    reference = json.loads(path.read_text(encoding="utf-8"))
    # Runtime candidate rules live in separate, versioned rule files.
    if pose_id == "tadasana":
        override = os.getenv("POSE133_TADASANA_RULES_PATH")
        reference["rules_file"] = str(Path(override).resolve()) if override else "tadasana_rules_B.json"
    else:
        override = os.getenv("POSE133_ARDHAKATI_RULES_PATH")
        reference["rules_file"] = str(Path(override).resolve()) if override else "ardhakati_chakrasana_rules.json"
    return reference


def context_for(session_id: str, pose_id: str) -> dict:
    session = memory.get_session(session_id)
    if session is None or session["pose_id"] != pose_id or session["ended_at"] is not None:
        raise ValueError("Unknown session or pose mismatch")
    return memory.get_memory_context(pose_id, session_id, session["user_id"])
