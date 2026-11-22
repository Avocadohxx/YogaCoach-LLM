# 检测规则说明

> 范围：本文保留旧 33 点兼容测量说明。当前前端使用 133 点，在线入口与审核范围以 README、rules_manifest.json 和 docs/正式纠错实现与验收.md 为准。

> 负责人：B

## Day 1 已实现：测量，不作动作结论

输入 `PoseFrame`，接口 `POST /api/analyze`。人体关键点的左右按 MediaPipe 索引；图像x向右、y向下。先用实际推理输入W/H将坐标转为像素；不使用Canvas显示尺寸，不混入图像z。

肩中心S=(p11+p12)/2，髋中心H=(p23+p24)/2，尺度s=||S-H||。

| 特征 | 公式与单位 | 所需点 |
|---|---|---|
| shoulder_height_diff | abs(y11-y12)/s，无量纲 | 11,12,23,24 |
| torso_tilt_deg | degrees(atan2(Sx-Hx, Hy-Sy))，图像带符号角 | 11,12,23,24 |
| left_elbow_angle_deg | 肩11—肘13—腕15的二维夹角，度 | 11,13,15 |
| right_elbow_angle_deg | 肩12—肘14—腕16的二维夹角，度 | 12,14,16 |

躯干正号指画面右，不表示解剖右；侧弯仅返回观察值，不套用山式直立规则。左右肘都先测量，不推断哪只臂应抬起，待参考动作变体确认后再定规则。

## 质量门禁

- 每个特征单独检查所需点，可见度初始门限0.75仅为待校准开发值。
- 所需点出框时停用对应特征；未参与特征的点不影响其测量。
- 线段/躯干<=1像素作为退化数值保护，不是经过验证的距离或安全标准。
- 首版只处理声明front的站立场景；其他视角不测量。没有自动验证镜头角度、全身是否完整入镜或是否多人，不能把请求中的front作为已经验证的事实。
- prepare阶段可显示有效测量，但assessment_status=not_assessable；只在hold且至少一个特征有效时返回uncalibrated。
- good/partial/poor表示追踪质量。任何质量等级都不代表动作对错。

## 当前与后续边界

当前无真实参考、无持续状态机、无正式偏差规则；所有真实请求 feedback_allowed=false、deviations=[]。不可评估不等于无差异，有效测量不等于within_reference。

合成Mock中的0.10参考上界、1800ms和confidence属于联调设定，不是统计结果。后续参考由A/B共用本模块函数提取，使用独立校准/测试视频；同一原片不能按相邻帧随机拆分。

下一阶段：按会话处理持续事件、断流/乱序/恢复、动作与侧别切换；C另外负责发言去重/冷却。A的数据到位后确认动作变体、保持阶段、参考范围和人工标签，再启用检测。整段Right/Wrong不能直接作为肩部或肘部的具体偏差标签。

开发与验证步骤见 `experiments/detection/DAY1.md`。

## 2026-11-18：新增DWPose 133点离线特征模块

A新增的`keypoints_133.jsonl`采用COCO-WholeBody133、原图像素和原始scores，不能输入上述33点MediaPipe接口。新增`backend/pose_features_133.py`独立计算肩高差、躯干角、左右肘角、左右上臂—躯干夹角、脚踝横距/二维肩宽。具体公式、运行命令及实际测量统计见`docs/detection_rules_133.md`。当前 /api/analyze 已兼容 133 点测量，正式图像纠错走 /api/pose/frame；33 点算法仅保留兼容。
