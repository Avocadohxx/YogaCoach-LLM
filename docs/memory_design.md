# 记忆设计（D）

> 当前生产写入：正式事件与反馈由后端负责，客户端原始导入默认禁用；YOGACOACH_ALLOW_TEST_WRITES 只用于隔离测试。前端先创建会话；异常离开通过心跳标记中断，不伪造结束。

> 负责人：D。代码：`backend/database.py`、`backend/memory.py`、`backend/routes_memory.py`。
> 测试：`tests/test_memory*.py`。所有数字（压缩比、耗时）来自 `experiments/results/memory_layer_check.md`，可用脚本复现。

## 1. 设计原则

1. **只存事实和用户确认的偏好**：L1 只存 B 判定为可信的偏差事件；L2 摘要只由已入库的 L1 + 反馈日志生成；L3 只存用户明确设置的偏好。D 不推断、不测量姿态，也不做医疗判断。
2. **不可信的观察不入库**：`feedback_allowed` 不是明确的 `true`、`tracking_quality` 不是明确的 `good`、`deviations=[]` 的事件一律不写入（与 MVP “置信不足、视角异常不纠错”一致）。
3. **持续的偏差只算一次**：B 每 200 ms 上报一次，同一偏差持续 4 秒会产生 20 条上报。D 把间隔不超过 3 秒的同类型、同侧偏差合并为一个“片段”（episode），避免 L1 被灌满、摘要次数失真。
4. **记忆可删除**：单个偏好、单次会话、某用户全部数据都能删除（见 §6）。
5. **D 不改公共文件**：不修改 `main.py`（B）、`schemas.py` / `contracts/`（公共）。接口约定写在本文件第 10 节，等团队确认。

## 2. 三层记忆

| 层 | 内容 | 谁写入 | 谁读取 | 表 |
|---|---|---|---|---|
| L1 事件 | 偏差片段：type、side、severity、confidence、duration_ms、count | B 的事件经 `save_analysis_event` 写入 | 生成 L2 摘要；E 的历史页（可选） | `pose_events` |
| L2 会话摘要 | 一次练习的事实性摘要（一句话） | `finish_session` 自动生成；C 也可用 `save_session_summary` 覆盖 | C（上次练习的情况）、E 的练习历史 | `sessions.summary` |
| L3 用户偏好 | `feedback_length`、`voice` 等，用户确认后才写 | 用户 → E → `PUT /preferences` | C | `user_preferences` |

另有 `feedback_logs`：C 每次发出的反馈话术，用于去重和冷却（不属于三层，但是 C 需要）。

### 数据流

```
E ──POST /sessions──────────────► sessions            (练习开始，E 生成 session_id)
B 事件 ─► C(/api/agent/feedback) ─► save_analysis_event ─► pose_events   (L1，合并片段)
C ──get_memory_context──────────► 读 L2 + L3 + 本次反馈  (生成话术前)
C ──log_feedback────────────────► feedback_logs         (话术发出后)
E ──POST /sessions/{id}/finish──► build_session_summary ─► sessions.summary (L2)
下次练习：C 读取上次的 L2 摘要
```

## 3. 表结构

```
sessions(session_id PK, user_id, pose_id, started_at, ended_at, summary, created_at)
pose_events(event_id PK, session_id FK→sessions ON DELETE CASCADE, event_type, side, severity,
            confidence, timestamp_ms, duration_ms, payload_json, created_at)
feedback_logs(feedback_id PK, session_id FK CASCADE, event_type, feedback_text, created_at)
user_preferences(preference_id PK, user_id, preference_key, preference_value, updated_at,
                 UNIQUE(user_id, preference_key))
schema_meta(key PK, value)        -- 记录 schema_version，将来迁移用
```

分成四张表是因为生命周期不同：事件随会话产生、随会话删除；偏好独立于会话长期存在；反馈日志按会话查询最近 N 条。

`timestamp_ms` 是相对本次练习开始的毫秒数（E 的 `/api/analyze` 就是这样上传的）。

## 4. 合并规则（L1）

- 键：`(session_id, type, side)`。
- 新观察距该片段最后一次观察 ≤ `MERGE_GAP_MS`（3000 ms）→ 合并：`duration_ms` 取最大值，`severity` 取最严重，`confidence` 取最高，`payload.count` +1。
- 超过间隔或 side 不同 → 新片段。
- 摘要里的“N 次”= 片段数，不是上报条数。
- 阈值是工程取值，不是医学或教学依据；B 定稿持续时间规则后需要一起确认。

## 5. Python 接口（C/B 直接 import）

```python
from backend import memory

memory.create_session(session_id, pose_id, user_id="default", started_at=None)
memory.save_analysis_event(event)              # B→C 完整事件，D 负责拆 deviations / 过滤 / 合并
memory.save_pose_event(session_id, one_dev)    # 单个偏差原样存储（不合并）
memory.get_pose_events(session_id)
memory.finish_session(session_id)              # 结束；没有摘要时自动生成并返回
memory.build_session_summary(session_id)       # 只读，生成摘要文本
memory.save_session_summary(session_id, text)  # C 自己写摘要时使用
memory.get_recent_sessions(pose_id, user_id="default", limit=5)
memory.get_user_preferences(user_id="default")
memory.set_user_preference(key, value, user_id="default")
memory.delete_user_preference(key, user_id="default")
memory.get_recent_feedback(session_id, n=5)    # 最新在前
memory.log_feedback(session_id, event_type, text)
memory.get_memory_context(pose_id, session_id) # 一次拿到 contracts/mock/memory_sample.json 形状
memory.delete_session(session_id) / memory.delete_user_data(user_id)
```

`get_memory_context` 返回（与 `contracts/mock/memory_sample.json` 同键）：

```json
{"recent_sessions": [{"session_id": "...", "pose_id": "tadasana", "ended_at": "...", "summary": "..."}],
 "recent_feedback": [{"event_type": "shoulder_asymmetry", "text": "...", "created_at": "..."}],
 "preferences": {"feedback_length": "short", "voice": false}}
```

当前会话不会出现在 `recent_sessions` 里；`recent_feedback` 只含当前会话；`"true"/"false"` 偏好值会转成布尔。

## 6. HTTP 接口（前缀 `/api/memory`，`main.py` 已挂载）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/sessions` | 创建会话 `{session_id, pose_id, started_at?}`（幂等） |
| GET | `/sessions?pose_id=&limit=` | 练习历史（仅含已有摘要的会话，最新在前） |
| GET / DELETE | `/sessions/{id}` | 查看 / 删除会话（连同事件、反馈） |
| POST | `/sessions/{id}/finish` | 结束会话，返回自动生成的摘要 |
| POST | `/sessions/{id}/summary` | 写入 / 覆盖摘要（C 使用） |
| GET | `/sessions/{id}/events` | L1 片段列表 |
| POST | `/sessions/{id}/events` | 存单个偏差（原样，不合并） |
| POST | `/sessions/{id}/analysis` | 存 B 的完整分析事件（拆分 / 过滤 / 合并） |
| GET / POST | `/sessions/{id}/feedback` | 读最近 N 条 / 记录一条反馈 |
| GET / PUT | `/preferences` | 读取 / 设置偏好 |
| DELETE | `/preferences/{key}` | 删除偏好 |
| GET | `/context?pose_id=&session_id=` | D→C 记忆上下文 |
| DELETE | `/user-data?user_id=` | 删除某用户全部练习记录和偏好 |

错误码：未知会话 404；参数不合法 400；请求体校验失败 422。

## 7. 配置

数据库路径优先级：`YOGACOACH_DB_PATH` → 公共 `.env.example` 里的 `DATABASE_PATH` → `data/yogacoach.db`。相对路径以仓库根目录为基准。`*.db` 已在 `.gitignore`，不要提交（含用户练习记录）。

## 8. 已知限制

- 用户身份：目前 `user_id="default"`，没有登录体系。
- 偏好值是字符串（布尔会转 `"true"/"false"`），没有按 key 做取值白名单；哪些 key 被 C 使用由 C 决定。
- 摘要是模板化的一句话，措辞固定，不含建议；偏差类型名称表（`DEVIATION_NAMES`）只覆盖 B 的草案枚举，未知类型原样输出。
- 合并阈值（3 s）未经真实录像调参。
- SQLite 单文件、每次操作一个连接，适合单机演示；多进程高并发不在 MVP 范围。

## 9. 评估

见 `experiments/memory/README.md`。`cases.json` 是 24 个合成场景（草稿，待 B/C 复核），`evaluate.py` 只对已收集的输出和人工标注计算指标。

## 10. 与 E / C / B 的对接（D 提议，待各方确认）

> 各人先提交自己的分支即可，下面这些在合并前后再对齐。D 只修改自己名下的文件，没有改 `main.py`、`schemas.py`、`contracts/`、`requirements.txt`、E 的前端或其他成员的模块。
> E 现状：前端在 `start()` 里用 `crypto.randomUUID()` 生成 `session_id` 并用于 `POST /api/analyze`；真实模式目前不保存到服务器，`api.ts` 还没有会话接口。

### 10.1 E 需要做的（只有 3 个调用）

| 时机 | 请求 | 说明 |
|---|---|---|
| 真实模式点“开始练习” | `POST /api/memory/sessions` `{session_id, pose_id, started_at}` | `started_at` 用 ISO 时间，如 `new Date(run.started).toISOString()` |
| 点“结束练习” | `POST /api/memory/sessions/{id}/finish` | 返回 `{summary}`，可直接展示为“本次记录” |
| 进入页面 / 结束后 | `GET /api/memory/sessions?limit=10` | 练习历史，替换 localStorage 假数据；字段 `session_id, pose_id, ended_at, summary` |

建议加到 `services/api.ts`（示例，由 E 决定是否采纳）：

```ts
export const memoryApi = {
  startSession: (b:{session_id:string;pose_id:Pose;started_at:string}) =>
    request<{ok:boolean}>('/api/memory/sessions', b),
  finishSession: (id:string) =>
    request<{ok:boolean;summary:string|null}>(`/api/memory/sessions/${id}/finish`, {}),
  history: () =>
    request<{items:{session_id:string;pose_id:Pose;ended_at:string|null;started_at:string|null;summary:string}[]}>(
      '/api/memory/sessions?limit=10', undefined),
};
```

注意：
- 演示模式（模拟练习）不要写入服务器，否则会混入假记录。
- `finish` 里如果会话不存在返回 404；E 应当忽略该错误，不能影响“结束练习”的本地流程。
- 摘要只说“检测到什么”，不评价“进步/改善”（E 现有文案“此记录不代表动作改善”保持一致）。

### 10.2 C 需要做的（在 `/api/agent/feedback` 里）

C 的路由会收到 B 的完整分析事件，是最合适的接入点：

```python
from backend import memory

def feedback_route(event: dict):                 # event = B→C 分析事件
    memory.save_analysis_event(event)            # ① L1：自动拆 deviations / 仅接受 feedback_allowed=true 且 tracking_quality=good 的事件 / 合并片段
    ctx = memory.get_memory_context(event["pose_id"], event["session_id"])   # ② 取记忆
    # ③ 用 ctx["recent_sessions"] / ctx["recent_feedback"] / ctx["preferences"] 生成话术
    #    - recent_feedback 用于去重/冷却；preferences 例如 feedback_length=short
    if result["should_speak"]:
        memory.log_feedback(event["session_id"], result["grounded_event_type"], result["text"])  # ④
    return result
```

- `save_analysis_event` 在会话不存在时会按事件里的 `session_id` / `pose_id` 自动建会话，这是内部兼容工具行为；真实图像入口仍要求先创建有效会话，不允许浏览器借此绕过写入校验。
- 记忆只是上下文：C 的话术仍必须只基于**当前事件**；历史只能用来调整语气、避免重复。
- 摘要：默认由 `finish` 自动生成。如果 C 想写自己的摘要，调用 `save_session_summary` 即可（`finish` 不会覆盖已有摘要）。
- 若 C 的数据库依赖需要 HTTP 而不是 import：对应接口见 `docs/memory_design.md` §6。

### 10.3 B 需要确认的

1. 偏差类型枚举定稿后告诉 D，更新 `DEVIATION_NAMES`（摘要中文名）和 `tests/test_memory.py` 的 `KNOWN_TYPES`。ardhakati_chakrasana 目前没有类型，`experiments/cases.json` 里只有该动作的“拒绝纠错”场景。
2. `severity` 取值：D 假定 `mild < moderate < severe`（未知值按最低处理）。
3. 合并阈值 `MERGE_GAP_MS=3000` 是否符合 B 的“持续偏差”规则。
4. B 事件里的 `timestamp_ms` 假定是**相对练习开始**的毫秒（E 现在就是这样上传）。

### 10.4 全组需要确认

- 用户身份：MVP 使用 `user_id="default"`。
- 谁在什么时候调用 `finish`（建议 E 在用户点“结束”时调用）。
- 数据库文件位置：默认 `data/yogacoach.db`，也可用 `DATABASE_PATH`（公共 `.env.example` 已有）或 `YOGACOACH_DB_PATH`。
- 修改公共契约（如给 `memory_sample.json` 增字段）必须走 PR 并通知所有下游。

### 10.5 依赖与未完成部分

- 接口测试需要 `httpx`。`requirements.txt` 暂无，未安装时这部分测试自动跳过；请 C 在 `requirements.txt` 中加入 `httpx`（D 没有改该文件）。
- 对照实验没有结果：需要 C 的 Agent 输出和人工标注（流程见 `experiments/memory/README.md`），所以 `experiments/results/` 里没有 `metrics.*`。
- `experiments/cases.json` 是 24 个合成场景，状态 `draft_unreviewed`，待 B/C 复核；站立侧弯式只有“拒绝纠错”场景，等 B 定稿类型。
- `pre/qa.md` 中 A/B/C/E 的部分是 D 起草的草稿，待各成员补充证据。
