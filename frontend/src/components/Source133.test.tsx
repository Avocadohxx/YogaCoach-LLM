// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import Source133 from "./Source133";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("摄像头切换到本地文件会释放轨道并清空srcObject", async () => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    clearRect: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop, addEventListener: vi.fn() }] };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:test-video"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
  const screen = render(
    <Source133
      initialSource="camera"
      sessionId="s"
      pose="tadasana"
      phase="prepare"
      movementVariant="unknown"
      raisedArm="unknown"
      bendDirection="unknown"
      onAnalysis={vi.fn()}
      onStatus={vi.fn()}
      onLost={vi.fn()}
    />,
  );
  const video = screen.container.querySelector("video")!;
  await waitFor(() => expect(video.srcObject).toBe(stream));
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "video" },
  });
  fireEvent.change(screen.container.querySelector("input")!, {
    target: { files: [new File(["x"], "sample.mp4", { type: "video/mp4" })] },
  });
  await waitFor(() => expect(video.src).toContain("blob:test-video"));
  expect(video.srcObject).toBeNull();
  expect(stop).toHaveBeenCalled();
  screen.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test-video");
});
