"""Local image storage for training-history evidence snapshots."""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

from .database import REPO_ROOT, connection, init_db

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def get_media_root() -> Path:
    raw = os.getenv("YOGACOACH_MEDIA_DIR")
    path = Path(raw).expanduser() if raw else REPO_ROOT / "data" / "evidence"
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def _has_valid_signature(data: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def save_snapshot(
    *,
    session_id: str,
    image_bytes: bytes,
    content_type: str,
    pose_id: str | None = None,
    event_type: str | None = None,
    side: str | None = None,
    severity: str | None = None,
    confidence: float | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    if content_type not in ALLOWED_TYPES:
        raise ValueError("Only JPEG, PNG, and WEBP images are accepted")
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image must be between 1 byte and 5 MB")
    if not _has_valid_signature(image_bytes, content_type):
        raise ValueError("Uploaded file content does not match its image type")

    init_db()
    with connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"Unknown session_id: {session_id}")

    snapshot_id = f"snap_{uuid.uuid4().hex}"
    folder_name = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
    relative_path = Path(folder_name) / f"{snapshot_id}{ALLOWED_TYPES[content_type]}"
    root = get_media_root()
    target = (root / relative_path).resolve()
    if root not in target.parents:
        raise ValueError("Invalid snapshot path")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        temporary.write_bytes(image_bytes)
        os.replace(temporary, target)
        with connection() as conn:
            conn.execute(
                """INSERT INTO event_snapshots
                   (snapshot_id,session_id,pose_id,event_type,side,severity,
                    confidence,timestamp_ms,relative_path)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    snapshot_id,
                    session_id,
                    pose_id,
                    event_type,
                    side,
                    severity,
                    confidence,
                    timestamp_ms,
                    relative_path.as_posix(),
                ),
            )
    except Exception:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise

    return {
        "snapshot_id": snapshot_id,
        "session_id": session_id,
        "image_url": f"/api/memory/snapshots/{snapshot_id}/image",
        "timestamp_ms": timestamp_ms,
    }


def list_snapshots(session_id: str) -> list[dict[str, Any]]:
    init_db()
    with connection() as conn:
        rows = conn.execute(
            """SELECT snapshot_id,session_id,pose_id,event_type,side,severity,
                      confidence,timestamp_ms,feedback_text,created_at
               FROM event_snapshots WHERE session_id=?
               ORDER BY COALESCE(timestamp_ms,0),created_at""",
            (session_id,),
        ).fetchall()
    return [
        {
            **dict(row),
            "image_url": f"/api/memory/snapshots/{row['snapshot_id']}/image",
        }
        for row in rows
    ]


def get_snapshot_file(snapshot_id: str) -> tuple[Path, dict[str, Any]] | None:
    init_db()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM event_snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
    if not row:
        return None
    root = get_media_root()
    path = (root / row["relative_path"]).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path, dict(row)


def update_snapshot_feedback(snapshot_id: str, feedback_text: str) -> bool:
    init_db()
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE event_snapshots SET feedback_text=? WHERE snapshot_id=?",
            (feedback_text, snapshot_id),
        )
    return cursor.rowcount > 0


def delete_session_snapshot_files(session_id: str) -> None:
    init_db()
    with connection() as conn:
        rows = conn.execute(
            "SELECT relative_path FROM event_snapshots WHERE session_id=?",
            (session_id,),
        ).fetchall()
    root = get_media_root()
    for row in rows:
        path = (root / row["relative_path"]).resolve()
        if root in path.parents:
            path.unlink(missing_ok=True)
    for row in rows:
        folder = (root / row["relative_path"]).resolve().parent
        if root in folder.parents and folder.is_dir():
            try:
                folder.rmdir()
            except OSError:
                pass
