# 山式规则说明、数据依据与持续事件接口

版本：`tadasana-rtmw-draft-v1`。本文与 `knowledge/tadasana_rules_B.json`、`backend/pose_rules_tadasana.py`、`backend/tadasana_event_tracker.py` 配套。

## 1. 本次实现的边界与结论

目前已经实现一条可以独立回放的 B 模块链路：

```text
A 的 RTMW-x 133 点 / 已有 features.jsonl
  → pose_features_133.extract_features_133（已有几何特征计算）
  → pose_rules_tadasana.compare_tadasana_frame（本次：单帧逐规则比较）
  → TadasanaEventTracker.update（本次：持续确认、恢复、中断、去重）
  → 结构化证据交给 C 的 Agent / E 的页面
```

输入已经是 `features.jsonl` 时，从单帧比较开始，不需要重复计算节点。这里比较的是**计算值与规则区间**，没有逐帧匹配某个示范者的骨架，也没有训练一个新的深度模型。

当前新增七条规则定义，其中两条左右肘规则可以在**显式探索模式**下产生候选和持续事件；其余五条保留观测值与参考说明，设置为 `monitor_only`，不产生纠错事件。规则的 `reviewed=false`，默认调用会保留审核门禁；通过 `allow_unreviewed=True` 可运行课程演示和离线验证，并保留探索标记。

这不是一个“整个人体动作合格/不合格”的二分类器。`within_reference` 只描述本帧被评估规则的结果；请同时查看 `assessment_coverage` 和每条 `rule_results`。规则范围、持续时间和阶段输入仍需要结合原视频人工复核。

本次没有改动原有 `/api/analyze`、共享 `schemas.py`、C 的 `knowledge/tadasana.json` 或兜底文案。旧接口仍沿用原来的约定；不要将本模块的输出直接伪装成旧响应结构。新增模块可先离线运行，后续接接口时再由 B/D 一起映射字段。

## 2. 依据的两组文件

来源目录：

- `experiments/detection/outputs/tadasana_rtmw_correct_2`
- `experiments/detection/outputs/tadasana_rtmw_incorrect_2`

每个目录使用 `features.csv`、`features.jsonl`、`summary.json` 交叉核对；原始点位的哈希也与 summary 的记录核对。详细审计在 `experiments/detection/tadasana_rule_audit.json`。


| 项目                       |                 correct_2 |        incorrect_2 |
| -------------------------- | ------------------------: | -----------------: |
| JSONL / CSV / summary 帧数 |        2132 / 2132 / 2132 | 1899 / 1899 / 1899 |
| 时间戳范围                 |               0–71016 ms |        0–63251 ms |
| 相邻帧时间差               |                33 / 34 ms |         33 / 34 ms |
| 重复、倒序时间戳           |                         0 |                  0 |
| 八个特征全部有效的帧       |                      2132 |               1899 |
| 模型                       | RTMW-x，`rtmw_x_384.onnx` |               同左 |
| 点位布局                   |        COCO-WholeBody 133 |               同左 |
| 坐标                       |  图像像素，x 向右、y 向下 |               同左 |
| 人工保持阶段标注           |                        无 |                 无 |
| 逐帧错误类型标注           |                        无 |                 无 |

`correct` 和 `incorrect` 是来源文件名的标签，不能解释为前者每一帧都标准、后者每一帧都错误。这两段视频都含有准备、举臂、保持、放下等变化，不能将整段的最小值/最大值直接当作保持动作阈值。

文件追溯：


| 文件                     | SHA256                                                             |
| ------------------------ | ------------------------------------------------------------------ |
| correct features.jsonl   | `99b02ee8a94e8868adff0c36010d2bd8198154f7fdaa7d2c04deda54c6d12654` |
| incorrect features.jsonl | `a4b9c637119377ea417e5b7596c37fae250bd5f75648717aef6e7b96606d0ad8` |
| correct 原始 keypoints   | `e6b029d1848f88968b7b7df6f6bcb00a51fbeea0a21ce7dbc46735b7af0cb44e` |
| incorrect 原始 keypoints | `13482ec38dd265847af2b3bdbeb90b3a0cace2df01c2ca7add78f20405579db2` |

特征文件里的 `feature_version="dwpose133-geometry-v1"` 是已有几何公式的版本名，不代表本次来源模型是 DWPose。实际模型信息独立保存为 RTMW-x；没有为了命名一致而改写已有数据。

### 2.1 点位分数的真实含义

规则检查所需点位的最低原始 score 是否至少为 0.5，作为临时质量门槛。它不是概率、事件置信度或 MediaPipe visibility，也没有被校准。

- 所有 133 点的原始 score：correct 约 0.5718–1.0016，incorrect 约 0.6054–1.0157。
- score > 1 的点数分别为 3、215；保留原值，不截断为 1。
- 本次涉及的身体点最低 score 分别约 0.6574、0.7010，所以 0.5 门槛没有排除这两组中的相关点。
- 因此这两组数据不能用于证明遮挡、低分过滤或多人场景的可靠性；这类行为主要由合成边界测试覆盖，后续应补真实样本。

## 3. 已有特征公式与规则使用方法

令 `P_i=(x_i,y_i)`。关键点索引为：左/右肩 5/6，左/右肘 7/8，左/右腕 9/10，左/右髋 11/12，左/右踝 15/16。左右为模型的人体解剖左右，不是屏幕左右；镜像显示时前端要保持这一约定。

定义：肩中心 `S=(P5+P6)/2`，髋中心 `H=(P11+P12)/2`，中心躯干长度 `T=||H-S||`，投影肩宽 `W=||P6-P5||`。角函数为 `angle(u,v)=acos(clamp(dot(u,v)/(||u||||v||),-1,1)) × 180/π`。


| 特征名                         | 公式/意义                          | 单位                 | 所需点      |
| ------------------------------ | ---------------------------------- | -------------------- | ----------- |
| `shoulder_height_diff_px`      | `abs(y5-y6)`                       | px                   | 5,6         |
| `shoulder_height_diff`         | `abs(y5-y6)/T`                     | torso_ratio          | 5,6,11,12   |
| `torso_tilt_deg`               | `atan2(S.x-H.x, H.y-S.y) ×180/π` | deg                  | 5,6,11,12   |
| `left_elbow_angle_deg`         | `angle(P5-P7, P9-P7)`              | deg                  | 5,7,9       |
| `right_elbow_angle_deg`        | `angle(P6-P8, P10-P8)`             | deg                  | 6,8,10      |
| `left_arm_torso_angle_deg`     | `angle(P7-P5, H-S)`                | deg                  | 5,6,7,11,12 |
| `right_arm_torso_angle_deg`    | `angle(P8-P6, H-S)`                | deg                  | 5,6,8,11,12 |
| `ankle_spacing_shoulder_ratio` | `abs(x15-x16)/W`                   | shoulder_width_ratio | 5,6,15,16   |

解释时需要保留以下区别：

- 肩高差规则使用归一化的 `shoulder_height_diff`，避免直接使用像素阈值随分辨率和人与镜头距离变化。分母是中心躯干长度，不是肩宽。
- `torso_tilt_deg` 的正值表示肩中心向**图像右侧**偏离髋中心，负值表示向图像左侧；比较时用绝对值。它是二维侧倾投影，不能测量真实前倾/后仰，也不能据此诊断脊柱问题。
- 肘角接近 180° 表示二维投影中的肘部接近伸直；接近 0° 表示明显折叠。它不判断关节超伸或是否适合某个个体。
- 上臂相对躯干的角度约 0° 为上臂向下，约 180° 为上臂向上。它使用肩到肘的向量，不是肩到腕的整臂方向，也不是肘关节内角。
- 脚距是**双踝横向间距 / 二维欧氏肩宽**，不是双脚边缘距离、脚尖距离、髋宽或三维站距。比值 0.3 表示该投影下踝间距约为肩宽的 30%，不能解释为“脚必须并拢到某个厘米数”。

所有特征仍通过已有函数处理缺点、低分、长度为零等几何失败。规则层再次检查 `valid`、有限数值、单位、score 和几何数值域；异常特征只让相关规则不可评估，不使用 0 填充成一个“正常值”。NaN/Infinity 在传给持续层的保留特征中转为 null。

## 4. 阶段必须明确：不能混用垂臂与举臂

这一来源中存在举臂变体，当前两条可演示规则只适用于**举臂保持阶段的肘角**。这不代表所有山式都必须举臂。


| phase            | 意义                  | 当前行为                   |
| ---------------- | --------------------- | -------------------------- |
| `unknown`        | 阶段不明              | 不产生肘部候选             |
| `prepare`        | 准备                  | 不产生肘部候选             |
| `transition`     | 举起/放下/切换        | 不产生肘部候选；中断旧事件 |
| `arms_down_hold` | 人工/上游确认垂臂保持 | 两条举臂肘规则不适用       |
| `arms_up_hold`   | 人工/上游确认举臂保持 | 可评估两条肘规则           |

`phase` 是阶段标签，不是 `pose_id`。当前模块专用于山式，不需要传动作 ID；`phase_source` 和 `phase_reviewed` 记录阶段来自哪里、是否经过人工审核。传 `phase_reviewed=True` 只记录调用者的声明，不会自动完成视频审核。

### 4.1 本次统计用的几何分组

为了避免把明显垂臂与举臂混合统计，审计报告使用以下临时分组：

- 双侧上臂角均 <30°：`arms_down_geometry`。
- 双侧上臂角均 >150°：`arms_overhead_geometry`。
- 其余：`other_geometry`。

这些分组只描述当帧形状，不等于人工确认的稳定保持动作。举臂组分别有 correct 971 帧、incorrect 936 帧。它会包含进入/离开保持动作时的帧；尤其不能先按上臂角筛选，再声称在同一组上验证了上臂角规则。

离线脚本为演示可将此分组映射为 phase，但必须同时显式开启 `--allow-unreviewed --preview-geometric-phases`，输出标记为 `geometry_preview_NOT_HOLD_GROUND_TRUTH`、`phase_reviewed=false`。日后评估应换成人工时间段标注。

## 5. 数据支持了什么

### 5.1 整段统计不能直接产生动作标准


| 特征          | correct 中位数 / P95 | incorrect 中位数 / P95 | 判断                           |
| ------------- | -------------------: | ---------------------: | ------------------------------ |
| 肩高差/躯干长 |      0.0142 / 0.0378 |        0.0156 / 0.0406 | 大量重叠                       |
| 绝对躯干倾角  |  0.7943° / 2.0237° |    0.6228° / 2.2026° | 大量重叠，incorrect 中位数更小 |
| 踝距/肩宽     |      0.2742 / 0.5900 |        0.3246 / 0.7655 | 含不同阶段和站姿变化           |

correct 视频开头也有约 5.7 秒的比值 >0.4；若对全视频直接做“脚距 >0.4 就错误”，会把来源为正确示范的准备过程报成错误。因此本版不激活脚距纠错。

### 5.2 双臂举起几何组的描述性统计

以下 P05 / 中位数 / P95 均来自上述几何组，不是人工标注的合格区间。


| 特征          | correct：P05 / 中位数 / P95 | incorrect：P05 / 中位数 / P95 |
| ------------- | --------------------------- | ----------------------------- |
| 左肘角        | 169.32 / 175.54 / 178.52°  | 153.51 / 168.55 / 178.09°    |
| 右肘角        | 167.24 / 176.51 / 179.41°  | 148.66 / 167.65 / 179.10°    |
| 左上臂角      | 174.67 / 176.46 / 179.63°  | 169.91 / 175.29 / 179.44°    |
| 右上臂角      | 172.63 / 175.69 / 178.93°  | 166.16 / 177.47 / 179.62°    |
| 肩高差/躯干长 | 0 / 0.0189 / 0.0384         | 0.0065 / 0.0212 / 0.0426      |
| 绝对躯干倾角  | 0 / 0.6228 / 1.8358°       | 0 / 0.3769 / 1.4528°         |
| 踝距/肩宽     | 0.2564 / 0.2800 / 0.3266    | 0.2916 / 0.3498 / 0.3854      |

肘角在两组之间有可观察到的差异，但分布仍然重叠。160° 触发、165° 恢复是根据这两段数据选择的保守**工程演示值**，不是由 P05 自动计算的结果，也不是教学或生理标准。将 170° 直接设为触发值会在 correct 来源中出现超过 1 秒的连续命中，因此本版降低灵敏度并加入持续时间过滤。

两段视频不构成独立训练/验证/测试集；本次不报告准确率、召回率或推广能力。

## 6. 七条规则的精确定义

`reference_range` 是配置中说明用的工作参考范围，`trigger_range` 定义不触发的区间，`clear_range` 定义可以连续确认恢复的区间。实际判定先看是否在 trigger 外，再看是否在 clear 内；两者之间为灰区。边界均包含在区间内。


| rule_id                     | 特征          | 工作参考范围 | 触发候选条件            | 恢复条件   | 适用阶段 | 模式         |
| --------------------------- | ------------- | ------------ | ----------------------- | ---------- | -------- | ------------ |
| `left_elbow_bend_overhead`  | 左肘角        | 165–180°   | <160°                  | ≥165°    | 举臂保持 | candidate    |
| `right_elbow_bend_overhead` | 右肘角        | 165–180°   | <160°                  | ≥165°    | 举臂保持 | candidate    |
| `shoulder_height_monitor`   | 肩高差/躯干长 | 0–0.04      | 配置示例 >0.06          | ≤0.04     | 两种保持 | monitor_only |
| `torso_tilt_monitor`        | 绝对躯干倾角  | 0–3°       | 配置示例 >5°           | ≤3°      | 两种保持 | monitor_only |
| `stance_monitor`            | 踝距/肩宽     | 0.25–0.33   | 配置示例 <0.20 或 >0.40 | 0.25–0.35 | 两种保持 | monitor_only |
| `left_upper_arm_monitor`    | 左上臂角      | 170–180°   | 配置示例 <160°         | ≥170°    | 举臂保持 | monitor_only |
| `right_upper_arm_monitor`   | 右上臂角      | 170–180°   | 配置示例 <160°         | ≥170°    | 举臂保持 | monitor_only |

后五条数值只是方便后续审核的配置草案，不是已启用判据。即使观测值远超其范围，`monitor_only` 仍返回 `disabled / monitor_only`，不会进入候选或持续事件。原始观测保留在 features 及 rule_results 中。

每条规则当前时间参数相同：


| 参数                | 当前值 | 用途                                |
| ------------------- | -----: | ----------------------------------- |
| `min_duration_ms`   |   1500 | 连续命中候选至少 1.5 秒后确认事件   |
| `clear_duration_ms` |    700 | 连续达到恢复范围至少 0.7 秒后恢复   |
| `max_gap_ms`        |    500 | 相邻有效更新超过 0.5 秒就中断连续性 |

这些时间也是工程参数，需要后续通过延迟与误触发的权衡来调节；不是按 45 帧硬编码。约 30 FPS 时通常接近 45 个间隔，但程序始终以时间戳差计算。

### 6.1 肘角边界实例


|                               当前肘角 | 单帧状态                  |
| -------------------------------------: | ------------------------- |
|                               159.99° | `deviation`：单帧偏差候选 |
|                                  160° | `gray_zone`               |
|                               164.99° | `gray_zone`               |
|                                  165° | `within_reference`        |
|                                  180° | `within_reference`        |
| >180°、负值、null、非有限数、单位错误 | `not_assessable`          |

灰区的作用是避免角度在同一条边界附近抖动时不断开始/恢复。待确认时进入灰区会清空该次待确认；事件已激活后进入灰区会保留事件，但不能据此恢复。

## 7. 单帧规则层的调用与输出

`backend/pose_rules_tadasana.py` 的主函数：

```python
from backend.pose_rules_tadasana import compare_tadasana_frame, load_rules

rules = load_rules()  # 可在练习开始时加载一次，逐帧复用
evaluation = compare_tadasana_frame(
    feature_frame,                 # extract_features_133 的返回值或 JSONL 中一行
    phase="arms_up_hold",          # 调用者明确提供；默认 unknown
    camera_view="front",           # 当前仅评估正面二维投影
    source_model="RTMW-x",
    phase_source="caller_declared",
    phase_reviewed=False,
    allow_unreviewed=True,         # 仅课程探索；不等于把规则审核通过
    ruleset=rules,
)
```

未经人工审核的配置默认不比较候选；显式探索模式才放行两条 candidate 规则。将来如完成审核，可在 JSON 中设置 `reviewed=true` 并填写非空 `review_record`，包括审核人、视频/阶段范围、日期、教学依据与版本。只改布尔值没有审核记录会被配置校验拒绝；程序也无法替代审核记录的真实性。

全局前提不满足时，该帧规则返回不可评估，原因码包括：`layout_mismatch`、`coordinate_space_mismatch`、`feature_version_mismatch`、`source_model_missing_or_mismatch`、`front_view_required`、`features_missing`。

每条规则还会检查缺点/无效值、单位、点位分数及数值域。`timestamp_ms` 必须为非负整数；非法的规则配置会直接抛出 ValueError，避免一边运行一边使用不一致配置。


| 输出字段                                    | 含义与下游用法                                                                                |
| ------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `schema_version`                            | 当前为`tadasana-comparison-v1`                                                                |
| `rule_version` / `feature_version`          | 分别追溯规则配置和几何公式                                                                    |
| `rules_reviewed` / `execution_mode`         | 标明已审核、探索模式或默认审核门禁                                                            |
| `phase` / `phase_source` / `phase_reviewed` | 阶段与阶段证据来源                                                                            |
| `camera_view_verified`                      | 当前固定 false；front 来自输入声明，未进行视觉核验                                            |
| `assessment_status`                         | 该帧汇总：candidate_deviation / gray_zone / within_reference / not_assessable / not_evaluated |
| `assessment_coverage`                       | 当前阶段启用规则中，哪些成功评估、哪些未评估；complete 也只针对这些规则                       |
| `features`                                  | 原有特征证据，保留给 C/E 使用                                                                 |
| `rule_results`                              | 七条规则各自的状态、原因、观测值、阈值、单位和时间参数                                        |
| `candidates`                                | 仅当前帧超触发范围的规则，无 event_id 和 duration_ms                                          |
| `deviations`                                | 当前保持空列表；避免误解为已持续确认的反馈输入                                                |
| `feedback_allowed`                          | 单帧层始终 false                                                                              |

例如左肘不可评估、右肘在范围内时，汇总可以是 `within_reference`，但 coverage.complete 为 false；C 不能只读汇总字段便说“双臂动作标准”。即使 coverage.complete=true，也不代表全身姿态正确，因为肩、躯干、脚距等仍为监测模式。

单帧 `status` 的解释：`deviation` 是瞬时超阈值；`within_reference` 是满足恢复范围；`gray_zone` 为中间带；`not_assessable` 是证据不足；`not_applicable` 是阶段不适用；`disabled` 是监测/禁用/审核门禁。它们和下节事件的生命周期 status 属于不同层级，事件会把原状态另存为 `rule_status`。

## 8. 持续事件状态机

代码位于 `backend/tadasana_event_tracker.py`。每条规则独立计时，左右肘可以同时形成两个事件，不会先合并为一个“整个人错误”。

```text
无状态 --deviation--> pending（待确认）
pending --连续 deviation 达到1500ms--> active + started 一次
pending --正常/灰区/无效/不适用--> 清空待确认
active --within_reference--> clearing（等待恢复确认）
clearing --连续 within_reference 达到700ms--> recovered + 清空
clearing --deviation 或 gray_zone--> 返回 active，取消恢复计时
active/clearing --无效/丢规则/阶段变更/超间隔等--> interrupted + 清空
```

示例时间线（每隔 100ms 更新，间隔没有超过 max_gap）：

```text
t=0      左肘150°：pending
t=1400   左肘150°：仍 pending，不发反馈
t=1500   左肘150°：new_events 中一个 started，允许消费一次
t=1600   左肘150°：仍 active，但不重复生成 started
t=2000   左肘170°：进入 clearing
t=2600   左肘170°：尚未达到700ms
t=2700   左肘170°：一个 recovered
```

如果 t=1400 的角度变成 162°，待确认会被清空，下一次低于 160° 从新起点计时；不能把不连续的 10 次低角度累计为“持续 1.5 秒”。

### 8.1 生命周期输出

`update` 返回单帧 evaluation 的副本，并补充：


| 字段                         | 内容                                                                    |
| ---------------------------- | ----------------------------------------------------------------------- |
| `new_events`                 | 此帧新发生的 started / recovered / interrupted；不是每帧重复推送 active |
| `active_events`              | 当前已确认但尚未结束的事件快照，包含 clearing 中的事件                  |
| `pending_events`             | 尚未持续足够时间的规则快照，无 event_id                                 |
| `feedback_allowed`           | 仅本帧存在 started 时 true，表示达到工程持续条件                        |
| `ignored` / `ignored_reason` | 重复或倒序时间戳被忽略，不改变内部状态                                  |

事件保留 `rule_id`、`event_type`、`target`、特征值、阈值、score、规则版本、阶段来源及探索标记，再补充：

- `event_id`：实例随机前缀加递增计数；同一事件开始到结束保持一致；reset 后也不复用旧编号。
- `start_timestamp_ms`：此次连续偏差起点。
- `confirmed_timestamp_ms`：达到持续条件的实际帧时间。
- `timestamp_ms`：本条生命周期通知被生成的帧时间。
- `duration_ms`：`duration_semantics="episode_elapsed"`，从开始到最后证据帧/恢复帧的区间长度。
- `end_timestamp_ms`：recovered 或 interrupted 的证据结束时间。
- `interruption_reason`：中断原因。

**duration_ms 不是事件激活后所有超阈值帧时长的累计。**激活后事件允许灰区及恢复等待时间，所以最终 duration 包括这些时间。started 时的 1500ms 确认过程才要求连续 deviation。中断时 duration 只计算到最后连续证据时间，不把缺失的长间隔计入。

### 8.2 中断与恢复严格区分


| 情况                                                | 行为                                                    |
| --------------------------------------------------- | ------------------------------------------------------- |
| 当前规则 not_assessable / not_applicable / disabled | 旧 active 事件 interrupted；pending 清空                |
| 某条规则从结果中消失                                | interrupted，原因 rule_missing                          |
| phase 改变                                          | interrupted，原因 phase_changed                         |
| rule_version 改变                                   | interrupted，原因 rule_version_changed                  |
| 模型/特征版本/审核状态/阶段来源/运行模式等改变      | interrupted，原因 context_changed                       |
| 某规则 temporal 参数改变                            | interrupted，原因 temporal_parameters_changed           |
| 相邻更新间隔 >500ms                                 | interrupted，原因 frame_gap；若当前仍偏差，重新 pending |
| 相邻更新间隔恰好500ms                               | 保持连续；仍以时间差判断                                |
| 时间戳重复或倒序                                    | ignored，不开始、不结束、不重置事件                     |
| 视频结束时仍有 active                               | 报告为未结束，不编造 recovered                          |

例如“手放下后肘角变化”属于阶段切换，不能称为“经过纠正后恢复”。当前两组探索回放中的已激活事件最终都是 phase_changed 中断，没有发生可确认的恢复。

### 8.3 不使用 session_id / pose_id 的做法

```python
from backend.pose_rules_tadasana import compare_tadasana_frame, load_rules
from backend.tadasana_event_tracker import TadasanaEventTracker

rules = load_rules()
tracker = TadasanaEventTracker()  # 一次视频/一条摄像头练习流创建一个

for feature_frame in feature_stream:  # 按时间戳顺序串行调用
    evaluation = compare_tadasana_frame(
        feature_frame, phase=current_phase, camera_view="front",
        source_model="RTMW-x", ruleset=rules, allow_unreviewed=True,
    )
    payload = tracker.update(evaluation)
    # payload 是给后续消费者的结构化证据；持续状态存在 tracker 中

tracker.reset()  # 新一轮练习之前调用；或直接创建新实例
```

`reset()` 清空状态和时间戳，不会伪造恢复通知；如果需要保留旧事件中断记录，先提交一个规则已不适用的末帧，再 reset。

此实现是内存状态，不自动跨刷新、重启、服务器 worker 或机器保存。同一实例需要串行调用；不同用户/并行视频必须用不同实例。不能在每一帧都 new tracker（永远无法累计），也不能把所有 HTTP 用户共用一个全局 tracker（会把人的时间线混起来）。

无需 session_id 的可用集成方式：离线上传一个完整视频时，在一次任务内创建 tracker 并处理全部帧；或一条 WebSocket 连接持有一个 tracker。若后续改成多次独立 HTTP 请求逐帧上传，再由 D 设计如何识别流并管理实例；本次不虚构这套会话机制。

## 9. 给下游 C / E 提供什么

C 应优先消费 `new_events` 中 `status="started"` 的结构化证据，按 event_id 去重，不要把每帧 candidates / active_events 都发给 LLM。`recovered` 可用于更新历史记录，`interrupted` 表示证据结束，不能生成“你做对了”。

生成反馈时保留 target、observed_value、reference_range、规则版本和来源标签。可表达“当前画面中右肘的二维夹角约159°，连续低于本次演示阈值1.5秒”；不能把它扩展为肩、脊柱或全身的判断。left/right 文案要按人体左右解释。

`feedback_allowed=true` 只表示有新的持续事件，**不是审核认证**。当前演示还会同时带 `rules_reviewed=false`、`execution_mode="exploratory_preview"`、`phase_reviewed=false`；界面和日志应保留这些标记。正常面向用户启用前，应明确审核规则、阶段识别及相机约定，不能去掉探索标记后继续沿用未审核数据。

建议消费逻辑：

```python
started = [e for e in payload["new_events"] if e["status"] == "started"]
if payload["feedback_allowed"]:
    for evidence in started:
        # 由 C 在 Agent 的既有输入约定中映射；保留审核/探索字段。
        # event_id 去重；按 evidence.target 选择知识与措辞。
        pass
```

E 可显示 measurements、单帧候选、pending、active、clearing、interrupted；状态缺失与“正常”应显示为不同信息。不要显示未经定义的全身得分或将 `min_keypoint_score` 当成“动作准确率”。本模块没有合成 overall_score/confidence。

## 10. 实际回放结果与复现命令

从项目根目录执行，脚本只需 Python 标准库，不需要重新推理 RTMW，也不调用 LLM。

```bash
cd /Users/tzc/Downloads/YogaCoach-LLM-main

# 默认：未审核规则 + 阶段未知，验证没有自动纠错输出
python3 -m experiments.detection.replay_tadasana_rules \
  experiments/detection/outputs/tadasana_rtmw_correct_2 \
  --output-dir experiments/detection/outputs/tadasana_rules_guard/correct

# 显式探索：用几何分组预览规则与持续事件
python3 -m experiments.detection.replay_tadasana_rules \
  experiments/detection/outputs/tadasana_rtmw_incorrect_2 \
  --output-dir experiments/detection/outputs/tadasana_rules_preview/incorrect \
  --allow-unreviewed --preview-geometric-phases
```

将输入与输出末尾的 correct / incorrect 对应替换，可复现两组。输出 `rule_frames.jsonl` 为逐帧规则及持续状态追踪，`rule_summary.json` 为计数、来源、全部生命周期事件和末尾开放事件。trace 不重复保存 features；原始特征保留在来源目录。


| 运行                              | correct_2（2132帧） | incorrect_2（1899帧） |
| --------------------------------- | ------------------: | --------------------: |
| 默认门禁持续 started              |                   0 |                     0 |
| 探索：单帧 candidate_deviation 帧 |                  16 |                   310 |
| 探索：gray_zone 汇总帧            |                  18 |                    30 |
| 探索：within_reference 汇总帧     |                 937 |                   596 |
| 探索：started                     |                   0 |                     3 |
| 探索：recovered                   |                   0 |                     0 |
| 探索：interrupted                 |                   0 |                     3 |

单帧候选数按“至少一条肘规则命中”的帧计，不等于两侧命中数之和。没有持续 started 也不能说明整段正确，只表示这些规则和当前参数没有形成已确认事件。

incorrect 探索运行的三个开始事件：


| 目标 | 连续候选开始 | 持续确认时间 | 确认时角度 | 后续结束                                  |
| ---- | -----------: | -----------: | ---------: | ----------------------------------------- |
| 右肘 |     26.360 s |     27.860 s |  159.414° | 30.559 s 检测到阶段切换，最后证据30.526 s |
| 左肘 |     53.620 s |     55.120 s |  154.534° | 60.118 s 检测到阶段切换，最后证据60.085 s |
| 右肘 |     53.587 s |     55.120 s |  149.301° | 60.118 s 检测到阶段切换，最后证据60.085 s |

第一个事件尤其需要查看原视频确认是否仍处于动作变化过程。由于当前 phase 来自几何分组，不能直接把三个事件当作三次真实教学错误，也不能用 correct=0、incorrect=3 计算准确率。

### 10.1 改用人工审核阶段文件

复制 `experiments/detection/tadasana_segments.example.json`，填写该 features 文件的 SHA256 和经视频复核的时间段。时间范围为 `[start_ms,end_ms)`，必须排序且不重叠；未标注时间默认 unknown。

```json
{
  "source_features_sha256": "填写对应features.jsonl的实际SHA256",
  "reviewed": false,
  "segments": []
}
```

模板故意不预填“正确保持段”。审核者应查看原视频，逐段写入 start_ms、end_ms、phase，并保留审核说明。`reviewed=true` 表示人工标注确已完成，不由程序根据文件名决定。

```bash
python3 -m experiments.detection.replay_tadasana_rules \
  experiments/detection/outputs/tadasana_rtmw_incorrect_2 \
  --output-dir experiments/detection/outputs/tadasana_rules_manual/incorrect \
  --segments path/to/reviewed_segments.json --allow-unreviewed
```

这里仍需 `--allow-unreviewed` 是因为规则配置本身尚未审核；阶段审核与规则审核是两件事。`--segments` 不能与 `--preview-geometric-phases` 混用。源特征哈希不符会拒绝运行。

## 11. 后续如何从草案变成可评估规则

1. 先让负责动作解释的成员确认项目采用的山式版本，明确垂臂/举臂的教学要求、正面相机角度与允许的自然差异。
2. 在原始视频上标注准备、过渡、保持阶段，以及每条错误规则的起止时间与目标身体部位；不以正确/错误目录名代替帧级标签。
3. 再补多个人、不同拍摄条件、可见/遮挡、正常抖动和错误程度的片段。至少按人或完整视频划分开发与验证集，不能把相邻帧随机拆开当独立样本。
4. 对审核后的正常保持段计算稳健分位数，并结合人工错误标签确定触发值、恢复值及时间参数；检查肩/躯干等重叠特征是否真的能区分目标问题。
5. 固定参数后在独立视频上按事件评估：误触发次数/分钟、事件召回、确认延迟、左右目标是否正确、缺点时是否正确中断。帧指标可辅助，但不要代替事件指标。
6. 审核通过的具体规则再把 mode 从 monitor_only 改为 candidate；记录依据、修改规则 version、更新 review_record 后重放。不要只因想让演示更热闹而打开全部规则。
7. C/D/E 对齐返回结构、事件去重、练习开始/结束与 tracker 生命周期后，再接入现有 API。

相机侧转会缩短投影肩宽，影响脚距比；镜头倾斜会改变肩高差与躯干角；二维图像不能充分判断三维旋转。现有 summary 的 front 只是元数据声明，camera_view_verification 仍未完成。本版只在这一输入约定下解释数值。

## 12. 文件清单、测试与维护


| 文件                                                   | 职责                                                                     |
| ------------------------------------------------------ | ------------------------------------------------------------------------ |
| `knowledge/tadasana_rules.md`                          | 本文：数据依据、规则含义、调用和下游约定                                 |
| `knowledge/tadasana_rules_B.json`                      | 可机读草案；区间、阶段、时间、模式和来源哈希                             |
| `backend/pose_rules_tadasana.py`                       | 无状态单帧比较与配置校验                                                 |
| `backend/tadasana_event_tracker.py`                    | 一条流的持续事件状态机                                                   |
| `experiments/detection/tadasana_rule_audit.json`       | 两组文件的一致性、分组统计、连续区间与原始score审计                      |
| `experiments/detection/build_tadasana_rules.py`        | 从已保存的审计结果重建当前草案配置；会覆盖该JSON，人工改规则前先保存版本 |
| `experiments/detection/replay_tadasana_rules.py`       | feature文件离线回放、逐帧追踪和事件汇总                                  |
| `experiments/detection/tadasana_segments.example.json` | 人工阶段标注格式模板                                                     |
| `tests/test_pose_rules_tadasana.py`                    | 边界、单位、质量门禁、来源、阶段、草案及覆盖信息                         |
| `tests/test_tadasana_event_tracker.py`                 | 确认、恢复、灰区、间隔、丢点、乱序、重置、上下文隔离                     |
| `tests/test_tadasana_rules_integration.py`             | 单帧→持续链路、回放门禁、阶段文件及末尾重复帧                           |

运行测试：

```bash
python -m pytest tests/ -q
```

交付时全量测试为 **84 passed、95 subtests passed**。它验证代码行为与边界，不等于验证人体动作阈值的有效性。两个真实文件的默认与探索回放也均已执行。

维护时优先修改 JSON；只有增加新特征、改变公式、增加比较方式或状态机语义才需要改 Python。添加新特征必须先同步特征计算/单位/版本，不能只在规则 JSON 写一个上游没有的字段。审核状态、版本和数据来源应随规则一起交付，避免 C/E 使用无法追溯的阈值。
