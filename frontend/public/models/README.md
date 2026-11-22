# 模型资源

当前主路径使用后端 `data/models/rtmw_x_384.onnx`，由 Git LFS 分发。前端不再包含 MediaPipe 模型或 WASM。

仓库根目录运行 `python -m scripts.download_pose_model`，核对权重与记录的 SHA256。模型就绪状态见 `/api/ready`。
