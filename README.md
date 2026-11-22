# YogaCoach-LLM

主方案：**COCO-WholeBody 133 点**。支持前端选择本地视频或摄像头，抽取 JPEG 图像帧发送到本机 Python 后端，由本地 RTMW 模型推理，计算肩、躯干、肘、上臂和站距特征，再交给反馈工作流。

## 运行

Python >=3.10、Node.js >=20。仓库根目录：

```powershell
python -m venv .venv
\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

macOS/Linux 激活方式：

```sh
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

另一个终端：

```sh
cd frontend
npm ci
npm run dev
```

打开 http://127.0.0.1:5173。选择“133 点：摄像头 / 上传视频”，选择图像来源、阶段和侧别，开始练习。视频模式在开始后选取本地文件；视频由浏览器解码，上传的是抽样图像帧，不是整个原视频文件。摄像头模式也上传图像帧，图像不发送给 LLM。

默认模型：`data/models/rtmw_x_384.onnx`，本地已有。其他环境请放置团队相同权重，或配置根目录 `.env` 中的 `POSE133_MODEL_PATH`。不需要前端 MediaPipe 模型。仅支持正面、单人、全身入镜；当前采用与参考数据一致的全图 ROI，没有多人检测器。

如果 `/api/pose/frame` 返回 503，请查看启动后端的终端日志。`rtmlib`、`onnxruntime` 缺失或模型初始化失败时，日志会记录具体异常；请确认安装依赖和启动 Uvicorn 使用的是同一个 Python 环境。Windows 可用 `\.venv\Scripts\python.exe -m pip show rtmlib onnxruntime` 检查。

## 当前能力与限制

- `/api/pose/frame`：JPEG → RTMW → 133 点、原始 scores 和结构化测量。
- `/api/analyze`：接受 133 点像素坐标和原始 scores；保留旧 33 点输入兼容，但前端主链路不再使用它。
- `/api/agent/feedback`：LangGraph 证据核验、知识/记忆读取、镜头提示和冷却。对服务端规则确认的动作偏差，chat-completions 兼容 LLM 可基于最小测量摘要生成结构化建议；目标/事件不匹配或生成失败时回退模板。镜头提示仍只选择受控模板。LLM 输入不含图像、原始关键点、会话 ID 或历史记录。
- `/api/memory`：SQLite 会话、总结、历史、偏好；真实模式创建和结束会话，模拟历史单独保存在浏览器。
- 原始模型 scores 不是 visibility，也不是概率，可以超过 1；133 点像素坐标不做二次宽高缩放。
- 133 点离线规则和事件跟踪已存在，正式在线规则/阶段与阈值审核仍待完成，当前测量不声称动作正确或错误。

本机已经用已有参考图完成真实 RTMW 推理，并验证图像 API → 分析 → 反馈 → 会话结束。尚未完成浏览器实际摄像头/视频交互验收、持续帧率测试或真实教学效果评估。

## 测试

```sh
.venv/bin/python -m pytest -q
cd frontend
npm test
npm run build
```

当前使用单个 Uvicorn worker，分析证据和反馈冷却为进程内状态。多实例需要共享存储。LLM 配置仅放后端 `.env`，不要放入前端。

更多说明：[133 点链路](docs/133点视频与摄像头链路.md)、[特征定义](docs/detection_rules_133.md)、[架构](docs/architecture.md)。README-v1、README-D、README-E 保留历史交付说明，不代表当前主链路。

## 在线纠错更新

已启用**山式双臂举起保持阶段的持续肘部偏差提醒**，使用已有已审核规则，连续确认后才提醒，同一事件去重并保存 SQLite。练习过程中可切换阶段；准备/过渡/自然下垂不做当前山式纠错。侧弯规则仍未审核，保持测量模式。

上文“尚未接入正式在线规则”的说明由本节更新。使用步骤、规则范围和验证边界见 [正式纠错实现与验收](docs/正式纠错实现与验收.md)。
