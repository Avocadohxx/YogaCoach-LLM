export type Pose = 'tadasana' | 'ardhakati_chakrasana';
export type Phase133 = 'prepare'|'hold'|'transition'|'arms_down_hold'|'arms_up_hold'|'side_bend_hold'|'return_upright';
export type Variant133 = 'unknown'|'both_arms_overhead'|'single_arm_overhead';
export type Point = { x:number; y:number; z:number; visibility:number };
export type Analysis = { session_id:string; pose_id:Pose; timestamp_ms:number; tracking_quality:string; feedback_allowed:boolean; observations?:{name:string;value:number|null;unit:string;valid:boolean}[]; analysis_mode?:string; reason_codes?:string[]; rule_evaluation?:{pending_count:number;scope:string;phase:string}|null; deviations:{event_id?:string;target?:string;type:string; side?:string; duration_ms:number}[] };
export type Feedback = {should_speak:boolean; feedback_type:'correction'|'camera_hint'|'none'; text:string; target?:string; grounded_event_type?:string};
export type StoredSession = {session_id:string; pose_id:Pose; started_at:string|null; ended_at:string|null; summary:string|null};
export type Summary = {id:string; pose:Pose; seconds:number; feedbacks:number; ended:string};

// Shared backend contracts; simulated history stays browser-local.
async function request<T>(path:string, body:unknown, signal?:AbortSignal):Promise<T> {
  const response = await fetch(path, {method:body === undefined ? 'GET':'POST', headers:{'Content-Type':'application/json'}, body:body === undefined ? undefined:JSON.stringify(body), signal:AbortSignal.any([signal ?? new AbortController().signal, AbortSignal.timeout(15000)])});
  if (!response.ok) throw new Error(`接口 ${path} 返回 ${response.status}，请检查后端是否实现。`);
  return response.json();
}
export const api = {
  sessions: () => request<{items:StoredSession[]}>('/api/memory/sessions',undefined),
  createSession: (id:string,pose:Pose) => request('/api/memory/sessions',{session_id:id,pose_id:pose,started_at:new Date().toISOString()}),
  finishSession: (id:string) => request<{summary:string|null}>(`/api/memory/sessions/${encodeURIComponent(id)}/finish`,{ended_at:new Date().toISOString()}),
  health: () => request<{status:string;mode?:string}>('/api/health', undefined),
  analyze: (body:{session_id:string;pose_id:Pose;timestamp_ms:number;frame_seq:number;phase:'prepare'|'hold';side:'left'|'right'|null;camera_view:'front';image_width:number;image_height:number;landmarks:Point[]}, signal:AbortSignal) => request<Analysis>('/api/analyze',body,signal),
  feedback: (event:Analysis, signal:AbortSignal) => request<Feedback>('/api/agent/feedback',event,signal),
};
export function parseFeedback(value:Feedback):Feedback {
  if(typeof value.should_speak !== 'boolean' || typeof value.text !== 'string' || !['correction','camera_hint','none'].includes(value.feedback_type)) throw new Error('反馈格式不符合约定。');
  return value;
}
export function readHistory():Summary[] {
  try { const value:unknown = JSON.parse(localStorage.getItem('yoga-demo-history') || '[]');
    return Array.isArray(value) ? value.filter((x):x is Summary => x && typeof x.id === 'string' && typeof x.seconds === 'number' && typeof x.feedbacks === 'number' && typeof x.ended === 'string' && ['tadasana','ardhakati_chakrasana'].includes(x.pose)).slice(0,10) : [];
  } catch { return []; }
}
