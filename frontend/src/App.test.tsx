// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  waitFor,
} from "@testing-library/react";
const voiceMock = vi.hoisted(() => ({
  text: (_text: string) => {},
  start: vi.fn(),
  stop: vi.fn(),
  cancel: vi.fn(),
  speak: vi.fn(),
}));
vi.mock("./services/speech", () => ({
  createSpeech: (text: (text: string) => void) => {
    voiceMock.text = text;
    return voiceMock;
  },
}));
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
  default: ({
    initialSource,
    movementVariant,
    raisedArm,
  }: {
    initialSource: string;
    movementVariant: string;
    raisedArm: string;
  }) => (
    <div
      data-testid="source"
      data-variant={movementVariant}
      data-raised-arm={raisedArm}
    >
      {initialSource}
    </div>
  ),
}));
import App from "./App";

it("侧弯默认双臂，切换回双臂清空单侧参数以避免422", async () => {
  const screen = render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /站立侧弯式/ }));
  expect((screen.getByLabelText("举臂方式") as HTMLSelectElement).value).toBe(
    "both_arms_overhead",
  );
  fireEvent.click(screen.getByRole("button", { name: /开始练习/ }));
  await waitFor(() => expect(screen.getByTestId("source")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("举臂方式"), {
    target: { value: "single_arm_overhead" },
  });
  fireEvent.change(screen.getByLabelText("举起的手臂"), {
    target: { value: "left" },
  });
  expect(screen.getByTestId("source").dataset.raisedArm).toBe("left");
  fireEvent.change(screen.getByLabelText("举臂方式"), {
    target: { value: "both_arms_overhead" },
  });
  expect(screen.getByTestId("source").dataset.raisedArm).toBe("unknown");
  expect(screen.getByTestId("source").dataset.variant).toBe(
    "both_arms_overhead",
  );
});

it("语音切换阶段，拒绝否定口令并结束练习", async () => {
  const screen = render(<App />);
  expect(
    (screen.getByRole("button", { name: "开启语音" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: /开始练习/ }));
  await waitFor(() => expect(screen.getByTestId("source")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: "开启语音" }));
  expect(voiceMock.start).toHaveBeenCalledOnce();
  act(() => voiceMock.text("教练开始举臂保持"));
  expect((screen.getByLabelText("练习阶段") as HTMLSelectElement).value).toBe(
    "arms_up_hold",
  );
  act(() => voiceMock.text("教练不要准备"));
  expect((screen.getByLabelText("练习阶段") as HTMLSelectElement).value).toBe(
    "arms_up_hold",
  );
  act(() => voiceMock.text("教练结束练习"));
  await waitFor(() => expect(mock.finish).toHaveBeenCalledOnce());
  expect(voiceMock.stop).toHaveBeenCalled();
});
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
