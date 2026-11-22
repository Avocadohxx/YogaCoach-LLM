import { describe, it, expect, vi, afterEach } from "vitest";
import { api, parseFeedback, readHistory } from "./api";
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
  it("损坏的浏览器记录不会阻止启动", () => {
    vi.stubGlobal("localStorage", { getItem: () => "{bad" });
    expect(readHistory()).toEqual([]);
  });
  it("过滤不合法历史条目", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => JSON.stringify([{}, null]),
    });
    expect(readHistory()).toEqual([]);
  });
  it("将真实后端错误展示为明确状态", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404 }),
    );
    await expect(api.health()).rejects.toThrow("404");
  });
});
