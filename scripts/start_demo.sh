#!/usr/bin/env bash
# Owner: E —— 一键启动后端与前端（演示用）
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .venv/Scripts/python.exe ]]; then PY=.venv/Scripts/python.exe
elif [[ -f .venv/bin/python ]]; then PY=.venv/bin/python
else echo '请先创建 .venv 并安装 requirements.txt'; exit 1; fi
command -v npm >/dev/null || { echo '请安装包含 npm 的 Node.js'; exit 1; }
[[ -d frontend/node_modules ]] || { echo '请先在 frontend 执行 npm install'; exit 1; }
"$PY" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT
sleep 1
kill -0 "$BACKEND_PID" 2>/dev/null || { echo '后端未启动，请检查 8000 端口与依赖'; exit 1; }
cd frontend
npm run dev
