import { useEffect, useRef, useState } from 'react'
import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import { type LiveAnalysis, type TraceSample } from './liveDsp'
import { buildTraceCsv, buildTraceMetadata, buildWindowRecord, buildWindowsExport } from './exports'
import { newSessionId } from './provenance'
import {
  FEATURE_MASKS,
  REGION_EXCLUSIONS,
  buildPatch,
  extractAllRois,
  type RoiDiagnostics,
  type RoiName,
} from './roiGeometry'
import { estimateKeyLabel, partitionEstimateKeys } from './estimateKeys'
import {
  drawRoiOverlay,
  computeOverlayTransform,
  backingStoreSize,
  overlayState,
  shouldMirror,
  type OverlayRegion,
} from './overlay'
import {
  describeTrackGeometry,
  inspectBrowserEnvironment,
  videoConstraintsFor,
  type SecureContextReport,
  type TrackGeometry,
} from './cameraEnvironment'
import { MIN_USABLE_FS_HZ, integrityReason, recoveryDelayMs, type CaptureIntegrity } from './captureIntegrity'
import {
  CONSENSUS,
  SessionCollector,
  type SessionLifecycle,
  buildSessionAggregateExport,
  buildSessionReadingsCsv,
  summarizeSession,
  type SessionSummary,
} from './sessionAggregate'
import { SessionResult } from './SessionResult'
import './browserPulse.css'

const WASM = import.meta.env.VITE_MEDIAPIPE_WASM_URL || 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.2.3/wasm'
const MODEL = import.meta.env.VITE_FACE_LANDMARKER_MODEL_URL || 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
// The ROI geometry lives in ./roiGeometry, where every landmark index is
// verified against the MediaPipe canonical face model and pinned by tests.

type AcquisitionPhase = 'idle'|'initialising'|'face_search'|'acquiring'|'processing'|'degraded'|'interrupted'|'completed'
const PHASE_LABELS: Record<AcquisitionPhase,string> = {
  idle:'Not started', initialising:'Initialising camera and face model', face_search:'Camera open, searching for a face',
  acquiring:'Acquiring signal', processing:'Processing window', degraded:'Acquisition degraded',
  interrupted:'Interrupted', completed:'Session complete (camera released)',
}
const PHASE_DETAIL: Record<AcquisitionPhase,string> = {
  idle:'Camera access begins only when you press Start.',
  initialising:'Requesting camera permission and loading the face landmarker.',
  face_search:'Frames are arriving; no valid forehead/cheek ROI yet.',
  acquiring:'Collecting a window. Estimates appear only after the quality checks pass.',
  processing:'A window is being analysed in the local worker.',
  degraded:'Frames are arriving but the timing or quality is not usable for a pulse estimate.',
  interrupted:'Capture stopped. No estimate is shown until a fresh window passes the checks.',
  completed:'Camera tracks, worker and face model released. Downloaded traces remain valid.',
}
type Track = 'idle'|'loading'|'model_loading'|'tracking'|'face_not_detected'|'reacquiring'|'error'
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
  const sessionId=useRef(0),stream=useRef<MediaStream|null>(null), landmarker=useRef<FaceLandmarker|null>(null), worker=useRef<Worker|null>(null), pendingJob=useRef(false), jobId=useRef(0), raf=useRef(0), lastSample=useRef(0), lastAnalysis=useRef(0), lastUi=useRef(0),lastVideoTime=useRef(-1), lastPlaybackCount=useRef<number|null>(null), lastPlaybackTime=useRef(0), lostAt=useRef<number|null>(null), samples=useRef<TraceSample[]>([]),exportSamples=useRef<TraceSample[]>([]),exportDropped=useRef(0),acquisitionStart=useRef<number|null>(null), previousCenter=useRef<{x:number;y:number}|null>(null), centers=useRef<Array<{t:number;x:number;y:number}>>([]), smoothed=useRef<Array<{x:number;y:number;z:number}>>([])
  const windowLog=useRef<Array<Record<string,unknown>>>([]),pendingWindow=useRef<{start_s:number;end_s:number;n_samples:number}|null>(null),sessionRef=useRef(newSessionId())
  const recovery=useRef({attempt:0,timer:0 as number|ReturnType<typeof setTimeout>})
  const [recoveryNote,setRecoveryNote]=useState('')
  // The single measurement collector for this session. Both the browser and the
  // server pathway use this class, so the two UIs cannot compute a session
  // average differently. Readings are append-only; the aggregate is derived.
  const collector=useRef(new SessionCollector())
  const [session,setSession]=useState<SessionSummary>(()=>summarizeSession([],{lifecycle:'stopped'}))
  const [devices,setDevices]=useState<MediaDeviceInfo[]>([]),[deviceId,setDeviceId]=useState(''),[track,setTrack]=useState<Track>('idle'),[error,setError]=useState(''),[analysis,setAnalysis]=useState(initial),[duration,setDuration]=useState(0),[roiState,setRoiState]=useState('Waiting for face'),[algorithm,setAlgorithm]=useState('green'),[cameraFps,setCameraFps]=useState<number|null>(null)
  const algorithmRef=useRef(algorithm);algorithmRef.current=algorithm
  const windowsDropped=useRef(0)
  const roiDiagRef=useRef<RoiDiagnostics[]>([])
  const lastDiagUi=useRef(0)
  const [roiDiagnostics,setRoiDiagnostics]=useState<RoiDiagnostics[]>([])
  const [showRoiDetails,setShowRoiDetails]=useState(false)
  const [unparsableKeys,setUnparsableKeys]=useState<string[]>([])
  const [environment,setEnvironment]=useState<SecureContextReport|null>(null)
  const [geometry,setGeometry]=useState<TrackGeometry|null>(null)
  const stop=()=>{sessionId.current++;cancelAnimationFrame(raf.current);worker.current?.terminate();worker.current=null;pendingJob.current=false;stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;landmarker.current?.close();landmarker.current=null;if(video.current)video.current.srcObject=null;setTrack('idle');setRoiState('Camera stopped');setRoiDiagnostics([]);roiDiagRef.current=[];setAnalysis(prev=>({...prev,status:'low_signal_quality',bpm:null,reason:'Capture stopped; no live estimate is available'}))}
  // Re-derive the session state whenever the capture lifecycle changes: the same
  // readings mean different things while running, stopped, or interrupted.
  useEffect(()=>{if(collector.current.size>0)resummarize()},[track])
  useEffect(()=>{void refreshDevices();const onVisibility=()=>{if(document.hidden&&stream.current){stop();setAnalysis(prev=>({...prev,status:'low_signal_quality',bpm:null,reason:'Capture stopped because the browser tab became hidden'}))}};document.addEventListener('visibilitychange',onVisibility);return()=>{document.removeEventListener('visibilitychange',onVisibility);clearTimeout(recovery.current.timer as number);stop()}},[])

  // A camera that drops out (USB, thermal shutdown, another app grabbing it) is
  // reopened with exponential backoff instead of silently dying with a stale
  // estimate on screen. After the attempt budget the user is told to press Start.
  function scheduleRecovery(reason:string){
    const attempt=recovery.current.attempt
    const delay=recoveryDelayMs(attempt)
    if(delay===null){setRecoveryNote(`${reason}. Automatic recovery stopped after ${attempt} attempts - press Start to try again.`);setTrack('error');return}
    const seconds=Math.round(delay/1000)
    setRecoveryNote(`${reason}. Reconnecting the camera in ${seconds} s (attempt ${attempt+1}).`)
    recovery.current.attempt=attempt+1
    clearTimeout(recovery.current.timer as number)
    recovery.current.timer=setTimeout(()=>{void start()},delay)
  }
  async function refreshDevices(){try{setDevices(await navigator.mediaDevices.enumerateDevices().then(d=>d.filter(x=>x.kind==='videoinput')))}catch{setDevices([])}}
  async function start(){
    const session=++sessionId.current
    setError('');setAnalysis(initial);samples.current=[];exportSamples.current=[];exportDropped.current=0;windowLog.current=[];pendingWindow.current=null;windowsDropped.current=0;acquisitionStart.current=null;centers.current=[];previousCenter.current=null;setDuration(0);lastVideoTime.current=-1;lastPlaybackCount.current=null;lastPlaybackTime.current=0;setCameraFps(null);sessionRef.current=newSessionId();collector.current.reset();setSession(summarizeSession([],{lifecycle:'running'}));setTrack('loading')
    try{
      // Check the browsing context explicitly and report *which* condition failed.
      // An arbitrary private-network HTTP address is not a secure context, so the
      // camera API is simply absent there; saying so is more useful than a generic
      // "camera unavailable".
      const env=inspectBrowserEnvironment()
      setEnvironment(env)
      if(!env.canCapture)throw new Error(env.message)
      const s=await navigator.mediaDevices.getUserMedia({audio:false,video:videoConstraintsFor(deviceId)})
      if(session!==sessionId.current){s.getTracks().forEach(t=>t.stop());return}
      stream.current=s;recovery.current.attempt=0;setRecoveryNote('');setTrack('model_loading');s.getVideoTracks().forEach(track=>{track.addEventListener('ended',()=>{stop();setError('Camera stream ended or was interrupted.');setAnalysis({...initial,status:'low_signal_quality',bpm:null,reason:'Camera stream ended'});setTrack('error');scheduleRecovery('The camera stream ended')},{once:true});track.addEventListener('mute',()=>{jobId.current++;pendingJob.current=false;setAnalysis({...initial,status:'reacquiring',reason:'Camera temporarily interrupted; reacquiring signal'});setTrack('reacquiring')});track.addEventListener('unmute',()=>{samples.current=[];centers.current=[];acquisitionStart.current=null;setDuration(0);setAnalysis({...initial,status:'reacquiring',reason:'Camera resumed; collecting a fresh window'});setTrack('reacquiring')})});if(video.current){video.current.srcObject=s;await video.current.play()}
      if(session!==sessionId.current)return
      await refreshDevices()
      let vision:Awaited<ReturnType<typeof FilesetResolver.forVisionTasks>>
      try{vision=await FilesetResolver.forVisionTasks(WASM)}catch{throw new Error(`MediaPipe WASM runtime failed to load from ${WASM}. Check your network or set VITE_MEDIAPIPE_WASM_URL to a reviewed mirror (see docs/MEDIAPIPE_ASSETS.md).`)}
      if(session!==sessionId.current)return
      let tracker:FaceLandmarker
      try{tracker=await FaceLandmarker.createFromOptions(vision,{baseOptions:{modelAssetPath:MODEL,delegate:'GPU'},runningMode:'VIDEO',numFaces:1,outputFaceBlendshapes:false,outputFacialTransformationMatrixes:false})}catch{try{tracker=await FaceLandmarker.createFromOptions(vision,{baseOptions:{modelAssetPath:MODEL,delegate:'CPU'},runningMode:'VIDEO',numFaces:1,outputFaceBlendshapes:false,outputFacialTransformationMatrixes:false})}catch{throw new Error(`Face Landmarker model failed to load from ${MODEL}. Check your network or set VITE_FACE_LANDMARKER_MODEL_URL to a reviewed mirror (see docs/MEDIAPIPE_ASSETS.md).`)}}
      if(session!==sessionId.current){tracker.close();return}
      landmarker.current=tracker
      if(typeof Worker==='undefined')throw new Error('Web Workers are unavailable; browser DSP cannot run safely in this browser.')
      worker.current=new Worker(new URL('./liveDsp.worker.ts',import.meta.url),{type:'module'})
      worker.current.onmessage=(event:MessageEvent<{id:number;result?:LiveAnalysis;error?:string}>)=>{
        pendingJob.current=false
        if(event.data.id!==jobId.current)return
        if(event.data.error){stop();setError(`Signal-processing worker failed: ${event.data.error}`);setAnalysis({...initial,status:'low_signal_quality',reason:'DSP worker failed; no current estimate'});setTrack('error');return}
        if(event.data.result){
          const result=event.data.result,win=pendingWindow.current
          windowLog.current.push(buildWindowRecord({windowIndex:windowLog.current.length + windowsDropped.current,analyzedUtc:new Date().toISOString(),pendingWindow:win,fs:result.fs,consensusBpm:result.bpm,estimates:result.estimates,qualityScore:result.quality,consistencyBpm:result.consistencyBpm,availabilityStatus:result.status,rejectionReason:result.status==='valid'?null:result.reason,scores:result.scores??null,concepts:result.concepts??null,selectedAlgorithm:algorithmRef.current}))
          if(windowLog.current.length>3600){windowLog.current.shift();windowsDropped.current++}
          recordWindow(result,win)
          setAnalysis(result)
        }
      }
      worker.current.onerror=()=>{stop();setError('Signal-processing worker crashed; no current estimate is available.');setAnalysis({...initial,status:'low_signal_quality',reason:'DSP worker failed'});setTrack('error')}
      setTrack('tracking');lastSample.current=0
      const frame=()=>{
        const v=video.current,c=canvas.current,o=overlay.current,lm=landmarker.current
        if(!v||!c||!o||!lm||v.readyState<2){raf.current=requestAnimationFrame(frame);return}
        const now=performance.now()
        if(now-lastSample.current>=50&&v.currentTime!==lastVideoTime.current){
          lastSample.current=now;lastVideoTime.current=v.currentTime
          const totalFrames=v.getVideoPlaybackQuality?.().totalVideoFrames
          if(Number.isFinite(totalFrames)&&(lastPlaybackCount.current===null||now-lastPlaybackTime.current>=500)){if(lastPlaybackCount.current!==null&&now>lastPlaybackTime.current)setCameraFps((totalFrames!-lastPlaybackCount.current)/((now-lastPlaybackTime.current)/1000));lastPlaybackCount.current=totalFrames!;lastPlaybackTime.current=now}
          const w=v.videoWidth,h=v.videoHeight;if(!w||!h){raf.current=requestAnimationFrame(frame);return}
          // Size the sampling canvas to the decoded frame exactly, and the overlay
          // backing store to the *displayed* box in device pixels. Getting these
          // two different sizes confused was the reason the overlay drifted off the
          // face on phone aspect ratios: the old code copied frame pixels into a
          // canvas then stretched it with CSS.
          c.width=w;c.height=h
          const box=o.getBoundingClientRect()
          const dpr=typeof window==='undefined'?1:(window.devicePixelRatio||1)
          const device=backingStoreSize(box.width||w,box.height||h,dpr)
          if(o.width!==device.width||o.height!==device.height){o.width=device.width;o.height=device.height}
          const ctx=c.getContext('2d',{willReadFrequently:true})!,ox=o.getContext('2d')!
          const overlayTransform=computeOverlayTransform(w,h,box.width||w,box.height||h,{mirrored:shouldMirror(stream.current?.getVideoTracks()[0]?.getSettings?.().facingMode),dpr})
          ctx.drawImage(v,0,0,w,h)
          let result:ReturnType<FaceLandmarker['detectForVideo']>
          try{result=lm.detectForVideo(v,now)}catch(e){setError(e instanceof Error?e.message:'Face tracker failed');stop();setTrack('error');return}
          const rawFace=result.faceLandmarks[0]
          const face=rawFace?.map((p,i)=>{const old=smoothed.current[i],alpha=.35;return{x:old?old.x*(1-alpha)+p.x*alpha:p.x,y:old?old.y*(1-alpha)+p.y*alpha:p.y,z:old?old.z*(1-alpha)+(p.z??0)*alpha:(p.z??0)}})
          if(face)smoothed.current=face
          ox.clearRect(0,0,w,h)
          if(!face){
            if(lostAt.current===null){lostAt.current=now;jobId.current++;pendingJob.current=false;setAnalysis(prev=>({...prev,status:'face_not_detected',bpm:null,reason:'Face not detected'}))}
            setTrack(now-lostAt.current>1800?'reacquiring':'face_not_detected');setRoiState('Face not detected')
            if(overlayTransform)drawRoiOverlay(ox,overlayTransform,[],{lost:true})
            setRoiDiagnostics([])
            if(now-lostAt.current>4000&&acquisitionStart.current!==null){samples.current=[];centers.current=[];acquisitionStart.current=null;setDuration(0);setAnalysis({...initial,status:'low_signal_quality',reason:'Face lost; acquisition buffer reset'});previousCenter.current=null}
          }else{
            const wasLost=lostAt.current!==null;lostAt.current=null;setTrack('tracking')
            if(wasLost){jobId.current++;pendingJob.current=false;samples.current=[];centers.current=[];previousCenter.current=null;acquisitionStart.current=now/1000;setDuration(0);setAnalysis({...initial,status:'reacquiring',reason:'Tracking reacquired; collecting a fresh window'})}
            if(acquisitionStart.current===null)acquisitionStart.current=now/1000
            const center=face[1]??face[4]
            previousCenter.current={x:center.x,y:center.y}
            centers.current.push({t:now/1000,x:center.x,y:center.y});centers.current=centers.current.filter(p=>now/1000-p.t<=2)
            // One pass over the frame: extract every ROI, keep its diagnostics, and
            // draw the same polygons back onto the overlay so what is shown is
            // exactly what was sampled.
            const pixels=ctx.getImageData(0,0,w,h).data
            const extracted=extractAllRois(pixels,w,h,face)
            const roiSamples:TraceSample['rois']=extracted.samples as TraceSample['rois']
            roiDiagRef.current=extracted.diagnostics
            if(now-lastDiagUi.current>=250){
              lastDiagUi.current=now
              setRoiDiagnostics(extracted.diagnostics)
              setGeometry(describeTrackGeometry({videoWidth:w,videoHeight:h,settings:stream.current?.getVideoTracks()[0]?.getSettings?.()??null,deviceLabel:devices.find(d=>d.deviceId===deviceId)?.label??null,canvasWidth:c.width,canvasHeight:c.height}))
            }
            if(overlayTransform){
              const overlayRegions:OverlayRegion[]=extracted.diagnostics.map(d=>({
                roi:d.region,
                polygon:buildPatchPolygon(d.region,face),
                masks:maskPolygons(d.region,face),
                sampled:d.meanRgb!==null,
              }))
              drawRoiOverlay(ox,overlayTransform,overlayRegions)
            }
            const sample={t:now/1000,rois:roiSamples,diagnostics:extracted.diagnostics};samples.current.push(sample);if(samples.current.length>300)samples.current.shift();exportSamples.current.push(sample);if(exportSamples.current.length>18000){exportSamples.current.shift();exportDropped.current++}
            const healthy=Object.values(roiSamples).filter(Boolean).length
            const state=overlayState(healthy,true)
            setRoiState(state==='all'?'3/3 skin ROIs available':state==='partial'?`${healthy}/3 skin ROIs available (some regions unusable)`:'Face found, but no ROI produced a usable sample this frame')
            const elapsed=acquisitionStart.current===null?0:now/1000-acquisitionStart.current;if(now-lastUi.current>=250){lastUi.current=now;setDuration(elapsed)}
            const spread=centers.current.length?Math.hypot(Math.max(...centers.current.map(p=>p.x))-Math.min(...centers.current.map(p=>p.x)),Math.max(...centers.current.map(p=>p.y))-Math.min(...centers.current.map(p=>p.y))):0
            if(spread>.08){jobId.current++;pendingJob.current=false;samples.current=[];acquisitionStart.current=null;setDuration(0);if(now-lastUi.current>=250){lastUi.current=now;setAnalysis({...initial,status:'excessive_motion',reason:'Excessive face displacement; hold still. Analysis buffer reset.'})}}
            else if(elapsed>=10&&now-lastAnalysis.current>=500&&!pendingJob.current&&worker.current){lastAnalysis.current=now;pendingJob.current=true;const id=++jobId.current;pendingWindow.current={start_s:samples.current[0]?.t??0,end_s:samples.current[samples.current.length-1]?.t??0,n_samples:samples.current.length};try{worker.current.postMessage({id,samples:samples.current})}catch(e){pendingJob.current=false;setAnalysis({...initial,status:'processing_error',reason:e instanceof Error?e.message:'DSP worker postMessage failed'})}}
          }
        }
        raf.current=requestAnimationFrame(frame)
      }
      raf.current=requestAnimationFrame(frame)
    }catch(e){if(session!==sessionId.current)return;stop();setTrack('error');setError(e instanceof Error?e.message:e instanceof DOMException?`${e.name}: ${e.message}`:String(e));setAnalysis({...initial,status:'low_signal_quality',reason:'Camera or face model unavailable'})}
  }
  const roiWave=Object.entries(analysis.waveforms).filter(([name])=>name.endsWith(`_${algorithm}`))
  // One analysed window -> one reading. The consensus series is what the
  // agreement gate already checked across ROIs and methods; the individual
  // estimator series are recorded separately so they are never averaged as if
  // they were interchangeable. Wall-clock arrival is used for staleness: a
  // result that arrives long after it was computed describes a past moment.
  // Lifecycle is derived from the tracked state at the moment of summarising, so
  // "insufficient" (a final verdict) can never be shown while the camera is still
  // collecting, and "collecting" can never be shown after an interruption.
  function lifecycleNow():SessionLifecycle{
    if(track==='error')return 'interrupted'
    if(track==='idle')return 'stopped'
    return 'running'
  }
  function resummarize(lifecycle:SessionLifecycle=lifecycleNow()){
    setSession(summarizeSession(collector.current.all(),{lifecycle}))
  }
  function recordWindow(result:LiveAnalysis,win:{start_s:number;end_s:number;n_samples:number}|null){
    const nowMs=Date.now()
    const sampling={fsHz:result.fs,nSamples:win?.n_samples??null,windowStartS:win?.start_s??null,windowEndS:win?.end_s??null}
    const elapsed=acquisitionStart.current===null?null:performance.now()/1000-acquisitionStart.current
    const rejected=result.status!=='valid'
    const shared={qualityScore:Number.isFinite(result.quality)?result.quality:null,qualityVerdict:result.status,sampling,rejectionReason:rejected?result.reason:null,analyzedAtMs:nowMs,sessionElapsedS:elapsed,windowIndex:windowLog.current.length+windowsDropped.current}
    collector.current.add({metric:'heart_rate',value:result.bpm,algorithm:CONSENSUS,roi:'all',...shared})
    // Parse "<roi>_<method>" against the known suffixes. Splitting on the first
    // underscore turned "left_cheek_green" into roi "left" + algorithm
    // "cheek_green", which silently detached every cheek estimate from its region
    // and from the known algorithm set. Unknown keys are counted, not guessed.
    const {parsed,unparsable}=partitionEstimateKeys(result.estimates)
    if(unparsable.length)setUnparsableKeys(unparsable)
    for(const {roi,method} of parsed){
      collector.current.add({metric:'heart_rate',value:result.estimates[`${roi}_${method}`]??null,algorithm:method,roi,...shared})
    }
    resummarize()
  }
  // Polygon helpers used by both extraction and the overlay, so the drawn shape
  // and the sampled shape cannot drift apart.
  function buildPatchPolygon(region:RoiName,face:Array<{x:number;y:number}>){
    const built=buildPatch(region,face)
    return built.ok?built.polygon:[]
  }
  function maskPolygons(region:RoiName,face:Array<{x:number;y:number}>){
    const out:Array<Array<{x:number;y:number}>>=[]
    for(const name of REGION_EXCLUSIONS[region]){
      const indices=FEATURE_MASKS[name]
      if(!indices)continue
      const pts=indices.map(i=>face[i]).filter(p=>p&&Number.isFinite(p.x)&&Number.isFinite(p.y))
      if(pts.length>=3)out.push(pts)
    }
    return out
  }
  function download(content:BlobPart,type:string,name:string){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000)}
  function exportSessionReadings(){
    download(buildSessionReadingsCsv(collector.current.all()),'text/csv',`rsbvp_session_readings_${new Date().toISOString().replaceAll(':','-')}.csv`)
  }
  function exportSessionAggregate(){
    const out=buildSessionAggregateExport({sessionId:sessionRef.current,createdUtc:new Date().toISOString(),readings:collector.current.all(),summary:session,capture:{algorithms:['Green','POS','CHROM'],rois:['forehead','left_cheek','right_cheek'],passbandHz:[0.7,3.5],requiredSeconds:10,backend:'rsbvp-browser-liveDsp',cameraLabel:devices.find(d=>d.deviceId===deviceId)?.label??null,samplingRateHz:measuredFps}})
    download(JSON.stringify(out,null,2),'application/json',`rsbvp_session_summary_${new Date().toISOString().replaceAll(':','-')}.json`)
  }
  function exportTrace(){
    const stamp=new Date().toISOString().replaceAll(':','-'),base=`rsbvp_rgb_trace_${stamp}`
    const createdUtc=new Date().toISOString(),sessionId=sessionRef.current
    const lines=buildTraceCsv(exportSamples.current)
    const metadata=buildTraceMetadata({createdUtc,sessionId,sampleCount:exportSamples.current.length,earlierSamplesDropped:exportDropped.current,traceStartTs:exportSamples.current[0]?.t??null,traceEndTs:exportSamples.current.at(-1)?.t??null,acquisitionDurationS:duration,cameraFps,sampleRateMedianHz:measuredFps,droppedIntervalFraction:droppedFraction,analysisStatus:analysis.status,analysisReason:analysis.reason,estimatesBpm:analysis.estimates,validConsensusBpm:analysis.bpm,qualityConcepts:analysis.concepts??null,roiCoverage:analysis.scores?.roiCoverage??null,roiCoverageOverall:analysis.scores?.roiCoverageOverall??null,userAgent:navigator.userAgent})
    const windows=buildWindowsExport(windowLog.current,windowsDropped.current,createdUtc,sessionId)
    const download=(content:BlobPart,type:string,name:string)=>{const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000)}
    download(lines,'text/csv',`${base}.csv`);download(JSON.stringify(metadata,null,2),'application/json',`${base}.json`);download(JSON.stringify(windows,null,2),'application/json',`${base}_windows.json`)
  }
  const intervals=samples.current.slice(1).map((s,i)=>s.t-samples.current[i].t).filter(d=>d>0)
  const sortedIntervals=[...intervals].sort((a,b)=>a-b),typicalInterval=sortedIntervals.length?sortedIntervals[Math.floor(sortedIntervals.length/2)]:null
  const measuredFps=typicalInterval?1/typicalInterval:null,droppedFraction=typicalInterval?intervals.filter(d=>d>1.5*typicalInterval).length/Math.max(1,intervals.length):null
  const roiCoverage=(['forehead','left_cheek','right_cheek'] as const).map(roi=>({roi,pct:samples.current.length?samples.current.filter(s=>s.rois[roi]!==null&&s.rois[roi]!==undefined).length/samples.current.length:0}))
  const unionCoverage=analysis.scores?.roiCoverageOverall??null
  const acquisition:CaptureIntegrity|null=analysis.scores?.acquisition??null
  const conceptEntries=analysis.concepts?Object.entries(analysis.concepts):[]
  const faceMotion=centers.current.length?Math.hypot(Math.max(...centers.current.map(p=>p.x))-Math.min(...centers.current.map(p=>p.x)),Math.max(...centers.current.map(p=>p.y))-Math.min(...centers.current.map(p=>p.y))):0
  const rgbWave=(['r','g','b'] as const).map((channel,index)=>({name:`Forehead ${channel.toUpperCase()}`,values:samples.current.map(s=>s.rois.forehead?.[index]??NaN).filter(Number.isFinite).slice(-240)}))
  // Explicit, non-overlapping acquisition phases. The old single "tracking" label
  // conflated "camera open" with "measuring"; the distinction matters because a
  // camera can deliver frames while the window is still not analysable.
  const phase: AcquisitionPhase = track==='idle' ? (duration>0 ? 'completed' : 'idle')
    : track==='loading' || track==='model_loading' ? 'initialising'
    : track==='error' ? 'interrupted'
    : track==='face_not_detected' ? 'face_search'
    : track==='reacquiring' ? 'acquiring'
    : acquisition===null ? 'acquiring'
    : acquisition.regular ? 'processing' : 'degraded'
  const timingProblem = acquisition===null ? null : integrityReason(acquisition)
  const reasons: string[] = []
  if (track==='idle') reasons.push('Camera is not open')
  if (track==='error' && error) reasons.push(error)
  if (track==='face_not_detected') reasons.push('No face found; point the camera at a well-lit face')
  if (track==='reacquiring') reasons.push('Camera resumed or face reacquired; a fresh window is needed')
  if (timingProblem) reasons.push(timingProblem)
  if (acquisition?.insufficientSamplingRate) reasons.push(`Needs at least ${MIN_USABLE_FS_HZ} fps`)
  if (analysis.status!=='valid') reasons.push(analysis.reason)
  const unavailableBecause = analysis.bpm===null ? [...new Set(reasons)].join(' · ') : ''
  return <section className="panel browser-pulse">
    <h2>Browser-local live pulse research</h2><p className="muted">Frames are analyzed in this browser; only numeric waveform summaries remain in memory. Camera access starts only after you press Start. This is experimental, not medical measurement.</p>
    <div className="live-controls"><label className="ctl">Camera<select value={deviceId} onChange={e=>setDeviceId(e.target.value)} disabled={track!=='idle'&&track!=='error'}><option value="">Default camera</option>{devices.map(d=><option value={d.deviceId} key={d.deviceId}>{d.label||'Camera'}</option>)}</select></label>{track!=='idle'&&track!=='error'?<button className="danger" onClick={stop}>Stop camera</button>:<button className="primary" onClick={start}>Start camera</button>}<span aria-live="polite" className="live-status">{track.replaceAll('_',' ')}</span></div>
    {error&&<div role="alert" className="status error">{error}</div>}
    <div className="acquisition-status" role="status" aria-live="polite">
      <span className={`phase-chip phase-${phase}`}>{PHASE_LABELS[phase]}</span>
      <span className="muted small">{PHASE_DETAIL[phase]}</span>
      {analysis.bpm===null&&<p className="muted small"><strong>Why unavailable:</strong> {unavailableBecause}</p>}
      <div className="session-progress" role="progressbar" aria-label="Accepted readings collected"
        aria-valuemin={0} aria-valuemax={session.config.targetAcceptedReadings}
        aria-valuenow={Math.min(session.nAcceptedTotal,session.config.targetAcceptedReadings)}
        aria-valuetext={`${session.nAcceptedTotal} of ${session.config.targetAcceptedReadings} accepted readings`}>
        <div className="session-progress-fill" style={{width:`${Math.min(100,(session.nAcceptedTotal/session.config.targetAcceptedReadings)*100)}%`}}/>
      </div>
      <p className="muted small">
        {session.resultAvailable
          ? `Session average available from ${session.nAcceptedTotal} accepted readings - you can stop the camera.`
          : `${session.nAcceptedTotal} accepted of ${session.config.targetAcceptedReadings} target readings (${session.config.minIndependentWindows} independent windows needed). ${
              analysis.status==='valid'
                ? 'Signal acceptable - keep still.'
                : 'Hold still in even, bright light until the signal is acceptable.'}`}
      </p>
    </div>
    <SessionResult summary={session} sessionId={sessionRef.current} onExportReadings={exportSessionReadings} onExportAggregate={exportSessionAggregate} liveStatus={session.completion==='collecting'||session.completion==='available'?`Live: ${analysis.status==='valid'?'signal acceptable':analysis.reason}`:null}/>
    <div className="browser-camera"><video ref={video} muted playsInline aria-label="Local camera preview"/><canvas ref={overlay} aria-label="Forehead and cheek ROI overlay"/><canvas ref={canvas} hidden/></div>
    <h3>ROI tracking quality</h3><div className="subcards">{roiCoverage.map(({roi,pct})=><div className="subcard" key={roi}><strong>{roi.replace('_',' ')}</strong><p>{pct>=.8?'Tracking':pct>0?'Partial / unstable':'ROI lost'}</p><p className="muted small">{(pct*100).toFixed(0)}% valid skin samples</p></div>)}</div>
    <p className="muted small">Union coverage: {unionCoverage===null?'—':`${(unionCoverage*100).toFixed(0)}%`} of analyzed-window samples have at least one usable skin ROI (a window is only analysable at ≥ 50%).</p>
    {roiDiagnostics.length>0 && <>
      <h3>ROI extraction diagnostics</h3>
      <p className="muted small">
        Per-region pixel accounting for the most recent frame. Every candidate pixel inside a region is
        either used, removed by a facial-feature mask, or rejected for a named reason - the counts add up
        exactly. Geometry and signal failures are reported separately: a region can be perfectly placed
        and still yield nothing usable.
      </p>
      <div className="subcards roi-diagnostics">
        {roiDiagnostics.map(d=><div className={`subcard roi-diag ${d.meanRgb?'diag-ok':'diag-fail'}`} key={d.region}>
          <strong>{d.region.replace('_',' ')}</strong>
          <p className={d.meanRgb?'concept-pass':'concept-fail'}>{d.meanRgb?'Sampling':'No sample'}</p>
          <p className="muted small">{d.summary}</p>
          {d.invalidReason&&<p className="muted small diag-reason"><code>{d.invalidReason}</code></p>}
        </div>)}
      </div>
      <button className="secondary small" aria-expanded={showRoiDetails} onClick={()=>setShowRoiDetails(v=>!v)}>
        {showRoiDetails?'Hide':'Show'} full pixel accounting
      </button>
      {showRoiDetails && <table className="roi-diag-table">
        <caption className="muted small">Counts for the most recent frame</caption>
        <thead><tr><th scope="col">Region</th><th scope="col">Polygon px²</th><th scope="col">Candidates</th><th scope="col">Masked</th><th scope="col">Rejected</th><th scope="col">Used</th><th scope="col">Used %</th><th scope="col">Mean RGB</th><th scope="col">Median RGB</th><th scope="col">Geometrically valid</th></tr></thead>
        <tbody>{roiDiagnostics.map(d=><tr key={d.region}>
          <th scope="row">{d.region.replace('_',' ')}</th>
          <td>{d.polygonAreaPx.toFixed(0)}</td>
          <td>{d.candidatePixels}</td>
          <td>{d.excludedByMask}</td>
          <td>{Object.values(d.rejected).reduce((a,b)=>a+b,0)}</td>
          <td>{d.acceptedPixels}</td>
          <td>{(d.acceptedFraction*100).toFixed(1)}%</td>
          <td>{d.meanRgb?d.meanRgb.map(v=>v.toFixed(0)).join(' / '):'—'}</td>
          <td>{d.medianRgb?d.medianRgb.map(v=>v.toFixed(0)).join(' / '):'—'}</td>
          <td className={d.valid?'concept-pass':'concept-fail'}>{d.valid?'yes':'no'}</td>
        </tr>)}</tbody>
      </table>}
      {showRoiDetails && <table className="roi-diag-table">
        <caption className="muted small">Why candidate pixels were not used</caption>
        <thead><tr><th scope="col">Region</th><th scope="col">Outside boundary</th><th scope="col">In feature mask</th><th scope="col">Too dark</th><th scope="col">Too bright</th><th scope="col">Channel order</th><th scope="col">Low chroma</th></tr></thead>
        <tbody>{roiDiagnostics.map(d=><tr key={d.region}>
          <th scope="row">{d.region.replace('_',' ')}</th>
          <td>{d.excludedByMask}</td>
          <td>{d.excludedByMask}</td>
          <td>{d.rejected.too_dark}</td>
          <td>{d.rejected.too_bright}</td>
          <td>{d.rejected.channel_order}</td>
          <td>{d.rejected.low_chroma}</td>
        </tr>)}</tbody>
      </table>}
      <p className="muted small">
        “Low chroma” means the patch was nearly grey - a signal-capability check, not a skin-tone
        judgement: POS and CHROM both need colour variation. Nothing here is a universal skin
        classifier and no per-person calibration is applied.
      </p>
    </>}
    {environment && <section className="camera-environment">
      <h3>Camera environment</h3>
      <p className="muted small">{environment.message}</p>
      <div className="subcards">
        <div className="subcard"><strong>Secure context</strong><p className={environment.secure?'concept-pass':'concept-fail'}>{environment.secure?'yes':'no'}</p><p className="muted small">{environment.origin??'unknown origin'}</p></div>
        <div className="subcard"><strong>Camera API</strong><p className={environment.canCapture?'concept-pass':'concept-fail'}>{environment.canCapture?'available':'unavailable'}</p><p className="muted small">mediaDevices {environment.mediaDevices?'present':'missing'}</p></div>
        {geometry&&<div className="subcard"><strong>Frame</strong><p>{geometry.videoWidth?`${geometry.videoWidth}x${geometry.videoHeight}`:'—'}</p><p className="muted small">{geometry.orientation}{geometry.aspectRatio?` · ${geometry.aspectRatio.toFixed(2)}:1`:''}{geometry.facingMode?` · facing ${geometry.facingMode}`:''}</p></div>}
        {geometry&&<div className="subcard"><strong>Sampling canvas</strong><p className={geometry.canvasMatchesVideo?'concept-pass':'concept-fail'}>{geometry.canvasMatchesVideo?'matches frame':'does not match'}</p><p className="muted small">{geometry.canvasWidth}x{geometry.canvasHeight}</p></div>}
      </div>
      {geometry&&<p className="muted small">{geometry.message}</p>}
    </section>}
    <div className="metric-grid"><div className="metric-card live-estimate"><div className="metric-label">Live reading (this window)</div><div className="metric-value">{analysis.bpm===null?'Unavailable':`${analysis.bpm.toFixed(0)} BPM`}</div><div className="metric-sub">Changes during the session; the session average is computed separately below. Only shown when quality checks pass.</div></div><div className="metric-card"><div className="metric-label">Acquisition</div><div className="metric-value">{duration.toFixed(1)} s</div><div className="metric-sub">{roiState} · camera {cameraFps?`${cameraFps.toFixed(1)} FPS`:'FPS —'} · sampled {measuredFps?`${measuredFps.toFixed(1)} Hz`:'rate —'} · dropped intervals {droppedFraction===null?'—':`${(droppedFraction*100).toFixed(1)}%`}</div></div><div className="metric-card"><div className="metric-label">Quality / agreement</div><div className="metric-value">{analysis.status.replaceAll('_',' ')}</div><div className="metric-sub">{analysis.reason} · spectral concentration {(analysis.quality*100).toFixed(0)}% · face motion {(faceMotion*100).toFixed(1)}%{analysis.consistencyBpm!==null?` · spread ${analysis.consistencyBpm.toFixed(1)} BPM`:''}</div></div></div>
    {recoveryNote&&<p role="status" className="muted small">{recoveryNote}</p>}
    <h3>Camera acquisition integrity</h3>
    {acquisition===null
      ? <p className="muted small">Timing diagnostics appear once a window has been analysed.</p>
      : <><div className="subcards">
          <div className="subcard"><strong>Effective rate</strong><p>{acquisition.medianFsHz===null?'—':`${acquisition.medianFsHz.toFixed(1)} fps`}</p><p className="muted small">mean {acquisition.meanFsHz===null?'—':`${acquisition.meanFsHz.toFixed(1)} fps`}</p></div>
          <div className="subcard"><strong>Largest gap</strong><p>{acquisition.maxGapS===null?'—':`${acquisition.maxGapS.toFixed(2)} s`}</p><p className="muted small">{acquisition.droppedIntervalFraction===null?'—':`${(acquisition.droppedIntervalFraction*100).toFixed(0)}% intervals dropped`}</p></div>
          <div className="subcard"><strong>Duplicate frames</strong><p>{acquisition.duplicateFrameFraction!==null?`${(acquisition.duplicateFrameFraction*100).toFixed(0)}%`:(acquisition.duplicateIntervalFraction!==null?`${(acquisition.duplicateIntervalFraction*100).toFixed(0)}%`:'—')}</p><p className="muted small">same sensor frame sampled twice</p></div>
          <div className="subcard"><strong>Timing regularity</strong><p className={acquisition.regular?'concept-pass':'concept-fail'}>{acquisition.regular?'Regular':'Irregular'}</p><p className="muted small">{acquisition.intervalJitterCv===null?'—':`jitter ${(acquisition.intervalJitterCv*100).toFixed(0)}%`}</p></div>
        </div>
        <p className="muted small">Measured from the capture timestamps themselves, not from the requested frame rate. A window with a reported timing defect is never presented as an available measurement, because the estimators assume uniform sampling.</p></>
    }
    <h3>Quality concepts</h3>
    <p className="muted small">Separated checks, not a blended score. Availability is the composite verdict; the other five are components. “Not evaluated” means the check never ran for this window.</p>
    <div className="subcards concept-grid">{conceptEntries.map(([name,state])=><div className="subcard" key={name}><strong>{name.replaceAll('_',' ')}</strong><p className={state==='pass'?'concept-pass':state==='fail'?'concept-fail':'concept-na'}>{state==='pass'?'Pass':state==='fail'?'Fail':'Not evaluated'}</p></div>)}{conceptEntries.length===0&&<p className="muted small">Concept checks appear once analysis begins.</p>}</div>
    <p><strong>Measurement reason:</strong> {analysis.reason} · sampling {analysis.fs?`${analysis.fs.toFixed(1)} Hz`:'—'}</p>
    <p className="muted small">Per-region, per-algorithm estimates. Region and algorithm are kept separate; they are never averaged together. None of these is a session result on its own.</p>
    <div className="subcards">{Object.entries(analysis.estimates).map(([name,bpm])=><div className="subcard" key={name}><strong>{estimateKeyLabel(name)}</strong><p>{bpm===null?'Unavailable':`${bpm.toFixed(1)} BPM`}</p></div>)}</div>
    {unparsableKeys.length>0&&<div role="alert" className="status error">
      Unrecognised estimate key{unparsableKeys.length===1?'':'s'} {unparsableKeys.map(k=>`"${k}"`).join(', ')}. These values are <strong>not</strong> attributed to any region or algorithm and are excluded from the session readings rather than being guessed.
    </div>}
    <button className="secondary" disabled={!exportSamples.current.length} onClick={exportTrace}>Export traces + window analysis (CSV & JSON)</button>
    <p className="muted small">Exports are local downloads; nothing is sent anywhere. Each window record carries its provenance (bounds, sampling rate, selected algorithm, per-estimator estimates, concepts, ROI coverage, rejection reason) — see <code>docs/EXPORT_SCHEMA.md</code>.</p>
    <label className="ctl">Displayed pulse algorithm<select value={algorithm} onChange={e=>setAlgorithm(e.target.value)}><option value="green">Green</option><option value="pos">POS</option><option value="chrom">CHROM</option></select></label>
    <h3>Forehead RGB traces</h3><div className="plot-grid">{rgbWave.map(({name,values})=><Trace key={name} label={name} values={values}/>)}</div>
    <h3>Pulse algorithm waveforms</h3><div className="plot-grid">{roiWave.map(([name,values])=><Trace key={name} label={name.replace('_',' ')} values={values}/>)}</div>
    <p className="muted small">MediaPipe Tasks Vision code and the Google-hosted Face Landmarker task are fetched at camera start from documented URLs; see <a href="https://github.com/Hemansh2633B/Rsbvp-Vitals-and-anemia/blob/main/docs/MEDIAPIPE_ASSETS.md">asset provenance and licensing notes</a>. Only those assets are requested: camera frames remain in this browser and are not uploaded. Tracking may fail with occlusion, lighting, pose, or ROI visibility.</p>
  </section>
}
