import os
import tempfile
import unittest
from pathlib import Path

from backend import database

try:
    from fastapi.testclient import TestClient
    from backend.main import app
except ImportError:  # pragma: no cover
    TestClient = None

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"
)


@unittest.skipIf(TestClient is None, "需要 httpx：pip install httpx")
class HistoryMediaApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("YOGACOACH_DB_PATH")
        self.old_media = os.environ.get("YOGACOACH_MEDIA_DIR")
        os.environ["YOGACOACH_DB_PATH"] = str(Path(self.tmp.name) / "history.db")
        os.environ["YOGACOACH_MEDIA_DIR"] = str(Path(self.tmp.name) / "media")
        database.reset_init_cache()
        self.client = TestClient(app)
        response = self.client.post(
            "/api/memory/sessions",
            json={
                "session_id": "session-1",
                "pose_id": "tadasana",
                "started_at": "2026-11-22T09:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("YOGACOACH_DB_PATH", None)
        else:
            os.environ["YOGACOACH_DB_PATH"] = self.old_db
        if self.old_media is None:
            os.environ.pop("YOGACOACH_MEDIA_DIR", None)
        else:
            os.environ["YOGACOACH_MEDIA_DIR"] = self.old_media
        database.reset_init_cache()
        self.tmp.cleanup()

    def test_upload_and_get_training_detail_image(self):
        response = self.client.post(
            "/api/memory/sessions/session-1/snapshots",
            data={
                "pose_id": "tadasana",
                "event_type": "elbow_bend",
                "side": "left",
                "timestamp_ms": "1800",
            },
            files={"image": ("error.png", PNG_BYTES, "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        snapshot_id = response.json()["snapshot_id"]

        image = self.client.get(f"/api/memory/snapshots/{snapshot_id}/image")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/png")
        self.assertEqual(image.content, PNG_BYTES)

        update = self.client.post(
            f"/api/memory/snapshots/{snapshot_id}/feedback",
            json={"feedback_text": "放松手肘，保持舒适。"},
        )
        self.assertEqual(update.status_code, 200)
        detail = self.client.get("/api/memory/sessions/session-1/detail")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.json()["snapshots"]), 1)
        self.assertEqual(
            detail.json()["snapshots"][0]["feedback_text"],
            "放松手肘，保持舒适。",
        )

        deleted = self.client.delete("/api/memory/sessions/session-1")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/memory/snapshots/{snapshot_id}/image").status_code,
            404,
        )

    def test_rejects_wrong_image_type_and_unknown_session(self):
        wrong = self.client.post(
            "/api/memory/sessions/session-1/snapshots",
            files={"image": ("bad.jpg", b"not an image", "image/jpeg")},
        )
        self.assertEqual(wrong.status_code, 400)
        unknown = self.client.post(
            "/api/memory/sessions/missing/snapshots",
            files={"image": ("error.png", PNG_BYTES, "image/png")},
        )
        self.assertEqual(unknown.status_code, 404)


if __name__ == "__main__":
    unittest.main()
