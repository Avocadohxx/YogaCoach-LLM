import {useEffect,useRef,useState} from 'react';
import type {Analysis,Pose,Phase133,Variant133} from '../services/api';

type Props={initialSource:'camera'|'video';sessionId:string;pose:Pose;phase:Phase133;movementVariant:Variant133;raisedArm:'unknown'|'left'|'right';bendDirection:'unknown'|'image_left'|'image_right';started:number;onAnalysis:(event:Analysis)=>void;onStatus:(text:string)=>void;onLost:()=>void};
const bones=[[5,6],[5,7],[7,9],[6,8],[8,10],[5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16]];
export default function Source133(props:Props){
  const [source,setSource]=useState<'camera'|'video'>(props.initialSource),[file,setFile]=useState<File|null>(null);
  const sequence=useRef(0),generation=useRef(0),streamId=useRef(crypto.randomUUID());
  const video=useRef<HTMLVideoElement>(null),canvas=useRef<HTMLCanvasElement>(null);
  const callbacks=useRef(props);callbacks.current=props;
  useEffect(()=>{generation.current++;streamId.current=crypto.randomUUID();props.onLost();},[props.phase,props.movementVariant,props.raisedArm,props.bendDirection]);
  useEffect(()=>{
    let stopped=false,stream:MediaStream|undefined,url='',timer:ReturnType<typeof setTimeout>|undefined;
    const controller=new AbortController();
    const valid=()=>!stopped&&!controller.signal.aborted;
    async function tick(){
      const epoch=generation.current;
      if(!valid())return;
      const v=video.current!,c=canvas.current!;
      if(v.paused||v.ended||v.readyState<2){timer=setTimeout(tick,250);return;}
      try{
        const scale=Math.min(1,960/v.videoWidth);c.width=Math.round(v.videoWidth*scale);c.height=Math.round(v.videoHeight*scale);
        const off=document.createElement('canvas');off.width=c.width;off.height=c.height;off.getContext('2d')!.drawImage(v,0,0,c.width,c.height);
        const blob=await new Promise<Blob>((resolve,reject)=>off.toBlob(b=>b?resolve(b):reject(new Error('图像编码失败。')),'image/jpeg',.85));
        if(!valid())return;
        if(generation.current!==epoch){timer=setTimeout(tick,100);return;}
        const p=callbacks.current;
        const query=new URLSearchParams({session_id:p.sessionId,pose_id:p.pose,phase:p.phase,stream_id:streamId.current,movement_variant:p.movementVariant,raised_arm_side:p.movementVariant==='single_arm_overhead'?p.raisedArm:'unknown',bend_direction:p.bendDirection,camera_view:'front',frame_seq:String(sequence.current++),timestamp_ms:String(Date.now()-p.started)});
        const response=await fetch('/api/pose/frame?'+query,{method:'POST',headers:{'Content-Type':'image/jpeg'},body:blob,signal:AbortSignal.any([controller.signal,AbortSignal.timeout(30000)])});
        if(!response.ok)throw new Error(`133 点推理接口返回 ${response.status}，请检查后端模型。`);
        const result=await response.json();
        if(!valid())return;
        if(generation.current!==epoch){timer=setTimeout(tick,250);return;}
        if(result.layout!=='COCO-WholeBody 133'||result.keypoints?.length!==133||result.scores?.length!==133)throw new Error('后端未返回 133 点。');
        const ctx=c.getContext('2d')!;ctx.clearRect(0,0,c.width,c.height);ctx.strokeStyle='#9df4ca';ctx.fillStyle='#fff';ctx.lineWidth=2;
        const targets=new Set((result.analysis.deviations||[]).map((d:{target?:string})=>d.target));
        for(const [a,b] of bones){ctx.strokeStyle=(targets.has('left_elbow')&&[5,7].includes(a)&&[7,9].includes(b))||(targets.has('right_elbow')&&[6,8].includes(a)&&[8,10].includes(b))?'#ffb06b':'#9df4ca';if(result.scores[a]<.5||result.scores[b]<.5)continue;ctx.beginPath();ctx.moveTo(...result.keypoints[a] as [number,number]);ctx.lineTo(...result.keypoints[b] as [number,number]);ctx.stroke();}
        result.keypoints.forEach(([x,y]:number[],i:number)=>{if(result.scores[i]>=.5){ctx.beginPath();ctx.arc(x,y,2,0,Math.PI*2);ctx.fill();}});
        callbacks.current.onStatus(result.analysis.feedback_allowed?'已确认持续偏差，请查看右侧提醒':'133 点推理已完成 · 单人全图模式');callbacks.current.onAnalysis(result.analysis);
        timer=setTimeout(tick,100);
      }catch(error){if(valid()){if(generation.current!==epoch){timer=setTimeout(tick,250);return;}callbacks.current.onLost();callbacks.current.onStatus(error instanceof Error?error.message:'推理失败。');}}
    }
    async function start(){
      try{
        if(source==='camera'){
          stream=await navigator.mediaDevices.getUserMedia({video:{width:960,height:720},audio:false});
          if(!valid()){stream.getTracks().forEach(t=>t.stop());return;}
          stream.getTracks().forEach(t=>t.addEventListener('ended',()=>{if(valid()){callbacks.current.onLost();callbacks.current.onStatus('摄像头断开，请重新开始练习。');controller.abort();}}));
          video.current!.srcObject=stream;
        }else{
          if(!file){callbacks.current.onStatus('请选择本地视频。');return;}
          url=URL.createObjectURL(file);video.current!.src=url;
        }
        await video.current!.play();if(valid())void tick();
      }catch(error){if(valid()){callbacks.current.onLost();callbacks.current.onStatus(error instanceof Error?error.message:'无法打开视频源。');}}
    }
    void start();
    return()=>{stopped=true;controller.abort();clearTimeout(timer);stream?.getTracks().forEach(t=>t.stop());if(url)URL.revokeObjectURL(url);};
  },[source,file,props.sessionId]);
  function lost(){generation.current++;streamId.current=crypto.randomUUID();props.onLost();}
  function changeSource(value:'camera'|'video'){lost();setSource(value);}
  return <><label>图像来源 <select value={source} onChange={e=>changeSource(e.target.value as 'camera'|'video')}><option value="camera">摄像头</option><option value="video">本地视频</option></select></label>{source==='video'&&<input type="file" accept="video/*" onChange={e=>{lost();setFile(e.target.files?.[0]||null);}}/>}<div className="camera"><video ref={video} style={{objectFit:'contain',transform:'none'}} muted playsInline controls={source==='video'} onPause={lost} onSeeking={lost} onEnded={lost}/><canvas ref={canvas} style={{transform:'none',pointerEvents:'none'}}/><span className="camera-tag" style={{pointerEvents:'none'}}>COCO-WholeBody 133 · 正面单人</span></div><p className="note">视频与摄像头均抽取图像帧发送到本机后端，RTMW 在后端推理。请保持单人全身入镜。</p></>;
}
