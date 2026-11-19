# 站立侧弯式：规则设计、数据依据、持续事件与 B→C 交接

规则版本：`ardhakati-rtmw-draft-v1`。配置：`knowledge/ardhakati_chakrasana_rules.json`。

## 1. 实现结构

```text
A 的 133 点 → 已有 pose_features_133.py → 一帧8个几何特征
                                ↓
                 pose_rules_ardhakati.compare_ardhakati_frame
                 检查阶段、变体、举臂侧、方向、视角和质量
                                ↓
                    单帧 rule_results / candidates
                                ↓
                    ArdhakatiEventTracker.update
                 连续确认 → started / recovered / interrupted
                                ↓
                   agent_events.jsonl → C 的 Agent
```

本次输入直接使用附件 features.jsonl，不重新推理人体节点。单帧比较没有内部时间状态；持续层用一个实例维护一条练习流，不要求 session_id、pose_id。规则和状态机均为确定性 Python，核心运行不需要 LLM。

本次新增独立侧弯模块、规则、文档、审计/回放脚本和测试。山式持续层只做了可覆写阶段/上下文/事件前缀的参数化，以便侧弯复用同一状态机。C 已有的 `knowledge/ardhakati_chakrasana.json`、旧接口 Schema、HTTP 路由和 Agent 实现不在本次修改范围内。

## 2. 首先确认动作变体：附件和双臂描述存在差别

你的主目标动作是：山式站立 → 双臂经体侧举过头顶 → 双手合掌、上臂靠耳 → 保持侧屈 → 回正 → 放下双臂 → 换侧。代码支持这个版本，标记为 `both_arms_overhead`。

但是，两份附件都没有“双上臂角同时 >150°”的帧。侧弯期间通常一臂抬起、另一臂下垂：

| 来源几何分组 | correct 左上臂角中位数 | correct 右上臂角中位数 |
|---|---:|---:|
| 躯干向图像左侧倾斜超过15° | 143.93° | 8.60° |
| 躯干向图像右侧倾斜超过15° | 11.14° | 138.44° |

这支持“更接近单臂变体”的几何解释，仍需要查看原视频确认。因此保留独立 `single_arm_overhead` 上下文供附件探索，**不能将附件当作双臂版的合格示范，也不能把单臂变体天然报为双臂版做错了**。

| movement_variant | 代码行为 |
|---|---|
| `unknown` | 不猜动作版本，相关规则不可评估 |
| `both_arms_overhead` | 检查左右肘与两侧上臂对齐；不传单个 raised_arm_side |
| `single_arm_overhead` | 只检查明确举起侧的肘；上臂角保留监测 |

单臂版本需要 `raised_arm_side="left"/"right"`。这是**模型人体解剖侧别**，与 `bend_direction="image_left"/"image_right"` 是两种坐标概念，不建立固定映射。不能只根据躯干在屏幕上向右倾，就直接说人体右臂是举起臂。

双臂版本的上臂阈值是待验证的几何演示设计；它没有被这两份附件验证。后续若以双臂版为最终项目动作，应补采这个版本的正常/错误保持数据。

## 3. 附件一致性审计

来源目录：

- `experiments/detection/outputs/ardhakati_chakrasana_rtmx_correct`
- `experiments/detection/outputs/ardhakati_chakrasana_rtmx_incorrect`

目录名虽写 rtmx，summary 标明实际来源是 `RTMW-x / rtmw_x_384.onnx`。点位为 COCO-WholeBody 133，图像像素坐标。`dwpose133-geometry-v1` 是现有几何公式的版本名，与实际点位模型单独追溯。

| 检查项 | correct | incorrect |
|---|---:|---:|
| CSV / JSONL / summary 帧数 | 2691 / 2691 / 2691 | 2089 / 2089 / 2089 |
| 时间戳范围 | 0–89644 ms | 0–69583 ms |
| 相邻时间差 | 33 / 34 ms | 33 / 34 ms |
| 重复/倒序时间戳 | 0 | 0 |
| 所有特征有效帧数 | 2691 | 2089 |
| 三文件对应统计/数值核对 | 通过 | 通过 |
| 原始节点 SHA256 核对 | 通过 | 通过 |
| 从原始节点逐帧重算8个特征 | 与附件一致 | 与附件一致 |
| 双上臂同时 >150° 帧数 | 0 | 0 |
| 来源视角 | angle_1_unverified | angle_1_unverified |
| 人工保持阶段与错误起止标注 | 无 | 无 |

文件名 correct/incorrect 不是逐帧标签。几何分组包含过渡帧，也不证明已进入稳定保持。详细数据与文件哈希见 `experiments/detection/ardhakati_rule_audit.json`；可用 `audit_ardhakati_rules.py` 重算。

关键哈希：

| 文件 | SHA256 |
|---|---|
| correct features.jsonl | `d334baee9fc8169a526766bd4c267948c0bd8884cb39bce6180048e7735ea19b` |
| incorrect features.jsonl | `e380c40406bc8884847b5d25a32edef8bb5dd4b269bec670212f7d2daefde10a` |
| correct 原始节点 | `7e4d0d9ce18eedcc7909b8d679c22aefd9af4819c6c428388182b0c56b5f2c2f` |
| incorrect 原始节点 | `4c9bbe4f699cd3c1f0756ef55db590989f0f25b3ce27cc79ecc317e0e1a1aba8` |

## 4. 特征含义与侧弯判定的区别

关键点：左右肩5/6、肘7/8、腕9/10、髋11/12、踝15/16。定义肩中心 S、髋中心 H、中心躯干长度 T=||H-S||、投影肩宽 W=||P6-P5||。

| 特征 | 公式或含义 | 侧弯中的用法 |
|---|---|---|
| shoulder_height_diff_px | abs(y5-y6) | 像素观测，不设固定像素纠错阈值 |
| shoulder_height_diff | abs(y5-y6)/T | 肩高差通常随侧弯增大，监测即可 |
| torso_tilt_deg | atan2(S.x-H.x, H.y-S.y) 转为度 | 表示侧屈投影和图像方向，不能将不竖直视为错误 |
| 左右 elbow_angle_deg | 肩-肘与腕-肘两向量夹角 | 判断所要求举起的臂是否存在明显肘部折叠 |
| 左右 arm_torso_angle_deg | 肩→肘与中心躯干向下向量夹角 | 双臂版使用独立草案，单臂版暂时监测 |
| ankle_spacing_shoulder_ratio | abs(x15-x16)/W | 踝横向间距比例，不能证明重量均分 |

肘角0–180°，接近180°表示二维投影接近伸直；上臂角约0°为垂下，约180°为与躯干向下轴相反。上臂角不是肩到腕的整体方向，也不是临床肩关节角度。

torso_tilt_deg 正号是肩中心相对髋中心向**图像右侧**倾，负号为图像左侧。镜像后的屏幕左右与人体解剖左右需要上游统一约定，不能把图像方向直接写成人体左/右侧指令。

## 5. 为什么不直接沿用山式阈值

correct 整段左/右肘最小值约155.71°/158.17°。在图像左侧屈几何组中，正常来源左肘中位数约161.23°，低于山式之前讨论的165°触发值；举起臂相对中心躯干角约139–144°也可能是该来源变体的正常投影。

因此：

- 不能把山式165°肘角阈值直接认定为侧弯标准。
- 不能把山式“肩水平、躯干竖直”的规则用于保持侧屈。
- 双臂版本与单臂来源的上臂角不能混用统计范围。
- 双脚在画面中间距接近某个值，不能推出髋不动、脚掌均匀受力。

部分分组对照：

| 几何组/特征中位数 | correct | incorrect |
|---|---:|---:|
| image-left <-15°，躯干倾角 | -28.60° | -19.30° |
| 同组左肘角 | 161.23° | 143.48° |
| 同组左上臂角 | 143.93° | 160.88° |
| 同组踝距/肩宽 | 0.2191 | 0.2504 |
| image-right >15°，躯干倾角 | 26.10° | 29.93° |
| 同组右肘角 | 168.37° | 169.20° |
| 同组右上臂角 | 138.44° | 137.84° |
| 同组踝距/肩宽 | 0.2172 | 0.2395 |

它们只用于描述差异，不构成训练/验证集。右侧组肘角大量重叠，不能假设每个错误来源片段必定有肘部错误；左侧屈时间较短也不能自动解释为动作幅度或保持不足。

## 6. 十条规则配置

所有规则以 `reviewed=false` 交付。默认禁用纠错，显式 `allow_unreviewed=True` 才允许 candidate 规则用于探索。monitor_only 即使在探索模式也不触发。

| rule_id | 适用条件 | 偏差候选 | 恢复条件 | 状态 |
|---|---|---|---|---|
| left_raised_elbow_bend | 双臂版左肘，或单臂版明确举左臂；举臂/侧弯保持 | 左肘<150° | ≥160° | candidate |
| right_raised_elbow_bend | 同上，右侧 | 右肘<150° | ≥160° | candidate |
| left_upper_arm_alignment_both | 仅双臂版；举臂/侧弯保持 | 左上臂角<150° | ≥160° | candidate，双臂数据尚缺 |
| right_upper_arm_alignment_both | 同上，右侧 | 右上臂角<150° | ≥160° | candidate，双臂数据尚缺 |
| left_upper_arm_single_monitor | 仅单臂版 | 不触发 | 不产生恢复事件 | monitor_only |
| right_upper_arm_single_monitor | 仅单臂版 | 不触发 | 不产生恢复事件 | monitor_only |
| bend_direction_mismatch | 侧弯保持，独立指定预期图像弯向 | 朝相反方向超过5° | 朝预期方向至少5° | candidate |
| lateral_bend_magnitude_monitor | 侧弯保持 | 不判断过浅或过深 | 无 | monitor_only |
| shoulder_height_monitor | 侧弯保持 | 不把肩高差视为错误 | 无 | monitor_only |
| stance_monitor | 侧弯保持 | 只记录踝距比 | 无 | monitor_only |

配置中 monitor 的 reference/trigger/clear 数字是后续审核占位范围，不是已验证的动作判据。disabled 的 monitor 仍保留观测值，不参与候选。

### 6.1 肘角150° / 160°的依据与边界

150°低于本次 correct 全视频两个肘角最小值，是保守的探索触发选择。incorrect 左肘<150°最长持续7265ms，其中与 image-left <-15°几何桶相交的一段持续1633ms，足够测试1500ms确认。160°恢复属于工程滞回设计，不是统计拟合出的教学标准。双臂版采用这些肘角仅作为待验证迁移，不能声称已被单臂数据验证。

| 有效肘角 | 单帧状态 |
|---:|---|
| <150° | deviation |
| 150° ≤ angle <160° | gray_zone |
| 160°–180° | within_reference |
| 负值/>180°/缺失/非有限数 | not_assessable |

恰好150°不会触发，恰好160°可以开始恢复确认。双臂上臂角规则采用同样150°/160°边界，但其数值只是表达“明显偏离所要求上举方向”的工程草案，缺乏双臂样本验证。

### 6.2 方向规则不用绝对值

声明预期 image_right 时 comparison_value=torso_tilt_deg；声明预期 image_left 时 comparison_value=-torso_tilt_deg。

- comparison_value < -5°：明显朝反方向，候选。
- -5° ≤ comparison_value <5°：灰区，不代表侧屈不足。
- comparison_value ≥5°：与预期方向一致，允许恢复计时，不代表幅度达标。

预期方向未知时不可评估。`direction_source` 为 `geometry_preview...` 时也不可评估，因为如果先从本帧倾角推断方向、再用同一倾角判断方向，就永远能“证明正确”。真实接入可以由页面选择的目标侧/独立人工时间段提供预期图像方向。

## 7. 阶段设计

| phase | 对应动作 | 当前行为 |
|---|---|---|
| unknown | 不知道进行到哪一步 | 不启动候选 |
| prepare | 山式准备站姿 | 不启动候选 |
| arms_up_hold | 双臂/单臂已举起的稳定阶段 | 评估适用的肘/双臂上臂规则 |
| transition | 举臂、进入侧弯、放臂或切换过程 | 不启动候选；中断旧事件 |
| side_bend_hold | 明确处于保持侧屈 | 评估侧弯规则 |
| return_upright | 躯干回正过程 | 中断旧事件，不将回正自动当成纠正成功 |
| arms_down_hold | 放臂后的站姿 | 本版侧弯纠错不适用 |

这些是阶段输入约定，不是已经训练好的自动阶段识别器。主函数默认unknown；需要页面、独立识别模块或人工标注提供阶段。

离线 `--preview-geometric-context` 只是调试：abs(tilt)>15°暂映射到 side_bend_hold，正负号映射图像方向；单臂模式中一侧上臂>60°且另一侧<60°暂估计举臂侧。其余映射prepare/transition/unknown。它没有用速度判断保持，不识别动作意图，也可能在丢臂、过渡时误分阶段。所有相关review字段保持false，不能据此计算阶段准确率或验证依赖该上下文的规则。

## 8. 主函数调用

```python
from backend.pose_rules_ardhakati import compare_ardhakati_frame, load_rules
from backend.ardhakati_event_tracker import ArdhakatiEventTracker

rules = load_rules()
tracker = ArdhakatiEventTracker()  # 一轮练习创建一次，不能每帧重建

# feature_frame 来自已有 extract_features_133 或 features.jsonl。
# 下面以页面明确要求“双臂版、向图像右侧保持”为例。
evaluation = compare_ardhakati_frame(
    feature_frame,
    phase="side_bend_hold",
    movement_variant="both_arms_overhead",
    raised_arm_side="unknown",  # 双臂版不指定单侧
    bend_direction="image_right",
    phase_source="ui_selected",
    direction_source="ui_target",
    variant_source="ui_selected",
    camera_view="front",
    source_model="RTMW-x",
    allow_unreviewed=True,      # 当前草案的探索开关
    ruleset=rules,
)
payload = tracker.update(evaluation)
```

如果改为单臂版，应设置 movement_variant=single_arm_overhead，且独立提供 raised_arm_side。不要直接把附件的一行解释成已经符合双臂前提的真实样本。

`phase_reviewed`、`direction_reviewed`、`variant_reviewed`、`raised_arm_reviewed`、`camera_view_verified` 是调用者提供的溯源标记，不是自动审核功能，也不是额外布尔门禁。当前正式质量前提包括camera_view必须显式为front；即使camera_view_verified=false也可进入探索。默认回放保留来源angle_1_unverified，绝不静默替换成front。

全局阻断原因包括 layout/coordinate_space/feature_version/source_model 不匹配、非front、features缺失。每条规则进一步检查阶段、变体、举起侧、独立方向、特征valid、单位、原始score和数值域。缺失/低质量让相应规则不可评估，不填0当正常。NaN/Infinity在保留features中转null，避免持续层被无效测量污染。

## 9. 持续事件与换侧

各candidate规则的时间参数：连续偏差1500ms确认、连续满足clear700ms恢复、相邻更新间隔>500ms中断。等于阈值时按达到处理；计时使用timestamp_ms，不硬编码帧数。

```text
deviation → pending → 连续1500ms → started（一次）→ active
active → clear范围内 → clearing → 连续700ms → recovered
pending遇灰区/正常/不可评估 → 清空待确认
active遇灰区 → 保留事件、取消恢复计时
active遇阶段/方向/举起侧/变体/来源改变或丢证据 → interrupted
```

左侧弯换为右侧弯时不能把前一侧1500ms累计带过去；旧事件必须按旧方向/变体/审核信息中断，新上下文重新计时。阶段变更与规则版本变更分别有phase_changed、rule_version_changed，其余上下文变更为context_changed。

其他行为与山式一致：低分/缺特征/规则消失中断，长帧间隔中断；重复或倒序timestamp被忽略且不改变内部状态；reset清空流，不伪造恢复；视频结束保留未结束事件快照，不自动宣称恢复。独立流使用不同实例，单实例更新需要串行；内存状态不跨HTTP worker或服务器重启保存。

事件中 duration_ms 的语义为episode_elapsed：从连续偏差起点到当前连续证据末尾的经过时间。started之前要求连续偏差；激活后该时长还可能包括灰区与等待恢复时间，不能解释为纯超阈值时间总和。中断时不把缺失间隔计入。

## 10. 单帧结果与给 C 的输出

单帧输出包括：

- schema_version=ardhakati-comparison-v1，exercise=ardhakati_chakrasana；不要求会话/动作ID。
- rule_version、feature_version、source_model。
- phase、movement_variant、raised_arm_side、bend_direction及其来源和review标记。
- camera_view、camera_view_source、camera_view_verified。
- features、rule_results、candidates、assessment_status、assessment_coverage。
- 单帧feedback_allowed始终false；deviations保持空列表，防止混同旧Schema的持续事件。
- unsupported_checks明确当前不能评估的动作要求。

tracker.update再补new_events、pending_events、active_events、ignored/ignored_reason。只有new_events含started时feedback_allowed=true。

assessment_status只是摘要。例如一个肘规则在范围内而预期方向未知时，可能汇总为within_reference，但coverage里方向规则仍是unassessed。coverage.complete也只针对当前阶段/变体的已启用规则，不代表全身合格。单臂举起侧未知时，两条可能适用的肘规则会计入未评估，避免只评方向就声称覆盖完整。

回放自动生成 `agent_events.jsonl`，schema_version=ardhakati-bc-demo-v1，为**待 C 对齐的交接草案**。每行包含一帧新确认的started事件，可同时包含多个目标。保留完整规则证据与探索、机位、方向、变体标记；不生成整体评分、置信度或严重程度。

C应按event_id去重，按event_type/target检索知识，并依据observed_value、单位、trigger/clear、duration等组织文案。同帧多个事件可以合并为一次反馈。不要每帧读candidates或active_events就重复调用LLM。

recovered只能说明某条测量满足恢复条件，不代表整个人体合格；interrupted表示证据终止，不能写成“你已改正”。生命周期历史保留在rule_frames/summary中，agent_events仅导出用于新纠错提示的started。

示例C接收：

```python
import json

seen = set()  # 单次演示内去重；长期保存由C/D按项目约定实现
with open("path/to/agent_events.jsonl") as source:
    for line in source:
        packet = json.loads(line)
        for event in packet["new_events"]:
            if event["status"] != "started" or event["event_id"] in seen:
                continue
            # 此处由C送入知识检索与Agent；保留packet和event的模式/溯源信息。
            print(event["target"], event["observed_value"], event["duration_ms"])
            seen.add(event["event_id"])
```

feedback_allowed表示工程持续条件达成，**不意味着规则或视频已人工认证**。当前exploratory_preview、rules_reviewed=false等标记必须保留。旧AnalysisResult需要的session_id/pose_id/confidence等不应随意补造；接HTTP接口时由B/C/D统一新协议，本次没有更改旧接口。

## 11. 可执行的运行步骤

在项目根目录运行，核心脚本仅用标准库，Python3.10+：

```bash
cd /Users/tzc/Downloads/YogaCoach-LLM-main

# 默认门禁：保持原始未核验视角与未知上下文，不产生纠错
python3 -m experiments.detection.replay_ardhakati_rules \
  experiments/detection/outputs/ardhakati_chakrasana_rtmx_correct \
  --output-dir experiments/detection/outputs/ardhakati_rules_guard/correct

# 附件单臂变体的明确探索运行
# front是本次调用的临时声明，不是程序已核验拍摄角度
python3 -m experiments.detection.replay_ardhakati_rules \
  experiments/detection/outputs/ardhakati_chakrasana_rtmx_incorrect \
  --output-dir experiments/detection/outputs/ardhakati_rules_preview/incorrect \
  --allow-unreviewed --preview-geometric-context \
  --movement-variant single_arm_overhead --camera-view front
```

替换correct/incorrect后可运行另一个来源。输出：

| 文件 | 内容 |
|---|---|
| rule_frames.jsonl | 逐帧规则与持续状态，原features仍在来源文件，避免重复保存 |
| rule_summary.json | 来源、模式、视角、计数、全部生命周期、结尾开放事件 |
| agent_events.jsonl | 可交给C的started批次；没有started时为空文件 |

实际回放：

| 项目 | correct | incorrect |
|---|---:|---:|
| 帧数 | 2691 | 2089 |
| 默认门禁started | 0 | 0 |
| 显式单臂探索candidate_deviation帧数 | 0 | 74 |
| 单臂探索started | 0 | 1 |
| 单臂探索recovered | 0 | 0 |
| 单臂探索interrupted | 0 | 1 |
| 交给C的数据包 | 0 | 1 |

incorrect的左肘事件从59185ms开始连续命中，60685ms确认（角度143.403°，duration1500ms）；60851ms检测到阶段变化而中断，最后证据60818ms，episode duration1633ms。它不是一条自动证明的教学错误，只是当前几何阶段和参数下的工程证据。两份数据不能报告双臂版准确率。

### 11.1 人工阶段标注优先于几何预览

使用 `experiments/detection/ardhakati_segments.example.json`，填入features的实际SHA256与经视频确认的半开时间段[start_ms,end_ms)。每段明确phase、movement_variant、bend_direction、raised_arm_side，区间排序且不可重叠。模板不预填任何保持段。

格式示意（数值需由审核者填写；这不是附件真实标注）：

```text
source_features_sha256: 对应features.jsonl的SHA256
reviewed: 人工确认是否完成
segments:
  start_ms / end_ms
  phase: side_bend_hold
  movement_variant: both_arms_overhead 或 single_arm_overhead
  bend_direction: image_left / image_right / unknown
  raised_arm_side: left / right / unknown（双臂用unknown）
```

```bash
python3 -m experiments.detection.replay_ardhakati_rules \
  experiments/detection/outputs/ardhakati_chakrasana_rtmx_incorrect \
  --output-dir experiments/detection/outputs/ardhakati_rules_manual/incorrect \
  --segments path/to/reviewed_segments.json \
  --allow-unreviewed --camera-view front
```

segments模式不要再传--movement-variant（变体在每段里指定），也不能同时开geometry preview。规则草案尚未审核，因此即使阶段已审核仍需allow-unreviewed。未标注区间默认unknown，不强行补成保持阶段。

如果使用新采集的双臂数据，在阶段文件里写both_arms_overhead即可运行双臂规则；没有独立人工阶段时也能显式用双臂geometry preview调试，但不要在现有单臂附件上强制套双臂版后把命中当作错误率。

## 12. 当前无法从8个特征证明的要求

| 用户动作要求 | 当前缺口 | 后续可考虑的输入 |
|---|---|---|
| 髋中正、保持不动 | 无髋相对脚踝/起始站姿的平移与时间基线 | 骨盆中心相对踝中心轨迹、基线校准 |
| 肩下沉 | 肩高差不能代表耸肩/下沉 | 肩-耳相对距离、躯干/头颈坐标与角度控制 |
| 双手合掌 | 没有腕间/掌间距离特征 | 手腕/手部点相对距离与可见性 |
| 头中正、目视前方 | 当前8特征不含头颈/面朝向 | 头颈轴、脸部朝向；视线仍有额外限制 |
| 身体在一个平面 | 2D正面投影不能验证3D前后偏移/旋转 | 多视角/深度及明确可观察性约定 |
| 双脚掌均匀承重 | 几何脚距不是受力测量 | 压力/力传感，不能仅凭姿态给出结论 |
| 两侧伸展感 | 几何不能测量主观牵伸感 | 用户反馈与教练审核 |

这些项目在unsupported_checks中显式列出。没有为了文档完整而生成无法观测的“已通过”结果。

## 13. 验证、维护与后续工作

测试覆盖单帧区间边界、灰区、变体与举臂侧、独立方向、视角、质量与缺失、覆盖信息、持续确认、恢复/中断、换侧、乱序/重复、reset、来源变更、阶段文件及Agent交接。共享持续引擎的山式测试也参与回归。

```bash
python -m pytest \
  tests/test_pose_rules_ardhakati.py \
  tests/test_ardhakati_event_tracker.py \
  tests/test_ardhakati_rules_integration.py \
  tests/test_tadasana_event_tracker.py -q
```

项目已有山式配置目前是tadasana_rules_B.json，而旧山式比较器/测试默认读取tadasana_rules.json；本任务开始前旧全量测试已因缺失默认路径失败。本次保持用户山式规则内容不变，不以侧弯验证通过代替旧全量测试通过。

本次四个核心测试文件合计83 passed、141 subtests passed；扩展运行其余测试（排除上述两个依赖缺失山式配置的测试文件）为119 passed、168 subtests passed。包括旧API、特征计算及山式持续引擎回归。真实两组文件的默认门禁和单臂探索回放均已执行；双臂规则链路由明确标记的合成输入测试覆盖。

后续优先工作：确认最终采用双臂还是单臂版本并补采匹配的数据；人工审核视角、左右/镜像和保持时间段；按人/完整视频划分开发与独立验证，补齐每条错误类型标注；评估误触发/分钟、事件召回和确认延迟，之后再调阈值。reviewed变true时必须填写review_record并更新规则version；审核标记不由程序替代。

文件职责：

| 文件 | 职责 |
|---|---|
| backend/pose_rules_ardhakati.py | 单帧规则比较、配置校验 |
| backend/ardhakati_event_tracker.py | 侧弯上下文、阶段与事件前缀，复用持续引擎 |
| backend/tadasana_event_tracker.py | 共享连续性引擎，保留山式默认行为 |
| knowledge/ardhakati_chakrasana_rules.json | 十条可机读规则草案 |
| knowledge/ardhakati_chakrasana_rules.md | 本说明 |
| experiments/detection/audit_ardhakati_rules.py | 三文件与原始点位一致性、统计、连续段审计 |
| experiments/detection/ardhakati_rule_audit.json | 本次审计结果与哈希 |
| experiments/detection/build_ardhakati_rules.py | 从保存的审计重建草案JSON；会覆盖JSON，手调后先保存版本 |
| experiments/detection/replay_ardhakati_rules.py | 离线回放、追踪、汇总、B→C文件 |
| experiments/detection/ardhakati_segments.example.json | 人工阶段标注模板 |

调整区间和持续时间优先改JSON并更新version；增加新测量须先扩展特征计算与单位/版本，再加规则，不能仅在JSON里写上游并未提供的字段。
