# Owner: D —— SQLite 表定义与连接管理
"""SQLite database layer for the D (memory) module.

仅使用 Python 标准库。数据库路径解析顺序：

1. 环境变量 ``YOGACOACH_DB_PATH``（D 模块专用，优先级最高，测试用它隔离数据库）
2. 公共 ``.env.example`` 里已有的 ``DATABASE_PATH``
3. 默认 ``<repo>/data/yogacoach.db``

相对路径一律以仓库根目录为基准，不依赖启动时的工作目录。
``*.db`` 已在 ``.gitignore`` 中，禁止提交数据库文件（含用户练习记录）。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = REPO_ROOT / "data" / "yogacoach.db"

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    pose_id TEXT,
    started_at TEXT,
    ended_at TEXT,
    summary TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS pose_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    side TEXT,
    severity TEXT,
    confidence REAL,
    timestamp_ms INTEGER,
    duration_ms INTEGER,
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback_logs (
    feedback_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT,
    feedback_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_preferences (
    preference_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    preference_key TEXT NOT NULL,
    preference_value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(user_id, preference_key)
);

CREATE TABLE IF NOT EXISTS event_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    pose_id TEXT,
    event_type TEXT,
    side TEXT,
    severity TEXT,
    confidence REAL,
    timestamp_ms INTEGER,
    feedback_text TEXT,
    relative_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_started
    ON sessions(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_pose
    ON sessions(pose_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pose_events_session
    ON pose_events(session_id, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_feedback_session
    ON feedback_logs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_preferences_user
    ON user_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_session_time
    ON event_snapshots(session_id, timestamp_ms);
"""

_init_lock = threading.Lock()
_initialized: set[str] = set()


def get_db_path() -> Path:
    raw = os.getenv("YOGACOACH_DB_PATH") or os.getenv("DATABASE_PATH")
    if not raw:
        return _DEFAULT_DB
    path = Path(raw).expanduser()
    if not path.is_absolute() and raw != ":memory:":
        path = REPO_ROOT / path
    return path


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Return a configured SQLite connection; the caller must close it."""
    path = Path(db_path) if db_path is not None else get_db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def connection(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Connection context: commit on success, rollback on error, always close."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None) -> None:
    """Create tables/indexes if missing. Idempotent and cheap after first call.

    ``:memory:`` databases are never cached (each connection is a fresh DB).
    """
    path = Path(db_path) if db_path is not None else get_db_path()
    key = str(path)
    if key != ":memory:" and key in _initialized and path.exists():
        return
    with _init_lock:
        with connection(path) as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                """INSERT INTO schema_meta(key,value) VALUES('schema_version',?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (str(SCHEMA_VERSION),),
            )
        if key != ":memory:":
            _initialized.add(key)


def reset_init_cache() -> None:
    """Test helper: forget which database files were already initialised."""
    with _init_lock:
        _initialized.clear()
