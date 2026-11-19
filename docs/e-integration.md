# E v2 联调交接

## 当前适配约定（待对应负责人确认，不视为公共契约已冻结）

| 接口 | 请求 | 响应 | 对接人 |
|---|---|---|---|
| GET /api/health | 无 | `{status:"ok"}`；联调桩额外标记 mode=mock | B |
| POST /api/analyze | session_id、pose_id、相对会话开始的 timestamp_ms、camera_view=front、image_width/image_height、33项 landmarks | contracts/mock/analysis_event.json | B，A确认坐标 |
| POST /api/agent/feedback | 上一接口完整事件对象，直接转发额外字段 | contracts/mock/agent_feedback.json | C |
| 会话、摘要、历史 | 未约定，不猜测路径 | 真实记录仅当次显示，不持久化 | D |

关键点 x/y/z/visibility 原样上传；镜像只用于 video/canvas 显示。正面拍摄是当前使用前置条件，camera_view=front 不是自动视角检测结论。前端基础门限仅检查33点、有限数值及肩髋可见性；B 仍负责视角、完整质量判定和持续偏差规则。

现有占位样例33点相同；接口脚本也会用同一组点检查两种 pose_id，不能当作姿态算法测试。C 需确认反馈请求是否确实接收完整分析事件。D 契约确认后再增加真实历史。

## E 的运行行为

- 有效帧最多每200ms上传一次，同一会话最多一个分析请求；等待反馈时继续分析。
- 遮挡、识别错误、结束会话立即使待返回请求失效；新会话使用独立控制器。
- 事件消失或变化立即撤回旧指导；事件消失后重现也不复用旧请求结果。
- 反馈请求冷却10秒；从触发分析起超过10秒的反馈显示“已过期”，请求网络超时15秒。两个时限分别保护证据时效和网络等待，不取消安全保护。
- 联调桩只监听本机8001，真实服务默认8000。不会自动从真实服务降级为桩。
- 生产静态部署需同源 /api 反向代理，Vite 代理仅用于开发。

## 联调检查顺序

1. 启动 mock，运行 check:integration；默认 difference 应检查两种动作的分析及反馈形状。
2. 在 /__mock 选择 normal、blocked，再运行检查；应允许无纠错返回。
3. 选择 error，检查应明确非零退出并指出HTTP 503；slow 用于前端超期提示回归。
4. 设置 BACKEND_URL 到真实后端；B/C 用上述相同路径和 JSON 样例协作排查404/422或字段不符。
5. A 模型就绪后用摄像头实测；D 接口和真实业务验收另行开展。
