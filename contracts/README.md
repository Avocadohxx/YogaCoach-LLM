# 接口契约（contracts）

> 本目录是五人之间的「接口约定」。每个人先按这里的 Mock 数据开发，不必等上游完成。
> **任何改动都要走 PR，并 @ 所有使用方，同时更新 `mock/` 里的样例。**

## 统一命名

| 项 | 取值 |
|---|---|
| `pose_id` | `tadasana`（山式）、`ardhakati_chakrasana`（站立侧弯式） |
| `camera_view` | `front` |
| 关键点 | MediaPipe Pose 33 点，坐标含 `x, y, z, visibility` |

## 四份接口

| 方向 | 说明 | Mock 样例 |
|---|---|---|
| A → B | 关键点输入（必须是 33 个点） | `mock/landmarks_tadasana.json` |
| B → C | 姿态分析事件 | `mock/analysis_event.json` |
| C → E | Agent 反馈 | `mock/agent_feedback.json` |
| D → C | 历史摘要、偏好、本次会话反馈 | `mock/memory_sample.json` |

## 待 Day 2 前确认的事项

1. **偏差类型枚举**（B 定稿，下表为草案）：

   | 动作 | `type` | 含义 | 状态 |
   |---|---|---|---|
   | `tadasana` | `shoulder_asymmetry` | 双肩高度差异 | 草案 |
   | `tadasana` | `torso_tilt` | 躯干侧倾 | 草案 |
   | `ardhakati_chakrasana` | 待 B 填写 | | 待定 |

2. **B → C 事件字段**：在团队文档基础上增加了 `side`（偏向哪一侧）和 `duration_ms`（持续时长），供 Agent 校验与话术使用。
3. **C → E 反馈字段**：增加 `target`（反馈部位）和 `grounded_event_type`（依据的事件类型，供输出校验）；`feedback_type` 取值固定为 `correction` / `camera_hint` / `none`。
4. **D → C 记忆函数**：团队文档里的三个函数之外，建议 D 补充本次会话内的反馈读写，用于去重和冷却：

   ```python
   get_recent_sessions(pose_id: str)
   get_user_preferences()
   save_session_summary(session_id: str, summary: str)
   get_recent_feedback(session_id: str, n: int = 5)                  # 建议新增
   log_feedback(session_id: str, event_type: str, text: str)         # 建议新增
   ```

## 变更规则

1. 先在群里说明要改什么、为什么。
2. 改 `contracts/` 与 `backend/schemas.py`，并同步更新 `mock/` 样例。
3. PR 里 @ 所有使用方，至少一位下游成员 approve 后再合并。
