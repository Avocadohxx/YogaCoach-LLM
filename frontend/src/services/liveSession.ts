import { api, parseFeedback, type Analysis, type Pose } from "./api";

// One instance per practice. Async completions may only update their own generation.
type LiveTransport = Pick<typeof api, "feedback"> &
  Partial<Pick<typeof api, "saveSnapshot" | "updateSnapshotFeedback">>;
type HistoryCapture = {
  sessionId: string;
  pose: Pose;
  capture: () => Promise<Blob | null>;
  onPersistenceError: (message: string | null) => void;
};

export function createLiveSession(
  show: (text: string, isAdvice?: boolean) => void,
  counted: () => void,
  transport: LiveTransport = api,
  history?: HistoryCapture,
) {
  let generation = 0,
    closed = false,
    controller = new AbortController();
  let feedbackBusy = false,
    lastFeedback = -Infinity;
  let evidence = "",
    evidenceVersion = 0;
  let evidenceSnapshot: {
    signature: string;
    promise: Promise<{ snapshot_id: string } | null>;
  } | null = null;
  const pendingWrites = new Set<Promise<unknown>>();
  const persistenceErrors = new Map<string, string>();
  function trackWrite<T>(promise: Promise<T>) {
    pendingWrites.add(promise);
    void promise.finally(() => pendingWrites.delete(promise)).catch(() => {});
    return promise;
  }
  function reportPersistenceError(kind: string, error: unknown) {
    persistenceErrors.set(
      kind,
      `${kind}失败：${error instanceof Error ? error.message : String(error)}`,
    );
    history?.onPersistenceError([...persistenceErrors.values()].join("；"));
  }
  function clearPersistenceError(kind: string) {
    if (persistenceErrors.delete(kind))
      history?.onPersistenceError(
        [...persistenceErrors.values()].join("；") || null,
      );
  }
  async function persist<T>(
    kind: string,
    promise: Promise<T>,
  ): Promise<T | undefined> {
    try {
      const result = await trackWrite(promise);
      clearPersistenceError(kind);
      return result;
    } catch (error) {
      reportPersistenceError(kind, error);
      return undefined;
    }
  }
  async function flush() {
    while (pendingWrites.size) await Promise.allSettled([...pendingWrites]);
  }
  function invalidate(text: string) {
    if (closed) return;
    generation++;
    controller.abort();
    controller = new AbortController();
    feedbackBusy = false;
    evidence = "";
    evidenceSnapshot = null;
    evidenceVersion++;
    lastFeedback = -Infinity;
    show(text);
  }
  function close() {
    closed = true;
    generation++;
    controller.abort();
  }
  async function observe(event: Analysis) {
    if (closed) return;
    const now = Date.now(),
      token = generation,
      signal = controller.signal;
    const trustedEvidence =
      event.feedback_allowed &&
      event.tracking_quality === "good" &&
      event.deviations.length > 0;
    const signature = trustedEvidence
      ? event.deviations
          .map((x) => (x.event_id || x.type) + ":" + (x.side || ""))
          .sort()
          .join("|")
      : ["partial", "poor"].includes(event.tracking_quality)
        ? "camera_hint"
        : "";
    const isNewEvidence = Boolean(signature && signature !== evidence);
    if (signature !== evidence) {
      evidence = signature;
      evidenceVersion++;
      if (!signature) evidenceSnapshot = null;
      show(
        signature
          ? "正在获取当前画面的提醒…"
          : "已获得 133 点测量，参考规则尚未校准。",
      );
    }
    if (isNewEvidence && trustedEvidence && history && transport.saveSnapshot) {
      const snapshotPromise = persist(
        "错误截图保存",
        Promise.resolve()
          .then(() => history.capture())
          .then((blob) => {
            if (!blob) throw new Error("无法读取当前摄像头画面");
            return transport.saveSnapshot!(history.sessionId, blob, {
              pose_id: event.pose_id,
              event_type: event.deviations.map((item) => item.type).join(", "),
              side: event.deviations[0]?.side,
              timestamp_ms: event.timestamp_ms,
            });
          }),
      ).then((result) => (result ? { snapshot_id: result.snapshot_id } : null));
      evidenceSnapshot = { signature, promise: snapshotPromise };
    }
    if (!signature) {
      const reasons = new Set([
        ...(event.reason_codes || []),
        ...(event.rule_evaluation?.rule_results
          ?.filter((rule) => rule.mode === "candidate" && rule.reason)
          .map((rule) => rule.reason) || []),
      ]);
      const hasElbowEvidence = (event.observations || []).some(
        (item) =>
          (item.name === "left_elbow_angle_deg" ||
            item.name === "right_elbow_angle_deg") &&
          item.valid,
      );
      const contextHint = reasons.has("movement_variant_required")
        ? "请选择侧弯的举臂方式（单臂或双臂）。"
        : reasons.has("raised_arm_side_required")
          ? "请选择当前举起的是身体左臂还是右臂。"
          : reasons.has("independent_intended_direction_required")
            ? "请选择计划倾斜的画面方向，再进行侧弯保持纠错。"
            : null;
      if (contextHint) {
        show(contextHint);
        return;
      }
      show(
        reasons.has("phase_mismatch_arms_down")
          ? "画面与举臂阶段不一致，请核对阶段或举臂位置。"
          : reasons.has("inference_frame_expired")
            ? "图像分析已过期，正在等待新画面。"
            : reasons.has("frame_gap_reset")
              ? "画面分析间隔较长，已重新积累持续证据。"
              : reasons.has("rules_require_manual_review")
                ? "当前动作规则尚未审核，仅显示测量。"
                : reasons.has("source_model_missing_or_mismatch")
                  ? "当前模型不符合已配置的动作规则。"
                  : reasons.has("front_view_required")
                    ? "请正对摄像头练习。"
                    : reasons.has("explicit_supported_phase_required")
                      ? event.pose_id === "ardhakati_chakrasana"
                        ? "请选择举臂保持或侧弯保持阶段，再查看持续纠错。"
                        : "请选择实际动作阶段；山式纠错支持双臂举起保持。"
                      : reasons.has("required_measurement_invalid") ||
                          !hasElbowEvidence
                        ? "请调整摄像头，让双肩、手肘和手腕完整入镜。"
                        : (event.rule_evaluation?.pending_count || 0) > 0
                          ? "肘部角度偏离参考范围，正在确认是否持续。"
                          : event.analysis_mode === "reviewed_rules_133"
                            ? "当前未触发持续偏差；这不代表整体动作完全标准。"
                            : "已获得角度测量，等待持续偏差确认。",
      );
      return;
    }
    if (feedbackBusy || now - lastFeedback < 10000) return;
    feedbackBusy = true;
    lastFeedback = now;
    const version = evidenceVersion;
    try {
      const result = parseFeedback(await transport.feedback(event, signal));
      if (closed || generation !== token || evidenceVersion !== version) return;
      if (Date.now() - now >= 8000) return;
      if (result.text) show(result.text, result.should_speak);
      if (result.should_speak) {
        counted();
        if (history && transport.updateSnapshotFeedback) {
          const snapshot =
            evidenceSnapshot?.signature === signature
              ? await evidenceSnapshot.promise
              : null;
          if (snapshot)
            await persist(
              "截图建议关联",
              transport.updateSnapshotFeedback(
                snapshot.snapshot_id,
                result.text,
              ),
            );
        }
      }
    } catch (error) {
      if (!closed && generation === token && !signal.aborted)
        invalidate(error instanceof Error ? error.message : "反馈请求失败。");
    } finally {
      if (generation === token) feedbackBusy = false;
    }
  }
  return { observe, invalidate, close, flush };
}
