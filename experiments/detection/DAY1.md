# B Day 1 交付与运行说明

日期：2026-11-17。阶段结论：已完成输入输出草案、合成骨架、几何测量和三类Mock；真实视频校准与效果评估尚未完成。未训练模型，未使用A的真实数据，未调用LLM。

## 已完成文件

- `backend/schemas.py`：公共Schema草案，必须通知全员Review。
- `backend/pose_analyzer.py`：纯Python、按特征质量检查的二维测量。
- `backend/routes_pose.py`：无状态 `/api/analyze`；复用原有main路由装配。
- `experiments/detection/synthetic_day1.py`：确定性合成数据生成器。
- `experiments/detection/fixtures/`：正常几何、肩部差异、遮挡、侧弯四份33点输入及来源manifest。
- `contracts/mock/b_day1/`：normal/deviation/not_assessable 三类合成返回；原B的analysis_event.json扩充为同一deviation样例。
- `tests/test_pose_analyzer.py`：公式、平移/缩放/镜像、画面宽高校正、退化、局部遮挡、Schema、FastAPI和Mock一致性检查。
- `docs/detection_rules.md`：公式、单位、质量规则与未完成边界。

保留A的原landmarks_tadasana.json、C/D文件、root requirements、README、前端、知识库和真实数据目录。没有替组员实现业务，没有提交或合并到Git主分支。

## 运行

推荐Python3.12。下面均在仓库根目录执行。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r experiments/detection/requirements-day1.txt
python -m pytest tests/ -q
```

这份requirements只用于B的最小环境。若已有项目虚拟环境，不必重建；但Schema使用Pydantic2，需核对版本。全项目依赖以后由团队统一锁定。

离线查看一帧，无摄像头、网络和API密钥：

```bash
python -m experiments.detection.replay_day1 experiments/detection/fixtures/normal.json
python -m experiments.detection.replay_day1 experiments/detection/fixtures/side_bend.json
```

重新生成合成数据（会覆盖B的合成fixture和B的analysis Mock，不覆盖A的关键点样例）：

```bash
python -m experiments.detection.synthetic_day1
```

启动接口：

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000/docs，在POST /api/analyze中粘贴fixtures/normal.json的完整内容；或另开终端：

```bash
curl -sS http://127.0.0.1:8000/api/health
curl -sS http://127.0.0.1:8000/api/analyze -H 'Content-Type: application/json' --data-binary @experiments/detection/fixtures/normal.json
```

接口当前不涉及C/D，不需要.env/API密钥。没有修改主app跨域设置；E浏览器接入时需团队约定使用Vite代理或配置明确CORS来源。

## 如何读结果

1. normal几何有效：追踪good，特征有值，但assessment_status=uncalibrated，不是“动作正确”。
2. shoulder_difference：肩高差有值，但无真实参考，因此不产生纠正。
3. side_bend：倾斜角有值，仍不产生山式的侧倾错误。
4. occluded：poor/not_assessable，观测值null且有原因，不把无法测量写成0。
5. 部分遮挡：只有依赖被遮挡点的特征停用；例如左腕遮挡不影响肩髋测量。

三类Mock只给C/E开发接线；deviation中的事件与1800ms是人为设定，测试不意味着已经实现持续过滤或证明动作错误。

## 测试记录

本地：Python3.12.14、依赖见requirements-day1.txt；`python -m pytest tests/ -q`通过19项测试及18个参数子项。包含ASGI路由/422响应检查；另实际启动Uvicorn，通过HTTP验证health和normal/occluded/side_bend三类请求均返回200及预期状态。没有测试真实摄像头或真实用户。

当前Starlette的TestClient对httpx适配会给出一条弃用提示；不影响本次通过，测试依赖已记录。正式团队锁定依赖时可一起评估升级，不为此修改全项目依赖。

## 发给组员的接口变更说明（请B自行群内同步）

“B已完成Day1草案。请A/E提供session_id、frame_seq、实际推理图像宽高、phase和侧弯的side，时间统一会话内毫秒；33点格式仍为x/y/z/visibility。C请保留原B→C字段并检查新增observations和模式标记。正式接口现在只测量，feedback_allowed始终false；三类synthetic Mock供你们独立开发。公共Schema/contracts待全员Review，持续事件和真实阈值下一阶段再接。”

没有发送群消息，也没有获得其他成员批准；请走项目原有PR流程。项目下载包本身无.git，当前没有创建虚假feature分支或推送仓库。

## 你接下来做什么

1. 同步契约给A/C/E，确认镜像、坐标变换、侧弯变体和抬臂侧。
2. 第二天：持续事件状态机、时间间隔/乱序/恢复和会话隔离；不依赖A即可用合成序列开发。
3. A到位：共用几何函数提取参考，校准质量门限与参考区间，人工审核具体偏差。
4. D配合：用独立真实片段统计检测指标；当前19项代码测试不能当作检测准确率。
