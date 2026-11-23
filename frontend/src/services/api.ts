export type Pose = "tadasana" | "ardhakati_chakrasana";
export type Phase133 =
  | "prepare"
  | "hold"
  | "transition"
  | "arms_down_hold"
  | "arms_up_hold"
  | "side_bend_hold"
  | "return_upright";
export type Variant133 =
  | "unknown"
  | "both_arms_overhead"
  | "single_arm_overhead";
export type Analysis = {
  session_id: string;
  pose_id: Pose;
  timestamp_ms: number;
  tracking_quality: string;
  feedback_allowed: boolean;
  observations?: {
    name: string;
    value: number | null;
    unit: string;
    valid: boolean;
  }[];
  analysis_mode?: string;
  reason_codes?: string[];
  rule_evaluation?: {
    pending_count: number;
    scope: string;
    phase: string;
    rule_results?: {
      mode: string;
      reason?: string | null;
      status: string;
      feature_name: string;
    }[];
  } | null;
  deviations: {
    event_id?: string;
    target?: string;
    type: string;
    side?: string;
    duration_ms: number;
  }[];
};
export type Feedback = {
  should_speak: boolean;
  feedback_type: "correction" | "camera_hint" | "none";
  text: string;
  target?: string;
  grounded_event_type?: string;
};
export type StoredSession = {
  session_id: string;
  pose_id: Pose;
  started_at: string | null;
  ended_at: string | null;
  summary: string | null;
};
export type Snapshot = {
  snapshot_id: string;
  session_id: string;
  pose_id: string | null;
  event_type: string | null;
  side: string | null;
  severity: string | null;
  confidence: number | null;
  timestamp_ms: number | null;
  feedback_text: string | null;
  created_at: string;
  image_url: string;
};
export type PoseEvent = {
  event_id: string;
  event_type: string;
  side: string | null;
  severity: string | null;
  confidence: number | null;
  timestamp_ms: number | null;
  duration_ms: number | null;
};
export type FeedbackLog = {
  feedback_id: string;
  session_id: string;
  event_type: string | null;
  feedback_text: string;
  created_at: string;
};
export type SessionDetail = {
  session: StoredSession;
  events: PoseEvent[];
  snapshots: Snapshot[];
  feedback: FeedbackLog[];
};
export type ProgressSummary = {
  ok: boolean;
  source: string;
  cached: boolean;
  practice_count: number;
  measurement_count: number;
  summary: {
    trend: "improving" | "maintaining" | "needs_attention" | "insufficient_data";
    encouragement: string;
    summary: string;
    suggestions: string[];
  };
};
export type Summary = {
  id: string;
  pose: Pose;
  seconds: number;
  feedbacks: number;
};

// Shared backend contracts.
async function request<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
  method?: string,
  timeoutMs = 15000,
): Promise<T> {
  const response = await fetch(path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers:
      typeof FormData !== "undefined" && body instanceof FormData
        ? undefined
        : { "Content-Type": "application/json" },
    body:
      body === undefined
        ? undefined
        : typeof FormData !== "undefined" && body instanceof FormData
          ? body
          : JSON.stringify(body),
    signal: AbortSignal.any([
      signal ?? new AbortController().signal,
      AbortSignal.timeout(timeoutMs),
    ]),
  });
  if (!response.ok) {
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Keep a useful status message if the backend did not return JSON.
    }
    throw new Error(
      detail || `接口 ${path} 返回 ${response.status}，请检查后端是否实现。`,
    );
  }
  return response.json();
}
export const api = {
  ready: () =>
    request<{
      status: string;
      model: { name: string; available: boolean; reason: string };
      rules: Record<string, { reviewed: boolean; correction_phases: string[] }>;
      llm: { configured: boolean };
    }>("/api/ready", undefined),
  preferences: () =>
    request<{ preferences: Record<string, string> }>(
      "/api/memory/preferences",
      undefined,
    ),
  preference: (value: string) =>
    request(
      "/api/memory/preferences",
      { preference_key: "feedback_length", preference_value: value },
      undefined,
      "PUT",
    ),
  deleteData: () =>
    request("/api/memory/user-data", undefined, undefined, "DELETE"),
  events: (id: string) =>
    request<{
      items: {
        event_id: string;
        event_type: string;
        duration_ms: number;
        side: string | null;
      }[];
    }>(`/api/memory/sessions/${encodeURIComponent(id)}/events`, undefined),
  incomplete: () =>
    request<{ items: (StoredSession & { state: string })[] }>(
      "/api/memory/incomplete-sessions",
      undefined,
    ),
  heartbeat: (id: string) =>
    request(`/api/memory/sessions/${encodeURIComponent(id)}/heartbeat`, {}),
  sessions: () =>
    request<{ items: StoredSession[] }>("/api/memory/sessions", undefined),
  sessionDetail: (id: string) =>
    request<SessionDetail>(
      `/api/memory/sessions/${encodeURIComponent(id)}/detail`,
      undefined,
    ),
  progressSummary: (sessionId: string, pose: Pose, force = false) =>
    request<ProgressSummary>(
      `/api/memory/progress-summary?user_id=default&pose_id=${encodeURIComponent(pose)}&session_id=${encodeURIComponent(sessionId)}${force ? "&force=true" : ""}`,
      undefined,
      undefined,
      undefined,
      30000,
    ),
  createSession: (id: string, pose: Pose) =>
    request("/api/memory/sessions", {
      session_id: id,
      pose_id: pose,
      started_at: new Date().toISOString(),
    }),
  finishSession: (id: string) =>
    request<{ summary: string | null }>(
      `/api/memory/sessions/${encodeURIComponent(id)}/finish`,
      { ended_at: new Date().toISOString() },
    ),
  health: () =>
    request<{ status: string; mode?: string }>("/api/health", undefined),
  feedback: (event: Analysis, signal: AbortSignal) =>
    request<Feedback>("/api/agent/feedback", event, signal),
  saveSnapshot: (
    sessionId: string,
    blob: Blob,
    meta: {
      pose_id: Pose;
      event_type: string;
      side?: string;
      timestamp_ms: number;
    },
  ) => {
    const form = new FormData();
    form.append("image", blob, `error-${meta.timestamp_ms}.jpg`);
    Object.entries(meta).forEach(([key, value]) => {
      if (value !== undefined) form.append(key, String(value));
    });
    return request<{ ok: boolean; snapshot_id: string; image_url: string }>(
      `/api/memory/sessions/${encodeURIComponent(sessionId)}/snapshots`,
      form,
    );
  },
  updateSnapshotFeedback: (snapshotId: string, feedback_text: string) =>
    request<{ ok: boolean; snapshot_id: string }>(
      `/api/memory/snapshots/${encodeURIComponent(snapshotId)}/feedback`,
      { feedback_text },
    ),
};
export function parseFeedback(value: Feedback): Feedback {
  if (
    typeof value.should_speak !== "boolean" ||
    typeof value.text !== "string" ||
    !["correction", "camera_hint", "none"].includes(value.feedback_type)
  )
    throw new Error("反馈格式不符合约定。");
  return value;
}
