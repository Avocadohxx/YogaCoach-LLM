# YogaCoach-LLM

基于 **RTMW / COCO-WholeBody 133 点**的本机单人瑜伽观察工具。摄像头与本地视频由浏览器解码为 JPEG 帧，发送到本机后端提取关键点；图像不会发送给 LLM。

## 当前能力

- 语音陪练：开始练习后点击“开启语音”。每条中文口令以“教练”开头：准备、开始举臂保持、双臂放下保持、切换动作、开始侧弯保持、结束练习。侧弯口令仅在侧弯动作下接受，不绕过规则审核。
- 有效建议通过扬声器或耳机播报；播报期间暂停识别，结束后恢复。阶段或证据变化取消旧播报；结束练习关闭语音。保留手动阶段选择、文字提示和立即停止播报按钮。
- 不保存录音，但浏览器识别服务可能向外部服务发送音频，不能保证离线使用。需要支持 SpeechRecognition/webkitSpeechRecognition 的浏览器与中文语音。权限拒绝或不支持时可继续手动操作。自动化测试使用模拟语音引擎，实际麦克风、中文识别和播放仍需在目标电脑核验。

- 山式：仅在明确选择“举臂保持”且画面与阶段基本一致时，对已审核配置中的持续肘部偏差提醒。
- 侧弯：课程演示纠错已启用，在线读取 `ardhakati_chakrasana_rules_B.json`。支持单臂/双臂版持续肘部偏差、双臂版上臂对齐及所选画面方向不符；肩高差、侧屈幅度、脚距仍只监测。此启用是用户授权的工程演示，不代表专业教学审核或阈值验证。
- 连续性：仅分析新解码帧，视频按媒体时间计时；暂停、跳转、缓冲、来源变化会中断证据。
- 指导：服务器核验事件后返回受控提示；确认的持续偏差可交给可选 LLM，按最小数值摘要生成结构化建议，目标校验失败或服务不可用时回退到安全模板。LLM 不接收图像、原始关键点、会话 ID 或历史记录。历史中可信的同类规则事件可影响关注重点，不引用任意手写摘要作为测量事实。
- 记忆：保存确认事件和反馈，提供总结、偏好、事件回看和删除确认。异常离开通过心跳超时标为中断，不虚构正常结束或改善。
- 练习总结：结合已确认偏差和本次实际显示的反馈，归纳纠错、镜头/观察提示及其出现次数；旧总结不会自动重算。
- 训练回顾：可信偏差出现时在本地保存错误截图；从历史详情查看训练事件、建议和截图，数据随训练记录一起删除。详见 [训练历史截图与详情](docs/training_history.md)。

C 的实时建议流程、本轮采样门限调整、LLM 输入边界和本地验收步骤见 [README-C.md](README-C.md)。

### 站立侧弯式纠错操作

1. 选择“站立侧弯式”，按实际动作选择双臂或单臂（单臂需选择举起侧）。
2. 先选择“准备中”，开始摄像头/视频；稳定后选择“举臂保持”或“侧弯保持”。侧弯保持需指定**画面**左/右目标方向，不等于人体解剖左右。
3. 肘角低于150°连续1500ms后确认，恢复到至少160°连续700ms清除；双臂版上臂角沿用此演示边界。非举起臂、不适用变体或阶段不阻断当前适用规则。
4. 新确认事件进入Agent：LLM返回结构化建议，调用失败/校验失败时使用模板。同一事件不重复提醒，纠错有10秒冷却。回正/换侧/放臂时先切到“动作切换中”。

准备、过渡、未知变体、缺少必要方向/举起侧或低质量测量不产生纠错。独立旧草案 `ardhakati_chakrasana_rules.json` 保持未启用，仍可用于离线复现实验。

## 环境与启动

已验证环境为 Python 3.12；Node.js 20/22/24+（CI 使用 22）。Python 运行、测试及间接依赖统一在 requirements.txt 中固定版本；前端使用锁文件。

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

已有 `.env` 时保留原配置，尤其不要直接覆盖数据库路径。默认数据库与示例统一为 `data/yogacoach.db`；环境变量仍可覆盖，启动日志会打印实际路径，不自动搬移已有历史。

模型通过 Git LFS 获取：

```sh
git lfs install
git lfs pull
python -m scripts.download_pose_model
```

脚本核对本项目记录的 RTMW SHA256，不会用其他模型静默替换。模型加载还可单独检查：

```sh
python -m scripts.check_model --image data/reference/tadasana_rtmw_original_correct_full/comparison_frame_2067ms.jpg
```

启动后端：

```sh
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

另一个终端：

```sh
cd frontend
npm ci
npm run dev
```

访问 http://127.0.0.1:5173。先选择真实模式和图像来源，再开始；练习阶段可随时调整。模型未就绪时不会创建新的真实练习。

## 构建后同源运行

```sh
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

后端在启动时发现 frontend/dist 后托管构建产物，访问 http://127.0.0.1:8000。构建后需重新启动后端；此方案同源，不需要增加 CORS。不要将开发服务器当作正式托管方案。

## 检查与测试

```sh
python -m pytest -q
python -m scripts.check_sources
cd frontend
npm test
npm run build
```

CI 已配置快速测试和构建，不下载大型 LFS 权重；真实模型检查另行执行。`/api/health` 表示进程存活，`/api/ready` 显示模型、规则、数据库和可选 LLM 状态；前端保留联调桩标识。

## 性能与效果评估

浏览器可导出本次采样性能 JSON；本地模型与 API 基准：

```sh
python -m scripts.benchmark_pipeline --image data/reference/tadasana_rtmw_original_correct_full/comparison_frame_2067ms.jpg --frames 20
```

基准是准备阶段的重复图像吞吐测量，不是浏览器真实帧率、动作持续性或检测准确率。真实效果评估须先收集输出和人工标注，再运行 experiments/evaluate.py；24 个合成场景不能当作真实视频准确率。

## 运行边界

当前仅适用于 **127.0.0.1、单人、正面、单 worker**。没有账号鉴权，勿直接开放公网。推理有全服务并发上限，过期图像不参与纠错；多人部署需身份、所有权与共享状态设计。原始事件/反馈导入默认禁用，YOGACOACH_ALLOW_TEST_WRITES 仅用于隔离测试，真实服务不要开启。

RTMW 模型 scores 不是概率或 MediaPipe visibility，可以超过 1。当前规则与测试不证明医疗安全、整体姿态标准或教学效果。

参见 [133 点链路](docs/133点视频与摄像头链路.md)、[纠错与验收](docs/正式纠错实现与验收.md)、[改进实施记录](docs/改进实施记录.md)、[特征定义](docs/detection_rules_133.md)。
