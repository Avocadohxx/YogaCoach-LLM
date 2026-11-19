import { api, parseFeedback, type Point, type Pose } from './api';

// One instance per practice. Async completions may only update their own generation.
export function createLiveSession(id:string, pose:Pose, started:number, show:(text:string)=>void, counted:()=>void, transport=api) {
  let generation=0, closed=false, controller=new AbortController();
  let analysisBusy=false, feedbackBusy=false, lastFrame=-Infinity, lastFeedback=-Infinity;
  let evidence='', evidenceVersion=0, lastSeen=0;
  function invalidate(text:string) {
    if(closed)return;
    generation++; controller.abort(); controller=new AbortController();
    analysisBusy=false; feedbackBusy=false; evidence=''; evidenceVersion++; lastFeedback=-Infinity;
    show(text);
  }
  function close(){closed=true; generation++; controller.abort();}
  async function frame(points:Point[],width:number,height:number){
    if(closed)return;
    const now=Date.now();
    // Tracking loss must bypass both request concurrency and upload throttling.
    if(points.length!==33 || points.some(p=>![p.x,p.y,p.z,p.visibility].every(Number.isFinite)) || [11,12,23,24].some(i=>points[i].visibility<0.5)){
      invalidate('等待身体关键点重新清晰可见。'); return;
    }
    lastSeen=now;
    if(analysisBusy || now-lastFrame<200)return;
    const token=generation, signal=controller.signal;
    analysisBusy=true; lastFrame=now;
    try {
      const event=await transport.analyze({session_id:id,pose_id:pose,timestamp_ms:now-started,camera_view:'front',image_width:width,image_height:height,landmarks:points},signal);
      if(closed || generation!==token)return;
      if(!event || typeof event.feedback_allowed!=='boolean' || !Array.isArray(event.deviations) || event.deviations.some(x=>!x || typeof x.type!=='string'))throw new Error('分析接口返回格式不符合约定。');
      const signature=event.feedback_allowed?event.deviations.map(x=>x.type+':'+(x.side||'')).sort().join('|'):'';
      if(signature!==evidence){evidenceVersion++; evidence=signature; show(signature?'正在获取当前动作的提醒…':'当前没有可提供纠错的有效证据。');}
      if(!signature){show('当前没有可提供纠错的有效证据。');return;}
      if(feedbackBusy || now-lastFeedback<10000)return;
      feedbackBusy=true; lastFeedback=now;
      const version=evidenceVersion;
      // Analysis continues while the Agent responds.
      analysisBusy=false;
      try {
        const result=parseFeedback(await transport.feedback(event,signal));
        if(closed || generation!==token || evidenceVersion!==version)return;
        if(Date.now()-lastSeen>1500){invalidate('画面已中断，等待重新识别。');return;}
        if(Date.now()-now>=10000){show('本次回复已过期，正在等待新的观察。');return;}
        show(result.should_speak?result.text:'本次无需提醒。');
        if(result.should_speak)counted();
      } finally {if(generation===token)feedbackBusy=false;}
    }catch(error){
      if(!closed && generation===token && !signal.aborted)invalidate(error instanceof Error?error.message:'请求失败，请检查后端。');
    }finally{if(generation===token && lastFrame===now)analysisBusy=false;}
  }
  return {frame,invalidate,close};
}
