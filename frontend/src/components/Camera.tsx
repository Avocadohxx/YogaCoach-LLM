import { useEffect, useRef } from 'react';
import { createPoseLandmarker, connections } from '../services/poseLandmarker';
import type { Point } from '../services/api';
type Props = {onFrame:(points:Point[],width:number,height:number)=>void;onStatus:(text:string)=>void;onTrackingLost:()=>void};
export default function Camera({onFrame,onStatus,onTrackingLost}:Props) {
  const video = useRef<HTMLVideoElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const callbacks = useRef({onFrame,onStatus,onTrackingLost}); callbacks.current={onFrame,onStatus,onTrackingLost};
  useEffect(()=>{
    let stopped=false, raf=0, last=0; let stream:MediaStream|undefined; let model:Awaited<ReturnType<typeof createPoseLandmarker>>|undefined;
    const lost=()=>{if(!stopped)callbacks.current.onTrackingLost();};
    const stopResources=()=>{stream?.getTracks().forEach(t=>t.stop());model?.close();model=undefined;};
    const disconnected=()=>{
      if(stopped)return;
      lost();callbacks.current.onStatus('摄像头已断开，请结束练习后重试。');
      stopped=true;cancelAnimationFrame(raf);stopResources();
    };
    async function start(){
      try {
        callbacks.current.onStatus('正在开启摄像头…');
        stream=await navigator.mediaDevices.getUserMedia({video:{width:960,height:720},audio:false});
        if(stopped){stopResources();return;}
        stream.getVideoTracks().forEach(track=>track.addEventListener('ended',disconnected));
        video.current!.srcObject=stream; await video.current!.play();
        if(stopped){stopResources();return;}
        callbacks.current.onStatus('正在加载身体识别模型…');
        model=await createPoseLandmarker();
        if(stopped){stopResources();return;}
        function tick(now:number){
          if(stopped)return;
          try {
            const v=video.current!, c=canvas.current!;
            if(now-last>100 && v.readyState>=2){
              last=now;c.width=v.videoWidth;c.height=v.videoHeight;
              const result=model!.detectForVideo(v,now), points=result.landmarks[0] || [];
              const ctx=c.getContext('2d')!;ctx.clearRect(0,0,c.width,c.height);ctx.strokeStyle='#9df4ca';ctx.fillStyle='#fff';ctx.lineWidth=3;
              for(const {start,end} of connections){const a=points[start],b=points[end];if(a && b && a.visibility>.5 && b.visibility>.5){ctx.beginPath();ctx.moveTo(a.x*c.width,a.y*c.height);ctx.lineTo(b.x*c.width,b.y*c.height);ctx.stroke();}}
              points.filter(p=>p.visibility>.5).forEach(p=>{ctx.beginPath();ctx.arc(p.x*c.width,p.y*c.height,4,0,Math.PI*2);ctx.fill();});
              callbacks.current.onStatus(points.length?'已找到身体，请保持全身入镜':'没有找到身体，请调整位置');
              callbacks.current.onFrame(points,c.width,c.height);
            }
            raf=requestAnimationFrame(tick);
          } catch { lost();callbacks.current.onStatus('识别中断，请结束练习后重试。');stopResources(); }
        }
        raf=requestAnimationFrame(tick);
      } catch(error){lost();if(!stopped)callbacks.current.onStatus(`无法启动：${error instanceof Error?error.message:'请检查摄像头权限及本地模型资源'}`);stopResources();}
    }
    void start();return()=>{stopped=true;cancelAnimationFrame(raf);stopResources();};
  },[]);
  return <div className="camera"><video ref={video} muted playsInline onStalled={onTrackingLost} onWaiting={onTrackingLost}/><canvas ref={canvas}/><span className="camera-tag">镜像预览 · 原始坐标上传</span></div>;
}
