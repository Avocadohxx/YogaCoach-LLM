import { useEffect, useRef, useState } from 'react';
import Source133 from './components/Source133';
import { api, readHistory, type Pose, type Analysis, type Phase133, type Variant133, type Summary, type StoredSession } from './services/api';
import { createLiveSession } from './services/liveSession';
const names:Record<Pose,string>={tadasana:'山式',ardhakati_chakrasana:'站立侧弯式'};
export default function App(){
  const [pose,setPose]=useState<Pose>('tadasana'),[mode,setMode]=useState<'demo'|'live'>('demo');
  const [active,setActive]=useState(false),[status,setStatus]=useState('准备好后，开始一次练习。'),[feedback,setFeedback]=useState('把注意力放回身体，慢慢开始。');
  const [history,setHistory]=useState(readHistory),[summary,setSummary]=useState<Summary|null>(null),[seconds,setSeconds]=useState(0),[health,setHealth]=useState('尚未检查');
  const [busy,setBusy]=useState(false),[serverHistory,setServerHistory]=useState<StoredSession[]>([]),[serverSummary,setServerSummary]=useState('');
  const [phase,setPhase]=useState<Phase133>('prepare'),[side,setSide]=useState<'left'|'right'>('left');
  const [inputSource,setInputSource]=useState<'camera'|'video'>('camera');
  const [movementVariant,setMovementVariant]=useState<Variant133>('unknown'),[raisedArm,setRaisedArm]=useState<'unknown'|'left'|'right'>('unknown'),[bendDirection,setBendDirection]=useState<'unknown'|'image_left'|'image_right'>('unknown');
  const [analysis,setAnalysis]=useState<Analysis|null>(null);
  const mounted=useRef(true);
  const run=useRef({id:'',generation:0,started:0,count:0,lastFrame:0,lastFeedback:0,analysisBusy:false,feedbackBusy:false,controller:new AbortController()});
  const live=useRef<ReturnType<typeof createLiveSession>|null>(null);
  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;run.current.controller.abort();live.current?.close();};},[]);
  useEffect(()=>{if(!active)return;const timer=setInterval(()=>setSeconds(Math.floor((Date.now()-run.current.started)/1000)),1000);return()=>clearInterval(timer);},[active]);
  async function start(){
    setBusy(true);setServerSummary('');setAnalysis(null);
    const id=crypto.randomUUID(), started=Date.now();
    try {
      if(mode==='live')await api.createSession(id,pose);
      if(!mounted.current)return;
      live.current?.close();run.current.controller.abort();
      run.current={id,generation:run.current.generation+1,started,count:0,lastFrame:0,lastFeedback:0,analysisBusy:false,feedbackBusy:false,controller:new AbortController()};
      live.current=createLiveSession(id,pose,started,setFeedback,()=>{run.current.count++;},api,{phase:phase==='prepare'?'prepare':'hold',side:pose==='tadasana'?null:side});
      setSeconds(0);setSummary(null);setFeedback('等待新的观察结果…');setStatus(mode==='demo'?'模拟模式：点击场景按钮查看页面变化。':'会话已创建，准备摄像头…');setActive(true);
    }catch(error){if(mounted.current)setStatus(error instanceof Error?error.message:'创建会话失败。');}
    finally{if(mounted.current)setBusy(false);}
  }
  async function finish(){
    setBusy(true);live.current?.close();
    const current=run.current;current.controller.abort();current.generation++;
    const item:Summary={id:current.id,pose,seconds:Math.floor((Date.now()-current.started)/1000),feedbacks:current.count,ended:new Date().toISOString()};
    setActive(false);setSummary(item);setStatus('已结束练习，摄像头已关闭。');
    try{
      if(mode==='demo'){
        const items=[item,...history].slice(0,10);localStorage.setItem('yoga-demo-history',JSON.stringify(items));setHistory(items);
      }else{
        const result=await api.finishSession(current.id);
        if(!mounted.current)return;
        setServerSummary(result.summary||'没有可用的总结。');setStatus('会话已保存到服务器。');
        const resultHistory=await api.sessions();if(mounted.current)setServerHistory(resultHistory.items);
      }
    }catch(error){if(mounted.current)setStatus('记录保存或读取失败：'+(error instanceof Error?error.message:'请检查后端。'));}
    finally{if(mounted.current)setBusy(false);}
  }
  function simulate(kind:'difference'|'hidden'|'normal'){
    setStatus(kind==='hidden'?'模拟：关键点被遮挡':kind==='normal'?'模拟：未发现目标差异':'模拟：持续发现双肩高度差异');
    if(kind==='normal'){setFeedback('本次模拟不发送提醒。');return;}
    setFeedback(kind==='hidden'?'请调整摄像头位置，让全身进入画面后再继续。':'模拟反馈：观察两侧肩部位置，在舒适范围内放松。');run.current.count++;
  }
  return <main><header><a className="brand" href="#">◌ YogaCoach<span>练习空间</span></a><span className="badge">联调版本 v2 · E</span></header>
    <section className="intro"><span className="eyebrow">留一点时间，照顾自己</span><h1>看见动作，<br/>找到自己的节奏。</h1><p>选择一种练习，观察身体的位置。每次只关注一个小变化。</p></section>
    <div className="layout"><section className="workspace"><div className="section-title"><h2>开始练习</h2><span>{active?`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`:'01 / 准备'}</span></div>
      <div className="choices">{(Object.keys(names) as Pose[]).map(id=><button key={id} disabled={active||busy} className={pose===id?'selected':''} onClick={()=>{setPose(id);setPhase('prepare');}}>{names[id]}<small>{id==='tadasana'?'举臂保持 · 持续肘部偏差提醒':'侧弯 · 检测项待团队确认'}</small></button>)}</div>
      <label className="mode">运行方式 <select disabled={active||busy} value={mode} onChange={e=>setMode(e.target.value as 'demo'|'live')}><option value="demo">模拟练习（不调用模型）</option><option value="live">133 点：摄像头 / 上传视频</option></select></label>{active&&<p className="note">切换运行方式前，请先结束当前练习。练习阶段可以随时切换。</p>}
      {mode==='live' && <div className="choices"><label>图像来源 <select disabled={active||busy} value={inputSource} onChange={e=>setInputSource(e.target.value as 'camera'|'video')}><option value="camera">摄像头</option><option value="video">本地视频</option></select></label><label>练习阶段 <select disabled={busy} value={phase} onChange={e=>{live.current?.invalidate('阶段已切换，重新积累证据。');setPhase(e.target.value as Phase133);}}><option value="prepare">准备中（不纠错）</option><option value="arms_up_hold">双臂举起并保持</option><option value="arms_down_hold">双臂自然下垂保持</option>{pose==='ardhakati_chakrasana'&&<option value="side_bend_hold">侧弯保持</option>}<option value="transition">动作切换中（不纠错）</option></select></label>{pose==='ardhakati_chakrasana' && <label>练习侧别 <select disabled={active||busy} value={side} onChange={e=>setSide(e.target.value as 'left'|'right')}><option value="left">身体左侧</option><option value="right">身体右侧</option></select></label>}</div>}
      {mode==='live' && pose==='ardhakati_chakrasana' && <div className="choices"><label>举臂方式 <select value={movementVariant} onChange={e=>setMovementVariant(e.target.value as Variant133)}><option value="unknown">请选择</option><option value="both_arms_overhead">双臂举起</option><option value="single_arm_overhead">单臂举起</option></select></label>{movementVariant==='single_arm_overhead'&&<label>举起的手臂 <select value={raisedArm} onChange={e=>setRaisedArm(e.target.value as 'unknown'|'left'|'right')}><option value="unknown">请选择</option><option value="left">身体左臂</option><option value="right">身体右臂</option></select></label>}<label>计划倾斜方向（画面） <select value={bendDirection} onChange={e=>setBendDirection(e.target.value as 'unknown'|'image_left'|'image_right')}><option value="unknown">未指定</option><option value="image_left">画面左侧</option><option value="image_right">画面右侧</option></select></label></div>}
      {active && mode==='live'?<Source133 movementVariant={movementVariant} raisedArm={raisedArm} bendDirection={bendDirection} initialSource={inputSource} sessionId={run.current.id} pose={pose} phase={phase} started={run.current.started} onAnalysis={event=>{setAnalysis(event);void live.current?.observe(event);}} onStatus={setStatus} onLost={()=>{setAnalysis(null);live.current?.invalidate('画面已变化，等待新的 133 点结果。');}}/>:<div className="placeholder"><span className="pose-symbol">♧</span><h3>{active?'模拟练习已开始':'给身体留出完整的画面'}</h3><p>{mode==='demo'?'模拟模式帮助检查操作流程，不评价你的动作。':'正面拍摄，保持全身入镜，并摆正摄像头。'}</p></div>}
      <p className="status" role="status">● {status}</p>
      {active && mode==='demo' && <div className="scenarios"><button onClick={()=>simulate('normal')}>没有差异</button><button onClick={()=>simulate('difference')}>模拟肩部差异</button><button onClick={()=>simulate('hidden')}>模拟遮挡</button></div>}
      <button disabled={busy} className="primary" onClick={active?finish:start}>{active?'结束并查看记录':'开始练习'} <span>→</span></button>
      <p className="note">示范视频尚未接入，等待 A 提供授权资源。侧弯规则未审核时仅显示测量。</p>
    </section><aside><section className="card feedback"><span className="eyebrow">本次提醒</span><h2 aria-live="polite">{feedback}</h2>{mode==='live'&&analysis&&<p>{(['left_elbow_angle_deg','right_elbow_angle_deg'] as const).map((key,i)=>{const item=analysis.observations?.find(o=>o.name===key);return <span key={key}>{i?' · ':''}{i?'右肘':'左肘'}：{item?.valid&&typeof item.value==='number'?item.value.toFixed(1)+'°':'暂不可测'}</span>;})}</p>}<p>{mode==='demo'?'此处展示固定模拟文本，没有调用 LLM。':'图像帧发送到本机后端，使用 RTMW 提取 133 点；不上传到 LLM。'}</p></section>
    <section className="card"><h2>连接状态</h2><p>网页 5173 → 后端 8000</p><p role="status">{health}</p><button onClick={()=>{setHealth('正在检查…');void api.health().then(r=>setHealth(r.status==='ok'?(r.mode==='mock'?'联调桩在线（非真实检测/LLM）':'后端在线（不代表业务接口已完成）'):'后端状态异常')).catch(e=>setHealth(e.message));}}>检查后端</button><p className="note">真实模式保存会话到 SQLite。山式举臂保持支持已审核的持续肘部偏差提醒；侧弯规则仍等待审核。</p></section>
    <section className="card"><h2>服务器练习记录</h2><button disabled={busy} onClick={()=>{void api.sessions().then(r=>setServerHistory(r.items)).catch(e=>setStatus(e.message));}}>刷新记录</button>{serverHistory.map(x=><p key={x.session_id}>{names[x.pose_id]||x.pose_id} · {x.summary||'尚未生成总结'}</p>)}</section>
    {serverSummary && <section className="card"><h2>服务器总结</h2><p>{serverSummary}</p></section>}
    {summary && <section className="card"><h2>本次记录</h2><p>{names[summary.pose]} · {summary.seconds} 秒</p><p>显示提醒 {summary.feedbacks} 次。此记录不代表动作改善。</p></section>}
    <section className="card"><h2>模拟练习记录</h2>{history.length?history.map(x=><p key={x.id}>{names[x.pose]} · {x.seconds} 秒 · {new Date(x.ended).toLocaleDateString()}</p>):<p>还没有记录，完成一次模拟练习后会保存在此浏览器。</p>}<button disabled={!history.length} onClick={()=>{try{localStorage.removeItem('yoga-demo-history');setHistory([]);}catch{setStatus('浏览器拒绝清除记录，请检查存储权限。');}}}>清除模拟记录</button></section></aside></div>
    <footer>YogaCoach · 辅助观察与学习，不提供医疗诊断。感到不适时请暂停。</footer>
  </main>;
}
