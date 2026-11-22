import { useEffect, useRef, useState } from "react";
import { api, type Pose, type Analysis, type Summary } from "../services/api";
import { createLiveSession } from "../services/liveSession";
type Options = {
  pose: Pose;
  setFeedback: (text: string, isAdvice?: boolean) => void;
  setStatus: (text: string) => void;
  setServerSummary: (text: string) => void;
  setAnalysis: (value: Analysis | null) => void;
  capture: () => Promise<Blob | null>;
  setPersistenceWarning: (message: string | null) => void;
};
export function usePracticeSession({
  pose,
  setFeedback,
  setStatus,
  setServerSummary,
  setAnalysis,
  capture,
  setPersistenceWarning,
}: Options) {
  const [active, setActive] = useState(false),
    [busy, setBusy] = useState(false),
    [seconds, setSeconds] = useState(0),
    [summary, setSummary] = useState<Summary | null>(null);
  const mounted = useRef(true);
  const run = useRef({ id: "", started: 0, count: 0 });
  const live = useRef<ReturnType<typeof createLiveSession> | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      live.current?.close();
    };
  }, []);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(
      () => setSeconds(Math.floor((Date.now() - run.current.started) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [active]);
  useEffect(() => {
    if (!active) return;
    const id = run.current.id;
    const timer = setInterval(() => {
      void api.heartbeat(id).catch(() => {});
    }, 15000);
    return () => clearInterval(timer);
  }, [active]);
  async function start() {
    setBusy(true);
    setPersistenceWarning(null);
    setServerSummary("");
    setAnalysis(null);
    const id = crypto.randomUUID(),
      started = Date.now();
    try {
      const ready = await api.ready();
      if (!ready.model.available)
        throw new Error("模型未就绪，请先完成 Git LFS 下载。");
      await api.createSession(id, pose);
      if (!mounted.current) return;
      live.current?.close();
      run.current = { id, started, count: 0 };
      live.current = createLiveSession(
        setFeedback,
        () => {
          run.current.count++;
        },
        api,
        {
          sessionId: id,
          pose,
          capture,
          onPersistenceError: setPersistenceWarning,
        },
      );
      setSeconds(0);
      setSummary(null);
      setFeedback("等待新的观察结果…");
      setStatus("会话已创建，准备图像来源…");
      setActive(true);
    } catch (error) {
      if (mounted.current)
        setStatus(error instanceof Error ? error.message : "创建会话失败。");
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function finish() {
    setBusy(true);
    const currentLive = live.current;
    currentLive?.close();
    const current = run.current;
    const item: Summary = {
      id: current.id,
      pose,
      seconds: Math.floor((Date.now() - current.started) / 1000),
      feedbacks: current.count,
    };
    setActive(false);
    setSummary(item);
    setStatus("已结束练习，摄像头已关闭。");
    try {
      await currentLive?.flush();
      const result = await api.finishSession(current.id);
      if (!mounted.current) return;
      setServerSummary(result.summary || "没有可用的总结。");
      setStatus("会话已保存到服务器。");
    } catch (error) {
      if (mounted.current)
        setStatus(
          "记录保存或读取失败：" +
            (error instanceof Error ? error.message : "请检查后端。"),
        );
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return {
    active,
    busy,
    seconds,
    summary,
    run,
    live,
    start,
    finish,
    clearSummary() {
      setSummary(null);
      setServerSummary("");
    },
  };
}
