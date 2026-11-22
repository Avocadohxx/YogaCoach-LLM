# YogaCoach D — 记忆模块与评估交付

## 1. 交付范围

本交付只包含成员 D 负责的记忆模块、配套测试、实验评估文件和说明文档；不包含其他成员的业务实现，也不覆盖主仓库公共契约或其他成员文件。

## 2. 功能内容

- **L1 姿态事件**：保存可信分析事件；按同一会话、偏差类型和侧别合并连续片段。
- **L2 会话摘要**：根据已保存的事件生成事实性练习摘要。
- **L3 用户偏好**：保存和读取用户明确设置的偏好，不自动推断。
- **反馈记录与上下文**：提供反馈日志、近期练习和偏好读取能力，供 Agent 侧使用。
- **HTTP API**：通过 `/api/memory` 提供会话、事件、反馈、偏好及上下文相关接口。

## 3. 可信事件规则

L1 事件只有同时满足以下条件才会写入：

1. `feedback_allowed` 的值明确为 `true`；
2. `tracking_quality` 的值为 `good`；
3. `deviations` 非空。

任一字段缺失或不满足条件，均跳过写入。

## 4. 主要文件

| 路径 | 内容 |
|---|---|
| `backend/database.py` | SQLite 表结构、连接和初始化 |
| `backend/memory.py` | L1/L2/L3 记忆读写逻辑 |
| `backend/routes_memory.py` | `/api/memory` 路由 |
| `tests/test_memory.py` | 记忆逻辑测试 |
| `tests/test_memory_api.py` | HTTP API 测试 |
| `tests/test_memory_eval.py` | 实验场景与评估脚本测试 |
| `experiments/memory/` | 记忆层自检及实验输入构建 |
| `experiments/evaluate.py` | 对照实验指标计算 |
| `docs/memory_design.md` | 记忆设计、数据结构和接口约定 |
| `docs/D_E_integration.md` | D 侧与 E/C/B 的接口交接说明 |
| `pre/qa.md` | D 相关答辩问答补充 |

## 5. 本地运行

在主仓库根目录执行：

```bash
pip install -r requirements.txt
python -m pytest tests/test_memory.py tests/test_memory_api.py tests/test_memory_eval.py -q
```

运行记忆层自检和实验输入构建：

```bash
python experiments/memory/memory_layer_check.py
python experiments/memory/build_inputs.py
```

计算真实对照实验指标：

```bash
python experiments/evaluate.py
```

真实指标计算前，需要先准备 `experiments/results/outputs.json`，其中包含各实验条件的实际输出及人工标注。`outputs.template.json` 只是填写模板，不是实验结果。

## 6. 实验结果边界

`memory_layer_check` 使用模拟事件验证记忆存储行为，只能说明记忆层逻辑可复现，不能证明姿态检测质量或 Agent 反馈效果。真实对照实验尚需实际 Agent 输出和人工标注；在此之前不报告 Agent 效果结论。

## 7. 依赖说明

`requirements.txt` 中包含 D 的 API 测试依赖 `httpx`。该文件属于共享依赖清单，提交时应在团队协作中说明新增项。
