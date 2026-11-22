// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
const sessionDetail = vi.hoisted(() =>
  vi.fn().mockResolvedValue({
    session: {
      session_id: "session-1",
      pose_id: "tadasana",
      started_at: "2026-11-22T09:00:00Z",
      ended_at: "2026-11-22T09:05:00Z",
      summary: "系统给出提示 1 次。",
    },
    events: [
      {
        event_id: "event-1",
        event_type: "elbow_bend",
        side: "left",
        severity: null,
        confidence: null,
        timestamp_ms: 1200,
        duration_ms: 1800,
      },
    ],
    snapshots: [
      {
        snapshot_id: "snap-1",
        session_id: "session-1",
        pose_id: "tadasana",
        event_type: "elbow_bend",
        side: "left",
        severity: null,
        confidence: null,
        timestamp_ms: 1200,
        feedback_text: "放松手肘，保持舒适。",
        created_at: "2026-11-22T09:00:02Z",
        image_url: "/api/memory/snapshots/snap-1/image",
      },
    ],
    feedback: [
      {
        feedback_id: "feedback-1",
        session_id: "session-1",
        event_type: "elbow_bend",
        feedback_text: "放松手肘，保持舒适。",
        created_at: "2026-11-22T09:00:02Z",
      },
    ],
  }),
);
vi.mock("./services/api", () => ({
  api: { sessionDetail },
}));
import HistoryDetail from "./HistoryDetail";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("显示训练总结、错误截图和建议时间线", async () => {
  const screen = render(
    <HistoryDetail sessionId="session-1" onBack={vi.fn()} />,
  );
  await waitFor(() =>
    expect(screen.getByText("本次训练总结")).toBeTruthy(),
  );
  expect(screen.getByText("系统给出提示 1 次。")).toBeTruthy();
  expect(screen.getByAltText("错误动作截图 1").getAttribute("src")).toBe(
    "/api/memory/snapshots/snap-1/image",
  );
  expect(screen.getAllByText("放松手肘，保持舒适。")).toHaveLength(2);
});
