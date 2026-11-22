# 实时训练截图与历史详情

## 记录规则

- 仅在后端返回 `feedback_allowed=true`、`tracking_quality=good` 且包含偏差事件时，从当前视频帧和 133 点骨架覆盖层截取 JPEG。
- 同一偏差事件不会逐帧重复截图。截图上传到后端本机磁盘，SQLite 保存事件元数据和相对路径。
- Agent 仍由后端验证并写入反馈日志；前端只在建议返回后，将建议文本关联到当时的截图，不重复写入反馈日志。
- 截图或元数据保存失败会在练习界面显示错误。结束练习时会等待已开始的图片写入完成，再结束会话。

## 本地存储和删除

- 数据库继续使用项目现有路径：`YOGACOACH_DB_PATH`、`DATABASE_PATH` 或默认 `data/yogocoach.db`。
- 图片默认存放在 `data/evidence/<session-hash>/`，可用 `YOGACOACH_MEDIA_DIR` 指定其他本地目录。
- 图片不放入 SQLite 或浏览器 `localStorage`。`data/evidence/` 已加入 `.gitignore`。
- 删除单次会话或用户全部记录时，同时删除其截图文件和数据库记录。
- 上传只接受 JPEG、PNG、WEBP，单张最大 5 MB；服务器验证 MIME、文件签名和会话是否存在。

## 历史详情

主页右上角“训练历史”打开 `#/history` 历史列表。打开一条记录进入 `#/history/<session_id>`，页面包含训练摘要、检测偏差的相对时间、截图、截图对应建议及 Agent 建议时间线。训练尚未完成或没有可用总结时，列表会明确显示空状态。

相关接口：

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/memory/sessions/{id}/snapshots` | 保存实时错误截图 |
| GET | `/api/memory/sessions/{id}/detail` | 获取训练、事件、截图和建议 |
| GET | `/api/memory/snapshots/{snapshot_id}/image` | 读取本地图片 |
| POST | `/api/memory/snapshots/{snapshot_id}/feedback` | 关联已返回的建议 |

## 验证

```powershell
python -m pytest -q tests/test_history_media.py
cd frontend
npm test
npm run build
```

使用摄像头前需先启动后端、确保模型就绪，并在浏览器允许摄像头访问。无可信偏差的练习不会生成错误截图。
