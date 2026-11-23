import { useEffect, useState } from 'react';
import { api, type StoredSession } from './services/api';

const poseNames: Record<string, string> = {
  tadasana: '山式',
  ardhakati_chakrasana: '站立侧弯式',
};

function dateText(value: string | null) {
  return value ? new Date(value).toLocaleString() : '时间未知';
}

export default function HistoryIndex({
  onBack,
  onOpenSession,
}: {
  onBack: () => void;
  onOpenSession: (sessionId: string) => void;
}) {
  const [sessions, setSessions] = useState<StoredSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    api
      .sessions()
      .then((result) => {
        if (!cancelled) setSessions(result.items);
      })
      .catch((reason) => {
        if (!cancelled)
          setError(
            reason instanceof Error ? reason.message : '无法读取训练历史',
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="history-page">
      <header className="history-header">
        <button onClick={onBack}>← 返回练习</button>
        <span className="badge">训练历史</span>
      </header>
      <section className="history-hero">
        <span className="eyebrow">YOUR PRACTICE</span>
        <h1>每次练习，都可以回看。</h1>
        <p>打开一条记录，查看当时的建议、检测时间点和错误截图。</p>
      </section>
      <section className="history-section">
        <div className="history-section-title">
          <h2>已完成的训练</h2>
          <span>{sessions.length} 条</span>
        </div>
        {loading ? (
          <div className="history-empty">
            <p>正在读取本地训练记录…</p>
          </div>
        ) : error ? (
          <div className="history-empty" role="alert">
            <p>{error}</p>
          </div>
        ) : sessions.length === 0 ? (
          <div className="history-empty">
            <p>
              暂无已完成的训练记录。完成一次真实摄像头或本地视频练习后，记录会显示在这里。
            </p>
          </div>
        ) : (
          <div className="history-list">
            {sessions.map((session) => (
              <article className="history-entry" key={session.session_id}>
                <strong>
                  {poseNames[session.pose_id] || session.pose_id || '瑜伽训练'}
                </strong>
                <span>{dateText(session.ended_at || session.started_at)}</span>
                <p className="history-summary-line">
                  {session.summary || '本次训练暂无总结。'}
                </p>
                <button onClick={() => onOpenSession(session.session_id)}>
                  查看建议与错误截图 →
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
      <footer>训练记录保存在本机，不构成医疗诊断。</footer>
    </main>
  );
}
