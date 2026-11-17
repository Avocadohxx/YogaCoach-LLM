# Owner: D —— 记忆层自身的可复现验证（不调用 LLM，不涉及 Agent 输出质量）
"""Replay a deterministic, simulated B-event stream through D's memory layer.

What it measures (about D's layer ONLY):
  * L1 compression  : raw B reports (every 200 ms while a deviation persists)
                      vs. stored episode rows after merging
  * L2 correctness  : every deviation count in the auto summary equals the number
                      of stored episodes (summary is grounded in L1)
  * recall          : a later session sees earlier sessions through get_memory_context;
                      with no stored history the context is empty ("no memory" control)
  * cost            : median / p95 latency of the write and read calls on SQLite

The input stream is SIMULATED (scripted deviation windows) — this shows the memory
layer works and how much it compresses; it says nothing about pose-detection accuracy
or Agent feedback quality. Writes experiments/results/memory_layer_check.{json,md}.

Usage:  python experiments/memory/memory_layer_check.py
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend import database, memory  # noqa: E402

STEP_MS = 200
SESSION_MS = 60_000
# per session: list of (type, side, start_ms, end_ms) scripted deviation windows
SCRIPT = {
    "sim_s1": [("shoulder_asymmetry", "right_higher", 5_000, 9_000),
               ("shoulder_asymmetry", "right_higher", 30_000, 33_000)],
    "sim_s2": [("shoulder_asymmetry", "right_higher", 8_000, 12_000),
               ("torso_tilt", "left", 40_000, 43_000)],
    "sim_s3": [("shoulder_asymmetry", "right_higher", 15_000, 17_000)],
}


def pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(p / 100 * (len(vals) - 1))))]


def timed(fn, bucket, *a, **k):
    t0 = time.perf_counter()
    out = fn(*a, **k)
    bucket.append((time.perf_counter() - t0) * 1000)
    return out


def main() -> None:
    old = os.environ.get("YOGACOACH_DB_PATH")
    write_ms, read_ms = [], []
    report = {"sessions": [], "notes": "simulated event stream; measures D's layer only"}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["YOGACOACH_DB_PATH"] = str(Path(tmp) / "check.db")
            database.reset_init_cache()
            control = memory.get_memory_context("tadasana")          # nothing stored yet
            for n, (sid, windows) in enumerate(SCRIPT.items()):
                start = f"2026-11-1{n}T10:00:00Z"
                end = f"2026-11-1{n}T10:01:00Z"
                ctx_before = timed(memory.get_memory_context, read_ms, "tadasana", sid)
                memory.create_session(sid, "tadasana", started_at=start)
                raw = 0
                for ts in range(0, SESSION_MS, STEP_MS):
                    devs = [{"type": t, "side": s, "severity": "mild", "confidence": 0.85,
                             "duration_ms": ts - a} for (t, s, a, b) in windows if a <= ts < b]
                    ev = {"session_id": sid, "pose_id": "tadasana", "timestamp_ms": ts,
                          "tracking_quality": "good", "feedback_allowed": True, "deviations": devs}
                    raw += len(devs)
                    if devs:
                        timed(memory.save_analysis_event, write_ms, ev)
                episodes = memory.get_pose_events(sid)
                summary = timed(memory.finish_session, write_ms, sid, ended_at=end)
                grounded = all(
                    f"{memory.DEVIATION_NAMES[t]} {sum(1 for e in episodes if e['event_type']==t)} 次" in summary
                    for t in {e["event_type"] for e in episodes})
                report["sessions"].append({
                    "session_id": sid,
                    "raw_deviation_reports": raw,
                    "stored_episodes": len(episodes),
                    "scripted_windows": len(windows),
                    "summary_matches_stored_events": grounded,
                    "history_items_visible_at_start": len(ctx_before["recent_sessions"]),
                    "summary": summary,
                })
    finally:
        if old is None:
            os.environ.pop("YOGACOACH_DB_PATH", None)
        else:
            os.environ["YOGACOACH_DB_PATH"] = old
        database.reset_init_cache()

    raw = sum(s["raw_deviation_reports"] for s in report["sessions"])
    stored = sum(s["stored_episodes"] for s in report["sessions"])
    report["totals"] = {
        "raw_reports": raw, "stored_episodes": stored,
        "compression_ratio": round(raw / stored, 1) if stored else None,
        "episodes_equal_scripted_windows": all(
            s["stored_episodes"] == s["scripted_windows"] for s in report["sessions"]),
        "no_memory_control_is_empty": control == {"recent_sessions": [], "recent_feedback": [], "preferences": {}},
        "write_ms_median": round(statistics.median(write_ms), 2),
        "write_ms_p95": round(pct(write_ms, 95), 2),
        "read_ms_median": round(statistics.median(read_ms), 2),
        "writes_measured": len(write_ms),
    }
    out = REPO_ROOT / "experiments/results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "memory_layer_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    t = report["totals"]
    md = ["# 记忆层自检（模拟事件流，仅验证 D 的存储层）", "",
          "> 输入是脚本生成的模拟 B 事件流（每 200 ms 上报一次），**不代表姿态检测或 Agent 话术质量**。", "",
          "| session | 原始上报 | 入库片段 | 场景设定片段 | 摘要与入库一致 | 开始时可见历史 |", "|---|---|---|---|---|---|"]
    md += [f"| {s['session_id']} | {s['raw_deviation_reports']} | {s['stored_episodes']} | {s['scripted_windows']} | "
           f"{'是' if s['summary_matches_stored_events'] else '否'} | {s['history_items_visible_at_start']} |"
           for s in report["sessions"]]
    md += ["", f"- 压缩比：{t['raw_reports']} 条原始上报 → {t['stored_episodes']} 条片段（{t['compression_ratio']}:1）",
           f"- 无记忆对照（空库）上下文为空：{'是' if t['no_memory_control_is_empty'] else '否'}",
           f"- 写入耗时：中位 {t['write_ms_median']} ms，p95 {t['write_ms_p95']} ms（{t['writes_measured']} 次，本机 SQLite）",
           f"- 读取上下文耗时：中位 {t['read_ms_median']} ms", "", "## 自动生成的摘要", ""]
    md += [f"- {s['session_id']}: {s['summary']}" for s in report["sessions"]]
    (out / "memory_layer_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
