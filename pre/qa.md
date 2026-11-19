# 答辩 Q&A

> 负责人：D 汇总。每位成员至少 2 个本模块的潜在问题，并写明**现有证据**（仓库里能指出的文件/结果）和**待补证据**。
> 状态：D 的部分已核对；A/B/C/E 的问题由 D 根据仓库现状起草，**需各成员确认、补充证据后再定稿**。

## D：记忆与评估

**Q1. 为什么用 SQLite？**
MVP 只在单机演示，SQLite 无需单独服务，Python 标准库自带；关系模型之后可迁移到 MySQL/PostgreSQL。
证据：`backend/database.py`（仅用 `sqlite3`）。局限：不面向多进程高并发。

**Q2. 记忆会不会编造？**
不会新增事实。L1 只存 B 明确允许且跟踪质量为 good 的事件（只有 `feedback_allowed=true`、`tracking_quality=good` 且存在偏差时才写入；字段缺失也不写入）；L2 摘要由程序按已入库的事件和反馈日志生成，不调用 LLM；L3 只存用户设置的偏好。
证据：`tests/test_memory.py::test_untrusted_events_are_not_stored`、`test_summary_is_grounded_in_events_and_feedback`；`experiments/results/memory_layer_check.md` 中“摘要与入库一致”。

**Q3. B 每 200 ms 上报一次，数据库不会爆吗？**
同类型、同侧偏差在 3 秒内重复出现会合并为一个片段。模拟 3 次练习：80 条原始上报 → 5 条片段（16:1）。
证据：`experiments/results/memory_layer_check.md`。局限：输入是模拟事件流，3 秒阈值未经真实录像调参。

**Q4. 如何证明“开启记忆”更好？**
目前**还不能**。已完成：24 个合成场景、三种条件的输入包、自动指标（拒绝纠错准确率、同序列重复率、偏好长度遵守率）和人工标注指标的计算脚本。缺少：C 的 Agent 输出与人工标注，所以没有对照结果。
证据：`experiments/cases.json`、`experiments/memory/`、`experiments/evaluate.py`；`experiments/results/` 里没有 `metrics.*`。

**Q5. 用户隐私怎么处理？**
练习记录只存本地 SQLite；`*.db` 在 `.gitignore`；提供删除单个偏好、单次会话、某用户全部数据的接口。局限：没有登录，`user_id` 固定为 `default`；数据库文件本身未加密。
证据：`backend/routes_memory.py`（`DELETE` 接口）、`.gitignore`。

**Q6. 删除偏好后会怎样？**
对应行被删除，之后 `get_user_preferences` / `get_memory_context` 不再返回。证据：`test_upsert_and_delete`。

## A：数据与关键点（草稿，待 A 补充）

**Q1. 为什么用 MediaPipe 33 点而不微调模型？**
MVP 范围明确不做 MediaPipe 微调；课程两周周期内用预训练模型 + 规则检测。证据：README“MVP 范围与限制”。待补：A 的参考骨架对比图 `pre/assets/skeleton_comparison.png`。

**Q2. 参考视频的授权怎么处理？**
原始视频不入库（`data/raw_videos/` 在 `.gitignore`），`data/README.md` 应列出来源与许可。待补：`data/README.md` 目前只有标题，未填来源清单。

**Q3. 浏览器端和离线提取的坐标是否一致？**
E 的 `poseLandmarker.ts` 按 A 的 `docs/keypoint_format.md` 对齐。待补：`keypoint_format.md` 目前仅一句占位，A 需写明坐标系、归一化与 visibility 含义后，才能确认一致。

## B：姿态分析（草稿，待 B 补充）

**Q1. 为什么要 `feedback_allowed` 和 `tracking_quality`？**
置信不足、遮挡、视角异常时拒绝纠错，避免错误建议。证据：`contracts/mock/analysis_event.json`；README“不在本 MVP”一节。待补：B 的判定阈值和 `docs/detection_rules.md`。

**Q2. 偏差检测的精确率/召回率是多少？**
待补：`experiments/detection/` 目前为空，没有实验数据，不能回答具体数字。

**Q3. 侧弯式检测哪些偏差？**
待补：`contracts/README.md` 中 ardhakati_chakrasana 的类型仍是“待 B 填写”。

## C：Agent（草稿，待 C 补充）

**Q1. LLM 不可用时怎么办？**
有固定降级话术 `knowledge/fallback_templates.json`。待补：`routes_agent.py` 尚未实现降级逻辑，需 C 补充并给出演示。

**Q2. 如何防止 Agent 说出没有依据的建议？**
输出契约含 `grounded_event_type`，要求每条纠错都对应一个检测事件。待补：校验逻辑（`backend/agent.py` 目前为空）与 `tests/test_agent.py`。

**Q3. 为什么不是纯模板？**
对比实验（模板 vs Agent vs Agent+记忆）用于回答此问题，但目前没有结果，见 D 的 Q4。

## E：前端与演示（草稿，待 E 补充）

**Q1. 为什么限制每 200 ms 上传一次、同时最多一个请求？**
控制后端负载并避免旧结果覆盖新画面；遮挡、识别中断会使待返回请求失效。证据：`docs/e-integration.md`“E 的运行行为”。

**Q2. 反馈为什么 10 秒后显示“已过期”？**
防止展示与当前画面不符的旧建议。证据：同上；待补：E 的竞态回归测试（`experiments/e2e/E-audit-2026-11-16.md` 列出 E-01~E-05 缺陷，需确认修复状态）。

**Q3. 现场网络/摄像头/LLM 出故障怎么办？**
`pre/demo_plan.md` 的故障预案与备份视频。待补：`demo_backup.mp4` 尚未录制。
