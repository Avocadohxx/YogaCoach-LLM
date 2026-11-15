# 本地模型资源（A/E 对接）

需要放置 `pose_landmarker_lite.task` 与 `wasm/` 目录。模型文件由 A 提供并确认版本及许可。
安装 npm 依赖后执行 `node scripts/copy-wasm.mjs`，从本地安装的 MediaPipe 包复制匹配的 WASM 文件。
默认不请求外部 CDN。资源缺失时摄像头模式显示错误；模拟模式不需要模型。
可在 frontend/.env 中修改 VITE_POSE_MODEL 与 VITE_POSE_WASM。
