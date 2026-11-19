# 本地模型资源（A/E 对接）

需要放置 `pose_landmarker_lite.task` 与 `wasm/` 目录。模型文件由 A 提供并确认版本及许可。
安装 npm 依赖后执行 `node scripts/copy-wasm.mjs`，从本地安装的 MediaPipe 包复制匹配的 WASM 文件。
默认不请求外部 CDN。资源缺失时摄像头模式显示错误；模拟模式不需要模型。
可在 frontend/.env 中修改 VITE_POSE_MODEL 与 VITE_POSE_WASM。

## 下载固定版本

在仓库根目录运行 `python scripts/download_pose_model.py`，下载 Google 官方 Lite float16 **版本 1**，校验 ZIP 模型包并原子写入目标路径，输出 SHA256。若已有团队确认的散列，可传 `--sha256 <散列>` 强制校验。二进制文件不提交 Git。

来源：[Google 官方样例](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/web/vision/README.md)、[模型任务说明](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker)。模型使用与分发条件仍需团队核对来源条款，不将代码仓库许可自动视为权重许可。

本轮尝试下载时 Google 存储端 TLS 连接失败，未得到模型文件，未完成设备摄像头实测。脚本可在可访问该地址的网络运行；不要用空文件替代模型。
