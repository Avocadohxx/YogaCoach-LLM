# Owner: D —— 评估脚本与实验场景的测试
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "experiments"))
import evaluate  # noqa: E402

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
