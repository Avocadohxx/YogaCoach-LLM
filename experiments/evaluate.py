# Owner: D —— 评估总入口脚本
"""Compute reproducible metrics for three conditions from collected outputs.

    python experiments/evaluate.py \
        --input experiments/results/outputs.json \
        --cases experiments/cases.json \
        --output experiments/results/metrics.json

Conditions: ``template`` (固定话术), ``agent_no_memory``, ``agent_memory``.

Input ``outputs.json`` — a list with ONE row per (case_id, condition)::

    {"case_id": "g1_01", "condition": "agent_memory",
     "output": "…text shown to the user…",   # "" = 系统保持沉默；null = 尚未收集（该行被跳过）
     "latency_ms": 812,
     "grounded": true,          # 人工标注：话术是否只基于当前事件（及合法记忆）
     "actionability": 4,        # 人工标注 1-5：用户能否照着做
     "uses_history": false}     # 人工标注（可选）：是否恰当地用到了历史记忆

``grounded`` / ``actionability`` / ``uses_history`` 必须由人工标注；
脚本不调用 LLM、不生成输出，也不会补全缺失标注（缺失会如实显示在 coverage 里）。
Automatic metrics (computed from ``cases.json``, no annotation needed):

* gating_accuracy   —— 该沉默的场景是否沉默、该开口的场景是否开口
* repetition_rate   —— 同一 sequence 内相邻两轮话术近似重复的比例（Jaccard ≥ 阈值）
* length_compliance —— 偏好 feedback_length=short 的场景，话术是否 ≤ max_chars

Small-n caveat: 24 synthetic cases → descriptive numbers only, no significance claims.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

CONDITIONS = ("template", "agent_no_memory", "agent_memory")
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SIM_THRESHOLD = 0.8


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?;；:：]+", "", (text or "").lower())


def _grams(text: str, n: int = 2) -> set[str]:
    t = _norm(text)
    return {t[i:i + n] for i in range(max(len(t) - n + 1, 1))} if t else set()


def similarity(a: str, b: str) -> float:
    """Character-bigram Jaccard similarity (works for Chinese without a tokenizer)."""
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def percentile(values: list[float], p: float):
    if not values:
        return None
    values = sorted(values)
    idx = max(0, min(len(values) - 1, int(round((p / 100) * (len(values) - 1)))))
    return values[idx]


def _mean(values):
    return statistics.mean(values) if values else None


def _rate(flags):
    return (sum(flags) / len(flags)) if flags else None


def load_cases(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {c["case_id"]: c for c in data["cases"]}


def validate(records: list[dict], cases: dict[str, dict]) -> None:
    seen = set()
    for i, row in enumerate(records):
        cond, cid = row.get("condition"), row.get("case_id")
        if cond not in CONDITIONS:
            raise ValueError(f"row {i}: unknown condition {cond!r}")
        if cid not in cases:
            raise ValueError(f"row {i}: unknown case_id {cid!r} (not in cases.json)")
        if (cid, cond) in seen:
            raise ValueError(f"row {i}: duplicate (case_id, condition) = ({cid}, {cond})")
        seen.add((cid, cond))
        act = row.get("actionability")
        if act is not None and not (1 <= float(act) <= 5):
            raise ValueError(f"row {i}: actionability must be 1-5, got {act}")
        for key in ("grounded", "uses_history"):
            if row.get(key) is not None and not isinstance(row[key], bool):
                raise ValueError(f"row {i}: {key} must be true/false/null")


def spoke(row: dict) -> bool:
    return bool((row.get("output") or "").strip())


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def repetition_rate(rows: list[dict], cases: dict[str, dict], threshold: float) -> dict:
    """Among adjacent turns inside the same sequence, share whose text is a
    near-duplicate of the previous turn. Only sequences with ≥2 spoken turns count."""
    seqs: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for r in rows:
        c = cases[r["case_id"]]
        if c.get("sequence_id") and spoke(r):
            seqs[c["sequence_id"]].append((c["step"], r["output"]))
    pairs = repeats = 0
    for items in seqs.values():
        items.sort()
        for (_, a), (_, b) in zip(items, items[1:]):
            pairs += 1
            repeats += similarity(a, b) >= threshold
    return {"rate": (repeats / pairs) if pairs else None, "pairs": pairs}


def evaluate(records: list[dict], cases: dict[str, dict], max_chars: int = 60,
             sim_threshold: float = DEFAULT_SIM_THRESHOLD) -> dict:
    validate(records, cases)
    grouped: dict[str, list[dict]] = defaultdict(list)
    pending: dict[str, int] = defaultdict(int)
    for row in records:
        if row.get("output") is None:      # 尚未收集：不计入任何指标，避免把“空模板”当成沉默
            pending[row["condition"]] += 1
            continue
        grouped[row["condition"]].append(row)

    result: dict = {}
    for cond in CONDITIONS:
        rows = grouped[cond]
        latencies = [float(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None]
        grounded = [r["grounded"] for r in rows if isinstance(r.get("grounded"), bool) and spoke(r)]
        action = [float(r["actionability"]) for r in rows if r.get("actionability") is not None and spoke(r)]
        uses_hist = [r["uses_history"] for r in rows
                     if isinstance(r.get("uses_history"), bool)
                     and cases[r["case_id"]]["group"] == "history"]
        gating = [spoke(r) == cases[r["case_id"]]["expected"]["should_speak"] for r in rows]
        length_flags = []
        for r in rows:
            exp = cases[r["case_id"]]["expected"]
            if exp.get("max_chars") and spoke(r):
                length_flags.append(len(r["output"].strip()) <= min(exp["max_chars"], max_chars))
        rep = repetition_rate(rows, cases, sim_threshold)
        result[cond] = {
            "n": len(rows),
            "pending_rows": pending[cond],
            "gating_accuracy": _rate(gating),
            "groundedness": _rate(grounded),
            "actionability_mean": _mean(action),
            "repetition_rate": rep["rate"],
            "repetition_pairs": rep["pairs"],
            "length_compliance": _rate(length_flags),
            "history_use_rate": _rate(uses_hist),
            "latency_mean_ms": _mean(latencies),
            "latency_p95_ms": percentile(latencies, 95),
            "annotation_coverage": {
                "spoken_rows": sum(spoke(r) for r in rows),
                "grounded": len(grounded),
                "actionability": len(action),
                "uses_history(history cases)": len(uses_hist),
                "latency": len(latencies),
            },
        }
    return result


def paired_delta(result: dict) -> dict:
    """agent_memory − agent_no_memory for every numeric metric present in both."""
    a, b = result.get("agent_memory", {}), result.get("agent_no_memory", {})
    out = {}
    for key in ("gating_accuracy", "groundedness", "actionability_mean", "repetition_rate",
                "length_compliance", "history_use_rate", "latency_mean_ms"):
        if a.get(key) is not None and b.get(key) is not None:
            out[key] = round(a[key] - b[key], 4)
    return out


# ---------------------------------------------------------------------------
# output formats
# ---------------------------------------------------------------------------
COLUMNS = ["n", "pending_rows", "gating_accuracy", "groundedness", "actionability_mean", "repetition_rate",
           "length_compliance", "history_use_rate", "latency_mean_ms", "latency_p95_ms"]


def _fmt(v):
    if v is None:
        return "—（无标注/不适用）"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def to_markdown(result: dict, delta: dict) -> str:
    lines = ["# 评估结果（由 experiments/evaluate.py 自动生成）", "",
             "> 合成场景、小样本，仅作描述性对比，不做显著性结论。“—”表示缺少对应人工标注或该指标不适用。", "",
             "| 指标 | " + " | ".join(CONDITIONS) + " |", "|---|" + "---|" * len(CONDITIONS)]
    for col in COLUMNS:
        lines.append(f"| {col} | " + " | ".join(_fmt(result[c][col]) for c in CONDITIONS) + " |")
    lines += ["", "## agent_memory − agent_no_memory", ""]
    lines += [f"- {k}: {v:+}" for k, v in delta.items()] or ["- 两组缺少可比较的指标"]
    lines += ["", "## 标注覆盖", ""]
    for c in CONDITIONS:
        lines.append(f"- {c}: {json.dumps(result[c]['annotation_coverage'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def write_outputs(result: dict, delta: dict, out_json: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"metrics": result, "memory_minus_no_memory": delta},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    out_json.with_suffix(".md").write_text(to_markdown(result, delta), encoding="utf-8")
    with out_json.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["condition"] + COLUMNS)
        for c in CONDITIONS:
            w.writerow([c] + [result[c][k] for k in COLUMNS])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default=str(REPO_ROOT / "experiments/results/outputs.json"))
    p.add_argument("--cases", default=str(REPO_ROOT / "experiments/cases.json"))
    p.add_argument("--output", default=str(REPO_ROOT / "experiments/results/metrics.json"))
    p.add_argument("--max-chars", type=int, default=60, help="“short” 偏好的字数上限")
    p.add_argument("--sim-threshold", type=float, default=DEFAULT_SIM_THRESHOLD)
    args = p.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(
            f"找不到 {in_path}。先运行 experiments/memory/build_inputs.py 生成输入，"
            "让 C 的 Agent 跑完后把结果填进 experiments/results/outputs.json（模板见 outputs.template.json）。")
    records = json.loads(in_path.read_text(encoding="utf-8"))
    cases = load_cases(Path(args.cases))
    result = evaluate(records, cases, args.max_chars, args.sim_threshold)
    delta = paired_delta(result)
    write_outputs(result, delta, Path(args.output))
    print(to_markdown(result, delta))


if __name__ == "__main__":
    main()
