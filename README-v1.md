# YogaCoach‑LLM

## E 初始前端（2026-11-15）

`frontend/` 已提供 React 页面、模拟练习、浏览器摄像头/骨架、真实 API 对接入口与本地模拟历史。
在 frontend 执行 `npm install`、`npm run dev`；页面固定为 `http://127.0.0.1:5173`，端口占用时直接报错。
前端 `/api` 通过 Vite 转发到 `http://127.0.0.1:8000`；更换后端地址请复制 `frontend/.env.example` 为 `.env` 并修改 `BACKEND_URL`，重启前端。
检查命令：`npm test`、`npm run build`。Vite 代理仅用于开发，生产部署另需配置同源反向代理。

真实摄像头模式需要 `frontend/public/models/pose_landmarker_lite.task`，以及运行 `node scripts/copy-wasm.mjs` 复制 WASM（在 frontend 下运行）。模型文件待 A 提供；模拟模式无需摄像头或模型。
当前服务端业务仍为占位，真实模式遇到 404 会明确报错。会话接口待 D 确认；本地模拟历史不代表 SQLite 或 LLM 记忆已实现。
对接集中在 `frontend/src/services/api.ts`；没有修改公共 Schema 或其他成员业务文件。


> 基于人体姿态感知与 LLM Agent 的轻量级瑜伽动作指导系统，课程小组两周 MVP 项目。 支持动作：山式（`tadasana`）、站立侧弯式（`ardhakati_chakrasana`）。 ⚠️ 本系统仅做辅助观察与温和练习建议，**不提供医疗诊断**；关键点置信不足、视角不匹配时拒绝给出纠错建议。

## 一、总体目录

```
yogacoach/
├── README.md                    # E：项目简介、安装、启动、演示步骤
├── requirements.txt             # 公共：新增依赖前小组内同步告知
├── .env.example                 # 公共：仅存放环境变量名，禁止填入真实密钥
├── .gitignore
├── .github/
│   ├── CODEOWNERS               # 目录负责人配置，PR自动请求对应人员审核
│   └── pull_request_template.md # PR提交模板
├── contracts/                   # 【公共契约目录】接口定义 + Mock数据，Day2前接口冻结
│   ├── README.md                # 四份接口字段说明、枚举值定义文档
│   └── mock/
│       ├── landmarks_tadasana.json     # A：A→B关键点样例（完整33个人体关键点）
│       ├── analysis_event.json         # B：B→C姿态事件样例
│       ├── agent_feedback.json         # C：C→E Agent反馈样例
│       └── memory_sample.json          # D：D→C历史摘要/偏好样例
├── data/                        # A：参考骨架、原始视频资源
│   ├── README.md                # 数据集来源、许可协议、选用视频清单
│   ├── reference/               # 提取得到的动作参考特征JSON
│   └── raw_videos/              # 原始练习视频，.gitignore不提交至仓库
├── scripts/
│   ├── extract_reference.py     # A：视频提取关键点，生成动作参考特征
│   └── start_demo.sh            # E：前后端一键启动脚本
├── backend/
│   ├── main.py                  # B：仅初始化FastAPI实例、挂载路由；C/D禁止修改本文件业务逻辑
│   ├── schemas.py               # 公共：Pydantic接口模型，修改后需要全体成员Review
│   ├── pose_analyzer.py         # B：姿态特征计算、偏差检测规则、事件过滤
│   ├── routes_pose.py           # B：姿态分析接口 /api/analyze
│   ├── agent.py                 # C：LangGraph Agent主流程
│   ├── tools.py                 # C：Agent工具集合
│   ├── prompts.py               # C：System Prompt、输出约束Schema
│   ├── routes_agent.py          # C：Agent反馈接口
│   ├── database.py              # D：SQLite数据库表定义与连接管理
│   ├── memory.py                # D：L1事件、L2会话摘要、L3用户偏好读写逻辑
│   └── routes_memory.py         # D：会话、练习摘要、用户偏好相关接口
├── knowledge/                   # C：Agent静态瑜伽知识库
│   ├── tadasana.json
│   ├── ardhakati_chakrasana.json
│   └── fallback_templates.json  # LLM接口异常降级固定话术
├── frontend/                    # E：React+TS+Vite前端工程
│   ├── package.json
│   ├── public/models/           # MediaPipe模型与WASM本地资源（适配国内网络）
│   └── src/
│       ├── App.tsx / pages/ / components/
│       └── services/
│           ├── poseLandmarker.ts   # E实现，A审核，保证离线/浏览器端关键点坐标系定义一致
│           └── api.ts
├── tests/
│   ├── test_pose_analyzer.py    # B：姿态分析单元测试
│   ├── test_agent.py            # C：Agent逻辑单元测试
│   └── test_memory.py           # D：记忆模块单元测试
├── experiments/
│   ├── cases.json               # D：人工核验姿态与指导测试场景
│   ├── evaluate.py              # D：评估总入口脚本
│   ├── agent_cases.json         # C：Agent专项评估用例
│   ├── detection/               # B：姿态检测精确率、召回率相关实验
│   ├── agent/                   # C：模板回复 vs Agent对比实验
│   ├── memory/                  # D：无记忆 vs 开启记忆对照实验
│   ├── e2e/                     # E：端到端系统测试检查清单
│   └── results/                 # D：实验输出表格、图表结果
├── docs/
│   ├── architecture.md          # C：系统架构图、完整数据流说明
│   ├── keypoint_format.md       # A：MediaPipe 33关键点格式、坐标、可见性文档
│   ├── detection_rules.md       # B：姿态偏差规则、枚举定义文档
│   └── memory_design.md         # D：L1/L2/L3分层记忆设计文档
└── pre/                         # Pre Presentation汇报全部材料
    ├── YogaCoach_Pre.pptx       # A：PPT唯一主文件，仅A可提交更新
    ├── YogaCoach_Pre.pdf        # A：PDF备份版本
    ├── speaker_notes.md         # C汇总，五位成员分别撰写对应模块讲稿
    ├── qa.md                    # D汇总，答辩问答清单
    ├── demo_plan.md             # E：演示操作步骤、启动命令、故障降级预案
    ├── demo_backup.mp4          # E：演示备份视频，建议使用网盘，仓库仅存放链接
    └── assets/                  # 汇报素材图片，各成员存放自己产出截图图表
```

## 二、小组分工

> 开发模式：每人独立功能分支，通过 Pull Request 合并入`main`主分支；公共文件修改需要同步小组并下游人员 Review。

表格

| 成员 | Git 功能分支                | 负责目录与文件                                               |
| ---- | --------------------------- | ------------------------------------------------------------ |
| A    | `feature/data-pose`         | `data/`、`scripts/extract_reference.py`、`docs/keypoint_format.md`；`pre/YogaCoach_Pre.*`、`pre/assets/skeleton_comparison.png` |
| B    | `feature/pose‑evaluator`    | `backend/main.py`、`backend/pose_analyzer.py`、`backend/routes_pose.py`；`tests/test_pose_analyzer.py`、`experiments/detection/`、`docs/detection_rules.md` |
| C    | `feature/agent`             | `backend/agent.py`、`backend/tools.py`、`backend/prompts.py`、`backend/routes_agent.py`；`knowledge/`、`tests/test_agent.py`、`experiments/agent*`、`docs/architecture.md`；`pre/speaker_notes.md` |
| D    | `feature/memory‑evaluation` | `backend/database.py`、`backend/memory.py`、`backend/routes_memory.py`；`tests/test_memory.py`、`experiments/cases.json`、`experiments/evaluate.py`、`experiments/memory/`、`experiments/results/`、`docs/memory_design.md`；`pre/qa.md` |
| E    | `feature/frontend`          | `frontend/`、`scripts/start_demo.sh`、根目录`README.md`；`experiments/e2e/`、`pre/demo_plan.md`、`pre/demo_backup.mp4` |

> 公共文件说明：
>
> 1. `contracts/`、`backend/schemas.py`、`requirements.txt`由 C 初始化初版；**任何改动需要群内同步，并且通知所有下游使用者 Review**。
> 2. `backend/main.py`仅做 FastAPI 路由挂载，业务逻辑拆分到各自`routes_*.py`，避免多人冲突。

## 三、快速开始 🚀 Getting Started

> 负责人：E；写完后需要 A/B/C/D 全员 Review。

### 前置依赖

- Python >=3.10
- Node.js >= 20
- Git
- 可用摄像头（完整演示必需）
- LLM API‑Key（配置到环境变量）

### 1. 克隆仓库

```
git clone https://github.com/Avocadohxx/YogaCoach‑LLM.git
cd YogaCoach‑LLM
```

### 2. 配置 Python 后端虚拟环境

```
# 创建虚拟环境
python -m venv .venv

# Windows 激活虚拟环境
.venv\Scripts\activate

# Linux / Mac / Git‑Bash 激活虚拟环境
source .venv/bin/activate

# 安装Python依赖包
pip install -r requirements.txt
```

### 3. 配置环境变量

复制环境变量模板，**禁止直接修改 `.env.example`，严禁将`.env`提交到 Git 仓库**

```
# Git‑Bash / Linux / Mac
cp .env.example .env
```

> Windows CMD：手动复制`.env.example`，重命名为`.env`，填入你的 LLM API 密钥。

### 4. 安装前端依赖

```
cd frontend
npm install
cd ..
```

### 5. 一键启动整套服务

> Linux / Mac / Git‑Bash；Windows 推荐使用 Git‑Bash 执行该脚本

```
bash scripts/start_demo.sh
```

### 访问系统服务

- FastAPI 接口文档：http://127.0.0.1:8000/docs
- Web 瑜伽教练前端页面：http://127.0.0.1:5173

### 一键脚本异常：手动分步启动

终端 1（启动后端）

```
# Windows
.venv\Scripts\activate
uvicorn backend.main:app --reload
# Linux / Mac
source .venv/bin/activate
uvicorn backend.main:app --reload
```

终端 2（启动前端）

```
cd frontend
npm run dev
```

### 常见问题

1. 摄像头无法使用：浏览器开启摄像头权限；关闭其他占用摄像头的软件。
2. LLM 接口报错：检查`.env`内 API 密钥正确性，确认网络可访问大模型服务。
3. MediaPipe 模型加载失败：优先读取`frontend/public/models`本地模型资源。
4. Windows 执行`.sh`脚本报错：安装 Git‑Bash，或者使用上面手动分步启动方案。

> 协作提示：后续任何人新增环境变量、新增 Python/npm 依赖，必须通知 E 同步更新本章节。

## 四、Git 协作规则

1. 开发全部在个人 feature 分支完成，**禁止直接 push 到 main 分支**；合并至 main 必须提交 Pull Request。
2. `.github/CODEOWNERS`配置目录负责人，修改对应目录文件会自动请求模块负责人审核；PPT 文件`pre/YogaCoach_Pre.pptx`指定 A 为唯一负责人，规避二进制文件合并冲突。
3. 修改接口契约`contracts/`、`backend/schemas.py`的 PR，必须 @全部下游开发成员。
4. 禁止提交：`.env`、sqlite 数据库`*.db`、原始视频`data/raw_videos/`、`node_modules`、`.venv`、缓存文件、用户练习记录；大体积演示视频建议存放网盘，仓库只保留链接。

## 五、项目 MVP 范围与限制

✅ 实现范围

- 动作：山式`tadasana`，站立侧弯式`ardhakati_chakrasana`
- MediaPipe 离线 / 浏览器端 33 人体关键点提取；姿态偏差规则检测
- LangGraph Agent + Tool‑Calling，生成温和瑜伽练习指导
- SQLite 分层记忆 L1 事件 / L2 会话摘要 / L3 用户偏好
- React 前端：摄像头实时骨架绘制、动作选择、Agent 反馈展示、练习历史查看

❌ 不在本 MVP 实现

- 不做 MediaPipe 模型微调；不做 LLM LoRA/SFT 微调
- 不提供医疗诊断；遮挡、视角异常、置信度低时拒绝纠错建议

## 六、测试与评估

### 单元测试执行

```
pytest tests/
```

### 运行项目评估脚本

```
python experiments/evaluate.py
```

## 七、Pre 相关说明

全部汇报材料存放于`pre/`目录，包含 PPT、PDF 备份、讲稿、答辩 Q&A、演示预案、备份演示视频、汇报素材图片。

> 重要提示：准备离线备份演示视频，应对现场网络、摄像头、LLM API 故障。

## 八、项目成员

A / B / C / D / E
