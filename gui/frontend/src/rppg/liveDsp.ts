export type RGB = [number, number, number]
import type { RoiDiagnostics } from './roiGeometry'
/**
 * One sampled frame. `diagnostics` is optional so existing fixtures and exports
 * stay valid: it carries the per-ROI pixel accounting for that frame, which is
 * how a rejection can be explained later without storing any pixels.
 */
export type TraceSample = {
  t: number
  rois: Partial<Record<'forehead' | 'left_cheek' | 'right_cheek', RGB | null>>
  diagnostics?: RoiDiagnostics[]
}
export type LiveAnalysis = {
  status: 'warming_up' | 'valid' | 'low_signal_quality' | 'excessive_motion' | 'face_not_detected' | 'roi_lost' | 'insufficient_frames' | 'irregular_timestamps' | 'reacquiring' | 'processing_error'
  reason: string
  bpm: number | null
  estimates: Record<string, number | null>
  consistencyBpm: number | null
  quality: number
  waveforms: Record<string, number[]>
  fs: number | null
  /** Per-window spectral diagnostics behind the verdict (uncalibrated research metrics). */
  scores?: { fsHz: number | null; durationS: number | null; maxGapS: number | null; peakFraction: number | null; snrDb: number | null; separationRatio: number | null; roiCoverage: Record<string, number> | null; roiCoverageOverall: number | null; acquisition?: CaptureIntegrity | null }
  /** Six explicitly separated quality concepts; each is pass | fail | not_evaluated. */
  concepts?: { face_tracking: QualityConcept; roi_extraction: QualityConcept; temporal_acquisition: QualityConcept; pulse_signal: QualityConcept; algorithm_agreement: QualityConcept; availability: QualityConcept }
}
export type QualityConcept = 'pass' | 'fail' | 'not_evaluated'
import { captureIntegrity, integrityReason, type CaptureIntegrity } from './captureIntegrity'
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
export function traceDiagnostics(samples:TraceSample[],roi:typeof ROI_NAMES[number]):{n:number;fsHz:number|null;durationS:number;maxGapS:number|null;droppedIntervalFraction:number|null} {
  const available=samples.filter(s=>s.rois[roi]&&Number.isFinite(s.rois[roi]![0])&&Number.isFinite(s.rois[roi]![1])&&Number.isFinite(s.rois[roi]![2]))
  const n=available.length
  if(n<2) return {n,fsHz:null,durationS:0,maxGapS:null,droppedIntervalFraction:null}
  const intervals=available.slice(1).map((s,i)=>s.t-available[i].t)
  const sorted=[...intervals].filter(d=>d>0).sort((a,b)=>a-b)
  const fs=sorted.length?1/sorted[Math.floor(sorted.length/2)]:null
  const maxGapS=intervals.length?Math.max(...intervals):null
  const typical=sorted.length?sorted[Math.floor(sorted.length/2)]:null
  const dropped=typical?intervals.filter(d=>d>1.5*typical).length/intervals.length:null
  return {n,fsHz:fs!==null&&Number.isFinite(fs)?fs:null,durationS:available[n-1].t-available[0].t,maxGapS,droppedIntervalFraction:dropped}
}
function median(a:number[]) { const x=[...a].sort((u,v)=>u-v); return x[Math.floor(x.length/2)] }
function filterBand(x:number[]) {
  // DC removal plus Hann-windowed spectral selection in the estimator. Retain
  // the trace here; browser-side IIR filtering would require state across frames.
  const mean=x.reduce((s,v)=>s+v,0)/x.length
  return x.map(v=>v-mean)
}
function chrom(rgb:number[][],fs:number) {
  // Match gui/rppg_core/research.py::chrom_rppg input contract: at least 8
  // finite, strictly positive RGB means and a finite fs > 2*HIGH. Rejected
  // input throws; callers convert that to an explicit unavailable estimate.
  // NOTE: the Python chrom_rppg additionally applies a zero-phase Butterworth
  // bandpass (scipy). The browser cannot call scipy, so the in-band Hann
  // periodogram in spectralDiagnostics performs the band restriction instead;
  // the two pathways are parity-tested on shared fixtures, not interchangeable.
  if(rgb.length<8) throw new Error('CHROM requires at least 8 samples')
  for(const row of rgb){
    if(!Array.isArray(row)||row.length!==3) throw new Error('CHROM requires RGB triples')
    if(!row.every(v=>Number.isFinite(v)&&v>0)) throw new Error('CHROM requires finite positive RGB means')
  }
  if(!Number.isFinite(fs)||fs<=2*HIGH) throw new Error('CHROM requires fs > 7 Hz')
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
const SPECTRAL_MIN_CONCENTRATION=0.20, SPECTRAL_MIN_SNR_DB=3.0, SPECTRAL_MIN_SEPARATION=1.5
const PEAK_GUARD_RADIUS_HZ=0.15, COMPETITOR_MIN_DISTANCE_HZ=0.25
const MIN_ROI_COVERAGE=0.50 // union of usable skin ROI coverage required per window
function hann(n:number){const w=new Array(n);for(let i=0;i<n;i++)w[i]=0.5-0.5*Math.cos(2*Math.PI*i/(n-1));return w}
export function spectralDiagnostics(x:number[],fs:number):{bpm:number|null;quality:number;snrDb:number|null;separationRatio:number|null;waveform:number[]} {
  if(x.length<8*fs || !x.every(Number.isFinite)) return {bpm:null,quality:0,snrDb:null,separationRatio:null,waveform:x}
  const y=filterBand(x), n=y.length, win=hann(n)
  let best=-1,bestPower=0,total=0
  const band:Array<{f:number;power:number}>=[]
  for(let i=0;i<Math.floor(n/2);i++) {
    const f=i*fs/n
    let re=0,im=0
    for(let j=0;j<n;j++) { const v=y[j]*win[j]; re+=v*Math.cos(2*Math.PI*i*j/n); im-=v*Math.sin(2*Math.PI*i*j/n) }
    const p=re*re+im*im
    if(f>=LOW && f<=HIGH) { total+=p; band.push({f,power:p}); if(p>bestPower){bestPower=p;best=f} }
  }
  if(best<=0 || total<=0) return {bpm:null,quality:0,snrDb:null,separationRatio:null,waveform:y}
  const peakPower=bestPower, peakHz=best
  const floorBins=band.filter(b=>Math.abs(b.f-peakHz)>PEAK_GUARD_RADIUS_HZ)
  let snrDb:number|null=null
  if(floorBins.length){const sorted=floorBins.map(b=>b.power).sort((a,b)=>a-b);const m=sorted.length;const median=m%2?sorted[(m-1)/2]:(sorted[m/2-1]+sorted[m/2])/2;if(median>0)snrDb=10*Math.log10(peakPower/median)}
  let separationRatio:number|null=null
  for(let i=1;i<band.length-1;i++) {
    const cur=band[i]
    if(Math.abs(cur.f-peakHz)<COMPETITOR_MIN_DISTANCE_HZ) continue
    if(cur.power>=band[i-1].power && cur.power>=band[i+1].power) {
      const ratio=peakPower/Math.max(cur.power,1e-30)
      separationRatio=separationRatio===null?ratio:Math.min(separationRatio,ratio)
    }
  }
  return {bpm:best*60,quality:bestPower/total,snrDb,separationRatio,waveform:y}
}
// POS projection on the complete buffered window; experimental in-browser
// variant. The original rolling-window Python method is retained.
export function posProjection(rgb:number[][]):number[] {
  if(rgb.length<8) throw new Error('POS requires at least 8 samples')
  for(const row of rgb){
    if(!Array.isArray(row)||row.length!==3) throw new Error('POS requires RGB triples')
    if(!row.every(v=>Number.isFinite(v))) throw new Error('POS requires finite RGB means')
  }
  const means=[0,1,2].map(i=>rgb.reduce((s,r)=>s+r[i],0)/rgb.length)
  const normalized=rgb.map(r=>r.map((v,i)=>v/Math.max(means[i],1e-8)-1))
  const s1=normalized.map(v=>v[1]-v[2]),s2=normalized.map(v=>v[1]+v[2]-2*v[0])
  const alpha=std(s1)/Math.max(std(s2),1e-8)
  return s1.map((v,i)=>v+alpha*s2[i])
}
export function chromProjection(rgb:number[][],fs:number):number[] {
  return chrom(rgb,fs)
}
function process(rgb:number[][],fs:number,method:typeof METHODS[number]) {
  if(method==='green') return spectralDiagnostics(rgb.map(v=>v[1]),fs)
  if(method==='chrom') return spectralDiagnostics(chromProjection(rgb,fs),fs)
  return spectralDiagnostics(posProjection(rgb),fs)
}
export function analyzeSamples(samples:TraceSample[], requiredSeconds=10):LiveAnalysis {
  const end=samples.at(-1)?.t ?? 0, start=samples[0]?.t ?? 0, duration=end-start
  if(duration<requiredSeconds) return {status:'warming_up',reason:`Acquire ${Math.ceil(requiredSeconds-duration)} more seconds`,bpm:null,estimates:{},consistencyBpm:null,quality:0,waveforms:{},fs:null,scores:{fsHz:null,durationS:duration,maxGapS:null,peakFraction:null,snrDb:null,separationRatio:null,roiCoverage:null,roiCoverageOverall:null,acquisition:captureIntegrity({times:samples.map(s=>s.t)})}}
  const estimates:Record<string,number|null>={}, waveforms:Record<string,number[]>={}, qualities:number[]=[]
  let worstSnr:number|null=null, worstSeparation:number|null=null
  let fs:number|null=null
  for(const roi of ROI_NAMES) {
    const rgb=([0,1,2] as const).map(ch=>resampleTrace(samples,roi,ch))
    if(rgb.some(v=>!v)) continue
    const rate=rgb[0]!.fs
    if(rgb.some(v=>Math.abs(v!.fs-rate)>.1)) continue
    fs=rate
    const matrix=rgb[0]!.values.map((_,i)=>[rgb[0]!.values[i],rgb[1]!.values[i],rgb[2]!.values[i]])
    for(const method of METHODS) {
      const key=`${roi}_${method}`
      // A failing estimator must not kill the window: report that estimator
      // unavailable (bpm null) and keep evaluating the others.
      let result
      try{result=process(matrix,rate,method)}catch{result={bpm:null,quality:0,snrDb:null,separationRatio:null,waveform:[] as number[]}}
      estimates[key]=result.bpm; waveforms[key]=result.waveform.slice(-240); qualities.push(result.quality)
      if(result.snrDb!==null) worstSnr=worstSnr===null?result.snrDb:Math.min(worstSnr,result.snrDb)
      if(result.separationRatio!==null) worstSeparation=worstSeparation===null?result.separationRatio:Math.min(worstSeparation,result.separationRatio)
    }
  }
  const values=Object.values(estimates).filter((v):v is number=>v!==null && Number.isFinite(v))
  const bpm=values.length>=2?median(values):null
  const consistency=values.length>=2?Math.max(...values)-Math.min(...values):Infinity
  const quality=qualities.length?median(qualities):0
  // Cross-window timestamp integrity: any ROI trace with a > 0.25 s gap means
  // the capture is irregular (frame drops, tab throttling) even if resampling
  // could hide it — report it explicitly, never as a quiet sample count issue.
  let irregular=false, maxGapS:number|null=null, durationS:number|null=null
  const roiCoverage:Record<string,number>={}
  for(const roi of ROI_NAMES){
    const diag=traceDiagnostics(samples,roi)
    roiCoverage[roi]=samples.length?diag.n/samples.length:0
    if(diag.n<2)continue
    durationS=durationS===null?diag.durationS:Math.max(durationS,diag.durationS)
    if(diag.maxGapS!==null){maxGapS=maxGapS===null?diag.maxGapS:Math.max(maxGapS,diag.maxGapS);if(diag.maxGapS>0.25)irregular=true}
  }
  // Acquisition integrity from the raw (unresampled) timestamps. This is the
  // independent check on *what the camera delivered*; resampling can hide
  // duplicates and gaps, so the verdict is derived from the original samples.
  const acquisition = captureIntegrity({ times: samples.map(s => s.t) })
  const acquisitionProblem = integrityReason(acquisition)
  // A window with a timing defect is reported as such even if the resampling
  // happened to succeed: the numbers would describe a signal that was not
  // recorded at the rate the estimator assumes.
  const acquisitionIrregular = acquisition.hasLargeGap || acquisition.hasDuplicateSamples || acquisition.hasIrregularTiming
  irregular = irregular || acquisitionIrregular
  if (acquisition.maxGapS !== null) maxGapS = maxGapS === null ? acquisition.maxGapS : Math.max(maxGapS, acquisition.maxGapS)
  // Union coverage: fraction of samples with at least one usable skin ROI.
  // Per-ROI traces may be valid even at partial coverage, so the *window*
  // verdict requires the union, not individual ROI completeness.
  const unionCoverage=samples.length?samples.filter(s=>ROI_NAMES.some(roi=>s.rois[roi]&&Number.isFinite(s.rois[roi]![0])&&Number.isFinite(s.rois[roi]![1])&&Number.isFinite(s.rois[roi]![2]))).length/samples.length:0
  const roiCoveragePass=unionCoverage>=MIN_ROI_COVERAGE
  const snrPass=worstSnr!==null && worstSnr>=SPECTRAL_MIN_SNR_DB
  const sepPass=worstSeparation===null || worstSeparation>=SPECTRAL_MIN_SEPARATION
  const concentrationPass=quality>=SPECTRAL_MIN_CONCENTRATION
  const spectralPass=snrPass && sepPass && concentrationPass
  const agreementPass=values.length>=2 && consistency<=12
  const valid=bpm!==null && agreementPass && spectralPass && roiCoveragePass
  const noRoi=Object.keys(estimates).length===0
  const insufficient=fs===null
  const spectralReason=concentrationPass?(snrPass?(sepPass?'':'peak separation too weak'):'pulse SNR below 3 dB'):'spectral concentration below 20%'
  const coverageReason=`ROI coverage ${(unionCoverage*100).toFixed(0)}% below ${MIN_ROI_COVERAGE*100}%`
  const reason=valid?'Independent ROI/method estimates agree':irregular?(acquisitionProblem ?? 'Timestamp gaps exceed 0.25 s (dropped frames or tab throttling)'):noRoi?'All skin ROIs are lost or unavailable':insufficient?'Insufficient frames or irregular sampling':!roiCoveragePass?coverageReason:values.length<2?'Insufficient valid ROI traces':consistency>12?'Estimator disagreement exceeds 12 BPM':spectralReason
  const status=valid?'valid':irregular?'irregular_timestamps':noRoi?'roi_lost':insufficient?'insufficient_frames':'low_signal_quality'
  // Six explicitly separated quality concepts. Availability is the composite;
  // the other five are components, never a single blended score.
  const concepts:NonNullable<LiveAnalysis['concepts']>={
    face_tracking:'pass' as QualityConcept, // tracking failure short-circuits earlier (status face_not_detected)
    roi_extraction:roiCoveragePass?'pass':'fail',
    temporal_acquisition:(fs!==null && !irregular && !acquisition.insufficientSamplingRate)?'pass':'fail',
    pulse_signal:spectralPass?'pass':(qualities.length?'fail':'not_evaluated'),
    algorithm_agreement:agreementPass?'pass':(values.length>=2?'fail':'not_evaluated'),
    availability:valid?'pass':'fail',
  }
  return {status,reason,bpm:valid?bpm:null,estimates,consistencyBpm:Number.isFinite(consistency)?consistency:null,quality,waveforms,fs,concepts,scores:{fsHz:fs,durationS,maxGapS,peakFraction:qualities.length?quality:null,snrDb:worstSnr,separationRatio:worstSeparation,roiCoverage,roiCoverageOverall:unionCoverage,acquisition}}
}
