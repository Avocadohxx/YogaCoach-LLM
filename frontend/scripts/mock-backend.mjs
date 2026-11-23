// Explicit integration fixture, not B/C/D business logic. No persistence or LLM.
import http from 'node:http';
import {readFile} from 'node:fs/promises';
const load=async name=>JSON.parse(await readFile(new URL(`../../contracts/mock/${name}.json`,import.meta.url),'utf8'));
const analysis=await load('analysis_event'), feedback=await load('agent_feedback');
const scenarios=['difference','normal','blocked','error','slow'];
let scenario='difference';
const server=http.createServer(async(req,res)=>{
  const send=(code,data)=>{res.writeHead(code,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(data));};
  const url=new URL(req.url,'http://localhost');
  if(req.method==='GET' && url.pathname==='/api/health')return send(200,{status:'ok',mode:'mock',scenario});
  if(url.pathname==='/__mock'){
    if(scenarios.includes(url.searchParams.get('scenario')))scenario=url.searchParams.get('scenario');
    res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});
    return res.end(`<h1>E 联调桩：不含真实检测、LLM 或存储</h1><p>当前：${scenario}</p>${scenarios.map(s=>`<p><a href="?scenario=${s}">${s}</a></p>`).join('')}`);
  }
  if(req.method!=='POST')return send(404,{detail:'Mock route not found'});
  try{
    let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>1000000)return send(413,{detail:'Payload too large'});}
    const body=JSON.parse(raw), current=scenario;
    if(current==='error')return send(503,{detail:'Intentional mock failure'});
    if(url.pathname==='/api/analyze'){
      if(!body.session_id || !['tadasana','ardhakati_chakrasana'].includes(body.pose_id) || body.camera_view!=='front' || body.landmarks?.length!==33)return send(422,{detail:'Expected session_id, pose_id, front view and 33 landmarks'});
      return send(200,{...analysis,session_id:body.session_id,pose_id:body.pose_id,timestamp_ms:body.timestamp_ms,feedback_allowed:current!=='blocked',deviations:current==='normal'||current==='blocked'?[]:analysis.deviations});
    }
    if(url.pathname==='/api/agent/feedback'){
      if(!Array.isArray(body.deviations))return send(422,{detail:'Expected analysis event'});
      if(current==='slow')await new Promise(r=>setTimeout(r,11000));
      return send(200,{...feedback,text:'【联调桩】'+feedback.text});
    }
    send(404,{detail:'Mock route not found'});
  }catch{send(400,{detail:'Invalid request'});}
});
server.listen(Number(process.env.MOCK_PORT||8001),'127.0.0.1',()=>console.log('E mock: http://127.0.0.1:8001/__mock (never a real backend)'));
