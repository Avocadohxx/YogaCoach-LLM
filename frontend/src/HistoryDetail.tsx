import { useEffect, useState } from "react";
import { api, type Pose, type SessionDetail } from "./services/api";

const poseNames: Record<Pose, string> = {
  tadasana: "山式",
  ardhakati_chakrasana: "站立侧弯式",
};
const eventNames: Record<string, string> = {
  elbow_bend: "持续肘部弯曲",
  upper_arm_alignment: "上臂位置偏差",
  bend_direction_mismatch: "侧弯方向不一致",
};
const sideNames: Record<string, string> = {
  left: "左侧",
  right: "右侧",
  left_higher: "左侧偏高",
  right_higher: "右侧偏高",
};

function dateText(value: string | null) {
  return value ? new Date(value).toLocaleString() : "时间未知";
}

function elapsed(timestamp: number | null) {
  if (timestamp === null) return "时间未知";
  const seconds = Math.max(0, Math.floor(timestamp / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function HistoryDetail({
  sessionId,
  onBack,
}: {
  sessionId: string;
  onBack: () => void;
}) {
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .sessionDetail(sessionId)
      .then((value) => {
        if (!cancelled) setDetail(value);
      })
      .catch((reason) => {
        if (!cancelled)
          setError(
            reason instanceof Error ? reason.message : "无法读取训练记录",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (loading)
    return (
      <main className="history-page">
        <button onClick={onBack}>← 返回历史记录</button>
        <p>正在读取本次训练记录…</p>
      </main>
    );
  if (error || !detail)
    return (
      <main className="history-page">
        <button onClick={onBack}>← 返回历史记录</button>
        <section className="history-empty">
          <h2>无法打开训练记录</h2>
          <p>{error || "记录不存在或已被删除。"}</p>
        </section>
      </main>
    );

  const { session, events, snapshots, feedback } = detail;
  const duration =
    session.started_at && session.ended_at
      ? Math.max(
          0,
          Math.round(
            (new Date(session.ended_at).getTime() -
              new Date(session.started_at).getTime()) /
              1000,
          ),
        )
      : null;

  return (
    <main className="history-page">
      <header className="history-header">
        <button onClick={onBack}>← 返回历史记录</button>
        <span className="badge">训练详情</span>
      </header>
      <section className="history-hero">
        <span className="eyebrow">TRAINING REVIEW</span>
        <h1>{poseNames[session.pose_id] || session.pose_id || "瑜伽训练"}</h1>
        <p>{dateText(session.started_at)}</p>
        <div className="history-stats">
          <div>
            <strong>
              {duration === null
                ? "—"
                : `${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, "0")}`}
            </strong>
            <span>训练时长</span>
          </div>
          <div>
            <strong>{events.length}</strong>
            <span>记录偏差</span>
          </div>
          <div>
            <strong>{snapshots.length}</strong>
            <span>错误截图</span>
          </div>
          <div>
            <strong>{feedback.length}</strong>
            <span>建议记录</span>
          </div>
        </div>
      </section>
      {session.summary && (
        <section className="history-section">
          <h2>本次训练总结</h2>
          <p className="history-summary">{session.summary}</p>
        </section>
      )}
      <section className="history-section">
        <div className="history-section-title">
          <h2>错误动作截图</h2>
          <span>{snapshots.length} 张</span>
        </div>
        {snapshots.length === 0 ? (
          <div className="history-empty">
            <p>本次训练没有保存错误截图。只有检测到可信偏差时才会截取画面。</p>
          </div>
        ) : (
          <div className="snapshot-grid">
            {snapshots.map((shot, index) => (
              <article className="snapshot-card" key={shot.snapshot_id}>
                <img
                  src={shot.image_url}
                  alt={`错误动作截图 ${index + 1}`}
                  loading="lazy"
                />
                <div className="snapshot-meta">
                  <strong>
                    {shot.event_type
                      ?.split(",")
                      .map((type) => eventNames[type.trim()] || type.trim())
                      .join("、") || "动作偏差"}
                  </strong>
                  <span>{elapsed(shot.timestamp_ms)}</span>
                </div>
                {shot.side && <p>{sideNames[shot.side] || shot.side}</p>}
                {shot.feedback_text && (
                  <div className="suggestion">
                    <span>对应建议</span>
                    <p>{shot.feedback_text}</p>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
      <section className="history-section">
        <div className="history-section-title">
          <h2>检测到的动作偏差</h2>
          <span>{events.length} 条</span>
        </div>
        {events.length === 0 ? (
          <div className="history-empty">
            <p>本次训练没有保存可信的动作偏差事件。</p>
          </div>
        ) : (
          <div className="history-timeline">
            {events.map((event) => (
              <article className="timeline-item" key={event.event_id}>
                <span className="timeline-dot" />
                <div>
                  <strong>
                    {eventNames[event.event_type] || event.event_type}
                  </strong>
                  <time>{elapsed(event.timestamp_ms)}</time>
                  <p>
                    {[
                      event.side ? sideNames[event.side] || event.side : null,
                      event.duration_ms
                        ? `持续 ${(event.duration_ms / 1000).toFixed(1)} 秒`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      <section className="history-section">
        <div className="history-section-title">
          <h2>Agent 建议记录</h2>
          <span>{feedback.length} 条</span>
        </div>
        {feedback.length === 0 ? (
          <div className="history-empty">
            <p>本次训练没有保存 Agent 建议。</p>
          </div>
        ) : (
          <div className="suggestion-list">
            {[...feedback].reverse().map((item) => (
              <article key={item.feedback_id}>
                <time>{dateText(item.created_at)}</time>
                <p>{item.feedback_text}</p>
                {item.event_type && (
                  <small>
                    对应偏差：
                    {eventNames[item.event_type] || item.event_type}
                  </small>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
      <footer>训练记录仅用于动作学习与回顾，不构成医疗诊断。</footer>
    </main>
  );
}
