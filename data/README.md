# A：数据与提取

已选择 Yoga for All，历史记录中的入口为 https://data.mendeley.com/datasets/jc4mmnvcdk/1 。本次未下载或核验数据集许可；实际使用前记录版本、许可、作者及视频选择依据。本地数据已找到：项目上一级 `Yoga Postures Dataset/`，包含 80 段 MP4 和 11,344 张 JPG。目标动作 16 段视频见 `video_manifest.json`。正确示范在第 8 秒抽帧确认 Angle 1 正面、2/4 侧面、3 背面；错误示范仍需单独核验。已完成山式 Angle 1 第 6–10 秒试跑：119/119 帧通过质量过滤，结果位于 `reference/tadasana_front_trial/`。时间戳相对裁剪片段，原视频偏移 6000 ms 记录在 selection.json；候选参考仍需人工复核。

准备一段完整入镜、正面、稳定保持的正确动作视频（优先山式），放入 `data/raw_videos/`。先人工裁剪出保持区间。准备 MediaPipe 官方 Pose Landmarker 的本地 `.task` 模型。使用项目虚拟环境安装 requirements.txt 的依赖，然后从项目根目录运行：

```sh
python scripts/extract_reference.py \
  --video data/raw_videos/tadasana_front.mp4 \
  --pose tadasana \
  --model data/models/pose_landmarker_lite.task \
  --output data/reference/tadasana_run1
```

脚本使用 MediaPipe Tasks VIDEO API。输出有效帧 JSONL、候选参考 JSON 和首个有效帧骨架 JPG。输出目录须使用新的运行目录，避免覆盖已有结果。零有效帧时不生成参考，并返回失败。处理中断时可能保留部分 JSONL，不应作为成功结果交付。

人工核验骨架、动作及视角后，将参考 JSON 提供给 B；逐帧 JSONL 每行均遵循 A→B 契约。候选参考的 metadata 是提取信息，不是 B 已冻结的特征接口。当前 mock 仍为占位，不用模拟点冒充真实提取结果。

选用视频清单（待真实数据补齐）：

| 动作 | 本地文件 | 数据集版本/许可 | 保持区间 | 人工核验 |
|---|---|---|---|---|
| tadasana | 待提供 | 待核验 | 待标注 | 未完成 |
| ardhakati_chakrasana | 待提供 | 待核验 | 左右分别标注 | 未完成 |

## 人工复核素材

`scripts/render_pose_review.py` 使用已有 JSONL 绘图，不重新推理。必须传入提取时使用的同一段视频（完整源视频不能直接替代裁剪片段）：

```sh
python scripts/render_pose_review.py --video /tmp/yoga-preview/tadasana_hold.mp4 \
  --frames data/reference/tadasana_front_trial/tadasana_frames.jsonl \
  --reference data/reference/tadasana_front_trial/tadasana_reference.json \
  --output data/reference/tadasana_front_trial/review
```

当前试跑已生成 `review/skeleton_review.mp4` 和 `review/reference_frame.jpg`。绿色线为骨架，黄色点及红色编号为身体关键点；未通过提取过滤的帧显示 REJECTED，不沿用上一帧骨架。REFERENCE 标记候选参考对应帧。时间仍相对片段，原视频位置加 6 秒。

依次检查完整片段的动作稳定性、关节定位和参考帧；审核人、日期、结论与问题记录在 selection.json 中，未审核前保留 requires_manual_review。临时目录中的裁剪视频不保证长期保留，重跑前请准备相同片段。

## RTMPose 架构对比实验

`reference/tadasana_dwpose_trial/`：同一山式 6–10 秒片段，DWPose-L（RTMPose 架构，384×288 输入），119 帧。使用 COCO-WholeBody 133 点，固定全图单人 ROI，未使用人体检测器。`keypoints_133.jsonl` 坐标为原图像素，scores 不是 MediaPipe visibility，无 z，不能直接替换 A→B 33 点接口。

实验依赖单独安装：`pip install rtmlib onnxruntime`。模型来源：https://github.com/Tau-J/rtmlib ，对应 ONNX 权重为 `rtmpose-l_simcc-ucoco_dw-ucoco_270e-384x288-2438fd99_20230728.zip`，解压后运行：

```sh
python scripts/compare_rtmpose.py --video /tmp/yoga-preview/tadasana_hold.mp4 \
  --model data/models/dwpose_l_384.onnx --output data/reference/tadasana_dwpose_new
```

输出叠加视频、逐帧原始结果、片段 2067 ms 截图及实验元数据。对比截图与 Lite/Heavy 同时刻一致。未经人工标注量化误差，不能由置信分数或截图直接宣称模型整体更准。

## Heavy + Hand Landmarker 实验

运行 `scripts/compare_pose_hands.py`，输入与 Heavy 提取完全一致的视频和 Heavy JSONL，独立推理双手。绿色保留原 Pose 骨架及粗略手部点，粉色为 Hand Landmarker，黄色为手部点。身体 33 点不覆盖、不修改。手部检测为空时保留空列表，不从 Pose 或前帧补点。

```sh
python scripts/compare_pose_hands.py --video /tmp/yoga-preview/tadasana_hold.mp4 \
  --pose-frames data/reference/tadasana_front_heavy/tadasana_frames.jsonl \
  --model data/models/hand_landmarker.task \
  --output data/reference/tadasana_heavy_hands_trial
```

手部结果单独存为 hands.jsonl：每只手 21 点，无 visibility；handedness_score 只代表左右手分类分数，不代表定位精度。handedness 保留原始模型分类，未审核人体左右归属。手部 z 以该手腕为原点，不与 Pose 的 z 混用。视频与截图仅供复核，不能将不同模型点位混合后当作原始 MediaPipe 33 点。

Heavy + Hand 实测：119 帧中，76 帧未检出手、9 帧检出一只、34 帧检出两只；未检出不等于没有手，表明当前输入条件下检测不稳定。保留结果供对比，不作为正式手部参考。模型为 hand_landmarker_clean.task，结果位于 reference/tadasana_heavy_hands_trial/。

## 山式完整正面交付（Heavy）

`reference/tadasana_front_correct_full/` 与 `reference/tadasana_front_incorrect_full/` 对应数据集 Right / Wrong Steps Angle 1 的整段原视频。时间戳从原视频 0 ms 开始，无裁剪偏移。

- `tadasana_frames.jsonl`：满足质量过滤的 A→B 33 点输入，时间戳可能有间隔。
- `all_frames.jsonl`：每个解码帧一条，包含被过滤的原始点和 quality_status；未检测到人体时 landmarks=null。此文件是审核记录，不能不经筛选直接送 B。
- `selection.json`：来源、视频级标签、统计与待补的阶段标注。
- `review/skeleton_review.mp4`：完整时序复核视频，无有效点的帧显示 REJECTED。
- `tadasana_reference.json`：脚本自动生成的全片代表帧，不是已审核的正确姿态；尤其错误示范的该文件不能作为正确参考。

本包可供 B 联调连续输入；未标注具体错误种类、阶段与时间区间，不能用于声称检测准确率。Right/Wrong 是源视频标签，不代表其中每一帧正确/错误。手腕与手部仍有模型定位误差。正式正确参考继续从人工核验的保持片段独立选择。

### 全片复核画面修正

`review_quality/skeleton_review.mp4` 使用 `--all-frames all_frames.jsonl`，在被整体过滤但仍有检测点的帧上，继续显示 visibility>=0.6 的局部骨架，并标记 REJECTED QUALITY。低置信关节不绘制；此叠加图用于定位过滤原因，不代表该帧可作为完整可靠输入。旧版 review 视频显示 no landmarks 实际可能只是未进入有效帧集合，提示容易误解，以新版为准。有效帧 JSONL 与阈值保持不变。
