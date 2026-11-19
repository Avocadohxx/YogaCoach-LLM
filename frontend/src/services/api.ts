export type Pose = 'tadasana' | 'ardhakati_chakrasana';
export type Point = { x:number; y:number; z:number; visibility:number };
export type Analysis = { session_id:string; pose_id:Pose; timestamp_ms:number; tracking_quality:string; feedback_allowed:boolean; deviations:{type:string; side?:string; duration_ms:number}[] };
export type Feedback = {should_speak:boolean; feedback_type:'correction'|'camera_hint'|'none'; text:string; target?:string; grounded_event_type?:string};
export type Summary = {id:string; pose:Pose; seconds:number; feedbacks:number; ended:string};

// B/C 已约定的路径放在此处；D 的会话接口尚未定稿，初版不猜测路径。
async function request<T>(path:string, body:unknown, signal?:AbortSignal):Promise<T> {
  const response = await fetch(path, {method:body === undefined ? 'GET':'POST', headers:{'Content-Type':'application/json'}, body:body === undefined ? undefined:JSON.stringify(body), signal:AbortSignal.any([signal ?? new AbortController().signal, AbortSignal.timeout(15000)])});
  if (!response.ok) throw new Error(`接口 ${path} 返回 ${response.status}，请检查后端是否实现。`);
  return response.json();
}
export const api = {
  health: () => request<{status:string;mode?:string}>('/api/health', undefined),
  analyze: (body:{session_id:string;pose_id:Pose;timestamp_ms:number;camera_view:'front';image_width:number;image_height:number;landmarks:Point[]}, signal:AbortSignal) => request<Analysis>('/api/analyze',body,signal),
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
