import { api, parseFeedback, type Point, type Pose, type Analysis } from './api';

// One instance per practice. Async completions may only update their own generation.
export function createLiveSession(id:string, pose:Pose, started:number, show:(text:string)=>void, counted:()=>void, transport:Pick<typeof api,'analyze'|'feedback'>=api, options:{phase:'prepare'|'hold';side:'left'|'right'|null}={phase:'prepare',side:null}) {
  let frameSeq=0;
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
      const event=await transport.analyze({session_id:id,pose_id:pose,timestamp_ms:now-started,frame_seq:frameSeq++,phase:options.phase,side:pose==='tadasana'?null:options.side,camera_view:'front',image_width:width,image_height:height,landmarks:points},signal);
      if(closed || generation!==token)return;
      if(!event || typeof event.feedback_allowed!=='boolean' || !Array.isArray(event.deviations) || event.deviations.some(x=>!x || typeof x.type!=='string'))throw new Error('分析接口返回格式不符合约定。');
      const signature=event.feedback_allowed?event.deviations.map(x=>(x.event_id||x.type)+':'+(x.side||'')).sort().join('|'):['partial','poor'].includes(event.tracking_quality)?'camera_hint':'';
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
        if(result.text)show(result.text);
        if(result.should_speak)counted();
      } finally {if(generation===token)feedbackBusy=false;}
    }catch(error){
      if(!closed && generation===token && !signal.aborted)invalidate(error instanceof Error?error.message:'请求失败，请检查后端。');
    }finally{if(generation===token && lastFrame===now)analysisBusy=false;}
  }
  async function observe(event:Analysis){
    if(closed)return;
    const now=Date.now(), token=generation, signal=controller.signal;
    lastSeen=now;
    const signature=event.feedback_allowed?event.deviations.map(x=>(x.event_id||x.type)+':'+(x.side||'')).sort().join('|'):['partial','poor'].includes(event.tracking_quality)?'camera_hint':'';
    if(signature!==evidence){evidence=signature;evidenceVersion++;show(signature?'正在获取当前画面的提醒…':'已获得 133 点测量，参考规则尚未校准。');}
    if(!signature){
      const reasons=event.reason_codes||[];
      const ruleReasons=event.rule_evaluation?.rule_results?.filter(r=>r.mode==='candidate'&&r.reason).map(r=>r.reason);
      const hasElbowEvidence=(event.observations||[]).some(o=>(o.name==='left_elbow_angle_deg'||o.name==='right_elbow_angle_deg')&&o.valid);
      show(reasons.includes('frame_gap_reset')?'画面分析间隔较长，正在重新确认持续偏差。':reasons.includes('rules_require_manual_review')?'当前动作规则尚未审核，仅显示测量。':(event.rule_evaluation?.pending_count||0)>0?'肘部角度偏离参考范围，正在确认是否持续。':event.analysis_mode==='reviewed_rules_133'?'当前未触发持续偏差；这不代表整体动作完全标准。':reasons.includes('explicit_supported_phase_required')?'请选择实际动作阶段；山式纠错支持双臂举起保持。':!hasElbowEvidence||ruleReasons?.includes('required_measurement_invalid')?'请调整摄像头，让双肩、手肘和手腕完整入镜。':ruleReasons?.includes('source_model_missing_or_mismatch')?'当前模型不符合已配置的山式规则。':ruleReasons?.includes('front_view_required')?'请正对摄像头练习山式。':'已获得角度测量，等待持续偏差确认。');return;
    }
    if(feedbackBusy || now-lastFeedback<10000)return;
    feedbackBusy=true;lastFeedback=now;const version=evidenceVersion;
    try{
      const result=parseFeedback(await transport.feedback(event,signal));
      if(closed || generation!==token || evidenceVersion!==version)return;
      if(Date.now()-now>=8000)return;
      if(result.text)show(result.text);
      if(result.should_speak)counted();
    }catch(error){if(!closed && generation===token && !signal.aborted)invalidate(error instanceof Error?error.message:'反馈请求失败。');}
    finally{if(generation===token)feedbackBusy=false;}
  }
  return {frame,observe,invalidate,close};

}
