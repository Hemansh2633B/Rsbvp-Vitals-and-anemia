import {describe,it,expect} from 'vitest'
import {captureIntegrity,integrityReason,median,recoveryDelayMs} from './captureIntegrity'
import {analyzeSamples,type TraceSample} from './liveDsp'

/** Regular capture at `fs` for `seconds`, starting at t0. */
function timestamps(fs:number,seconds:number,t0=0){
  const n=Math.round(fs*seconds),out:number[]=[]
  for(let i=0;i<n;i++)out.push(t0+i/fs)
  return out
}
/** One synthetic pulse sample train (30 fps, 20 s) with a 0.45 R/G/B amplitude. */
function pulseSamples(fs=30,seconds=20):TraceSample[]{
  return timestamps(fs,seconds).map(t=>({t,rois:{
    forehead:[120+0.45*Math.sin(2*Math.PI*1.2*t),100+0.35*Math.sin(2*Math.PI*1.2*t),80] as [number,number,number],
    left_cheek:[118+0.45*Math.sin(2*Math.PI*1.2*t),98+0.35*Math.sin(2*Math.PI*1.2*t),79] as [number,number,number],
    right_cheek:[122+0.45*Math.sin(2*Math.PI*1.2*t),102+0.35*Math.sin(2*Math.PI*1.2*t),81] as [number,number,number],
  }}))
}

// These tests exercise *software* behaviour of the acquisition bookkeeping.
// Synthetic timestamps and synthetic RGB are software fixtures: they say
// nothing about real cameras, skin optics or measurement accuracy.
describe('capture integrity from real timestamps',()=>{
  it('measures the effective rate of a regular 30 fps capture',()=>{
    const r=captureIntegrity({times:timestamps(30,10)})
    expect(r.nSamples).toBe(300)
    expect(r.medianFsHz).toBeCloseTo(30,6)
    expect(r.meanFsHz).toBeCloseTo(30,6)
    expect(r.maxGapS).toBeCloseTo(1/30,6)
    expect(r.regular).toBe(true)
    expect(r.insufficientSamplingRate).toBe(false)
    expect(integrityReason(r)).toBeNull()
  })

  it('flags a camera that delivers less than the analysable rate',()=>{
    const r=captureIntegrity({times:timestamps(8,10)})
    expect(r.medianFsHz).toBeCloseTo(8,6)
    expect(r.insufficientSamplingRate).toBe(true)
    expect(r.regular).toBe(false)
    expect(integrityReason(r)).toMatch(/8\.0 fps/)
  })

  it('detects duplicated samples when the loop outruns the sensor',()=>{
    // 30 fps capture read at 60 Hz: every other interval is 0 ms
    const base=timestamps(30,10),jittered:number[]=[]
    for(const t of base){jittered.push(t,t)}
    const r=captureIntegrity({times:jittered.sort((a,b)=>a-b)})
    expect(r.duplicateIntervalFraction).toBeCloseTo(0.5,2)
    expect(r.hasDuplicateSamples).toBe(true)
    expect(r.regular).toBe(false)
    expect(integrityReason(r)).toMatch(/repeated the same camera frame/)
  })

  it('uses camera frame ids to detect duplicates that timestamps cannot',()=>{
    // timestamps look fine, but the same sensor frame was sampled twice
    const times=timestamps(30,2)
    const frameIds=times.map((_,i)=>Math.floor(i/2))
    const r=captureIntegrity({times,frameIds})
    expect(r.duplicateFrameFraction).toBeCloseTo(0.5,1)
    expect(r.hasDuplicateSamples).toBe(true)
  })

  it('detects a dropped-frame gap and reports its size',()=>{
    const times=timestamps(30,10).filter(t=>t<4||t>4.6)
    const r=captureIntegrity({times})
    expect(r.maxGapS).toBeGreaterThan(0.5)
    expect(r.hasLargeGap).toBe(true)
    expect(r.droppedIntervalFraction).toBeGreaterThan(0)
    expect(r.regular).toBe(false)
    expect(integrityReason(r)).toMatch(/Frame gap of/)
  })

  it('treats a short stall as irregular timing rather than a hard gap',()=>{
    const times:number[]=[]
    for(let i=0;i<300;i++)times.push(i/30+(i>=150?0.12:0))
    const r=captureIntegrity({times})
    expect(r.hasLargeGap).toBe(false)
    expect(r.maxGapS).toBeLessThan(0.25)
    expect(r.hasIrregularTiming).toBe(true)
    expect(integrityReason(r)).toMatch(/Irregular frame timing/)
  })

  it('discards a clock that goes backwards instead of smoothing it',()=>{
    const r=captureIntegrity({times:[0,0.033,0.066,0.01,0.1,0.133]})
    expect(r.nSamples).toBe(5) // the backwards sample is dropped
    expect(r.medianFsHz).toBeCloseTo(30,0)
  })

  it('reports nothing usable for a single sample',()=>{
    const r=captureIntegrity({times:[1.5]})
    expect(r.nSamples).toBe(1)
    expect(r.medianFsHz).toBeNull()
    expect(r.regular).toBe(false)
    expect(integrityReason(r)).toMatch(/Not enough frames/)
  })

  it('ignores non-finite timestamps',()=>{
    const r=captureIntegrity({times:[0,1/30,NaN,3/30,4/30]})
    expect(r.nSamples).toBe(4)
  })
})

describe('median helper',()=>{
  it('handles odd, even and empty input',()=>{
    expect(median([3,1,2])).toBe(2)
    expect(median([4,1,3,2])).toBe(2.5)
    expect(Number.isNaN(median([]))).toBe(true)
  })
})

describe('camera recovery backoff',()=>{
  it('grows from 1 s and stops after the attempt budget',()=>{
    expect(recoveryDelayMs(0)).toBe(1000)
    expect(recoveryDelayMs(1)).toBe(2000)
    expect(recoveryDelayMs(2)).toBe(4000)
    expect(recoveryDelayMs(4)).toBeNull()
    expect(recoveryDelayMs(0,0)).toBeNull()
  })
  it('caps the delay at 30 s',()=>{
    expect(recoveryDelayMs(10,20)).toBe(30000)
  })
})

describe('a timing defect reaches the analysis verdict',()=>{
  it('a clean synthetic window stays available',()=>{
    const result=analyzeSamples(pulseSamples())
    expect(result.scores?.acquisition?.regular).toBe(true)
    expect(result.concepts?.temporal_acquisition).toBe('pass')
  })

  it('a window with 50% duplicated samples is not reported as valid',()=>{
    const clean=pulseSamples()
    const duplicated:TraceSample[]=[]
    for(const s of clean){duplicated.push(s,{t:s.t,rois:s.rois})}
    const result=analyzeSamples(duplicated)
    expect(result.scores?.acquisition?.hasDuplicateSamples).toBe(true)
    expect(result.concepts?.temporal_acquisition).toBe('fail')
    expect(result.bpm).toBeNull()
    expect(result.reason).toMatch(/repeated the same camera frame|dropped frames|Irregular/)
  })

  it('a window with a large gap is not reported as valid',()=>{
    const times=timestamps(30,20).filter(t=>t<8||t>9.2)
    const samples=times.map(t=>({t,rois:{forehead:[120+0.45*Math.sin(2*Math.PI*1.2*t),100,80] as [number,number,number],left_cheek:[118+0.45*Math.sin(2*Math.PI*1.2*t),98,79] as [number,number,number],right_cheek:[122+0.45*Math.sin(2*Math.PI*1.2*t),102,81] as [number,number,number]}}))
    const result=analyzeSamples(samples)
    expect(result.concepts?.temporal_acquisition).toBe('fail')
    expect(result.bpm).toBeNull()
  })

  it('never reports a timing defect as available, whatever the waveform looks like',()=>{
    // perfectly periodic signal, but sampled at a rate below the analysable floor
    const samples=pulseSamples(8,20)
    const result=analyzeSamples(samples)
    expect(result.status).not.toBe('valid')
    expect(result.bpm).toBeNull()
  })
})
