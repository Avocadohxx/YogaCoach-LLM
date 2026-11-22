import { afterEach, expect, it, vi } from "vitest";
import { createCaptureLoop, createFrameClock, releaseVideo } from "./capture";
afterEach(() => vi.useRealTimers());
it("重复帧和倒退不会累计时间，重置后接受新的媒体时间", () => {
  const clock = createFrameClock();
  expect(clock.sample(2)).toBe(2000);
  expect(clock.sample(2)).toBeNull();
  expect(clock.sample(1)).toBeNull();
  clock.reset();
  expect(clock.sample(1)).toBe(1000);
});
it("冻结画面不重复提交，超过750ms撤回证据", async () => {
  vi.useFakeTimers();
  const capture = vi.fn().mockResolvedValue(undefined),
    lost = vi.fn();
  const video = {
    currentTime: 1,
    getVideoPlaybackQuality: () => ({
      totalVideoFrames: 1,
      droppedVideoFrames: 0,
    }),
    paused: false,
    ended: false,
    readyState: 4,
  } as HTMLVideoElement;
  const loop = createCaptureLoop({
    video: () => video,
    capture,
    lost,
    error: vi.fn(),
  });
  loop.start();
  await vi.advanceTimersByTimeAsync(2000);
  expect(capture).toHaveBeenCalledOnce();
  expect(lost).toHaveBeenCalledOnce();
  loop.close();
});
it("失败后有上限重试，关闭后迟到任务不再调度", async () => {
  vi.useFakeTimers();
  let time = 0;
  const capture = vi.fn().mockRejectedValue(new Error("temporary"));
  const loop = createCaptureLoop({
    video: () =>
      ({
        currentTime: ++time,
        getVideoPlaybackQuality: () => ({
          totalVideoFrames: time,
          droppedVideoFrames: 0,
        }),
        paused: false,
        ended: false,
        readyState: 4,
      }) as HTMLVideoElement,
    capture,
    lost: vi.fn(),
    error: vi.fn(),
  });
  loop.start();
  await vi.advanceTimersByTimeAsync(20000);
  expect(capture).toHaveBeenCalledTimes(4);
  loop.close();
  await vi.advanceTimersByTimeAsync(10000);
  expect(capture).toHaveBeenCalledTimes(4);
});
it("释放旧摄像头并清除srcObject，允许切换视频文件", () => {
  const stop = vi.fn(),
    video = {
      pause: vi.fn(),
      srcObject: { getTracks: () => [{ stop }] },
      removeAttribute: vi.fn(),
      load: vi.fn(),
    } as unknown as HTMLVideoElement;
  releaseVideo(video);
  expect(stop).toHaveBeenCalledOnce();
  expect(video.srcObject).toBeNull();
  expect(video.removeAttribute).toHaveBeenCalledWith("src");
});
it("媒体时钟继续但没有新呈现帧时不重复分析", async () => {
  vi.useFakeTimers();
  let time = 0;
  const capture = vi.fn().mockResolvedValue(undefined);
  const video = {
    get currentTime() {
      return ++time;
    },
    paused: false,
    ended: false,
    readyState: 4,
    getVideoPlaybackQuality: () => ({
      totalVideoFrames: 1,
      droppedVideoFrames: 0,
    }),
  } as HTMLVideoElement;
  const loop = createCaptureLoop({
    video: () => video,
    capture,
    lost: vi.fn(),
    error: vi.fn(),
  });
  loop.start();
  await vi.advanceTimersByTimeAsync(1500);
  expect(capture).toHaveBeenCalledOnce();
  loop.close();
});
it("由新呈现帧回调驱动采样，关闭时取消回调", async () => {
  vi.useFakeTimers();
  let callback!: VideoFrameRequestCallback;
  const capture = vi.fn().mockResolvedValue(undefined),
    cancel = vi.fn();
  const video = {
    currentTime: 99,
    paused: false,
    ended: false,
    readyState: 4,
    requestVideoFrameCallback: vi.fn((cb) => {
      callback = cb;
      return 1;
    }),
    cancelVideoFrameCallback: cancel,
  } as unknown as HTMLVideoElement;
  const loop = createCaptureLoop({
    video: () => video,
    capture,
    lost: vi.fn(),
    error: vi.fn(),
  });
  loop.start();
  await vi.advanceTimersByTimeAsync(100);
  expect(capture).not.toHaveBeenCalled();
  callback(0, { mediaTime: 1 } as VideoFrameCallbackMetadata);
  await vi.advanceTimersByTimeAsync(100);
  expect(capture).toHaveBeenCalledWith(1000, expect.any(AbortSignal));
  await vi.advanceTimersByTimeAsync(500);
  expect(capture).toHaveBeenCalledOnce();
  loop.close();
  expect(cancel).toHaveBeenCalled();
});
