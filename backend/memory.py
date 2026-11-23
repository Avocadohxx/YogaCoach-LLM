# Owner: D —— L1 事件 / L2 会话摘要 / L3 用户偏好 读写逻辑
"""Memory read/write operations for YogaCoach.

* L1 = pose events      —— B 产出的、被判定为可信的偏差事件（相同偏差持续出现会合并为一条“片段”）
* L2 = session summary  —— 一次练习的事实性摘要，只由已入库的 L1 事件 + 反馈日志生成
* L3 = user preferences —— 仅保存用户明确设置/确认的偏好，不做自动推断、不自动升级

D 只存“观察到的事实”和“用户确认的偏好”，不编造姿态测量值，也不做医疗判断。
"""
from __future__ import annotations

import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .database import connection, init_db

# ---------------------------------------------------------------------------
# 常量（枚举名称仅用于摘要措辞；未知类型原样输出，不会报错，B 改枚举时不用改 D）
# ---------------------------------------------------------------------------
POSE_NAMES = {
    "tadasana": "山式",
    "ardhakati_chakrasana": "站立侧弯式",
}
DEVIATION_NAMES = {
    "shoulder_asymmetry": "双肩高度差异",
    "torso_tilt": "躯干侧倾",
    "elbow_bend": "持续肘部弯曲",
    "upper_arm_alignment": "上臂位置偏差",
    "bend_direction_mismatch": "侧弯方向不一致",
}
SIDE_NAMES = {
    "left_higher": "左侧偏高",
    "right_higher": "右侧偏高",
    "left": "偏向左侧",
    "right": "偏向右侧",
}
SEVERITY_NAMES = {"mild": "轻微", "moderate": "中等", "severe": "明显"}
SEVERITY_RANK = {"mild": 1, "moderate": 2, "severe": 3}

#: 同一 (type, side) 偏差，两次观察间隔不超过该值则视为同一个片段，合并为一条 L1 记录。
MERGE_GAP_MS = 3000
#: 只有 tracking_quality 为该值时，事件才可信、才入库（与 MVP “置信不足不纠错”一致）。
TRUSTED_TRACKING_QUALITY = "good"

_PREF_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def create_session(
    session_id: str,
    pose_id: str | None = None,
    user_id: str = "default",
    started_at: str | None = None,
) -> None:
    """Create a session (idempotent: calling again updates pose/start time)."""
    if not session_id:
        raise ValueError("session_id is required")
    init_db()
    with connection() as conn:
        conn.execute(
            """INSERT INTO sessions(session_id,user_id,pose_id,started_at)
               VALUES(?,?,?,?)
               ON CONFLICT(session_id) DO UPDATE SET
                 pose_id=COALESCE(excluded.pose_id,sessions.pose_id),
                 started_at=COALESCE(excluded.started_at,sessions.started_at)""",
            (session_id, user_id, pose_id, started_at),
        )


def _ensure_session(conn, session_id: str, pose_id: str | None, user_id: str) -> None:
    conn.execute(
        """INSERT INTO sessions(session_id,user_id,pose_id,started_at)
           VALUES(?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
           ON CONFLICT(session_id) DO UPDATE SET
             pose_id=COALESCE(sessions.pose_id,excluded.pose_id)""",
        (session_id, user_id, pose_id),
    )


def get_session(session_id: str) -> dict[str, Any] | None:
    init_db()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def finish_session(
    session_id: str,
    ended_at: str | None = None,
    auto_summary: bool = True,
) -> str | None:
    """Mark a session ended. If no summary exists yet and ``auto_summary`` is
    true, generate the factual L2 summary from stored L1 events. Returns the
    summary (existing or generated) or None."""
    init_db()
    with connection() as conn:
        cursor = conn.execute(
            """UPDATE sessions
               SET ended_at=COALESCE(?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
               WHERE session_id=?""",
            (ended_at, session_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Unknown session_id: {session_id}")
        row = conn.execute(
            "SELECT summary FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    existing = row["summary"]
    if existing or not auto_summary:
        return existing
    summary = build_session_summary(session_id)
    save_session_summary(session_id, summary)
    return summary


def save_session_summary(session_id: str, summary: str) -> None:
    """Store/overwrite the L2 summary (e.g. one supplied by C)."""
    if not session_id:
        raise ValueError("session_id is required")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")
    init_db()
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE sessions SET summary=? WHERE session_id=?",
            (summary.strip(), session_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Unknown session_id: {session_id}")


def get_recent_sessions(
    pose_id: str | None = None,
    user_id: str = "default",
    limit: int = 5,
    exclude_session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Recent sessions that have an L2 summary, newest first."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    init_db()
    sql = """SELECT session_id,user_id,pose_id,started_at,ended_at,summary,created_at
             FROM sessions WHERE user_id=? AND summary IS NOT NULL"""
    params: list[Any] = [user_id]
    if pose_id:
        sql += " AND pose_id=?"
        params.append(pose_id)
    if exclude_session_id:
        sql += " AND session_id<>?"
        params.append(exclude_session_id)
    sql += " ORDER BY COALESCE(ended_at,started_at,created_at) DESC, rowid DESC LIMIT ?"
    params.append(limit)
    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def delete_session(session_id: str) -> bool:
    """Delete a session and its events, feedback, and evidence images."""
    from .history_storage import delete_session_snapshot_files

    delete_session_snapshot_files(session_id)
    init_db()
    with connection() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
    return cursor.rowcount > 0


def delete_user_data(user_id: str = "default") -> dict[str, int]:
    """Erase every session, event, feedback, preference, and evidence image."""
    from .history_storage import delete_session_snapshot_files

    init_db()
    with connection() as conn:
        session_ids = [
            row[0]
            for row in conn.execute(
                "SELECT session_id FROM sessions WHERE user_id=?", (user_id,)
            ).fetchall()
        ]
    for session_id in session_ids:
        delete_session_snapshot_files(session_id)
    with connection() as conn:
        s = conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,)).rowcount
        p = conn.execute(
            "DELETE FROM user_preferences WHERE user_id=?", (user_id,)
        ).rowcount
    return {"sessions": s, "preferences": p}


# ---------------------------------------------------------------------------
# L1: pose events
# ---------------------------------------------------------------------------
def save_pose_event(session_id: str, event: dict[str, Any]) -> str:
    """Persist ONE deviation record as-is (no merging). Extra fields are kept in
    payload_json. Accepts ``event_type`` or ``type`` as the type key."""
    if not session_id:
        raise ValueError("session_id is required")
    if not isinstance(event, dict):
        raise TypeError("event must be a dictionary")
    event_type = event.get("event_type") or event.get("type")
    if not event_type:
        raise ValueError("event must include event_type or type")
    event_id = str(event.get("event_id") or _id("evt"))
    payload = json.dumps(event, ensure_ascii=False, default=str)
    init_db()
    with connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"Unknown session_id: {session_id}. Create the session first.")
        conn.execute(
            """INSERT INTO pose_events
               (event_id,session_id,event_type,side,severity,confidence,
                timestamp_ms,duration_ms,payload_json)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                event_id, session_id, str(event_type), event.get("side"),
                event.get("severity"), event.get("confidence"),
                event.get("timestamp_ms"), event.get("duration_ms"), payload,
            ),
        )
    return event_id


def save_analysis_event(
    event: dict[str, Any],
    session_id: str | None = None,
    user_id: str = "default",
    auto_create_session: bool = True,
) -> dict[str, Any]:
    """Persist a full B→C analysis event (``contracts/mock/analysis_event.json``).

    * 事件里的 ``deviations`` 数组被拆开，每个偏差一条 L1 记录；
    * ``feedback_allowed`` 不是明确的 True / ``tracking_quality`` 不是明确的 good / 无偏差 → 不入库
      （不可信的观察不能进入长期记忆）；
    * 同一 (type, side) 偏差在 ``MERGE_GAP_MS`` 内重复出现 → 合并进上一条片段
      （更新 duration_ms / confidence / severity，payload 里 ``count`` +1），
      避免 B 每 200ms 一次的上报把 L1 灌满。

    Returns ``{"saved": n_new, "merged": n_merged, "skipped_reason": str|None}``.
    """
    if not isinstance(event, dict):
        raise TypeError("event must be a dictionary")
    sid = session_id or event.get("session_id")
    if not sid:
        raise ValueError("session_id is required (argument or event['session_id'])")
    deviations = event.get("deviations") or []
    if not isinstance(deviations, list):
        raise ValueError("deviations must be a list")

    if event.get("feedback_allowed") is not True:
        return {"saved": 0, "merged": 0, "skipped_reason": "feedback_not_allowed"}
    quality = event.get("tracking_quality")
    if quality != TRUSTED_TRACKING_QUALITY:
        return {"saved": 0, "merged": 0, "skipped_reason": "tracking_quality_not_good"}
    if not deviations:
        return {"saved": 0, "merged": 0, "skipped_reason": "no_deviation"}

    ts = event.get("timestamp_ms")
    init_db()
    saved = merged = 0
    with connection() as conn:
        if auto_create_session:
            _ensure_session(conn, sid, event.get("pose_id"), user_id)
        elif not conn.execute(
            "SELECT 1 FROM sessions WHERE session_id=?", (sid,)
        ).fetchone():
            raise ValueError(f"Unknown session_id: {sid}. Create the session first.")

        for dev in deviations:
            if not isinstance(dev, dict):
                raise ValueError("each deviation must be an object")
            dtype = dev.get("type") or dev.get("event_type")
            if not dtype:
                raise ValueError("deviation must include type")
            side = dev.get("side")
            record = dict(dev)
            record.setdefault("timestamp_ms", ts)
            record["pose_id"] = event.get("pose_id")
            now_ts = record.get("timestamp_ms")

            last = conn.execute(
                """SELECT rowid AS rid,event_id,severity,confidence,timestamp_ms,
                          duration_ms,payload_json
                   FROM pose_events
                   WHERE session_id=? AND event_type=? AND COALESCE(side,'')=COALESCE(?,'')
                   ORDER BY rowid DESC LIMIT 1""",
                (sid, str(dtype), side),
            ).fetchone()

            if last is not None and now_ts is not None:
                try:
                    old = json.loads(last["payload_json"] or "{}")
                except json.JSONDecodeError:
                    old = {}
                last_seen = old.get("last_timestamp_ms", last["timestamp_ms"])
                if last_seen is not None and 0 <= now_ts - last_seen <= MERGE_GAP_MS:
                    first_ts = last["timestamp_ms"] if last["timestamp_ms"] is not None else now_ts
                    new_duration = max(
                        last["duration_ms"] or 0,
                        dev.get("duration_ms") or 0,
                        now_ts - first_ts,
                    )
                    sev_old, sev_new = last["severity"], dev.get("severity")
                    severity = (
                        sev_new
                        if SEVERITY_RANK.get(sev_new, 0) > SEVERITY_RANK.get(sev_old, 0)
                        else sev_old
                    )
                    conf_vals = [c for c in (last["confidence"], dev.get("confidence")) if c is not None]
                    old["last_timestamp_ms"] = now_ts
                    old["count"] = int(old.get("count", 1)) + 1
                    old["duration_ms"] = new_duration
                    old["severity"] = severity
                    conn.execute(
                        """UPDATE pose_events SET duration_ms=?,severity=?,confidence=?,
                                  payload_json=? WHERE event_id=?""",
                        (
                            new_duration, severity,
                            max(conf_vals) if conf_vals else None,
                            json.dumps(old, ensure_ascii=False, default=str),
                            last["event_id"],
                        ),
                    )
                    merged += 1
                    continue

            record["count"] = 1
            record["last_timestamp_ms"] = now_ts
            conn.execute(
                """INSERT INTO pose_events
                   (event_id,session_id,event_type,side,severity,confidence,
                    timestamp_ms,duration_ms,payload_json)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    _id("evt"), sid, str(dtype), side, dev.get("severity"),
                    dev.get("confidence"), now_ts, dev.get("duration_ms"),
                    json.dumps(record, ensure_ascii=False, default=str),
                ),
            )
            saved += 1
    return {"saved": saved, "merged": merged, "skipped_reason": None}


def update_rule_episode(session_id: str, lifecycle: dict[str, Any]) -> None:
    """Update an already confirmed episode; interruptions never imply recovery."""
    init_db()
    with connection() as conn:
        row = conn.execute('SELECT payload_json FROM pose_events WHERE session_id=? AND event_id=?',
            (session_id, lifecycle['event_id'])).fetchone()
        if row is None:
            return
        payload = json.loads(row['payload_json'])
        payload.update(lifecycle_status=lifecycle['status'], duration_ms=lifecycle['duration_ms'],
            end_timestamp_ms=lifecycle.get('end_timestamp_ms'), interruption_reason=lifecycle.get('interruption_reason'))
        conn.execute('UPDATE pose_events SET duration_ms=?,payload_json=? WHERE session_id=? AND event_id=?',
            (lifecycle['duration_ms'], json.dumps(payload, ensure_ascii=False), session_id, lifecycle['event_id']))


def get_pose_events(session_id: str) -> list[dict[str, Any]]:
    init_db()
    with connection() as conn:
        rows = conn.execute(
            """SELECT * FROM pose_events
               WHERE session_id=? ORDER BY timestamp_ms ASC, rowid ASC""",
            (session_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if item.get("payload_json"):
            try:
                item["payload"] = json.loads(item["payload_json"])
            except json.JSONDecodeError:
                item["payload"] = None
        result.append(item)
    return result


def get_progress_snapshot(user_id: str = "default", pose_id: str | None = None) -> dict[str, Any]:
    """Return compact, ID-free historical training evidence for C's LLM summary."""
    init_db()
    with connection() as conn:
        sql = """SELECT session_id,pose_id,started_at,ended_at,summary
                 FROM sessions WHERE user_id=? AND ended_at IS NOT NULL"""
        params: list[Any] = [user_id]
        if pose_id:
            sql += " AND pose_id=?"
            params.append(pose_id)
        sql += " ORDER BY COALESCE(ended_at,started_at,created_at) ASC,rowid ASC"
        sessions = [dict(row) for row in conn.execute(sql, params).fetchall()]
        details = []
        for session in sessions:
            events = conn.execute(
                """SELECT event_type,side,duration_ms,payload_json FROM pose_events
                   WHERE session_id=? ORDER BY rowid""", (session["session_id"],)
            ).fetchall()
            feedback = conn.execute(
                """SELECT event_type,feedback_text FROM feedback_logs
                   WHERE session_id=? ORDER BY rowid""", (session["session_id"],)
            ).fetchall()
            numeric_events = []
            for row in events:
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    continue
                observed = payload.get("observed_value")
                bounds = payload.get("reference_range")
                if (not payload.get("rule_id") or not payload.get("feature_name")
                        or not isinstance(observed, (int, float)) or isinstance(observed, bool)
                        or not isinstance(bounds, list) or len(bounds) != 2):
                    continue
                low, high = bounds
                if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in bounds):
                    continue
                numeric_events.append({
                    "event_type": row["event_type"], "target": payload.get("target") or row["side"],
                    "rule_id": payload["rule_id"], "rule_version": payload.get("rule_version"),
                    "feature_name": payload["feature_name"], "observed_value": round(float(observed), 2),
                    "unit": "deg" if str(payload["feature_name"]).endswith("_deg") else payload.get("unit"),
                    "reference_range": [low, high],
                    "deviation_from_range": round(max(float(low) - float(observed), 0, float(observed) - float(high)), 2),
                    "duration_ms": row["duration_ms"],
                    "lifecycle_status": payload.get("lifecycle_status", "confirmed"),
                })
            details.append({
                "pose_id": session["pose_id"], "started_at": session["started_at"],
                "ended_at": session["ended_at"], "stored_summary": session["summary"],
                "confirmed_measurements": numeric_events,
                "feedback": [{"type": f["event_type"], "text": f["feedback_text"][:240]} for f in feedback],
            })
    return {"sessions": details, "preferences": get_user_preferences(user_id)}


# ---------------------------------------------------------------------------
# L2: factual summary
# ---------------------------------------------------------------------------
def _fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{max(seconds, 1)} 秒"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} 分钟" if rest < 10 else f"{minutes} 分 {rest} 秒"


def build_session_summary(session_id: str) -> str:
    """Deterministic, factual summary built ONLY from stored L1 events and
    feedback logs of the session. No model call, no invented measurements."""
    session = get_session(session_id)
    if session is None:
        raise ValueError(f"Unknown session_id: {session_id}")
    events = get_pose_events(session_id)
    feedback = get_recent_feedback(session_id, n=100)

    pose = POSE_NAMES.get(session["pose_id"] or "", session["pose_id"] or "未知动作")
    start, end = _parse_ts(session["started_at"]), _parse_ts(session["ended_at"])
    head = f"{pose}练习"
    if start and end and end >= start:
        head += f"约 {_fmt_duration((end - start).total_seconds())}"

    if not events:
        text = head + "，未记录到姿态偏差片段（这不代表姿态完全标准，只表示未检测到可信的偏差）。"
    else:
        groups: dict[tuple[str, str | None], list[dict]] = {}
        for ev in events:
            groups.setdefault((ev["event_type"], ev["side"]), []).append(ev)
        parts = []
        for (etype, side), evs in groups.items():
            name = DEVIATION_NAMES.get(etype, etype)
            worst = max(evs, key=lambda e: SEVERITY_RANK.get(e["severity"] or "", 0))
            sev = SEVERITY_NAMES.get(worst["severity"] or "")
            detail = "、".join(
                x for x in (SIDE_NAMES.get(side or "", side), f"最高程度{sev}" if sev else None) if x
            )
            parts.append(f"{name} {len(evs)} 次" + (f"（{detail}）" if detail else ""))
        text = head + "，检测到：" + "；".join(parts) + "。"
    if feedback:
        text += f"期间系统给出提示 {len(feedback)} 次。"
        prompt_groups: dict[str, list[str]] = defaultdict(list)
        for item in feedback:
            event_type = item.get("event_type") or "general_hint"
            if event_type == "camera_hint":
                label = "镜头与观察提示"
            elif event_type in DEVIATION_NAMES:
                label = f"{DEVIATION_NAMES[event_type]}纠正提示"
            else:
                label = "其他练习提示"
            prompt_groups[label].append(item["feedback_text"].strip())

        prompt_parts = []
        for label, messages in prompt_groups.items():
            variants = Counter(messages)
            examples = []
            for message, count in variants.most_common(2):
                quoted = message if len(message) <= 180 else message[:177] + "…"
                examples.append(f"“{quoted}”（{count} 次）")
            extra = len(variants) - len(examples)
            detail = "、".join(examples)
            if extra:
                detail += f"；另有 {extra} 种不同表述"
            prompt_parts.append(f"{label}（共 {len(messages)} 次）：{detail}")
        if prompt_parts:
            text += "本次提示重点：" + "；".join(prompt_parts) + "。"
    return text


# ---------------------------------------------------------------------------
# L3: preferences
# ---------------------------------------------------------------------------
def get_user_preferences(user_id: str = "default") -> dict[str, str]:
    init_db()
    with connection() as conn:
        rows = conn.execute(
            """SELECT preference_key,preference_value
               FROM user_preferences WHERE user_id=? ORDER BY preference_key""",
            (user_id,),
        ).fetchall()
    return {row["preference_key"]: row["preference_value"] for row in rows}


def set_user_preference(
    preference_key: str,
    preference_value: Any,
    user_id: str = "default",
) -> str:
    """Upsert a user-confirmed preference. Keys are snake_case; bool values are
    stored as 'true'/'false'. Only call this for preferences the user set/confirmed."""
    if not isinstance(preference_key, str) or not _PREF_KEY_RE.match(preference_key):
        raise ValueError("preference_key must be snake_case, 1-64 chars, starting with a letter")
    if isinstance(preference_value, bool):
        preference_value = "true" if preference_value else "false"
    if preference_value is None or not str(preference_value).strip():
        raise ValueError("preference_value is required")
    value = str(preference_value).strip()
    init_db()
    with connection() as conn:
        conn.execute(
            """INSERT INTO user_preferences
               (preference_id,user_id,preference_key,preference_value)
               VALUES(?,?,?,?)
               ON CONFLICT(user_id,preference_key) DO UPDATE SET
                 preference_value=excluded.preference_value,
                 updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            (_id("pref"), user_id, preference_key, value),
        )
        row = conn.execute(
            """SELECT preference_id FROM user_preferences
               WHERE user_id=? AND preference_key=?""",
            (user_id, preference_key),
        ).fetchone()
    return row["preference_id"]


def delete_user_preference(preference_key: str, user_id: str = "default") -> bool:
    init_db()
    with connection() as conn:
        cursor = conn.execute(
            "DELETE FROM user_preferences WHERE user_id=? AND preference_key=?",
            (user_id, preference_key),
        )
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Feedback log (for de-duplication / cool-down on C's side)
# ---------------------------------------------------------------------------
def get_recent_feedback(session_id: str, n: int = 5) -> list[dict[str, Any]]:
    """Latest ``n`` feedback logs of a session, newest first."""
    if n < 1 or n > 100:
        raise ValueError("n must be between 1 and 100")
    init_db()
    with connection() as conn:
        rows = conn.execute(
            """SELECT feedback_id,session_id,event_type,feedback_text,created_at
               FROM feedback_logs WHERE session_id=?
               ORDER BY created_at DESC, rowid DESC LIMIT ?""",
            (session_id, n),
        ).fetchall()
    return [dict(row) for row in rows]


def log_feedback(session_id: str, event_type: str | None, text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("feedback text is required")
    feedback_id = _id("fb")
    init_db()
    with connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"Unknown session_id: {session_id}")
        conn.execute(
            """INSERT INTO feedback_logs
               (feedback_id,session_id,event_type,feedback_text)
               VALUES(?,?,?,?)""",
            (feedback_id, session_id, event_type, text.strip()),
        )
    return feedback_id


# ---------------------------------------------------------------------------
# D → C: one-call memory context (shape of contracts/mock/memory_sample.json)
# ---------------------------------------------------------------------------
def _normalize_pref(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    return value


def get_memory_context(
    pose_id: str | None = None,
    session_id: str | None = None,
    user_id: str = "default",
    n_sessions: int = 3,
    n_feedback: int = 5,
) -> dict[str, Any]:
    """Everything C needs before composing feedback, in the D→C contract shape::

        {"recent_sessions": [{session_id,pose_id,ended_at,summary}],
         "recent_feedback": [{event_type,text,created_at}],   # this session only
         "preferences": {"feedback_length": "short", "voice": false}}

    The current session is excluded from ``recent_sessions``.
    """
    sessions = get_recent_sessions(
        pose_id=pose_id, user_id=user_id, limit=n_sessions, exclude_session_id=session_id
    )
    feedback = get_recent_feedback(session_id, n_feedback) if session_id else []
    return {
        "recent_sessions": [
            {
                "session_id": s["session_id"],
                "pose_id": s["pose_id"],
                "ended_at": s["ended_at"] or s["started_at"],
                "summary": s["summary"],
            }
            for s in sessions
        ],
        "recent_feedback": [
            {"event_type": f["event_type"], "text": f["feedback_text"], "created_at": f["created_at"]}
            for f in feedback
        ],
        "preferences": {k: _normalize_pref(v) for k, v in get_user_preferences(user_id).items()},
    }
