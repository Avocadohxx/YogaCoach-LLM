# Owner: D —— 生成“无记忆 vs 开启记忆”对照实验的输入包
"""Build experiment inputs from ``experiments/cases.json``.

For every case this script seeds a throw-away SQLite DB through D's REAL memory
layer (create_session / save_session_summary / log_feedback / set_user_preference),
reads the context back with ``memory.get_memory_context`` and checks it equals the
case's declared memory. So the ``agent_memory`` input is exactly what C would get
from D at runtime — not a hand-copied JSON.

Outputs (both git-ignored-free, small JSON):
  experiments/memory/inputs.json              给 C 的 Agent 逐条喂入的输入
  experiments/results/outputs.template.json   待填写的输出/标注模板（每个 case × 3 个条件一行）

Usage:  python experiments/memory/build_inputs.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend import database, memory  # noqa: E402

EMPTY_CONTEXT = {"recent_sessions": [], "recent_feedback": [], "preferences": {}}


def seed_and_read(case: dict, db_path: Path) -> dict:
    os.environ["YOGACOACH_DB_PATH"] = str(db_path)
    database.reset_init_cache()
    spec = case["memory"]
    for i, s in enumerate(spec["sessions"]):
        sid = f"{case['case_id']}_hist{i}"
        memory.create_session(sid, s["pose_id"], started_at=s["ended_at"])
        memory.finish_session(sid, ended_at=s["ended_at"], auto_summary=False)
        memory.save_session_summary(sid, s["summary"])
    cur = f"{case['case_id']}_current"
    memory.create_session(cur, case["pose_id"], started_at="2026-11-15T09:00:00Z")
    for fb in spec["feedback"]:
        memory.log_feedback(cur, fb["event_type"], fb["text"])
    for k, v in spec["preferences"].items():
        memory.set_user_preference(k, v)
    return memory.get_memory_context(case["pose_id"], cur)


def main() -> None:
    cases = json.loads((REPO_ROOT / "experiments/cases.json").read_text(encoding="utf-8"))["cases"]
    inputs, template_rows = [], []
    old = os.environ.get("YOGACOACH_DB_PATH")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for case in cases:
                ctx = seed_and_read(case, Path(tmp) / f"{case['case_id']}.db")
                # self-check: what D returns must equal what the case declares
                got = [(s["pose_id"], s["summary"]) for s in ctx["recent_sessions"]]
                want = [(s["pose_id"], s["summary"]) for s in case["memory"]["sessions"]]
                if got != want or [f["text"] for f in ctx["recent_feedback"]][::-1] != \
                        [f["text"] for f in case["memory"]["feedback"]] \
                        or ctx["preferences"] != case["memory"]["preferences"]:
                    raise SystemExit(f"{case['case_id']}: memory layer output differs from case definition")
                event = dict(case["analysis_event"], session_id=f"{case['case_id']}_current")
                inputs.append({
                    "case_id": case["case_id"],
                    "group": case["group"],
                    "sequence_id": case.get("sequence_id"),
                    "step": case.get("step"),
                    "conditions": {
                        "template": {"analysis_event": event},
                        "agent_no_memory": {"analysis_event": event, "memory": EMPTY_CONTEXT},
                        "agent_memory": {"analysis_event": event, "memory": ctx},
                    },
                })
                for cond in ("template", "agent_no_memory", "agent_memory"):
                    template_rows.append({
                        "case_id": case["case_id"], "condition": cond,
                        "output": None, "latency_ms": None,
                        "grounded": None, "actionability": None, "uses_history": None,
                    })
    finally:
        if old is None:
            os.environ.pop("YOGACOACH_DB_PATH", None)
        else:
            os.environ["YOGACOACH_DB_PATH"] = old
        database.reset_init_cache()

    (REPO_ROOT / "experiments/memory/inputs.json").write_text(
        json.dumps(inputs, ensure_ascii=False, indent=2), encoding="utf-8")
    out_dir = REPO_ROOT / "experiments/results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "outputs.template.json").write_text(
        json.dumps(template_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(inputs)} cases -> inputs.json; {len(template_rows)} rows -> outputs.template.json")


if __name__ == "__main__":
    main()
