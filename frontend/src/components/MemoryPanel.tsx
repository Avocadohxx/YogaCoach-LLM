import { useEffect, useState } from "react";
import { api, type StoredSession } from "../services/api";
const eventNames: Record<string, string> = {
  elbow_bend: "持续肘部弯曲",
  upper_arm_alignment: "上臂位置偏差",
  bend_direction_mismatch: "侧弯方向不一致",
};
const poseNames: Record<string, string> = {
  tadasana: "山式",
  ardhakati_chakrasana: "站立侧弯",
};
export default function MemoryPanel({
  active,
  refreshKey,
  onDeleted,
  onOpenSession,
}: {
  active: boolean;
  refreshKey: string;
  onDeleted?: () => void;
  onOpenSession?: (sessionId: string) => void;
}) {
  const [length, setLength] = useState("normal"),
    [message, setMessage] = useState(""),
    [confirm, setConfirm] = useState(false);
  const [sessions, setSessions] = useState<StoredSession[]>([]),
    [open, setOpen] = useState<(StoredSession & { state: string })[]>([]);
  const [events, setEvents] = useState<
    Record<
      string,
      {
        event_id: string;
        event_type: string;
        duration_ms: number;
        side: string | null;
      }[]
    >
  >({});
  async function refresh() {
    const [p, s, o] = await Promise.allSettled([
      api.preferences(),
      api.sessions(),
      api.incomplete(),
    ]);
    const failures: string[] = [];
    if (p.status === "fulfilled")
      setLength(p.value.preferences.feedback_length || "normal");
    else failures.push("偏好");
    if (s.status === "fulfilled") setSessions(s.value.items);
    else failures.push("训练记录");
    if (o.status === "fulfilled") setOpen(o.value.items);
    else failures.push("未完成练习");
    setMessage(
      failures.length
        ? `${failures.join("、")}暂不可用，请检查对应后端接口。`
        : "",
    );
  }
  useEffect(() => {
    void refresh();
  }, [refreshKey]);
  return (
    <section className="card">
      <h2>偏好与练习详情</h2>
      <label>
        提醒长度{" "}
        <select
          value={length}
          onChange={(e) => {
            setLength(e.target.value);
            void api
              .preference(e.target.value)
              .then(() => setMessage("偏好已保存"))
              .catch(() => setMessage("偏好保存失败"));
          }}
        >
          <option value="short">简短</option>
          <option value="normal">完整</option>
        </select>
      </label>
      <p role="status">{message}</p>
      <button onClick={() => void refresh()}>刷新详情</button>
      {open.map((s) => (
        <p key={s.session_id}>
          未结束的练习：{s.state === "interrupted" ? "已中断" : "进行中"}{" "}
          <button
            disabled={active}
            onClick={() => {
              void api
                .finishSession(s.session_id)
                .then(refresh)
                .catch(() => setMessage("结束会话失败"));
            }}
          >
            结束并生成事实总结
          </button>
        </p>
      ))}
      {sessions.map((s) => (
        <details key={s.session_id}>
          <summary
            onClick={() => {
              void api
                .events(s.session_id)
                .then((r) =>
                  setEvents((previous) => ({
                    ...previous,
                    [s.session_id]: r.items,
                  })),
                )
                .catch(() => setMessage("事件读取失败"));
            }}
          >
            {poseNames[s.pose_id] || s.pose_id} · {s.ended_at || "未结束"}
          </summary>
          <button
            disabled={!onOpenSession}
            onClick={() => onOpenSession?.(s.session_id)}
          >
            查看训练详情、建议与错误截图
          </button>
          <p>{s.summary}</p>
          {(events[s.session_id] || []).map((e) => (
            <p key={e.event_id}>
              {eventNames[e.event_type] || e.event_type} {e.side || ""} ·{" "}
              {(e.duration_ms / 1000).toFixed(1)} 秒
            </p>
          ))}
        </details>
      ))}
      <hr />
      {!confirm ? (
        <button
          className="danger"
          disabled={active}
          onClick={() => setConfirm(true)}
        >
          删除服务器记录和偏好
        </button>
      ) : (
        <>
          <p>
            将删除当前本地用户的全部服务器练习、事件、反馈和偏好，无法撤销。
          </p>
          <button
            disabled={active}
            onClick={() => {
              void api
                .deleteData()
                .then(() => {
                  setConfirm(false);
                  setEvents({});
                  setMessage("已删除");
                  onDeleted?.();
                  void refresh();
                })
                .catch(() => setMessage("删除失败"));
            }}
          >
            确认删除
          </button>
          <button onClick={() => setConfirm(false)}>取消</button>
        </>
      )}
    </section>
  );
}
