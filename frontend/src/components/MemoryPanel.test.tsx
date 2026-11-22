// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
const mocks = vi.hoisted(() => ({
  remove: vi.fn().mockResolvedValue({}),
  preference: vi.fn().mockResolvedValue({}),
}));
vi.mock("../services/api", () => ({
  api: {
    preferences: vi.fn().mockResolvedValue({ preferences: {} }),
    sessions: vi.fn().mockResolvedValue({ items: [] }),
    incomplete: vi.fn().mockResolvedValue({ items: [] }),
    preference: mocks.preference,
    deleteData: mocks.remove,
  },
}));
import MemoryPanel from "./MemoryPanel";
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("保存明确偏好，删除必须二次确认", async () => {
  const deleted = vi.fn(),
    screen = render(
      <MemoryPanel active={false} refreshKey="" onDeleted={deleted} />,
    );
  await waitFor(() => expect(screen.getByRole("combobox")).toBeTruthy());
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "short" },
  });
  expect(mocks.preference).toHaveBeenCalledWith("short");
  fireEvent.click(screen.getByText("删除服务器记录和偏好"));
  expect(mocks.remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("确认删除"));
  await waitFor(() => expect(deleted).toHaveBeenCalledOnce());
  expect(mocks.remove).toHaveBeenCalledOnce();
});
it("开始练习后，已经打开的删除确认也被禁用", () => {
  const screen = render(<MemoryPanel active={false} refreshKey="" />);
  fireEvent.click(screen.getByText("删除服务器记录和偏好"));
  screen.rerender(<MemoryPanel active={true} refreshKey="" />);
  expect((screen.getByText("确认删除") as HTMLButtonElement).disabled).toBe(
    true,
  );
  fireEvent.click(screen.getByText("确认删除"));
  expect(mocks.remove).not.toHaveBeenCalled();
});
