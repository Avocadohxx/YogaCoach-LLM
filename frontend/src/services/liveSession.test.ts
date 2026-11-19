import {afterEach,describe,expect,it,vi} from 'vitest';
import {createLiveSession} from './liveSession';
import {type Analysis, type Feedback} from './api';
const points=Array.from({length:33},()=>({x:.5,y:.5,z:0,visibility:1}));
const event:Analysis={session_id:'s',pose_id:'tadasana',timestamp_ms:0,tracking_quality:'good',feedback_allowed:true,deviations:[{type:'shoulder_asymmetry',duration_ms:1800}]};
const reply:Feedback={should_speak:true,feedback_type:'correction',text:'测试指导'};
function deferred<T>(){let resolve!:(x:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};}
function setup(){const show=vi.fn(),count=vi.fn(),transport={health:vi.fn(),analyze:vi.fn().mockResolvedValue(event),feedback:vi.fn().mockResolvedValue(reply)};return {show,count,transport,session:createLiveSession('s','tadasana',Date.now(),show,count,transport)};}
afterEach(()=>vi.useRealTimers());
describe('真实会话回归',()=>{
  it('失去身体必须打断忙碌的分析，迟到分析不能调用 Agent',async()=>{
    const t=setup(),pending=deferred<Analysis>();t.transport.analyze.mockReturnValue(pending.promise);
    const work=t.session.frame(points,640,480);await t.session.frame([],640,480);pending.resolve(event);await work;
    expect(t.transport.feedback).not.toHaveBeenCalled();expect(t.show).toHaveBeenLastCalledWith('等待身体关键点重新清晰可见。');
  });
  it('事件消失撤回已显示指导',async()=>{
    vi.useFakeTimers();const t=setup();await t.session.frame(points,640,480);expect(t.count).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(250);t.transport.analyze.mockResolvedValue({...event,deviations:[]});await t.session.frame(points,640,480);
    expect(t.show).toHaveBeenLastCalledWith('当前没有可提供纠错的有效证据。');
  });
  it('识别错误后迟到 Agent 回复不能更新页面',async()=>{
    const t=setup(),pending=deferred<Feedback>();t.transport.feedback.mockReturnValue(pending.promise);
    const work=t.session.frame(points,640,480);await Promise.resolve();t.session.invalidate('识别中断');pending.resolve(reply);await work;
    expect(t.show).toHaveBeenLastCalledWith('识别中断');expect(t.count).not.toHaveBeenCalled();
  });
  it('结束后迟到 Agent 回复不能更新页面',async()=>{
    const t=setup(),pending=deferred<Feedback>();t.transport.feedback.mockReturnValue(pending.promise);
    const work=t.session.frame(points,640,480);await Promise.resolve();t.session.close();t.show.mockClear();pending.resolve(reply);await work;
    expect(t.show).not.toHaveBeenCalled();expect(t.count).not.toHaveBeenCalled();
  });
  it('持续有效画面下慢反馈显示过期提示',async()=>{
    vi.useFakeTimers();const t=setup(),pending=deferred<Feedback>();t.transport.feedback.mockReturnValue(pending.promise);
    const work=t.session.frame(points,640,480);await Promise.resolve();vi.advanceTimersByTime(11000);await t.session.frame(points,640,480);pending.resolve(reply);await work;
    expect(t.show).toHaveBeenLastCalledWith('本次回复已过期，正在等待新的观察。');expect(t.count).not.toHaveBeenCalled();
  });
  it('事件消失又重现也不能采用前一次事件的回复',async()=>{
    vi.useFakeTimers();const t=setup(),pending=deferred<Feedback>();t.transport.feedback.mockReturnValue(pending.promise);
    const work=t.session.frame(points,640,480);await Promise.resolve();vi.advanceTimersByTime(250);t.transport.analyze.mockResolvedValue({...event,deviations:[]});await t.session.frame(points,640,480);
    vi.advanceTimersByTime(250);t.transport.analyze.mockResolvedValue(event);await t.session.frame(points,640,480);pending.resolve(reply);await work;expect(t.count).not.toHaveBeenCalled();
  });
  it('分析失败撤回证据并允许下一帧恢复',async()=>{
    vi.useFakeTimers();const t=setup();t.transport.analyze.mockRejectedValueOnce(new Error('接口异常'));await t.session.frame(points,640,480);
    expect(t.show).toHaveBeenLastCalledWith('接口异常');vi.advanceTimersByTime(250);await t.session.frame(points,640,480);expect(t.count).toHaveBeenCalledOnce();
  });
});

describe('分析请求契约',()=>{
  it('发送递增序号、显式阶段和身体侧别',async()=>{
    vi.useFakeTimers();
    const t=setup();
    await t.session.frame(points,640,480);
    expect(t.transport.analyze.mock.calls[0][0]).toMatchObject({frame_seq:0,phase:'prepare',side:null});
    vi.advanceTimersByTime(250);
    await t.session.frame(points,640,480);
    expect(t.transport.analyze.mock.calls[1][0]).toMatchObject({frame_seq:1});
  });
});

describe('镜头提示',()=>{
  it('低质量测量可请求镜头提示而不宣称动作偏差',async()=>{
    const t=setup();
    t.transport.analyze.mockResolvedValue({...event,tracking_quality:'partial',feedback_allowed:false,deviations:[]});
    t.transport.feedback.mockResolvedValue({should_speak:true,feedback_type:'camera_hint',text:'请保持全身入镜。'});
    await t.session.frame(points,640,480);
    expect(t.show).toHaveBeenLastCalledWith('请保持全身入镜。');
    expect(t.count).toHaveBeenCalledOnce();
  });
});

describe('133 点后端结果接入',()=>{
  it('新画面清晰时丢弃旧镜头提示',async()=>{
    const t=setup(),pending=deferred<Feedback>();t.transport.feedback.mockReturnValue(pending.promise);
    const work=t.session.observe({...event,tracking_quality:'partial',feedback_allowed:false,deviations:[]});
    await t.session.observe({...event,tracking_quality:'good',feedback_allowed:false,deviations:[]});
    pending.resolve(reply);await work;
    expect(t.count).not.toHaveBeenCalled();
    expect(t.show).toHaveBeenLastCalledWith('已获得 133 点测量，参考规则尚未校准。');
  });
  it('视频暂停或拖动后，迟到提示不能显示',async()=>{
    const t=setup(),pending=deferred<Feedback>();t.transport.feedback.mockReturnValue(pending.promise);
    const work=t.session.observe({...event,tracking_quality:'poor',feedback_allowed:false,deviations:[]});
    t.session.invalidate('视频已暂停');pending.resolve(reply);await work;
    expect(t.count).not.toHaveBeenCalled();expect(t.show).toHaveBeenLastCalledWith('视频已暂停');
  });
});

describe('持续纠错事件',()=>{
  it('相同类型的新事件不能采用前一个事件的迟到反馈',async()=>{
    const t=setup(),pending=deferred<Feedback>();t.transport.feedback.mockReturnValue(pending.promise);
    const first={...event,deviations:[{...event.deviations[0],event_id:'episode-1'}]};
    const work=t.session.observe(first);
    await t.session.observe({...first,deviations:[{...first.deviations[0],event_id:'episode-2'}]});
    pending.resolve(reply);await work;
    expect(t.count).not.toHaveBeenCalled();
  });
  it('显示确认中的状态，而不提前给出纠错',async()=>{
    const t=setup();
    await t.session.observe({...event,feedback_allowed:false,deviations:[],rule_evaluation:{pending_count:1,phase:'arms_up_hold',scope:'enabled_phase_rules_only_not_full_posture'}});
    expect(t.transport.feedback).not.toHaveBeenCalled();
    expect(t.show).toHaveBeenLastCalledWith('正在确认偏差是否持续，请保持自然呼吸。');
  });
});
