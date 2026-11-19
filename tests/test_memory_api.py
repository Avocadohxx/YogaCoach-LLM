# Owner: D —— /api/memory 接口测试（通过 backend.main 验证路由确实已挂载）
import os
import tempfile
import unittest
from pathlib import Path

from backend import database

try:  # TestClient 依赖 httpx；requirements.txt 里暂未包含，缺失时跳过而不是报错
    from fastapi.testclient import TestClient
    from backend.main import app
except ImportError:  # pragma: no cover
    TestClient = None


@unittest.skipIf(TestClient is None, "需要 httpx：pip install httpx")
class MemoryApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("YOGACOACH_DB_PATH")
        os.environ["YOGACOACH_DB_PATH"] = str(Path(self.tmp.name) / "api.db")
        database.reset_init_cache()
        self.c = TestClient(app)
        self.base = "/api/memory"

    def tearDown(self):
        if self._old is None:
            os.environ.pop("YOGACOACH_DB_PATH", None)
        else:
            os.environ["YOGACOACH_DB_PATH"] = self._old
        database.reset_init_cache()
        self.tmp.cleanup()

    def _session(self, sid="s1", pose="tadasana"):
        r = self.c.post(f"{self.base}/sessions", json={
            "session_id": sid, "pose_id": pose, "started_at": "2026-11-16T10:00:00Z"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_health_still_works(self):
        self.assertEqual(self.c.get("/api/health").json(), {"status": "ok"})

    def test_full_live_session_flow(self):
        self._session()
        ev = {"session_id": "s1", "pose_id": "tadasana", "timestamp_ms": 1000,
              "tracking_quality": "good", "feedback_allowed": True,
              "deviations": [{"type": "shoulder_asymmetry", "side": "right_higher",
                              "severity": "mild", "confidence": .88, "duration_ms": 1800}]}
        r = self.c.post(f"{self.base}/sessions/s1/analysis", json=ev)
        self.assertEqual(r.json(), {"ok": True, "saved": 1, "merged": 0, "skipped_reason": None})
        self.c.post(f"{self.base}/sessions/s1/feedback",
                    json={"event_type": "shoulder_asymmetry", "feedback_text": "放松肩膀"})
        fin = self.c.post(f"{self.base}/sessions/s1/finish").json()
        self.assertIn("双肩高度差异 1 次", fin["summary"])
        hist = self.c.get(f"{self.base}/sessions", params={"pose_id": "tadasana"}).json()["items"]
        self.assertEqual(hist[0]["session_id"], "s1")
        events = self.c.get(f"{self.base}/sessions/s1/events").json()["items"]
        self.assertEqual(len(events), 1)

    def test_context_endpoint(self):
        self._session("old")
        self.c.post(f"{self.base}/sessions/old/finish")
        self._session("cur")
        self.c.put(f"{self.base}/preferences", json={"preference_key": "voice", "preference_value": False})
        ctx = self.c.get(f"{self.base}/context", params={"pose_id": "tadasana", "session_id": "cur"}).json()
        self.assertEqual([s["session_id"] for s in ctx["recent_sessions"]], ["old"])
        self.assertEqual(ctx["preferences"], {"voice": False})

    def test_preferences_crud(self):
        r = self.c.put(f"{self.base}/preferences", json={"preference_key": "feedback_length", "preference_value": "short"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get(f"{self.base}/preferences").json()["preferences"], {"feedback_length": "short"})
        self.assertEqual(self.c.delete(f"{self.base}/preferences/feedback_length").status_code, 200)
        self.assertEqual(self.c.delete(f"{self.base}/preferences/feedback_length").status_code, 404)
        bad = self.c.put(f"{self.base}/preferences", json={"preference_key": "Bad Key", "preference_value": "x"})
        self.assertEqual(bad.status_code, 400)

    def test_finish_accepts_empty_json_body(self):
        self._session()
        r = self.c.post(f"{self.base}/sessions/s1/finish", json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("山式练习", r.json()["summary"])

    def test_error_codes(self):
        self.assertEqual(self.c.post(f"{self.base}/sessions/nope/finish").status_code, 404)
        self.assertEqual(self.c.get(f"{self.base}/sessions/nope").status_code, 404)
        self.assertEqual(self.c.get(f"{self.base}/sessions/nope/events").status_code, 404)
        self.assertEqual(self.c.post(f"{self.base}/sessions/nope/feedback",
                                     json={"feedback_text": "x"}).status_code, 404)
        self.assertEqual(self.c.post(f"{self.base}/sessions", json={"session_id": "", "pose_id": "t"}).status_code, 422)
        self.assertEqual(self.c.get(f"{self.base}/sessions", params={"limit": 0}).status_code, 400)
        self._session()
        mismatch = self.c.post(f"{self.base}/sessions/s1/analysis", json={"session_id": "other", "deviations": []})
        self.assertEqual(mismatch.status_code, 400)

    def test_delete_session_and_user_data(self):
        self._session()
        self.assertEqual(self.c.delete(f"{self.base}/sessions/s1").status_code, 200)
        self.assertEqual(self.c.delete(f"{self.base}/sessions/s1").status_code, 404)
        self._session("s2")
        self.c.put(f"{self.base}/preferences", json={"preference_key": "voice", "preference_value": True})
        out = self.c.delete(f"{self.base}/user-data").json()
        self.assertEqual(out["deleted"], {"sessions": 1, "preferences": 1})


if __name__ == "__main__":
    unittest.main()
