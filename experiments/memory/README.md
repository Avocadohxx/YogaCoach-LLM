# 记忆对照实验（D）

目标：比较三种条件下的反馈质量——`template`（固定话术）、`agent_no_memory`、`agent_memory`。

## 谁做什么

| 步骤 | 命令 / 动作 | 负责 |
|---|---|---|
| 1. 生成输入 | `python experiments/memory/build_inputs.py` → `experiments/memory/inputs.json`、`experiments/results/outputs.template.json` | D（已完成，可重跑） |
| 2. 跑三种条件 | 把 `inputs.json` 里每条 case 的 `conditions.<条件>` 喂给对应系统，记录话术与耗时。`template` 用 `knowledge/fallback_templates.json`；两个 Agent 条件用 C 的 Agent，仅 `memory` 字段不同 | C（Agent）/ D（整理） |
| 3. 人工标注 | 在 `outputs.json` 里填 `grounded`、`actionability`(1-5)、`uses_history`（history 组）。建议两人独立标注后取一致 | D + 另一位成员 |
| 4. 计算指标 | `python experiments/evaluate.py` → `experiments/results/metrics.{json,md,csv}` | D |

`outputs.json` 的约定：`output` 为字符串（`""` = 系统保持沉默），`null` = 尚未收集，该行不计入指标。

## 文件

- `build_inputs.py`：用 D 真实的记忆层（写库再 `get_memory_context` 读回）构造 `agent_memory` 的输入，并校验与 `cases.json` 一致。
- `memory_layer_check.py`：不依赖 LLM 的记忆层自检（模拟事件流）。结果见 `experiments/results/memory_layer_check.md`。
- `inputs.json`：`build_inputs.py` 的产物，24 条 case × 3 种条件。

## 能说明什么，不能说明什么

- `memory_layer_check`：证明存储层行为正确（合并、摘要与入库一致、历史可被读取、空库对照为空）。这是**模拟输入**，不说明姿态检测或话术质量。
- 对照实验：只有在步骤 2、3 完成后才有数据。24 个合成场景 + 人工标注，样本小，只做描述性对比，不下显著性结论。
- 合成场景不等于真实用户录像；`cases.json` 状态为 `draft_unreviewed`，需 B/C 复核后再对外汇报。
