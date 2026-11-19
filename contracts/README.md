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

## B Day 1 接口草案（2026-11-17；待全员 Review，未冻结）

以下是本地实现草案，不代表已完成群内同步或成员批准。请由 B 同步 A/C/D/E 后走原有 PR 流程；没有自动发送消息或合并到主分支。

- `backend/schemas.py` 新增 `Landmark`、`PoseFrame`、`Observation`、`Deviation`、`AnalysisResult`，只定义 A→B/B→C；不接管 C/D 的模型。
- A/E 输入必须补 `session_id`、`frame_seq`、实际推理图像 `image_width/height`、`phase`。侧弯额外需要解剖侧别 `side`，山式传 null；时间为会话内单调毫秒。原 A mock 故意未改，其缺字段且33点重合，不能作为合法几何测试。
- 正式 `/api/analyze` 当前仅测量：`analysis_mode=measurements_only`、`reference_status=not_loaded`，永不产生纠正事件；有效测量也不是“动作正常”。
- `tracking_quality` 为 good/partial/poor；`assessment_status` 为 uncalibrated/within_reference/deviation/not_assessable，其中中间两项当前仅用于合成 Mock。
- B→C 保留原 `session_id/pose_id/timestamp_ms/tracking_quality/feedback_allowed/deviations` 和差异内 `type/side/severity/confidence/duration_ms`；新增测量证据、event_id与模式标识。仅原占位文件 `analysis_event.json` 被扩充，C的反馈和D的记忆Mock未改。
- Day 1 正式接口不记录持续时间，不判断重复/乱序，不做动作纠错；这是后续工作，不要从“接口有duration字段”推断状态机已实现。
- `confidence` 保留用于兼容，表示示意测量质量，非错误概率；Mock持续时间为手工设定。
- `side` 输入是解剖侧别；躯干角输出正号指图像右方，不能直接映射成解剖右方。需 A/E 用真实镜像样例确认。
- 侧弯候选类型 `raised_arm_elbow_bend` 仅为讨论草案，未启用；山式规则不能直接用于侧弯。

三类合成返回在 `mock/b_day1/`；完整输入在 `experiments/detection/fixtures/`，说明在 `experiments/detection/DAY1.md`。所有合成返回标为 `synthetic_mock/unvalidated_synthetic`；不得录入正式实验结果，也不应在实时练习中朗读Mock指导。
