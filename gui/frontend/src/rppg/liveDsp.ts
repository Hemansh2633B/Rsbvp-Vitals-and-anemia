export type RGB = [number, number, number]
export type TraceSample = { t: number; rois: Partial<Record<'forehead' | 'left_cheek' | 'right_cheek', RGB | null>> }
export type AlgorithmResult = { bpm: number | null; quality: number; waveform: number[] }
export type LiveAnalysis = {
  status: 'warming_up' | 'valid' | 'low_signal_quality' | 'excessive_motion' | 'face_not_detected' | 'roi_lost' | 'insufficient_frames' | 'reacquiring'
  reason: string
  bpm: number | null
  estimates: Record<string, number | null>
  consistencyBpm: number | null
  quality: number
  waveforms: Record<string, number[]>
  fs: number | null
}
const ROI_NAMES = ['forehead', 'left_cheek', 'right_cheek'] as const
const METHODS = ['green', 'pos', 'chrom'] as const
const LOW = 0.7
const HIGH = 3.5

export function resampleTrace(samples: TraceSample[], roi: typeof ROI_NAMES[number], channel: 'r'|'g'|'b'|0|1|2) {
  const available = samples.filter(s => s.rois[roi] && Number.isFinite(s.rois[roi]![0]) && Number.isFinite(s.rois[roi]![1]) && Number.isFinite(s.rois[roi]![2]))
  if (available.length < 8) return null
  const d = available.slice(1).map((s,i) => s.t - available[i].t).filter(x => x > 0)
  if (d.length < 3) return null
  const dt = median(d)
  const fs = 1 / dt
  if (!Number.isFinite(fs) || fs < 12 || fs <= 2*HIGH) return null
  const start = available[0].t, end = available[available.length-1].t
  const n = Math.floor((end-start)*fs)+1
  if (n < 8*fs) return null
  const k = typeof channel === 'number' ? channel : ({r:0,g:1,b:2} as const)[channel]
  const values:number[]=[]
  let j=0
  for(let i=0;i<n;i++) {
    const target=start+i/fs
    while(j+1<available.length && available[j+1].t<target) j++
    const a=available[j], b=available[Math.min(j+1,available.length-1)]
    if (b.t-a.t > Math.max(0.25, 2.5/fs)) return null
    const f=b.t===a.t?0:(target-a.t)/(b.t-a.t)
    values.push(a.rois[roi]![k]*(1-f)+b.rois[roi]![k]*f)
  }
  return {values, fs}
}
function median(a:number[]) { const x=[...a].sort((u,v)=>u-v); return x[Math.floor(x.length/2)] }
function filterBand(x:number[]) {
  // DC removal plus Hann-windowed spectral selection in the estimator. Retain
  // the trace here; browser-side IIR filtering would require state across frames.
  const mean=x.reduce((s,v)=>s+v,0)/x.length
  return x.map(v=>v-mean)
}
function chrom(rgb:number[][],fs:number) {
  const c=rgb.map(row=>row.map((v,i)=>v / (rgb.reduce((s,r)=>s+r[i],0)/rgb.length)-1))
  const xs=c.map(v=>3*v[0]-2*v[1]), ys=c.map(v=>1.5*v[0]+v[1]-1.5*v[2])
  const win=Math.max(8,Math.round(fs*1.6)), out=Array(xs.length).fill(0), weight=Array(xs.length).fill(0)
  for(let start=0;start<xs.length;start+=Math.max(1,Math.floor(win/2))) {
    const end=Math.min(xs.length,start+win), sx=xs.slice(start,end), sy=ys.slice(start,end)
    const alpha=std(sx)/Math.max(std(sy),1e-8)
    for(let i=start;i<end;i++){out[i]+=xs[i]-alpha*ys[i];weight[i]++}
  }
  return out.map((v,i)=>v/Math.max(1,weight[i]))
}
function std(x:number[]) { const m=x.reduce((s,v)=>s+v,0)/x.length; return Math.sqrt(x.reduce((s,v)=>s+(v-m)**2,0)/x.length) }
function spectral(x:number[],fs:number):AlgorithmResult {
  if(x.length<8*fs || !x.every(Number.isFinite)) return {bpm:null,quality:0,waveform:x}
  const y=filterBand(x), n=y.length
  let best=-1,bestPower=0,total=0
  for(let i=0;i<Math.floor(n/2);i++) {
    const f=i*fs/n
    if(f<LOW || f>HIGH) continue
    let re=0,im=0
    for(let j=0;j<n;j++) { const v=y[j]*(0.5-0.5*Math.cos(2*Math.PI*j/(n-1))); re+=v*Math.cos(2*Math.PI*i*j/n); im-=v*Math.sin(2*Math.PI*i*j/n) }
    const p=re*re+im*im; total+=p; if(p>bestPower){bestPower=p;best=f}
  }
  const bpm=best>0?best*60:null
  const quality=total>0?bestPower/total:0
  return {bpm,quality,waveform:y}
}
function process(rgb:number[][],fs:number,method:typeof METHODS[number]) {
  if(method==='green') return spectral(rgb.map(v=>v[1]),fs)
  if(method==='chrom') return spectral(chrom(rgb,fs),fs)
  // POS projection on the complete buffered window; treated as experimental
  // in-browser variant. The original rolling-window Python method is retained.
  const means=[0,1,2].map(i=>rgb.reduce((s,r)=>s+r[i],0)/rgb.length)
  const normalized=rgb.map(r=>r.map((v,i)=>v/Math.max(means[i],1e-8)-1))
  const s1=normalized.map(v=>v[1]-v[2]),s2=normalized.map(v=>v[1]+v[2]-2*v[0])
  const alpha=std(s1)/Math.max(std(s2),1e-8)
  return spectral(s1.map((v,i)=>v+alpha*s2[i]),fs)
}
export function analyzeSamples(samples:TraceSample[], requiredSeconds=10):LiveAnalysis {
  const end=samples.at(-1)?.t ?? 0, start=samples[0]?.t ?? 0, duration=end-start
  if(duration<requiredSeconds) return {status:'warming_up',reason:`Acquire ${Math.ceil(requiredSeconds-duration)} more seconds`,bpm:null,estimates:{},consistencyBpm:null,quality:0,waveforms:{},fs:null}
  const estimates:Record<string,number|null>={}, waveforms:Record<string,number[]>={}, qualities:number[]=[]
  let fs:number|null=null
  for(const roi of ROI_NAMES) {
    const rgb=([0,1,2] as const).map(ch=>resampleTrace(samples,roi,ch))
    if(rgb.some(v=>!v)) continue
    const rate=rgb[0]!.fs
    if(rgb.some(v=>Math.abs(v!.fs-rate)>.1)) continue
    fs=rate
    const matrix=rgb[0]!.values.map((_,i)=>[rgb[0]!.values[i],rgb[1]!.values[i],rgb[2]!.values[i]])
    for(const method of METHODS) {
      const key=`${roi}_${method}`, result=process(matrix,rate,method)
      estimates[key]=result.bpm; waveforms[key]=result.waveform.slice(-240); qualities.push(result.quality)
    }
  }
  const values=Object.values(estimates).filter((v):v is number=>v!==null && Number.isFinite(v))
  const bpm=values.length>=2?median(values):null
  const consistency=values.length>=2?Math.max(...values)-Math.min(...values):Infinity
  const quality=qualities.length?median(qualities):0
  const valid=bpm!==null && consistency<=12 && quality>=0.12
  const noRoi=Object.keys(estimates).length===0
  const insufficient=fs===null
  const reason=valid?'Independent ROI/method estimates agree':noRoi?'All skin ROIs are lost or unavailable':insufficient?'Insufficient frames or irregular sampling':values.length<2?'Insufficient valid ROI traces':consistency>12?'Estimator disagreement exceeds 12 BPM':'Weak pulse spectral concentration'
  return {status:valid?'valid':noRoi?'roi_lost':insufficient?'insufficient_frames':'low_signal_quality',reason,bpm:valid?bpm:null,estimates,consistencyBpm:Number.isFinite(consistency)?consistency:null,quality,waveforms,fs}
}
