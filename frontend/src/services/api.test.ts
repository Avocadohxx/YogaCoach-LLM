import { describe, it, expect, vi, afterEach } from "vitest";
import { api, parseFeedback } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("边界处理", () => {
  it("拒绝不合法的反馈，而不是直接展示", () => {
    expect(() =>
      parseFeedback({
        should_speak: true,
        text: "test",
        feedback_type: "unknown",
      } as never),
    ).toThrow();
  });
  it("将真实后端错误展示为明确状态", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404 }),
    );
    await expect(api.health()).rejects.toThrow("404");
  });
  it("上传截图时让浏览器生成 multipart boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        snapshot_id: "snap-1",
        image_url: "/image",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await api.saveSnapshot(
      "session-1",
      new Blob(["jpeg"], { type: "image/jpeg" }),
      {
        pose_id: "tadasana",
        event_type: "elbow_bend",
        timestamp_ms: 1200,
      },
    );
    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers).toBeUndefined();
    expect(options.body).toBeInstanceOf(FormData);
  });
});
