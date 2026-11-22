"""Best-effort client heartbeats with durable interruption status, no invented end."""
from time import time
from backend.database import init_db,connection

def setup(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS session_activity (session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,last_seen REAL NOT NULL,interrupted INTEGER NOT NULL DEFAULT 0)')

def touch(sid):
    init_db()
    with connection() as conn:
        setup(conn)
        if not conn.execute('SELECT 1 FROM sessions WHERE session_id=? AND ended_at IS NULL',(sid,)).fetchone():raise ValueError('Unknown or finished session')
        conn.execute('INSERT INTO session_activity(session_id,last_seen) VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET last_seen=excluded.last_seen,interrupted=0',(sid,time()))

def incomplete(timeout=180,user_id='default'):
    init_db()
    with connection() as conn:
        setup(conn)
        conn.execute("INSERT OR IGNORE INTO session_activity(session_id,last_seen) SELECT session_id,COALESCE(CAST(strftime('%s',created_at) AS REAL),?) FROM sessions WHERE ended_at IS NULL",(time(),))
        conn.execute('UPDATE session_activity SET interrupted=1 WHERE last_seen<?',(time()-timeout,))
        rows=conn.execute("SELECT s.*,CASE WHEN a.interrupted=1 THEN 'interrupted' ELSE 'active' END AS state FROM sessions s JOIN session_activity a USING(session_id) WHERE s.ended_at IS NULL AND s.user_id=? ORDER BY a.last_seen DESC LIMIT 20",(user_id,)).fetchall()
        return [dict(row) for row in rows]
