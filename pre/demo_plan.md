# v2 联调演示

1. 按根 README 安装依赖，运行 npm test、npm run build。
2. npm run dev，明确展示默认本地模拟模式：两种动作选择、开始、三种场景、结束与本地历史。
3. 无摄像头接口演示：frontend 下启动 npm run mock，另一个终端 npm run check:integration。输出标明 mock。
4. 在 http://127.0.0.1:8001/__mock 切换 normal/blocked/error/slow；error 场景检查失败是预期行为，切回 difference 后恢复。
5. A 模型与 B/C 服务就绪后，按 README 配置真实 BACKEND_URL、复制 WASM，重启 Vite，再演示摄像头。当前真实会话不持久化。
6. 现场缺模型、后端或摄像头时，明确使用模拟/契约联调；不宣称真实系统成功。正式演示备份视频待完整联调验收后录制，本次前端联调交付不以此阻塞。

一键临时桩冒烟：在 frontend 执行 node scripts/smoke-mock.mjs（使用18001，自动清理进程）。

原有真实服务脚本 bash scripts/start_demo.sh 仍要求根目录 .venv、Python >=3.10 和 npm；本次未实测 Git Bash 启动。
