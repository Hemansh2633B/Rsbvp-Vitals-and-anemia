import { useEffect, useRef, useState } from 'react'
import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import { analyzeSamples, type LiveAnalysis, type TraceSample } from './liveDsp'
import { polygonMean } from './roi'
import './browserPulse.css'

const WASM = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.2.3/wasm'
const MODEL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
const regions = {
  forehead: [10,338,297,332,284,251,389,356,454,127,162,21,54,103,67,109],
  left_cheek: [50,101,118,119,100,126,209,206,203,142,123,116],
  right_cheek: [280,330,347,348,329,355,429,426,423,371,352,345],
} as const

type Track = 'idle'|'loading'|'tracking'|'face_not_detected'|'reacquiring'|'error'
const initial: LiveAnalysis = {status:'warming_up',reason:'Start the camera to begin local analysis',bpm:null,estimates:{},consistencyBpm:null,quality:0,waveforms:{},fs:null}
function Trace({values,label}:{values:number[];label:string}) {
  const width=320,height=64
  if(values.length<2)return <div className="muted small">{label}: collecting waveform…</div>
  const min=Math.min(...values),max=Math.max(...values),span=Math.max(max-min,1e-7)
  const points=values.map((v,i)=>`${(i/(values.length-1))*width},${height-(v-min)/span*height}`).join(' ')
  return <figure className="trace"><figcaption>{label}</figcaption><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label} waveform`}><polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke"/></svg></figure>
}
export function BrowserPulse(){
  const video=useRef<HTMLVideoElement>(null), canvas=useRef<HTMLCanvasElement>(null), overlay=useRef<HTMLCanvasElement>(null)
  const stream=useRef<MediaStream|null>(null), landmarker=useRef<FaceLandmarker|null>(null), raf=useRef(0), lastSample=useRef(0), lastAnalysis=useRef(0), lastUi=useRef(0), lostAt=useRef<number|null>(null), samples=useRef<TraceSample[]>([]),exportSamples=useRef<TraceSample[]>([]),acquisitionStart=useRef<number|null>(null), previousCenter=useRef<{x:number;y:number}|null>(null), centers=useRef<Array<{t:number;x:number;y:number}>>([]), smoothed=useRef<Array<{x:number;y:number;z:number}>>([])
  const [devices,setDevices]=useState<MediaDeviceInfo[]>([]),[deviceId,setDeviceId]=useState(''),[track,setTrack]=useState<Track>('idle'),[error,setError]=useState(''),[analysis,setAnalysis]=useState(initial),[duration,setDuration]=useState(0),[roiState,setRoiState]=useState('Waiting for face'),[algorithm,setAlgorithm]=useState('green')
  const stop=()=>{cancelAnimationFrame(raf.current);stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;landmarker.current?.close();landmarker.current=null;if(video.current)video.current.srcObject=null;setTrack('idle');setRoiState('Camera stopped')}
  useEffect(()=>{void refreshDevices();return()=>stop()},[])
  async function refreshDevices(){try{setDevices(await navigator.mediaDevices.enumerateDevices().then(d=>d.filter(x=>x.kind==='videoinput')))}catch{setDevices([])}}
  async function start(){
    setError('');setAnalysis(initial);samples.current=[];exportSamples.current=[];acquisitionStart.current=null;centers.current=[];previousCenter.current=null;setDuration(0);setTrack('loading')
    try{
      if(!navigator.mediaDevices?.getUserMedia)throw new Error('Camera API unavailable. Use HTTPS or localhost in a supported browser.')
      const s=await navigator.mediaDevices.getUserMedia({audio:false,video:{deviceId:deviceId?{exact:deviceId}:undefined,width:{ideal:640},height:{ideal:480}}})
      stream.current=s;if(video.current){video.current.srcObject=s;await video.current.play()}
      await refreshDevices()
      const vision=await FilesetResolver.forVisionTasks(WASM)
      try{landmarker.current=await FaceLandmarker.createFromOptions(vision,{baseOptions:{modelAssetPath:MODEL,delegate:'GPU'},runningMode:'VIDEO',numFaces:1,outputFaceBlendshapes:false,outputFacialTransformationMatrixes:false})}catch{landmarker.current=await FaceLandmarker.createFromOptions(vision,{baseOptions:{modelAssetPath:MODEL,delegate:'CPU'},runningMode:'VIDEO',numFaces:1,outputFaceBlendshapes:false,outputFacialTransformationMatrixes:false})}
      setTrack('tracking');lastSample.current=0
      const frame=()=>{
        const v=video.current,c=canvas.current,o=overlay.current,lm=landmarker.current
        if(!v||!c||!o||!lm||v.readyState<2){raf.current=requestAnimationFrame(frame);return}
        const now=performance.now()
        if(now-lastSample.current>=50){
          lastSample.current=now
          const w=v.videoWidth,h=v.videoHeight;if(!w||!h){raf.current=requestAnimationFrame(frame);return}
          c.width=w;c.height=h;o.width=w;o.height=h
          const ctx=c.getContext('2d',{willReadFrequently:true})!,ox=o.getContext('2d')!
          ctx.drawImage(v,0,0,w,h)
          let result:ReturnType<FaceLandmarker['detectForVideo']>
          try{result=lm.detectForVideo(v,now)}catch(e){setError(e instanceof Error?e.message:'Face tracker failed');stop();setTrack('error');return}
          const rawFace=result.faceLandmarks[0]
          const face=rawFace?.map((p,i)=>{const old=smoothed.current[i],alpha=.35;return{x:old?old.x*(1-alpha)+p.x*alpha:p.x,y:old?old.y*(1-alpha)+p.y*alpha:p.y,z:old?old.z*(1-alpha)+(p.z??0)*alpha:(p.z??0)}})
          if(face)smoothed.current=face
          ox.clearRect(0,0,w,h)
          if(!face){
            if(lostAt.current===null){lostAt.current=now;setAnalysis(prev=>({...prev,status:'low_signal_quality',bpm:null,reason:'Face not detected'}))}
            setTrack(now-lostAt.current>1800?'reacquiring':'face_not_detected');setRoiState('Face not detected')
            if(now-lostAt.current>4000&&acquisitionStart.current!==null){samples.current=[];centers.current=[];acquisitionStart.current=null;setDuration(0);setAnalysis({...initial,status:'low_signal_quality',reason:'Face lost; acquisition buffer reset'});previousCenter.current=null}
          }else{
            const wasLost=lostAt.current!==null;lostAt.current=null;setTrack('tracking')
            if(wasLost){samples.current=[];centers.current=[];previousCenter.current=null;acquisitionStart.current=now/1000;setDuration(0);setAnalysis({...initial,reason:'Tracking reacquired; collecting a fresh window'})}
            if(acquisitionStart.current===null)acquisitionStart.current=now/1000
            const center=face[1]??face[4]
            previousCenter.current={x:center.x,y:center.y}
            centers.current.push({t:now/1000,x:center.x,y:center.y});centers.current=centers.current.filter(p=>now/1000-p.t<=2)
            const roiSamples:TraceSample['rois']={forehead:null,left_cheek:null,right_cheek:null}
            const pixels=ctx.getImageData(0,0,w,h).data
            for(const [name,indices] of Object.entries(regions) as Array<[keyof typeof regions,readonly number[]]>) {
              const pts=indices.map(i=>face[i]).filter(Boolean)
              if(pts.length<6)continue
              const mean=polygonMean(pixels,w,h,pts);roiSamples[name]=mean
              const ctxPath=ox;ctxPath.beginPath();ctxPath.moveTo(pts[0].x*w,pts[0].y*h);for(const p of pts.slice(1))ctxPath.lineTo(p.x*w,p.y*h);ctxPath.closePath();ctxPath.strokeStyle=mean?'#58dfba':'#ffb547';ctxPath.lineWidth=Math.max(2,w/320);ctxPath.stroke()
            }
            const sample={t:now/1000,rois:roiSamples};samples.current.push(sample);if(samples.current.length>300)samples.current.shift();exportSamples.current.push(sample);if(exportSamples.current.length>18000)exportSamples.current.shift()
            const healthy=Object.values(roiSamples).filter(Boolean).length
            setRoiState(`${healthy}/3 skin ROIs available`)
            const elapsed=acquisitionStart.current===null?0:now/1000-acquisitionStart.current;if(now-lastUi.current>=250){lastUi.current=now;setDuration(elapsed)}
            if(elapsed>=10&&now-lastAnalysis.current>=500){lastAnalysis.current=now;const a=analyzeSamples(samples.current);const spread=centers.current.length?Math.hypot(Math.max(...centers.current.map(p=>p.x))-Math.min(...centers.current.map(p=>p.x)),Math.max(...centers.current.map(p=>p.y))-Math.min(...centers.current.map(p=>p.y))):0;if(spread>.08){setAnalysis({...a,status:'low_signal_quality',bpm:null,reason:'Excessive face displacement; hold still'})}else setAnalysis(a)}
          }
        }
        raf.current=requestAnimationFrame(frame)
      }
      raf.current=requestAnimationFrame(frame)
    }catch(e){stop();setTrack('error');setError(e instanceof Error?e.message:e instanceof DOMException?`${e.name}: ${e.message}`:String(e));setAnalysis({...initial,status:'low_signal_quality',reason:'Camera or face model unavailable'})}
  }
  const roiWave=Object.entries(analysis.waveforms).filter(([name])=>name.endsWith(`_${algorithm}`))
  function exportTrace(){const fields=['timestamp_s',...Object.keys(regions).flatMap(name=>['r','g','b'].map(c=>`${name}_${c}`))];const lines=[fields.join(','),...exportSamples.current.map(s=>[s.t,...Object.keys(regions).flatMap(name=>s.rois[name as keyof typeof regions]??[null,null,null])].map(v=>v===null?'':String(v)).join(','))];const url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/csv'}));const a=document.createElement('a');a.href=url;a.download=`rsbvp_rgb_trace_${new Date().toISOString().replaceAll(':','-')}.csv`;a.click();URL.revokeObjectURL(url)}
  const rgbWave=(['r','g','b'] as const).map((channel,index)=>({name:`Forehead ${channel.toUpperCase()}`,values:samples.current.map(s=>s.rois.forehead?.[index]??NaN).filter(Number.isFinite).slice(-240)}))
  return <section className="panel browser-pulse">
    <h2>Browser-local live pulse research</h2><p className="muted">Frames are analyzed in this browser; only numeric waveform summaries remain in memory. Camera access starts only after you press Start. This is experimental, not medical measurement.</p>
    <div className="live-controls"><label className="ctl">Camera<select value={deviceId} onChange={e=>setDeviceId(e.target.value)} disabled={track==='tracking'}><option value="">Default camera</option>{devices.map(d=><option value={d.deviceId} key={d.deviceId}>{d.label||'Camera'}</option>)}</select></label>{track==='tracking'||track==='face_not_detected'||track==='reacquiring'?<button className="danger" onClick={stop}>Stop camera</button>:<button className="primary" onClick={start} disabled={track==='loading'}>{track==='loading'?'Loading…':'Start camera'}</button>}<span aria-live="polite" className="live-status">{track.replaceAll('_',' ')}</span></div>
    {error&&<div role="alert" className="status error">{error}</div>}
    <div className="browser-camera"><video ref={video} muted playsInline aria-label="Local camera preview"/><canvas ref={overlay} aria-label="Forehead and cheek ROI overlay"/><canvas ref={canvas} hidden/></div>
    <div className="metric-grid"><div className="metric-card"><div className="metric-label">Pulse estimate</div><div className="metric-value">{analysis.bpm===null?'Unavailable':`${analysis.bpm.toFixed(0)} BPM`}</div><div className="metric-sub">Only shown when quality checks pass</div></div><div className="metric-card"><div className="metric-label">Acquisition</div><div className="metric-value">{duration.toFixed(1)} s</div><div className="metric-sub">{roiState}</div></div><div className="metric-card"><div className="metric-label">Quality / agreement</div><div className="metric-value">{analysis.status.replaceAll('_',' ')}</div><div className="metric-sub">{analysis.reason} · spectral concentration {(analysis.quality*100).toFixed(0)}%{analysis.consistencyBpm!==null?` · spread ${analysis.consistencyBpm.toFixed(1)} BPM`:''}</div></div></div>
    <p><strong>Measurement reason:</strong> {analysis.reason} · sampling {analysis.fs?`${analysis.fs.toFixed(1)} Hz`:'—'}</p>
    <div className="subcards">{Object.entries(analysis.estimates).map(([name,bpm])=><div className="subcard" key={name}><strong>{name.replace('_',' · ')}</strong><p>{bpm===null?'Unavailable':`${bpm.toFixed(1)} BPM`}</p></div>)}</div>
    <button className="secondary" disabled={!exportSamples.current.length} onClick={exportTrace}>Export timestamped RGB traces (CSV)</button>
    <label className="ctl">Displayed pulse algorithm<select value={algorithm} onChange={e=>setAlgorithm(e.target.value)}><option value="green">Green</option><option value="pos">POS</option><option value="chrom">CHROM</option></select></label>
    <h3>Forehead RGB traces</h3><div className="plot-grid">{rgbWave.map(({name,values})=><Trace key={name} label={name} values={values}/>)}</div>
    <h3>Pulse algorithm waveforms</h3><div className="plot-grid">{roiWave.map(([name,values])=><Trace key={name} label={name.replace('_',' ')} values={values}/>)}</div>
    <p className="muted small">MediaPipe task model and WASM are fetched from their published endpoints at camera start. Review model/data privacy. Face and ROI tracking may fail with occlusion, lighting, or pose. Frame images are not uploaded.</p>
  </section>
}
