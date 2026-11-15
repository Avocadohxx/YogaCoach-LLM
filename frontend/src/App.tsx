import { useEffect, useRef, useState } from 'react';
import Camera from './components/Camera';
import { api, readHistory, type Point, type Pose, type Summary } from './services/api';
import { createLiveSession } from './services/liveSession';
const names:Record<Pose,string>={tadasana:'山式',ardhakati_chakrasana:'站立侧弯式'};
export default function App(){
  const [pose,setPose]=useState<Pose>('tadasana'),[mode,setMode]=useState<'demo'|'live'>('demo');
  const [active,setActive]=useState(false),[status,setStatus]=useState('准备好后，开始一次练习。'),[feedback,setFeedback]=useState('把注意力放回身体，慢慢开始。');
  const [history,setHistory]=useState(readHistory),[summary,setSummary]=useState<Summary|null>(null),[seconds,setSeconds]=useState(0),[health,setHealth]=useState('尚未检查');
  const run=useRef({id:'',generation:0,started:0,count:0,lastFrame:0,lastFeedback:0,analysisBusy:false,feedbackBusy:false,controller:new AbortController()});
  const live=useRef<ReturnType<typeof createLiveSession>|null>(null);
  useEffect(()=>()=>{run.current.controller.abort();live.current?.close();},[]);
  useEffect(()=>{if(!active)return;const timer=setInterval(()=>setSeconds(Math.floor((Date.now()-run.current.started)/1000)),1000);return()=>clearInterval(timer);},[active]);
  function start(){live.current?.close();run.current.controller.abort();run.current={id:crypto.randomUUID(),generation:run.current.generation+1,started:Date.now(),count:0,lastFrame:0,lastFeedback:0,analysisBusy:false,feedbackBusy:false,controller:new AbortController()};live.current=createLiveSession(run.current.id,pose,run.current.started,setFeedback,()=>{run.current.count++;});setSeconds(0);setSummary(null);setFeedback('等待新的观察结果…');setStatus(mode==='demo'?'模拟模式：点击场景按钮查看页面变化。':'准备摄像头…');setActive(true);}
  function finish(){live.current?.close();setFeedback('练习已结束。');const current=run.current;current.controller.abort();current.generation++;const item:Summary={id:current.id,pose,seconds:Math.floor((Date.now()-current.started)/1000),feedbacks:current.count,ended:new Date().toISOString()};setActive(false);setSummary(item);setStatus('已结束练习，摄像头已关闭。');if(mode==='demo'){const items=[item,...history].slice(0,10);setHistory(items);try{localStorage.setItem('yoga-demo-history',JSON.stringify(items));}catch{setStatus('练习已结束，但浏览器无法保存记录。');}}}
  function simulate(kind:'difference'|'hidden'|'normal'){
    setStatus(kind==='hidden'?'模拟：关键点被遮挡':kind==='normal'?'模拟：未发现目标差异':'模拟：持续发现双肩高度差异');
    if(kind==='normal'){setFeedback('本次模拟不发送提醒。');return;}
    setFeedback(kind==='hidden'?'请调整摄像头位置，让全身进入画面后再继续。':'模拟反馈：观察两侧肩部位置，在舒适范围内放松。');run.current.count++;
  }
  function onFrame(points:Point[],width:number,height:number){
    if(active && mode==='live')void live.current?.frame(points,width,height);
  }
  return <main><header><a className="brand" href="#">◌ YogaCoach<span>练习空间</span></a><span className="badge">联调版本 v2 · E</span></header>
    <section className="intro"><span className="eyebrow">留一点时间，照顾自己</span><h1>看见动作，<br/>找到自己的节奏。</h1><p>选择一种练习，观察身体的位置。每次只关注一个小变化。</p></section>
    <div className="layout"><section className="workspace"><div className="section-title"><h2>开始练习</h2><span>{active?`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`:'01 / 准备'}</span></div>
      <div className="choices">{(Object.keys(names) as Pose[]).map(id=><button key={id} disabled={active} className={pose===id?'selected':''} onClick={()=>setPose(id)}>{names[id]}<small>{id==='tadasana'?'站立 · 观察肩部与躯干':'侧弯 · 检测项待团队确认'}</small></button>)}</div>
      <label className="mode">运行方式 <select disabled={active} value={mode} onChange={e=>setMode(e.target.value as 'demo'|'live')}><option value="demo">模拟练习（不调用模型）</option><option value="live">摄像头与真实后端</option></select></label>
      {active && mode==='live'?<Camera onFrame={onFrame} onStatus={setStatus} onTrackingLost={()=>live.current?.invalidate('识别已中断，请重新开始练习。')}/>:<div className="placeholder"><span className="pose-symbol">♧</span><h3>{active?'模拟练习已开始':'给身体留出完整的画面'}</h3><p>{mode==='demo'?'模拟模式帮助检查操作流程，不评价你的动作。':'正面拍摄，保持全身入镜，并摆正摄像头。'}</p></div>}
      <p className="status" role="status">● {status}</p>
      {active && mode==='demo' && <div className="scenarios"><button onClick={()=>simulate('normal')}>没有差异</button><button onClick={()=>simulate('difference')}>模拟肩部差异</button><button onClick={()=>simulate('hidden')}>模拟遮挡</button></div>}
      <button className="primary" onClick={active?finish:start}>{active?'结束并查看记录':'开始练习'} <span>→</span></button>
      <p className="note">示范视频尚未接入，等待 A 提供授权资源。侧弯式规则等待 B 确认。</p>
    </section><aside><section className="card feedback"><span className="eyebrow">本次提醒</span><h2 aria-live="polite">{feedback}</h2><p>{mode==='demo'?'此处展示固定模拟文本，没有调用 LLM。':'仅展示后端回复；画面保持在浏览器，发送关键点供分析。'}</p></section>
    <section className="card"><h2>连接状态</h2><p>网页 5173 → 后端 8000</p><p role="status">{health}</p><button onClick={()=>{setHealth('正在检查…');void api.health().then(r=>setHealth(r.status==='ok'?(r.mode==='mock'?'联调桩在线（非真实检测/LLM）':'后端在线（不代表业务接口已完成）'):'后端状态异常')).catch(e=>setHealth(e.message));}}>检查后端</button><p className="note">会话存储接口尚未定稿。真实模式只显示本次记录，不宣称已保存到服务器。</p></section>
    {summary && <section className="card"><h2>本次记录</h2><p>{names[summary.pose]} · {summary.seconds} 秒</p><p>显示提醒 {summary.feedbacks} 次。此记录不代表动作改善。</p></section>}
    <section className="card"><h2>模拟练习记录</h2>{history.length?history.map(x=><p key={x.id}>{names[x.pose]} · {x.seconds} 秒 · {new Date(x.ended).toLocaleDateString()}</p>):<p>还没有记录，完成一次模拟练习后会保存在此浏览器。</p>}<button disabled={!history.length} onClick={()=>{try{localStorage.removeItem('yoga-demo-history');setHistory([]);}catch{setStatus('浏览器拒绝清除记录，请检查存储权限。');}}}>清除模拟记录</button></section></aside></div>
    <footer>YogaCoach · 辅助观察与学习，不提供医疗诊断。感到不适时请暂停。</footer>
  </main>;
}
