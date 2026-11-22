// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
const sessions = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ items: [] }),
);
vi.mock("./services/api", () => ({
  api: { sessions },
}));
import HistoryIndex from "./HistoryIndex";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("没有已完成训练时仍显示历史页和空状态", async () => {
  render(<HistoryIndex onBack={vi.fn()} onOpenSession={vi.fn()} />);
  expect(
    await screen.findByText(/暂无已完成的训练记录/),
  ).toBeTruthy();
});

it("从历史列表打开对应的训练详情", async () => {
  sessions.mockResolvedValueOnce({
    items: [
      {
        session_id: "session-1",
        pose_id: "tadasana",
        started_at: "2026-11-22T09:00:00Z",
        ended_at: "2026-11-22T09:05:00Z",
        summary: "系统给出提示 1 次。",
      },
    ],
  });
  const onOpenSession = vi.fn();
  render(
    <HistoryIndex onBack={vi.fn()} onOpenSession={onOpenSession} />,
  );
  fireEvent.click(await screen.findByText("查看建议与错误截图 →"));
  expect(onOpenSession).toHaveBeenCalledWith("session-1");
});
