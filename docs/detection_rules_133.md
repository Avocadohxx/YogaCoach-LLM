# B：DWPose / COCO-WholeBody 133 点的位置特征计算

日期：2026-11-18。对应 `backend/pose_features_133.py`，版本 `dwpose133-geometry-v1`。

## 1. 本次输入与原接口的区别

实际读取 `data/reference/tadasana_dwpose_correct_full/keypoints_133.jsonl`：2127帧，时间0～70849ms，单帧字段为timestamp_ms、keypoints[133][2]、scores[133]。

同目录metadata确认：COCO-WholeBody 133，原图像素，DWPose模型原始scores，固定全图单人ROI，无检测器。selection标明源文件名correct，但并非逐帧真值，尚无选定的保持区间，需人工审核。

因此不把它伪装成MediaPipe33点：不补z、不把scores改名为visibility、不二次乘图像宽高；原`schemas.py`、`pose_analyzer.py`和`/api/analyze`保持原33点接口。新增模块供离线分析或后续独立适配调用。

scores实测可超过1（本文件最大约1.07585），保留原值；不是[0,1]概率，也不是可见性。暂用min_score=0.5作可配置工程筛选，未证明适合全部人或动作，不沿用MediaPipe的0.75。

## 2. 0起始关键点编号

| 部位 | 左 | 右 |
|---|---:|---:|
| 肩 | 5 | 6 |
| 肘 | 7 | 8 |
| 腕 | 9 | 10 |
| 髋 | 11 | 12 |
| 踝 | 15 | 16 |

左右沿用模型的解剖侧标签，不根据屏幕左右重新命名。顺序核对来源：[MMPose COCO-WholeBody定义](https://github.com/open-mmlab/mmpose/blob/main/configs/_base_/datasets/coco_wholebody.py)。图像x向右、y向下。模型输入数据本身不证明左右归属或机位已正确。

## 3. 计算定义

设L/R表示左右，p_i是原图像素二维点。S=(p5+p6)/2，H=(p11+p12)/2，躯干向下向量t=H-S，躯干尺度s=||t||。

### 双肩高度差：两种表示

- `shoulder_height_diff_px = abs(y5-y6)`，单位像素，仅依赖5/6。
- `shoulder_height_diff = abs(y5-y6)/s`，单位torso_ratio，依赖5/6/11/12。保留与旧代码相同的归一化数学定义，但不能跨模型直接共用阈值。

绝对值不表示哪边更高；本次没有生成左右纠正建议。

### 身体倾斜角

`torso_tilt_deg = degrees(atan2(Sx-Hx, Hy-Sy))`。

0度表示躯干轴沿图像竖直方向；正号朝图像右，负号朝图像左。不取绝对值，用户如只关心幅度可读abs(value)。这是肩髋中心轴的二维角度，不是脊柱曲率，也不是健康/安全结论。

### 左右肘角

`angle(u,v)=degrees(arccos(clip(dot(u/||u||,v/||v||),-1,1)))`。

- 左：u=p5-p7，v=p9-p7。
- 右：u=p6-p8，v=p10-p8。

输出`left_elbow_angle_deg/right_elbow_angle_deg`，范围0～180度；180度表示投影接近伸直。不能只根据单一肘角断言动作正确。

### 双臂相对躯干夹角

- 左：`angle(p7-p5, H-S)`。
- 右：`angle(p8-p6, H-S)`。

输出`left_arm_torso_angle_deg/right_arm_torso_angle_deg`。采用“上臂方向”与“中央躯干向下方向”的夹角：顺着躯干下垂约0度、垂直躯干约90度、反向上举约180度。

这是对先前“肩到髋中心”口头提案的进一步明确：两个手臂共用H-S作为躯干轴，避免横向肩位使直立下垂出现额外几何偏置；公式有单独版本，需同步A/C。它不是临床肩关节角。前臂弯曲由肘角另行描述，因此无需手腕参与此特征。

### 双脚横向间距 / 肩宽

`ankle_spacing_shoulder_ratio = abs(x15-x16) / ||p5-p6||`。

本次用脚踝作左右脚位置代理，不是脚外缘间距，也不是脚趾间距。分子是图像横向距离；分母是二维欧氏肩宽sqrt((x5-x6)^2+(y5-y6)^2)，而非躯干长度。结果0.6表示脚踝横向距离相当于图像肩宽的0.6倍。

若团队想用“横向肩距”作分母，应另设特征版本，不能悄悄替换当前定义。身体侧转会让投影肩宽变化，侧弯/机位也会影响结果；目前没有自动验证视角。

## 4. 有效性与输出

每项特征只检查自身需要的点。腕低分只停用对应肘角，不停用无需腕的上臂夹角。无效时value=null、valid=false、reason提供原因；CSV用空白，不写0。

- `low_keypoint_score`：所需点原始score低于所选工程门限。
- `invalid_keypoint_coordinate/invalid_keypoint_score`：空值、非有限或无效值。
- `degenerate_torso/arm/arm_or_torso/shoulder_width`：参与运算的向量太短等数值退化。

1像素是退化保护，不是人体尺寸/安全标准；分数通过不意味着定位准确。输入没有图像宽高，程序不推断出框范围；摘要中明确未执行图像边界和视角验证。

结果标记measurements_only、reference_status=not_loaded、feedback_allowed=false。不作动作识别、保持阶段识别、参考比较、持续事件、诊断或纠正。

## 5. 如何运行

在仓库根目录运行，以下提取只需Python标准库，不需下载模型或安装NumPy。

```bash
python3 -m experiments.detection.extract_features_133 \
  data/reference/tadasana_dwpose_correct_full/keypoints_133.jsonl \
  --output-dir experiments/detection/outputs/tadasana_dwpose_correct_full \
  --min-score 0.5
```

输出：
- features.csv：逐帧值、每项valid/reason/min_score，便于Excel查看。
- features.jsonl：完整结构化逐帧结果，保持输入行顺序和原始时间戳。
- summary.json：有效数量、缺失原因、均值/中位数/范围/分位数、输入SHA256、来源元数据和限制。

生成文件放在B目录，不修改A的数据。结构不合规的行会给出行号并停止，不发布半份新结果；单点数值无效仅使相关特征无效。空白行不算帧。非递增时间记录在摘要，本次无时序计算。

函数调用：

```python
import json
from backend.pose_features_133 import extract_features_133

with open("data/reference/tadasana_dwpose_correct_full/keypoints_133.jsonl") as f:
    raw_frame = json.loads(next(f))
result = extract_features_133(raw_frame, min_score=0.5)
print(result["features"]["left_arm_torso_angle_deg"])
```

## 6. 本文件实际执行结果

min_score=0.5，2127帧全部读取：1906帧全部特征可计算，202帧部分可计算，19帧全部不可计算。这只是数值/分数门禁，不是动作正确率。

| 特征 | 有效帧 | 全片有效值中位数 |
|---|---:|---:|
| 双肩高差（像素） | 2105 | 4.1667 px |
| 双肩高差/躯干尺度 | 2105 | 0.0156 |
| 躯干倾角 | 2105 | -0.6296° |
| 左肘角 | 2081 | 159.9998° |
| 右肘角 | 1912 | 161.1402° |
| 左上臂/躯干夹角 | 2101 | 52.3524° |
| 右上臂/躯干夹角 | 2082 | 70.4582° |
| 脚踝横距/二维肩宽 | 2105 | 0.3428 |

以上涵盖全视频，不是已审核保持区间，不能直接转成参考规则或声称该数值代表标准。尤其手臂动作随时间变化，均值/分位数混合了不同阶段。

测试：新增17项测试覆盖已知0/90/180/45度、分母定义、原始分数>1、平移/缩放/镜像、局部低分、退化、错误结构、CSV空值和完整输出。与Day1共36项测试及27个子项通过；仍需真人视频人工核验关键点和具体动作阶段。
