import { api, parseFeedback, type Analysis } from "./api";

// One instance per practice. Async completions may only update their own generation.
export function createLiveSession(
  show: (text: string) => void,
  counted: () => void,
  transport: Pick<typeof api, "feedback"> = api,
) {
  let generation = 0,
    closed = false,
    controller = new AbortController();
  let feedbackBusy = false,
    lastFeedback = -Infinity;
  let evidence = "",
    evidenceVersion = 0;
  function invalidate(text: string) {
    if (closed) return;
    generation++;
    controller.abort();
    controller = new AbortController();
    feedbackBusy = false;
    evidence = "";
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
    const signature = event.feedback_allowed
      ? event.deviations
          .map((x) => (x.event_id || x.type) + ":" + (x.side || ""))
          .sort()
          .join("|")
      : ["partial", "poor"].includes(event.tracking_quality)
        ? "camera_hint"
        : "";
    if (signature !== evidence) {
      evidence = signature;
      evidenceVersion++;
      show(
        signature
          ? "正在获取当前画面的提醒…"
          : "已获得 133 点测量，参考规则尚未校准。",
      );
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
                  ? "当前模型不符合已配置的山式规则。"
                  : reasons.has("front_view_required")
                    ? "请正对摄像头练习山式。"
                    : reasons.has("explicit_supported_phase_required")
                      ? "请选择实际动作阶段；山式纠错支持双臂举起保持。"
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
      if (result.text) show(result.text);
      if (result.should_speak) counted();
    } catch (error) {
      if (!closed && generation === token && !signal.aborted)
        invalidate(error instanceof Error ? error.message : "反馈请求失败。");
    } finally {
      if (generation === token) feedbackBusy = false;
    }
  }
  return { observe, invalidate, close };
}
