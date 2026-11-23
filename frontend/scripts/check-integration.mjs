import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const base = process.env.BACKEND_URL || "http://127.0.0.1:8001";
const sample = JSON.parse(
  await readFile(
    new URL("../../contracts/mock/landmarks_tadasana.json", import.meta.url),
    "utf8",
  ),
);
async function request(path, body) {
  const response = await fetch(base + path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(15000),
  });
  assert.equal(response.ok, true, `${path}: HTTP ${response.status}`);
  return response.json();
}
const sample133 = JSON.parse(
  await readFile(
    new URL("../../contracts/mock/landmarks_133.json", import.meta.url),
    "utf8",
  ),
);
const health = await request("/api/health");
assert.equal(health.status, "ok");
console.log(
  "Backend mode (real uses 133-point fixture; mock uses legacy fixture):",
  health.mode || "unspecified (confirm with backend owner)",
);
for (const pose of ["tadasana", "ardhakati_chakrasana"]) {
  const body =
    health.mode === "mock"
      ? {
          landmarks: sample.landmarks,
          session_id: "integration-" + crypto.randomUUID(),
          pose_id: pose,
          timestamp_ms: 1800,
          frame_seq: 0,
          phase: "prepare",
          side: pose === "tadasana" ? null : "left",
          camera_view: "front",
          image_width: 640,
          image_height: 480,
        }
      : {
          ...sample133,
          session_id: "integration-" + crypto.randomUUID(),
          pose_id: pose,
        };
  const event = await request("/api/analyze", body);
  assert.equal(typeof event.feedback_allowed, "boolean");
  assert.ok(Array.isArray(event.deviations));
  if (event.feedback_allowed && event.deviations.length) {
    const feedback = await request("/api/agent/feedback", event);
    assert.equal(typeof feedback.should_speak, "boolean");
    assert.equal(typeof feedback.text, "string");
    assert.ok(
      ["correction", "camera_hint", "none"].includes(feedback.feedback_type),
    );
  }
  console.log(
    pose,
    "contract smoke passed (fixture coordinates, not pose accuracy validation)",
  );
}
