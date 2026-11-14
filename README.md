# YogaCoach

基于人体姿态感知与 LLM Agent 的轻量级瑜伽动作指导系统（课程项目，两周 MVP）。

支持动作：山式（`tadasana`）、站立侧弯式（`ardhakati_chakrasana`）。

## 快速开始

> 本节由 E 补全。下面是目前约定的最小步骤。

```bash
python -m venv .venv
source .venv/bin/activate          # Git Bash 里用 source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env               # 填入自己的 key，.env 不会被提交

uvicorn backend.main:app --reload --port 8000

cd frontend && npm install && npm run dev
```

## 目录与负责人

| 目录 / 文件 | 负责人 |
|---|---|
| `data/` `scripts/extract_reference.py` `pre/YogaCoach_Pre.*` | A |
| `backend/pose_analyzer.py` `backend/routes_pose.py` `backend/main.py` | B |
| `backend/agent.py` `tools.py` `prompts.py` `routes_agent.py` `knowledge/` | C |
| `backend/database.py` `memory.py` `routes_memory.py` `experiments/` | D |
| `frontend/` `scripts/start_demo.sh` `pre/demo_plan.md` | E |
| `contracts/` `backend/schemas.py` | 公共（改动需全员 review） |

协作规则见团队的《GitHub 上传与协作指南》：一人一分支，走 Pull Request，不直接推 main。
