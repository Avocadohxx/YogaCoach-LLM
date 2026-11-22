import { afterEach, describe, expect, it, vi } from "vitest";
import { createLiveSession } from "./liveSession";
import { type Analysis, type Feedback } from "./api";
const event: Analysis = {
  session_id: "s",
  pose_id: "tadasana",
  timestamp_ms: 0,
  tracking_quality: "good",
  feedback_allowed: true,
  analysis_mode: "reviewed_rules_133",
  observations: [
    { name: "left_elbow_angle_deg", value: 160, unit: "deg", valid: true },
    { name: "right_elbow_angle_deg", value: 175, unit: "deg", valid: true },
  ],
  deviations: [{ type: "shoulder_asymmetry", duration_ms: 1800 }],
};
const reply: Feedback = {
  should_speak: true,
  feedback_type: "correction",
  text: "测试指导",
};
function deferred<T>() {
  let resolve!: (x: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}
function setup() {
  const show = vi.fn(),
    count = vi.fn(),
    transport = { health: vi.fn(), feedback: vi.fn().mockResolvedValue(reply) };
  return {
    show,
    count,
    transport,
    session: createLiveSession(show, count, transport),
  };
}
afterEach(() => vi.useRealTimers());
describe("133 点后端结果接入", () => {
  it("新画面清晰时丢弃旧镜头提示", async () => {
    const t = setup(),
      pending = deferred<Feedback>();
    t.transport.feedback.mockReturnValue(pending.promise);
    const work = t.session.observe({
      ...event,
      tracking_quality: "partial",
      feedback_allowed: false,
      deviations: [],
    });
    await t.session.observe({
      ...event,
      tracking_quality: "good",
      feedback_allowed: false,
      deviations: [],
    });
    pending.resolve(reply);
    await work;
    expect(t.count).not.toHaveBeenCalled();
    expect(t.show).toHaveBeenLastCalledWith(
      "当前未触发持续偏差；这不代表整体动作完全标准。",
    );
  });
  it("视频暂停或拖动后，迟到提示不能显示", async () => {
    const t = setup(),
      pending = deferred<Feedback>();
    t.transport.feedback.mockReturnValue(pending.promise);
    const work = t.session.observe({
      ...event,
      tracking_quality: "poor",
      feedback_allowed: false,
      deviations: [],
    });
    t.session.invalidate("视频已暂停");
    pending.resolve(reply);
    await work;
    expect(t.count).not.toHaveBeenCalled();
    expect(t.show).toHaveBeenLastCalledWith("视频已暂停");
  });
});

describe("持续纠错事件", () => {
  it("相同类型的新事件不能采用前一个事件的迟到反馈", async () => {
    const t = setup(),
      pending = deferred<Feedback>();
    t.transport.feedback.mockReturnValue(pending.promise);
    const first = {
      ...event,
      deviations: [{ ...event.deviations[0], event_id: "episode-1" }],
    };
    const work = t.session.observe(first);
    await t.session.observe({
      ...first,
      deviations: [{ ...first.deviations[0], event_id: "episode-2" }],
    });
    pending.resolve(reply);
    await work;
    expect(t.count).not.toHaveBeenCalled();
  });
  it("显示确认中的状态，而不提前给出纠错", async () => {
    const t = setup();
    await t.session.observe({
      ...event,
      feedback_allowed: false,
      deviations: [],
      rule_evaluation: {
        pending_count: 1,
        phase: "arms_up_hold",
        scope: "enabled_phase_rules_only_not_full_posture",
      },
    });
    expect(t.transport.feedback).not.toHaveBeenCalled();
    expect(t.show).toHaveBeenLastCalledWith(
      "肘部角度偏离参考范围，正在确认是否持续。",
    );
  });
});

describe("测量不可评估时的提示", () => {
  it.each([
    ["source_model_missing_or_mismatch", "当前模型不符合已配置的山式规则。"],
    ["front_view_required", "请正对摄像头练习山式。"],
    [
      "required_measurement_invalid",
      "请调整摄像头，让双肩、手肘和手腕完整入镜。",
    ],
  ])("优先显示候选规则的具体原因：%s", async (reason, text) => {
    const t = setup();
    await t.session.observe({
      ...event,
      feedback_allowed: false,
      deviations: [],
      observations: [],
      rule_evaluation: {
        pending_count: 0,
        phase: "arms_up_hold",
        scope: "enabled_phase_rules_only_not_full_posture",
        rule_results: [
          {
            mode: "candidate",
            status: "not_assessable",
            feature_name: "left_elbow_angle_deg",
            reason,
          },
        ],
      },
    });
    expect(t.show).toHaveBeenLastCalledWith(text);
    expect(t.transport.feedback).not.toHaveBeenCalled();
  });
});
