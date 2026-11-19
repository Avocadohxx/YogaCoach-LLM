# YogaCoach E v2 — 前端联调交付版

本版本交付 E 的前端、必要竞态修复与接口联调工具。真实模型、B/C/D 业务仍由对应成员提供；不声称完整 MVP 已验收。

## 快速使用

需要 Node.js >=20（建议22或24），在本目录的 frontend 中执行：

```sh
npm ci
npm test
npm run build
npm run dev
```

访问 http://127.0.0.1:5173，默认是本地模拟模式，不请求摄像头或 LLM。

## 无摄像头接口联调

在 frontend 下开两个终端：

```sh
# 终端1：明确标识的契约联调桩，默认8001
npm run mock
# 终端2：使用仓库33点样例检查两种 pose_id 的请求形状
npm run check:integration
```

访问 http://127.0.0.1:8001/__mock 可选择 difference、normal、blocked、error、slow 场景。联调桩不做动作识别、LLM 或持久化，回复带【联调桩】标识。样例33点相同，只检查接口形状，不验证检测准确率。

连接真实后端时，设置检查脚本的 BACKEND_URL，例如 PowerShell：

```powershell
$env:BACKEND_URL='http://127.0.0.1:8000'
npm run check:integration
```

网页代理配置：复制 frontend/.env.example 为 frontend/.env，设置 BACKEND_URL（真实8000，联调桩8001），然后重启 Vite。浏览器始终请求同源 /api。

## 摄像头模式

先在 frontend 执行 `npm run prepare:models` 复制锁定版本 WASM。当前副本已复制。请 A 提供并确认 `frontend/public/models/pose_landmarker_lite.task` 的版本、许可与坐标约定，再选择摄像头模式。没有模型时可完成模拟和脚本联调，摄像头模式会明确报错。

Python 后端需要 >=3.10，安装根目录 requirements.txt 后执行 `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`。当前 B/C/D 路由仍占位，404 表示尚未接入，不能视为 E 前端真实链路成功。原有 `bash scripts/start_demo.sh` 保留，依赖根目录 .venv 和已安装的 npm。

## 交接资料

- [架构取舍及验收记录](experiments/e2e/v2-delivery.md)
- [接口联调约定](docs/e-integration.md)
- [演示步骤](pre/demo_plan.md)

原版说明作为历史参考保存在 README-v1.md；其中完整 MVP 目标不代表 v2 已全部完成。
