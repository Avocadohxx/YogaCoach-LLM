import { useEffect, useRef, useState } from "react";
import Source133 from "./components/Source133";
import VoiceControls from "./components/VoiceControls";
import { useVoiceCoach } from "./hooks/useVoiceCoach";
import MemoryPanel from "./components/MemoryPanel";
import HistoryDetail from "./HistoryDetail";
import HistoryIndex from "./HistoryIndex";
import {
  api,
  type Pose,
  type Analysis,
  type Phase133,
  type Variant133,
} from "./services/api";
import { usePracticeSession } from "./hooks/usePracticeSession";
const names: Record<Pose, string> = {
  tadasana: "山式",
  ardhakati_chakrasana: "站立侧弯式",
};
export default function App() {
  const [route, setRoute] = useState(window.location.hash || "#/");
  const [pose, setPose] = useState<Pose>("tadasana");
  const [status, setStatus] = useState("选择动作和图像来源后开始练习。");
  const [feedback, setFeedbackState] = useState({
    text: "开始练习后，这里显示当前建议。",
    latestAdvice: "",
    previousAdvice: "",
    sessionId: "",
  });
  function setFeedback(text: string, isAdvice = false) {
    if (isAdvice) voice.speak(text);
    else voice.cancel();
    const sessionId = run.current.id;
    setFeedbackState((previous) => {
      const sameSession = previous.sessionId === sessionId;
      if (
        sameSession &&
        previous.text === text &&
        (!isAdvice || previous.latestAdvice === text)
      )
        return previous;
      const latestAdvice = sameSession ? previous.latestAdvice : "";
      const previousAdvice = sameSession ? previous.previousAdvice : "";
      return {
        text,
        latestAdvice: isAdvice ? text : latestAdvice,
        previousAdvice:
          isAdvice && text !== latestAdvice ? latestAdvice : previousAdvice,
        sessionId,
      };
    });
  }
  const previousAdvice =
    feedback.text === feedback.latestAdvice
      ? feedback.previousAdvice
      : feedback.latestAdvice;
  const [health, setHealth] = useState("尚未检查");
  const [serverSummary, setServerSummary] = useState("");
  const [persistenceWarning, setPersistenceWarning] = useState("");
  const captureRef = useRef<(() => Promise<Blob | null>) | null>(null);
  const [phase, setPhase] = useState<Phase133>("prepare");
  const [inputSource, setInputSource] = useState<"camera" | "video">("camera");
  const [movementVariant, setMovementVariant] = useState<Variant133>("unknown"),
    [raisedArm, setRaisedArm] = useState<"unknown" | "left" | "right">(
      "unknown",
    ),
    [bendDirection, setBendDirection] = useState<
      "unknown" | "image_left" | "image_right"
    >("unknown");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [supported, setSupported] = useState<string[]>([]);
  useEffect(() => {
    const changed = () => setRoute(window.location.hash || "#/");
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  useEffect(() => {
    let valid = true;
    void api
      .ready()
      .then((r) => {
        if (valid) setSupported(r.rules?.[pose]?.correction_phases || []);
      })
      .catch(() => {
        if (valid) setSupported([]);
      });
    return () => {
      valid = false;
    };
  }, [pose]);
  function phaseLabel(name: string, value: string) {
    return name + (supported.includes(value) ? "（可纠错）" : "（仅测量）");
  }

  const {
    active,
    busy,
    seconds,
    summary,
    run,
    live,
    start,
    finish,
    clearSummary,
  } = usePracticeSession({
    pose,
    setFeedback,
    setStatus,
    setServerSummary,
    setAnalysis,
    capture: () => captureRef.current?.() ?? Promise.resolve(null),
    setPersistenceWarning: (message) => setPersistenceWarning(message || ""),
  });
  const voice = useVoiceCoach(active, busy, pose, (command) => {
    if (command === "finish") {
      voice.stop();
      void finish();
    } else changePhase(command);
  });
  function changePhase(next: Phase133) {
    if (busy || next === phase) return;
    voice.cancel();
    live.current?.invalidate("阶段已切换，重新积累证据。");
    setPhase(next);
  }
  const detailMatch = route.match(/^#\/history\/([^/]+)$/);
  if (route === "#/history")
    return (
      <HistoryIndex
        onBack={() => {
          window.location.hash = "#/";
        }}
        onOpenSession={(sessionId) => {
          window.location.hash = `#/history/${encodeURIComponent(sessionId)}`;
        }}
      />
    );
  if (detailMatch)
    return (
      <HistoryDetail
        sessionId={decodeURIComponent(detailMatch[1])}
        onBack={() => {
          window.location.hash = "#/";
        }}
      />
    );
  return (
    <main>
      <header>
        <a className="brand" href="#/">
          YogaCoach<span>/ 练习</span>
        </a>
        <a className="badge history-nav" href="#/history">
          训练历史
        </a>
      </header>
      <section className="intro">
        <h1>选择动作与阶段，使用摄像头或本地视频开始练习。</h1>
      </section>
      <VoiceControls disabled={!active || busy} {...voice} />
      <div className="layout">
        <section className="workspace">
          <div className="section-title">
            <h2>开始练习</h2>
            <span>
              {active
                ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`
                : "01 / 准备"}
            </span>
          </div>
          <div className="choices">
            {(Object.keys(names) as Pose[]).map((id) => (
              <button
                key={id}
                disabled={active || busy}
                className={pose === id ? "selected" : ""}
                onClick={() => {
                  setPose(id);
                  setPhase("prepare");
                  setMovementVariant(
                    id === "ardhakati_chakrasana"
                      ? "both_arms_overhead"
                      : "unknown",
                  );
                  setRaisedArm("unknown");
                  setBendDirection("unknown");
                }}
              >
                {names[id]}
                <small>
                  {id === "tadasana"
                    ? "举臂保持 · 持续肘部偏差提醒"
                    : "侧弯保持 · 持续偏差纠错"}
                </small>
              </button>
            ))}
          </div>
          {active && <p className="note">练习阶段可以随时切换。</p>}
          <div className="choices">
            {!active && (
              <label>
                图像来源{" "}
                <select
                  disabled={active || busy}
                  value={inputSource}
                  onChange={(e) =>
                    setInputSource(e.target.value as "camera" | "video")
                  }
                >
                  <option value="camera">摄像头</option>
                  <option value="video">本地视频</option>
                </select>
              </label>
            )}
            <label>
              练习阶段{" "}
              <select
                disabled={busy}
                value={phase}
                onChange={(e) => {
                  changePhase(e.target.value as Phase133);
                }}
              >
                <option value="prepare">准备中（不纠错）</option>
                <option value="arms_up_hold">
                  {phaseLabel(
                    pose === "ardhakati_chakrasana" &&
                      movementVariant === "single_arm_overhead"
                      ? "单臂举起并保持"
                      : "双臂举起并保持",
                    "arms_up_hold",
                  )}
                </option>
                <option value="arms_down_hold">双臂自然下垂（仅测量）</option>
                {pose === "ardhakati_chakrasana" && (
                  <option value="side_bend_hold">
                    {phaseLabel("侧弯保持", "side_bend_hold")}
                  </option>
                )}
                <option value="transition">动作切换中（不纠错）</option>
              </select>
            </label>
          </div>
          {pose === "ardhakati_chakrasana" && (
            <div className="choices">
              <label>
                举臂方式{" "}
                <select
                  value={movementVariant}
                  onChange={(e) => {
                    const next = e.target.value as Variant133;
                    setMovementVariant(next);
                    if (next !== "single_arm_overhead") setRaisedArm("unknown");
                  }}
                >
                  <option value="unknown">请选择</option>
                  <option value="both_arms_overhead">双臂举起</option>
                  <option value="single_arm_overhead">单臂举起</option>
                </select>
              </label>
              {movementVariant === "single_arm_overhead" && (
                <label>
                  举起的手臂{" "}
                  <select
                    value={raisedArm}
                    onChange={(e) =>
                      setRaisedArm(
                        e.target.value as "unknown" | "left" | "right",
                      )
                    }
                  >
                    <option value="unknown">请选择</option>
                    <option value="left">身体左臂</option>
                    <option value="right">身体右臂</option>
                  </select>
                </label>
              )}
              <label>
                计划倾斜方向（画面）{" "}
                <select
                  value={bendDirection}
                  onChange={(e) =>
                    setBendDirection(
                      e.target.value as
                        | "unknown"
                        | "image_left"
                        | "image_right",
                    )
                  }
                >
                  <option value="unknown">未指定</option>
                  <option value="image_left">画面左侧</option>
                  <option value="image_right">画面右侧</option>
                </select>
              </label>
            </div>
          )}
          {active ? (
            <Source133
              movementVariant={movementVariant}
              raisedArm={raisedArm}
              bendDirection={bendDirection}
              initialSource={inputSource}
              sessionId={run.current.id}
              pose={pose}
              phase={phase}
              onAnalysis={(event) => {
                setAnalysis(event);
                void live.current?.observe(event);
              }}
              onStatus={setStatus}
              onCaptureReady={(capture) => {
                captureRef.current = capture;
              }}
              onLost={() => {
                setAnalysis(null);
                live.current?.invalidate("画面已变化，等待新的 133 点结果。");
              }}
            />
          ) : (
            <div className="placeholder">
              <span className="pose-symbol" aria-hidden="true">
                ▣
              </span>
              <h3>等待图像来源</h3>
              <p>正面拍摄，保持全身入镜，并摆正摄像头。</p>
            </div>
          )}
          <p className="status" role="status">
            ● {status}
          </p>
          {persistenceWarning && (
            <p className="persistence-warning" role="alert">
              {persistenceWarning}。请结束前确认本地历史已保存。
            </p>
          )}
          <button
            disabled={busy}
            className={active ? "primary primary-exit" : "primary"}
            onClick={
              active
                ? () => {
                    voice.stop();
                    void finish();
                  }
                : start
            }
          >
            {active ? "结束并查看记录" : "开始练习"} <span>→</span>
          </button>
          <p className="note">
            {pose === "ardhakati_chakrasana"
              ? "侧弯纠错用于课程演示。请选择举臂方式；侧弯保持时需指定画面倾斜方向，单臂版还需指定举起侧。先选准备，动作稳定后再切到保持；回正或换侧时切到动作切换。"
              : "示范视频尚未接入，等待 A 提供授权资源。"}
          </p>
        </section>
        <aside>
          <MemoryPanel
            onOpenSession={(sessionId) => {
              window.location.hash = `#/history/${encodeURIComponent(sessionId)}`;
            }}
            onDeleted={() => {
              clearSummary();
              setAnalysis(null);
              setFeedbackState({
                text: "服务器记录已清除。",
                latestAdvice: "",
                previousAdvice: "",
                sessionId: run.current.id,
              });
            }}
            active={active || busy}
            refreshKey={(summary?.id || "") + serverSummary}
          />
          <section className="card feedback">
            <h2>实时建议</h2>
            <div className="feedback-previous">
              <h3>上一条建议</h3>
              <p>{previousAdvice || "暂无上一条建议。"}</p>
            </div>
            <div className="feedback-current">
              <h3>本次提醒</h3>
              <p className="feedback-text" aria-live="polite">
                {feedback.text}
              </p>
            </div>
            {analysis && (
              <p>
                {(
                  ["left_elbow_angle_deg", "right_elbow_angle_deg"] as const
                ).map((key, i) => {
                  const item = analysis.observations?.find(
                    (o) => o.name === key,
                  );
                  return (
                    <span key={key}>
                      {i ? " · " : ""}
                      {i ? "右肘" : "左肘"}：
                      {item?.valid && typeof item.value === "number"
                        ? item.value.toFixed(1) + "°"
                        : "暂不可测"}
                    </span>
                  );
                })}
              </p>
            )}
            <p>图像帧发送到本机后端，使用 RTMW 提取 133 点；不上传到 LLM。</p>
          </section>

          <section className="card">
            <h2>连接状态</h2>
            <p>网页 5173 → 后端 8000</p>
            <p role="status">{health}</p>
            <button
              onClick={() => {
                setHealth("正在检查…");
                void api
                  .health()
                  .then(async (r) => {
                    if (r.mode === "mock") {
                      setHealth("联调桩在线（非真实推理）");
                      return;
                    }
                    const state = await api.ready();
                    setHealth(
                      `${state.model.name}：${state.model.available ? "模型可用" : "模型未就绪，请检查 LFS 下载"}；LLM ${state.llm.configured ? "已配置" : "使用模板"}。`,
                    );
                  })
                  .catch((e) => setHealth(e.message));
              }}
            >
              检查后端
            </button>
            <p className="note">
              真实模式保存会话到
              SQLite。山式举臂保持支持已审核的持续肘部偏差提醒；侧弯规则仍等待审核。
            </p>
          </section>

          {serverSummary && (
            <section className="card">
              <h2>服务器总结</h2>
              <p>{serverSummary}</p>
            </section>
          )}
          {summary && (
            <section className="card">
              <h2>本次记录</h2>
              <p>
                {names[summary.pose]} · {summary.seconds} 秒
              </p>
              <p>显示提醒 {summary.feedbacks} 次。此记录不代表动作改善。</p>
            </section>
          )}
        </aside>
      </div>
      <footer>
        YogaCoach · 辅助观察与学习，不提供医疗诊断。感到不适时请暂停。
      </footer>
    </main>
  );
}
