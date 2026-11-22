// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
const mock = vi.hoisted(() => ({
  create: vi.fn().mockResolvedValue({}),
  finish: vi.fn().mockResolvedValue({ summary: "事实总结" }),
  sessions: vi.fn().mockResolvedValue({ items: [] }),
}));
vi.mock("./services/api", () => ({
  api: {
    createSession: mock.create,
    finishSession: mock.finish,
    sessions: mock.sessions,
    heartbeat: vi.fn().mockResolvedValue({}),
    ready: vi.fn().mockResolvedValue({ model: { available: true } }),
  },
}));
vi.mock("./components/MemoryPanel", () => ({ default: () => null }));
vi.mock("./components/Source133", () => ({
  default: ({ initialSource }: { initialSource: string }) => (
    <div data-testid="source">{initialSource}</div>
  ),
}));
import App from "./App";
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("视频练习创建和结束会话，阶段在练习中可选择", async () => {
  const screen = render(<App />);
  expect(screen.queryByLabelText("运行方式")).toBeNull();
  fireEvent.change(screen.getByLabelText("图像来源"), {
    target: { value: "video" },
  });
  fireEvent.click(screen.getByRole("button", { name: /开始练习/ }));
  await waitFor(() =>
    expect(screen.getByTestId("source").textContent).toBe("video"),
  );
  expect(mock.create).toHaveBeenCalledOnce();
  expect(
    (screen.getByLabelText("练习阶段") as HTMLSelectElement).disabled,
  ).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: /结束并查看记录/ }));
  await waitFor(() => expect(mock.finish).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.getByText("事实总结")).toBeTruthy());
});
