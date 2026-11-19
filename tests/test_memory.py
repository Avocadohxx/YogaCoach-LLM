# Owner: D —— 记忆模块、/api/memory 接口、评估脚本与实验场景的测试
# pytest 与 `python -m unittest tests.test_memory` 均可运行。
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from backend import database, memory

try:  # 接口测试依赖 httpx（FastAPI TestClient）；未安装时跳过，不影响其他测试
    from fastapi.testclient import TestClient
    from backend.main import app
except ImportError:  # pragma: no cover
    TestClient = None

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "experiments"))
import evaluate  # noqa: E402

class _DBTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = {k: os.environ.get(k) for k in ("YOGACOACH_DB_PATH", "DATABASE_PATH")}
        os.environ["YOGACOACH_DB_PATH"] = str(Path(self.tmp.name) / "test.db")
        os.environ.pop("DATABASE_PATH", None)
        database.reset_init_cache()
        database.init_db()

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        database.reset_init_cache()
        self.tmp.cleanup()


def _analysis(ts, deviations=None, **kw):
    ev = {
        "session_id": "s1", "pose_id": "tadasana", "timestamp_ms": ts,
        "tracking_quality": "good", "feedback_allowed": True,
        "deviations": deviations if deviations is not None else [
            {"type": "shoulder_asymmetry", "side": "right_higher",
             "severity": "mild", "confidence": 0.88, "duration_ms": 1800}
        ],
    }
    ev.update(kw)
    return ev


class DatabasePathTests(unittest.TestCase):
    def test_env_precedence_and_relative_path(self):
        old = {k: os.environ.get(k) for k in ("YOGACOACH_DB_PATH", "DATABASE_PATH")}
        try:
            os.environ.pop("YOGACOACH_DB_PATH", None)
            os.environ["DATABASE_PATH"] = "./data/yoga.db"
            self.assertEqual(database.get_db_path(), database.REPO_ROOT / "data" / "yoga.db")
            os.environ["YOGACOACH_DB_PATH"] = "/tmp/x.db"
            self.assertEqual(database.get_db_path(), Path("/tmp/x.db"))
            os.environ.pop("YOGACOACH_DB_PATH")
            os.environ.pop("DATABASE_PATH")
            self.assertEqual(database.get_db_path(), database._DEFAULT_DB)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class SessionTests(_DBTestCase):
    def setUp(self):
        super().setUp()
        memory.create_session("s1", "tadasana", "u1", "2026-11-16T10:00:00Z")

    def test_create_is_idempotent(self):
        memory.create_session("s1", "tadasana", "u1")
        self.assertEqual(memory.get_session("s1")["started_at"], "2026-11-16T10:00:00Z")

    def test_summary_round_trip_and_validation(self):
        memory.save_session_summary("s1", "肩部有一次轻微偏差")
        rows = memory.get_recent_sessions("tadasana", "u1")
        self.assertEqual([r["summary"] for r in rows], ["肩部有一次轻微偏差"])
        with self.assertRaises(ValueError):
            memory.save_session_summary("s1", "   ")
        with self.assertRaises(ValueError):
            memory.save_session_summary("missing", "x")

    def test_recent_sessions_filter_order_limit_exclude(self):
        for i, (sid, pose) in enumerate(
            [("a", "tadasana"), ("b", "ardhakati_chakrasana"), ("c", "tadasana")]
        ):
            memory.create_session(sid, pose, "u1", f"2026-11-1{i}T09:00:00Z")
            memory.save_session_summary(sid, f"sum-{sid}")
        ids = [r["session_id"] for r in memory.get_recent_sessions("tadasana", "u1")]
        self.assertEqual(ids, ["c", "a"])  # newest first, other pose filtered
        self.assertEqual(len(memory.get_recent_sessions(None, "u1", limit=1)), 1)
        ids = [r["session_id"] for r in memory.get_recent_sessions("tadasana", "u1", exclude_session_id="c")]
        self.assertEqual(ids, ["a"])
        self.assertEqual(memory.get_recent_sessions("tadasana", "other-user"), [])
        with self.assertRaises(ValueError):
            memory.get_recent_sessions(limit=0)

    def test_sessions_without_summary_are_not_history(self):
        self.assertEqual(memory.get_recent_sessions("tadasana", "u1"), [])

    def test_finish_unknown_session(self):
        with self.assertRaises(ValueError):
            memory.finish_session("missing")

    def test_delete_session_cascades(self):
        memory.save_pose_event("s1", {"type": "x"})
        memory.log_feedback("s1", "x", "hi")
        self.assertTrue(memory.delete_session("s1"))
        self.assertEqual(memory.get_pose_events("s1"), [])
        self.assertEqual(memory.get_recent_feedback("s1"), [])
        self.assertFalse(memory.delete_session("s1"))

    def test_delete_user_data(self):
        memory.set_user_preference("voice", True, "u1")
        memory.set_user_preference("voice", False, "u2")
        out = memory.delete_user_data("u1")
        self.assertEqual(out, {"sessions": 1, "preferences": 1})
        self.assertEqual(memory.get_user_preferences("u2"), {"voice": "false"})


class EventTests(_DBTestCase):
    def setUp(self):
        super().setUp()
        memory.create_session("s1", "tadasana", "u1", "2026-11-16T10:00:00Z")

    def test_single_event_round_trip(self):
        event = {"type": "shoulder_asymmetry", "side": "right_higher",
                 "severity": "mild", "confidence": 0.88, "timestamp_ms": 1800}
        event_id = memory.save_pose_event("s1", event)
        rows = memory.get_pose_events("s1")
        self.assertEqual(rows[0]["event_id"], event_id)
        self.assertEqual(rows[0]["payload"]["type"], "shoulder_asymmetry")

    def test_event_type_alias_and_errors(self):
        memory.save_pose_event("s1", {"event_type": "torso_tilt"})
        self.assertEqual(memory.get_pose_events("s1")[0]["event_type"], "torso_tilt")
        with self.assertRaises(ValueError):
            memory.save_pose_event("s1", {"side": "left"})
        with self.assertRaises(TypeError):
            memory.save_pose_event("s1", "not a dict")
        with self.assertRaises(ValueError):
            memory.save_pose_event("missing", {"type": "test"})

    def test_analysis_event_fans_out_deviations(self):
        res = memory.save_analysis_event(_analysis(1000, [
            {"type": "shoulder_asymmetry", "side": "right_higher", "severity": "mild", "confidence": .9, "duration_ms": 900},
            {"type": "torso_tilt", "side": "left", "severity": "moderate", "confidence": .8, "duration_ms": 900},
        ]))
        self.assertEqual(res, {"saved": 2, "merged": 0, "skipped_reason": None})
        types = sorted(e["event_type"] for e in memory.get_pose_events("s1"))
        self.assertEqual(types, ["shoulder_asymmetry", "torso_tilt"])

    def test_analysis_event_auto_creates_session_from_event(self):
        res = memory.save_analysis_event(_analysis(500, session_id="fresh", pose_id="ardhakati_chakrasana"))
        self.assertEqual(res["saved"], 1)
        self.assertEqual(memory.get_session("fresh")["pose_id"], "ardhakati_chakrasana")
        with self.assertRaises(ValueError):
            memory.save_analysis_event(_analysis(1, session_id="nope"), auto_create_session=False)

    def test_untrusted_events_are_not_stored(self):
        for ev, reason in [
            (_analysis(1, feedback_allowed=False), "feedback_not_allowed"),
            (_analysis(1, feedback_allowed=None), "feedback_not_allowed"),
            (_analysis(1, tracking_quality="low"), "tracking_quality_not_good"),
            (_analysis(1, tracking_quality=None), "tracking_quality_not_good"),
            (_analysis(1, deviations=[]), "no_deviation"),
        ]:
            self.assertEqual(memory.save_analysis_event(ev)["skipped_reason"], reason)
        self.assertEqual(memory.get_pose_events("s1"), [])

    def test_repeated_deviation_is_merged_into_one_episode(self):
        for ts in (1000, 1200, 1400, 1600):  # B reports every ~200ms
            memory.save_analysis_event(_analysis(ts, [
                {"type": "shoulder_asymmetry", "side": "right_higher",
                 "severity": "mild" if ts < 1400 else "moderate",
                 "confidence": 0.8 if ts < 1600 else 0.95, "duration_ms": ts}
            ]))
        events = memory.get_pose_events("s1")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["payload"]["count"], 4)
        self.assertEqual(ev["severity"], "moderate")      # worst severity kept
        self.assertAlmostEqual(ev["confidence"], 0.95)    # best confidence kept
        self.assertEqual(ev["duration_ms"], 1600)

    def test_gap_or_other_side_starts_new_episode(self):
        memory.save_analysis_event(_analysis(1000))
        memory.save_analysis_event(_analysis(1000 + memory.MERGE_GAP_MS + 1))  # long gap
        memory.save_analysis_event(_analysis(9000, [
            {"type": "shoulder_asymmetry", "side": "left_higher", "severity": "mild", "confidence": .8, "duration_ms": 10}]))
        self.assertEqual(len(memory.get_pose_events("s1")), 3)

    def test_bad_deviations_rejected(self):
        with self.assertRaises(ValueError):
            memory.save_analysis_event(_analysis(1, deviations=[{"side": "left"}]))
        with self.assertRaises(ValueError):
            memory.save_analysis_event(_analysis(1, deviations="oops"))
        with self.assertRaises(ValueError):
            memory.save_analysis_event({"deviations": []})  # no session id anywhere

    def test_events_sorted_by_timestamp(self):
        memory.save_pose_event("s1", {"type": "b", "timestamp_ms": 5000})
        memory.save_pose_event("s1", {"type": "a", "timestamp_ms": 100})
        self.assertEqual([e["event_type"] for e in memory.get_pose_events("s1")], ["a", "b"])


class SummaryTests(_DBTestCase):
    def test_summary_is_grounded_in_events_and_feedback(self):
        memory.create_session("s1", "tadasana", "u1", "2026-11-16T10:00:00Z")
        memory.save_analysis_event(_analysis(1000))
        memory.save_analysis_event(_analysis(20000))  # second episode
        memory.log_feedback("s1", "shoulder_asymmetry", "放松肩膀")
        summary = memory.finish_session("s1", ended_at="2026-11-16T10:02:05Z")
        self.assertIn("山式练习约 2 分钟", summary)
        self.assertIn("双肩高度差异 2 次", summary)
        self.assertIn("右侧偏高", summary)
        self.assertIn("提示 1 次", summary)
        self.assertEqual(memory.get_session("s1")["summary"], summary)

    def test_summary_without_events_does_not_claim_perfect_pose(self):
        memory.create_session("s1", "tadasana", "u1", "2026-11-16T10:00:00Z")
        summary = memory.finish_session("s1", ended_at="2026-11-16T10:00:30Z")
        self.assertIn("30 秒", summary)
        self.assertIn("不代表姿态完全标准", summary)

    def test_unknown_type_and_pose_pass_through(self):
        memory.create_session("s1", "new_pose", "u1")
        memory.save_pose_event("s1", {"type": "brand_new_type", "timestamp_ms": 1})
        s = memory.build_session_summary("s1")
        self.assertIn("new_pose", s)
        self.assertIn("brand_new_type 1 次", s)

    def test_finish_keeps_existing_summary_and_respects_flag(self):
        memory.create_session("s1", "tadasana", "u1")
        memory.save_session_summary("s1", "C 写的摘要")
        self.assertEqual(memory.finish_session("s1"), "C 写的摘要")
        memory.create_session("s2", "tadasana", "u1")
        self.assertIsNone(memory.finish_session("s2", auto_summary=False))
        self.assertIsNotNone(memory.get_session("s2")["ended_at"])


class PreferenceTests(_DBTestCase):
    def test_upsert_and_delete(self):
        memory.set_user_preference("feedback_length", "short", "u1")
        memory.set_user_preference("feedback_length", "very_short", "u1")
        self.assertEqual(memory.get_user_preferences("u1")["feedback_length"], "very_short")
        self.assertTrue(memory.delete_user_preference("feedback_length", "u1"))
        self.assertFalse(memory.delete_user_preference("feedback_length", "u1"))
        self.assertNotIn("feedback_length", memory.get_user_preferences("u1"))

    def test_isolation_between_users_and_validation(self):
        memory.set_user_preference("voice", False, "u1")
        self.assertEqual(memory.get_user_preferences("u2"), {})
        for key in ("", "Bad Key", "1abc", "x" * 65):
            with self.assertRaises(ValueError):
                memory.set_user_preference(key, "v")
        with self.assertRaises(ValueError):
            memory.set_user_preference("k", "  ")


class FeedbackTests(_DBTestCase):
    def setUp(self):
        super().setUp()
        memory.create_session("s1", "tadasana")

    def test_feedback_order_is_newest_first_even_within_same_millisecond(self):
        for i in range(6):
            memory.log_feedback("s1", "t", f"msg{i}")
        got = [r["feedback_text"] for r in memory.get_recent_feedback("s1", 3)]
        self.assertEqual(got, ["msg5", "msg4", "msg3"])

    def test_validation(self):
        with self.assertRaises(ValueError):
            memory.log_feedback("s1", "t", "  ")
        with self.assertRaises(ValueError):
            memory.log_feedback("missing", "t", "x")
        with self.assertRaises(ValueError):
            memory.get_recent_feedback("s1", 0)


class ContextTests(_DBTestCase):
    def test_context_matches_contract_shape(self):
        memory.create_session("old", "tadasana", started_at="2026-11-15T09:00:00Z")
        memory.save_session_summary("old", "上次：双肩高度差异 1 次")
        memory.create_session("cur", "tadasana", started_at="2026-11-16T09:00:00Z")
        memory.log_feedback("cur", "shoulder_asymmetry", "放松肩膀")
        memory.set_user_preference("feedback_length", "short")
        memory.set_user_preference("voice", False)

        ctx = memory.get_memory_context("tadasana", "cur")
        sample = json.loads(
            (database.REPO_ROOT / "contracts" / "mock" / "memory_sample.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(ctx), {"recent_sessions", "recent_feedback", "preferences"})
        self.assertEqual(set(ctx), set(sample) - {"_note"})
        self.assertEqual(set(ctx["recent_sessions"][0]), set(sample["recent_sessions"][0]))
        self.assertEqual([s["session_id"] for s in ctx["recent_sessions"]], ["old"])  # current excluded
        self.assertEqual(ctx["recent_feedback"][0]["text"], "放松肩膀")
        self.assertEqual(ctx["preferences"], {"feedback_length": "short", "voice": False})

    def test_empty_context(self):
        self.assertEqual(
            memory.get_memory_context("tadasana"),
            {"recent_sessions": [], "recent_feedback": [], "preferences": {}},
        )


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


CASES_PATH = REPO / "experiments" / "cases.json"
KNOWN_POSES = {"tadasana", "ardhakati_chakrasana"}  # contracts/README.md
KNOWN_TYPES = {"shoulder_asymmetry", "torso_tilt"}   # B 草案枚举；B 定稿后更新这里


def _load_build_inputs():
    spec = importlib.util.spec_from_file_location("build_inputs", REPO / "experiments/memory/build_inputs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CasesContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.cases = doc["cases"]

    def test_size_and_unique_ids(self):
        self.assertTrue(20 <= len(self.cases) <= 30)
        self.assertEqual(len({c["case_id"] for c in self.cases}), len(self.cases))

    def test_events_follow_contract(self):
        sample = json.loads((REPO / "contracts/mock/analysis_event.json").read_text(encoding="utf-8"))
        for c in self.cases:
            ev = c["analysis_event"]
            self.assertEqual(set(ev), set(sample), c["case_id"])
            self.assertIn(ev["pose_id"], KNOWN_POSES, c["case_id"])
            self.assertEqual(ev["pose_id"], c["pose_id"])
            for d in ev["deviations"]:
                self.assertEqual(set(d), set(sample["deviations"][0]), c["case_id"])
                self.assertIn(d["type"], KNOWN_TYPES, c["case_id"])

    def test_expectations_consistent_with_gating_rules(self):
        for c in self.cases:
            ev, exp = c["analysis_event"], c["expected"]
            blocked = (not ev["feedback_allowed"]) or ev["tracking_quality"] != "good" or not ev["deviations"]
            self.assertEqual(exp["should_speak"], not blocked, c["case_id"])
            if exp["should_speak"]:
                self.assertIn(exp["grounded_event_type"], {d["type"] for d in ev["deviations"]}, c["case_id"])

    def test_sequences_are_ordered(self):
        seqs = {}
        for c in self.cases:
            if "sequence_id" in c:
                seqs.setdefault(c["sequence_id"], []).append(c["step"])
        self.assertTrue(seqs)
        for steps in seqs.values():
            self.assertEqual(steps, sorted(steps))
            self.assertEqual(steps[0], 1)

    def test_memory_layer_reproduces_every_case_memory(self):
        bi = _load_build_inputs()
        old = os.environ.get("YOGACOACH_DB_PATH")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                for c in self.cases:
                    ctx = bi.seed_and_read(c, Path(tmp) / f"{c['case_id']}.db")
                    self.assertEqual([s["summary"] for s in ctx["recent_sessions"]],
                                     [s["summary"] for s in c["memory"]["sessions"]], c["case_id"])
                    self.assertEqual(ctx["preferences"], c["memory"]["preferences"], c["case_id"])
        finally:
            if old is None:
                os.environ.pop("YOGACOACH_DB_PATH", None)
            else:
                os.environ["YOGACOACH_DB_PATH"] = old


class EvaluateTests(unittest.TestCase):
    """Pipeline tests with hand-made rows. These are NOT experiment results."""

    @classmethod
    def setUpClass(cls):
        cls.cases = evaluate.load_cases(CASES_PATH)

    def _row(self, cid, cond, output, **kw):
        return {"case_id": cid, "condition": cond, "output": output, **kw}

    def test_gating_and_grounded_and_latency(self):
        rows = [
            self._row("g1_01", "template", "放松肩膀。", grounded=True, actionability=4, latency_ms=10),
            self._row("g2_01", "template", "", latency_ms=20),                   # correctly silent
            self._row("g2_02", "template", "请放松肩膀", grounded=True),          # should have been silent
        ]
        m = evaluate.evaluate(rows, self.cases)["template"]
        self.assertAlmostEqual(m["gating_accuracy"], 2 / 3)
        self.assertEqual(m["groundedness"], 1.0)
        self.assertEqual(m["actionability_mean"], 4.0)
        self.assertEqual(m["latency_mean_ms"], 15.0)
        self.assertIsNone(evaluate.evaluate(rows, self.cases)["agent_memory"]["groundedness"])

    def test_repetition_inside_sequence_only(self):
        same = "检测到双肩高度有些差异，可以在舒适范围内放松肩膀。"
        rows = [self._row("g4_11", "agent_no_memory", same),
                self._row("g4_12", "agent_no_memory", same),
                self._row("g4_13", "agent_no_memory", "这次试着把右肩轻轻下沉，再慢慢呼气。")]
        m = evaluate.evaluate(rows, self.cases)["agent_no_memory"]
        self.assertEqual(m["repetition_pairs"], 2)
        self.assertAlmostEqual(m["repetition_rate"], 0.5)
        # identical text in different cases/sequences is NOT repetition
        rows = [self._row("g1_01", "template", same), self._row("g1_02", "template", same)]
        self.assertIsNone(evaluate.evaluate(rows, self.cases)["template"]["repetition_rate"])

    def test_length_compliance(self):
        rows = [self._row("g5_01", "agent_memory", "放松右肩。"),
                self._row("g5_02", "agent_memory", "这" * 100)]
        self.assertEqual(evaluate.evaluate(rows, self.cases)["agent_memory"]["length_compliance"], 0.5)

    def test_validation(self):
        with self.assertRaises(ValueError):
            evaluate.evaluate([self._row("g1_01", "bogus", "x")], self.cases)
        with self.assertRaises(ValueError):
            evaluate.evaluate([self._row("nope", "template", "x")], self.cases)
        with self.assertRaises(ValueError):
            evaluate.evaluate([self._row("g1_01", "template", "x")] * 2, self.cases)
        with self.assertRaises(ValueError):
            evaluate.evaluate([self._row("g1_01", "template", "x", actionability=9)], self.cases)
        with self.assertRaises(ValueError):
            evaluate.evaluate([self._row("g1_01", "template", "x", grounded="yes")], self.cases)

    def test_outputs_written_and_empty_template_is_safe(self):
        template = json.loads((REPO / "experiments/results/outputs.template.json").read_text(encoding="utf-8"))
        res = evaluate.evaluate(template, self.cases)         # all-null template must not crash or invent numbers
        for cond in evaluate.CONDITIONS:
            self.assertEqual(res[cond]["n"], 0)
            self.assertEqual(res[cond]["pending_rows"], 24)
            self.assertIsNone(res[cond]["gating_accuracy"])
            self.assertIsNone(res[cond]["groundedness"])
            self.assertIsNone(res[cond]["latency_mean_ms"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "m.json"
            evaluate.write_outputs(res, evaluate.paired_delta(res), out)
            self.assertTrue(out.exists() and out.with_suffix(".md").exists() and out.with_suffix(".csv").exists())


if __name__ == "__main__":
    unittest.main()
