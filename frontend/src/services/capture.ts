export class CaptureError extends Error {
  constructor(
    message: string,
    public retryable: boolean,
    public retryAfterMs = 0,
  ) {
    super(message);
  }
}
// Media time proves frame progression; wall time only measures freshness/latency.
export function createFrameClock() {
  let last = -1;
  return {
    reset() {
      last = -1;
    },
    sample(seconds: number) {
      if (!Number.isFinite(seconds) || seconds < 0) return null;
      const ms = Math.round(seconds * 1000);
      if (ms <= last) return null;
      last = ms;
      return ms;
    },
  };
}
export function releaseVideo(video: HTMLVideoElement) {
  video.pause();
  (video.srcObject as MediaStream | null)?.getTracks().forEach((t) => t.stop());
  video.srcObject = null;
  video.removeAttribute("src");
  video.load();
}
export function percentile(values: number[], q: number) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[
    Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1)))
  ];
}
export function createCaptureLoop(options: {
  video: () => HTMLVideoElement;
  capture: (timestamp: number, signal: AbortSignal) => Promise<void>;
  lost: () => void;
  error: (message: string) => void;
}) {
  const clock = createFrameClock();
  const intervals: number[] = [],
    latency: number[] = [];
  let lastSample: number | null = null;
  let stopped = false,
    lastFresh = performance.now(),
    notified = false,
    failures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const controller = new AbortController();
  let decodedTime: number | null = null,
    frameCallback: number | undefined,
    lastPresented = -1;
  const source = options.video();
  const hasCallback = typeof source.requestVideoFrameCallback === "function";
  function watch(_now: number, metadata: VideoFrameCallbackMetadata) {
    if (stopped) return;
    decodedTime = metadata.mediaTime;
    frameCallback = source.requestVideoFrameCallback(watch);
  }
  const schedule = (delay: number) => {
    if (!stopped) timer = setTimeout(tick, delay);
  };
  async function tick() {
    if (stopped) return;
    const video = options.video();
    let time: number | null = null;
    if (
      !video.seeking &&
      !video.paused &&
      !video.ended &&
      video.readyState >= 2
    ) {
      if (hasCallback) time = decodedTime;
      else if (typeof video.getVideoPlaybackQuality === "function") {
        const quality = video.getVideoPlaybackQuality();
        const presented =
          quality.totalVideoFrames - (quality.droppedVideoFrames || 0);
        if (presented > lastPresented) {
          lastPresented = presented;
          time = video.currentTime;
        }
      }
    }
    const timestamp = time === null ? null : clock.sample(time);
    if (timestamp === null) {
      if (!notified && performance.now() - lastFresh > 750) {
        notified = true;
        lastSample = null;
        options.lost();
      }
      schedule(100);
      return;
    }
    lastFresh = performance.now();
    notified = false;
    if (lastSample !== null) intervals.push(lastFresh - lastSample);
    lastSample = lastFresh;
    if (intervals.length > 256) intervals.shift();
    const requestStart = performance.now();
    try {
      await options.capture(timestamp, controller.signal);
      latency.push(performance.now() - requestStart);
      if (latency.length > 256) latency.shift();
      failures = 0;
      schedule(100);
    } catch (error) {
      if (stopped) return;
      options.lost();
      failures++;
      options.error(error instanceof Error ? error.message : "图像分析失败。");
      // Stop after bounded retries; the component exposes an explicit retry.
      if (failures < 4 && !(error instanceof CaptureError && !error.retryable))
        schedule(
          Math.max(
            error instanceof CaptureError ? error.retryAfterMs : 0,
            Math.min(4000, 250 * 2 ** failures),
          ),
        );
    }
  }
  return {
    stats() {
      return {
        samples: latency.length,
        wall_interval_p50_ms: percentile(intervals, 0.5),
        wall_interval_p95_ms: percentile(intervals, 0.95),
        request_p50_ms: percentile(latency, 0.5),
        request_p95_ms: percentile(latency, 0.95),
        scope: "browser_capture_request_loop_not_detection_accuracy",
      };
    },
    start() {
      if (hasCallback) frameCallback = source.requestVideoFrameCallback(watch);
      else if (typeof source.getVideoPlaybackQuality !== "function") {
        options.error("当前浏览器无法确认新视频帧，请使用较新版本浏览器。");
        return;
      }
      void tick();
    },
    reset() {
      clock.reset();
      decodedTime = null;
      lastPresented = -1;
      lastSample = null;
      options.lost();
    },
    close() {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
      if (frameCallback !== undefined)
        source.cancelVideoFrameCallback(frameCallback);
    },
  };
}
