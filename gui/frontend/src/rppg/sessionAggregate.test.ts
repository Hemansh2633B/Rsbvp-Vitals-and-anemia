import {describe,it,expect} from 'vitest'
import {SessionCollector,DEFAULT_CONFIG,CONSENSUS,DUPLICATE_WINDOW,classifyReading,summarize,summarizeSession,countIndependentWindows,buildSessionReadingsCsv,buildSessionAggregateExport,SESSION_SCHEMA} from './sessionAggregate'
import type {ReadingInput} from './sessionAggregate'

const NOW = 1_767_000_000_000
// Seconds since capture began, one reading per 10 s window, so the default
// series really is non-overlapping. Overlap gets its own tests below rather
// than being smuggled into every case.
let elapsedS = 0
const base = (over: Partial<ReadingInput> = {}): ReadingInput => {
  const start = (elapsedS += 10)
  return {
    metric:'heart_rate', value:72, algorithm:CONSENSUS, roi:'all',
    qualityScore:0.6, qualityVerdict:'valid',
    sampling:{fsHz:30,nSamples:300,windowStartS:start,windowEndS:start+10},
    rejectionReason:null, analyzedAtMs:NOW+start*1000, sessionElapsedS:start, windowIndex:Math.round(start/10),
    ...over,
  }
}
// nowMs = the reading's own analysis time: a reading is always fresh when first
// recorded. Staleness is about a *later* consumer, and is tested on its own.
const collect = (values:Array<number|null>, over: Partial<ReadingInput> = {}) => {
  const c = new SessionCollector()
  for(const v of values){ const r = base({value:v, ...over}); c.add(r, r.analyzedAtMs) }
  return c
}

describe('acceptance rules',()=>{
 it('accepts a valid, finite, plausible reading',()=>{
   const reading = base()
   const r = classifyReading(reading, DEFAULT_CONFIG, reading.analyzedAtMs)
   expect(r).toEqual({accepted:true,reason:null})
 })
 it('rejects a reading that failed the existing quality verdict and keeps the reason',()=>{
   const reading = base({qualityVerdict:'low_signal_quality',rejectionReason:'spectral concentration below 20%'})
   const r = classifyReading(reading, DEFAULT_CONFIG, reading.analyzedAtMs)
   expect(r.accepted).toBe(false)
   expect(r.reason).toBe('spectral concentration below 20%')
 })
 it('rejects a missing estimate instead of filling in a zero',()=>{
   const r = base({value:null,qualityVerdict:'insufficient_frames',rejectionReason:'Insufficient frames or irregular sampling'})
   expect(classifyReading(r, DEFAULT_CONFIG, r.analyzedAtMs)).toEqual({accepted:false,reason:'Insufficient frames or irregular sampling'})
 })
 it('flags a valid verdict that carries no number as a contract violation',()=>{
   const r = base({value:null})
   expect(classifyReading(r, DEFAULT_CONFIG, r.analyzedAtMs).reason).toBe('valid_verdict_without_estimate')
 })
 it('rejects NaN and Infinity as missing, not as values',()=>{
   expect(classifyReading(base({value:Number.NaN}), DEFAULT_CONFIG, NOW).reason).toBe('valid_verdict_without_estimate')
   expect(classifyReading(base({value:Number.POSITIVE_INFINITY}), DEFAULT_CONFIG, NOW).reason).toBe('valid_verdict_without_estimate')
 })
 it('rejects a stale reading that describes a moment already past',()=>{
   const stale = base()
   const r = classifyReading(stale, DEFAULT_CONFIG, stale.analyzedAtMs + DEFAULT_CONFIG.staleAfterMs + 1)
   expect(r).toEqual({accepted:false,reason:'stale_reading'})
 })
 it('rejects an implausible value as a data error, naming the bounds',()=>{
   const low = base({value:3}), high = base({value:900})
   expect(classifyReading(low, DEFAULT_CONFIG, low.analyzedAtMs).reason).toContain('implausible_value')
   expect(classifyReading(high, DEFAULT_CONFIG, high.analyzedAtMs).reason).toContain('implausible_value')
 })
 it('rejects an unknown metric rather than guessing its unit',()=>{
   const r = base({metric:'spo2' as never})
   expect(classifyReading(r, DEFAULT_CONFIG, r.analyzedAtMs).reason).toContain('unsupported_metric')
 })
})

describe('arithmetic',()=>{
 it('computes the mean and median of accepted readings only',()=>{
   const c = collect([60,70,80,90,100])
   const a = summarize(c.all(),'heart_rate')
   expect(a.verdict).toBe('available')
   expect(a.mean).toBe(80)
   expect(a.median).toBe(80)
   expect(a.min).toBe(60); expect(a.max).toBe(100); expect(a.range).toBe(40)
   expect(a.sd).toBeCloseTo(15.8114,3)   // sample SD, not population SD
 })
 it('computes a median for an even count as the mean of the two middle values',()=>{
   const c = collect([60,70,80,90])
   expect(summarize(c.all(),'heart_rate').median).toBe(75)
 })
 it('leaves the median null, not zero, when there are no accepted readings',()=>{
   const c = collect([null,null])
   const a = summarize(c.all(),'heart_rate')
   expect(a.median).toBeNull(); expect(a.mean).toBeNull(); expect(a.verdict).toBe('insufficient')
 })
 it('counts rejected readings without letting them into the average',()=>{
   const c = new SessionCollector()
   c.add(base({value:70}),NOW); c.add(base({value:72}),NOW+1000)
   c.add(base({value:200,qualityVerdict:'low_signal_quality',rejectionReason:'low SNR'}),NOW+2000)
   c.add(base({value:74}),NOW+3000); c.add(base({value:76}),NOW+4000); c.add(base({value:78}),NOW+5000)
   const a = summarize(c.all(),'heart_rate',{config:{...DEFAULT_CONFIG,minAcceptedReadings:3}})
   expect(a.mean).toBe(74)
   expect(a.nAccepted).toBe(5); expect(a.nRejected).toBe(1); expect(a.nTotal).toBe(6)
   expect(a.acceptancePct).toBeCloseTo(83.333,2)
 })
 it('is outlier-sensitive in the mean but stable in the median',()=>{
   const c = collect([70,70,70,70,150])
   const a = summarize(c.all(),'heart_rate')
   expect(a.mean).toBe(86); expect(a.median).toBe(70)
 })
})

describe('insufficient data and completion',()=>{
 it('reports insufficient data rather than a number below the threshold',()=>{
   const c = collect([72,73,74])
   const a = summarize(c.all(),'heart_rate')
   expect(a.verdict).toBe('insufficient')
   expect(a.reason).toContain('at least 5')
   expect(a.mean).toBe(73)      // visible in details, never presented as the result
 })
 it('states insufficient independently of the count when windows all overlap',()=>{
   const c = new SessionCollector()
   for(let i=0;i<6;i++) c.add(base({value:72, sampling:{fsHz:30,nSamples:300,windowStartS:100+i,windowEndS:110+i}}), NOW+i*1000)
   const a = summarize(c.all(),'heart_rate')
   expect(a.nAccepted).toBe(6)
   expect(a.nIndependentAccepted).toBe(1)
   expect(a.verdict).toBe('insufficient')
   expect(a.reason).toContain('independent')
 })
 it('marks a session available once the aggregate is, and not merely when a count is reached',()=>{
   // Running with too few readings: provisional, not a final verdict.
   const short = summarizeSession(collect([72,72,72,72]).all(), { lifecycle:'running' })
   expect(short.completion).toBe('collecting')
   expect(short.resultAvailable).toBe(false)
   // Stopped with too few readings: a final state, and it never says "stop".
   const stopped = summarizeSession(collect([72,72,72,72]).all(), { lifecycle:'stopped' })
   expect(stopped.completion).toBe('insufficient')
   expect(stopped.completionReason).not.toMatch(/you can stop/i)
   const long = summarizeSession(collect([72,72,72,72,72]).all(), { lifecycle:'running' })
   expect(long.completion).toBe('available')
   expect(long.resultAvailable).toBe(true)
   const done = summarizeSession(collect([72,72,72,72,72]).all(), { lifecycle:'stopped' })
   expect(done.completion).toBe('completed')
 })
 it('counts accepted readings below the average threshold instead of denying they passed',()=>{
   // Regression: 2 accepted readings used to report "Waiting for readings that
   // pass the quality checks", which was untrue - they had passed.
   const s = summarizeSession(collect([72,73]).all(), { lifecycle:'running' })
   expect(s.completion).toBe('collecting')
   expect(s.completionReason).toBe('Collecting: 2 of 5 accepted readings')
 })
 it('reports the aggregate reason, never a reassuring count, when everything was rejected',()=>{
   const c = new SessionCollector()
   for(let i=0;i<3;i++){ const r = base({value:null,qualityVerdict:'roi_lost',rejectionReason:'All skin ROIs are lost'}); c.add(r,r.analyzedAtMs) }
   const running = summarizeSession(c.all(), { lifecycle:'running' })
   expect(running.completion).toBe('collecting')
   expect(running.nAcceptedTotal).toBe(0)
   expect(running.nRejectedTotal).toBe(3)
   const stopped = summarizeSession(c.all(), { lifecycle:'stopped' })
   expect(stopped.completion).toBe('insufficient')
   expect(stopped.completionReason).toMatch(/No accepted readings/)
 })
 it('starts from an initialising state before any reading exists',()=>{
   const s = summarizeSession([], { lifecycle:'running' })
   expect(s.completion).toBe('initialising'); expect(s.hasResult).toBe(false)
   expect(s.resultAvailable).toBe(false)
   expect(s.metrics.every(m=>m.verdict==='no_readings')).toBe(true)
 })
})

describe('metric and unit separation',()=>{
 it('never combines heart rate and respiratory rate',()=>{
   const c = new SessionCollector()
   for(let i=0;i<6;i++){
     c.add(base({metric:'heart_rate',value:72+ i}),NOW+i*1000)
     c.add(base({metric:'respiratory_rate',value:15+i}),NOW+i*1000)
   }
   const s = summarizeSession(c.all())
   const hr = s.metrics.find(m=>m.metric==='heart_rate')!
   const rr = s.metrics.find(m=>m.metric==='respiratory_rate')!
   expect(hr.unit).toBe('BPM'); expect(rr.unit).toBe('br/min')
   expect(hr.mean).toBe(74.5); expect(rr.mean).toBe(17.5)
 })
 it('applies resp-value plausibility bounds from the metric spec, not from heart rate',()=>{
   const c = new SessionCollector()
   c.add(base({metric:'respiratory_rate',value:72}),NOW)   // plausible HR, implausible breathing
   const rr = summarize(c.all(),'respiratory_rate')
   expect(rr.nAccepted).toBe(0); expect(rr.nRejected).toBe(1)
 })
 it('keeps each algorithm as its own series and never averages across them',()=>{
   const c = new SessionCollector()
   for(let i=0;i<6;i++){ c.add(base({value:70,algorithm:'green',roi:'forehead'}),NOW+i*1000); c.add(base({value:90,algorithm:'pos',roi:'forehead'}),NOW+i*1000) }
   const s = summarizeSession(c.all())
   const green = s.perAlgorithm.find(a=>a.algorithm==='green')!
   const pos = s.perAlgorithm.find(a=>a.algorithm==='pos')!
   expect(green.mean).toBe(70); expect(pos.mean).toBe(90)
   // The consensus series has no readings here, so no session result is invented.
   const consensus = s.metrics.find(m=>m.metric==='heart_rate')!
   expect(consensus.nTotal).toBe(0); expect(consensus.mean).toBeNull()
   expect(s.hasResult).toBe(false)
 })
})

describe('independence accounting',()=>{
 it('counts a sliding-window series as far fewer independent observations',()=>{
   const c = new SessionCollector()
   // 10 s window re-analysed every 1 s for 60 s: 51 readings, 6 independent.
   for(let k=0;k<=50;k++) c.add(base({value:72,sampling:{fsHz:30,nSamples:300,windowStartS:k,windowEndS:k+10}}),NOW+k*1000)
   const a = summarize(c.all(),'heart_rate')
   expect(a.nAccepted).toBe(51)
   expect(a.nIndependentAccepted).toBe(6)
   expect(a.overlapFactor).toBeCloseTo(8.5,1)
 })
 it('derives the standard error from independent windows only',()=>{
   const c = new SessionCollector()
   const values = [70,72,74,76,78,80]
   values.forEach((v,i)=>c.add(base({value:v,sampling:{fsHz:30,nSamples:300,windowStartS:i*10,windowEndS:i*10+10}}),NOW+i*1000))
   const a = summarize(c.all(),'heart_rate')
   expect(a.nIndependentAccepted).toBe(6)
   expect(a.standardError).toBeCloseTo((a.sd as number)/Math.sqrt(6),6)
 })
 it('leaves the standard error null when independence cannot be established',()=>{
   const c = new SessionCollector()
   for(let i=0;i<6;i++) c.add(base({value:72,sampling:{fsHz:null,nSamples:null,windowStartS:null,windowEndS:null}}),NOW+i*1000)
   const a = summarize(c.all(),'heart_rate')
   expect(a.nIndependentAccepted).toBeNull()
   expect(a.standardError).toBeNull()
 })
 it('treats touching windows as independent and overlapping ones as not',()=>{
   const c = new SessionCollector()
   c.add(base({value:70,sampling:{fsHz:30,nSamples:300,windowStartS:0,windowEndS:10}}),NOW)
   c.add(base({value:71,sampling:{fsHz:30,nSamples:300,windowStartS:10,windowEndS:20}}),NOW+1000)
   c.add(base({value:72,sampling:{fsHz:30,nSamples:300,windowStartS:15,windowEndS:25}}),NOW+2000)
   expect(countIndependentWindows(c.accepted())).toBe(2)
 })
})

describe('append-only history',()=>{
 it('never overwrites a reading when the aggregate changes',()=>{
   const c = collect([70,72])
   const before = c.all().map(r=>r.value)
   summarize(c.all(),'heart_rate')
   collect([1])
   expect(c.all().map(r=>r.value)).toEqual(before)
 })
 it('keeps rejected readings in history with their reason',()=>{
   const c = new SessionCollector()
   c.add(base({value:70}),NOW)
   c.add(base({value:null,qualityVerdict:'roi_lost',rejectionReason:'All skin ROIs are lost or unavailable'}),NOW+1000)
   const rejected = c.rejected()
   expect(rejected).toHaveLength(1)
   expect(rejected[0].finalRejectionReason).toBe('All skin ROIs are lost or unavailable')
   expect(rejected[0].value).toBeNull()
 })
 it('clears history and restarts ids on session reset',()=>{
   const c = collect([70,72,74])
   c.reset()
   expect(c.size).toBe(0); expect(c.all()).toEqual([])
   const next = c.add(base({value:70}),NOW)
   expect(next.id).toBe(1)
 })
})

describe('exports',()=>{
 it('writes one CSV row per reading, accepted and rejected, with empty cells for unknowns',()=>{
   const c = new SessionCollector()
   c.add(base({value:70}),NOW)
   c.add(base({value:null,qualityVerdict:'insufficient_frames',rejectionReason:'Insufficient frames',sampling:{fsHz:null,nSamples:null,windowStartS:null,windowEndS:null}}),NOW+1000)
   const lines = buildSessionReadingsCsv(c.all()).split('\n')
   expect(lines).toHaveLength(3)
   expect(lines[0].startsWith('reading_id,metric,unit,value,algorithm')).toBe(true)
   expect(lines[1]).toContain('heart_rate,BPM,70,consensus')
   expect(lines[2]).toContain('false')            // rejected flag
   expect(lines[2]).toContain('Insufficient frames')
 })
 it('serialises the aggregate with independence caveats attached',()=>{
   const c = collect([70,72,74,76,78])
   const summary = summarizeSession(c.all())
   const out = buildSessionAggregateExport({sessionId:'sess-1',createdUtc:'2026-11-26T00:00:00Z',readings:c.all(),summary,capture:{algorithms:['Green','POS','CHROM'],rois:['forehead'],passbandHz:[0.7,3.5],requiredSeconds:10,backend:'rsbvp-browser-liveDsp',cameraLabel:null,samplingRateHz:30}})
   expect(out.schema).toBe(SESSION_SCHEMA)
   const hr = out.metrics.find(m=>m.metric==='heart_rate')!
   expect(hr.mean).toBe(74)
   expect(hr.independent_windows).toBe(5)   // five 10 s windows, no overlap
   expect(out.statistics_notes.join(' ')).toContain('does not establish physiological accuracy')
   expect(out.frames_images_included).toBe(false)
   expect(out.aggregation_config.min_accepted_readings).toBe(5)
 })
})

// Sprint 14: the invariant that the previous implementation violated.
describe('session completion correctness',()=>{
 const overlapping = (n:number) => {
   const c = new SessionCollector()
   // Genuinely overlapping windows: sliding 1 s apart over a 10 s window, so each
   // is a distinct observation that still overlaps its neighbours. (Previously
   // this reused one identical window n times, which Sprint 16 correctly treats as
   // the same observation re-delivered rather than as overlap.)
   for(let i=0;i<n;i++){
     const start = 100 + i
     const r = base({value:72,sampling:{fsHz:30,nSamples:300,windowStartS:start,windowEndS:start+10}})
     c.add(r,r.analyzedAtMs)
   }
   return c
 }
 it('never invites a stop while the aggregate is still insufficient',()=>{
   // Regression: 8 accepted readings over ONE window reached the target count and
   // produced "you can stop the camera" while the aggregate was insufficient
   // (1 independent window < 2 required).
   const s = summarizeSession(overlapping(8).all(), { lifecycle:'running' })
   expect(s.nAcceptedTotal).toBe(8)
   expect(s.config.targetAcceptedReadings).toBe(8)   // the old trigger fired here
   expect(s.resultAvailable).toBe(false)
   expect(s.completion).toBe('collecting')
   expect(s.completionReason).not.toMatch(/you can stop/i)
   expect(s.completionReason).toMatch(/overlap/i)
 })
 it('names overlap, not a low count, when the count is already sufficient',()=>{
   const s = summarizeSession(overlapping(8).all(), { lifecycle:'running' })
   expect(s.completionReason).toContain('1 independent window')
 })
 it('uses all six distinct states for their intended situations',()=>{
   const empty = summarizeSession([], { lifecycle:'running' })
   expect(empty.completion).toBe('initialising')
   const first = summarizeSession(overlapping(1).all(), { lifecycle:'running' })
   expect(first.completion).toBe('collecting')
   const stoppedShort = summarizeSession(overlapping(2).all(), { lifecycle:'stopped' })
   expect(stoppedShort.completion).toBe('insufficient')
   const running = summarizeSession(collect([70,72,74,76,78]).all(), { lifecycle:'running' })
   expect(running.completion).toBe('available')
   const interrupted = summarizeSession(collect([70,72]).all(), { lifecycle:'interrupted' })
   expect(interrupted.completion).toBe('interrupted')
   const done = summarizeSession(collect([70,72,74,76,78]).all(), { lifecycle:'stopped' })
   expect(done.completion).toBe('completed')
 })
 it('reports an interruption as such rather than as insufficient progress',()=>{
   const s = summarizeSession(collect([70,72]).all(), { lifecycle:'interrupted' })
   expect(s.completionReason).toMatch(/interrupted/i)
   expect(s.completionReason).not.toMatch(/you can stop/i)
 })
 it('only statuses with an available aggregate ever say the camera can stop',()=>{
   const cases: Array<['running'|'stopped'|'interrupted', number[]]> = [
     ['running',[]], ['running',[70]], ['running',[70,72]], ['running',[70,72,74]],
     ['running',[70,72,74,76]], ['running',[70,72,74,76,78]],
     ['stopped',[70,72]], ['stopped',[70,72,74,76,78]],
     ['interrupted',[70,72]], ['interrupted',[70,72,74,76,78]],
   ]
   for(const [lifecycle, values] of cases){
     const s = summarizeSession(collect(values).all(), { lifecycle })
     if(/you can stop/i.test(s.completionReason)) expect(s.resultAvailable).toBe(true)
     if(s.resultAvailable) expect(s.metrics.find(m=>m.metric==='heart_rate')!.verdict).toBe('available')
   }
 })
})

describe('analysis density',()=>{
 it('is near 1 for an evenly analysed session',()=>{
   const c = new SessionCollector()
   for(let k=0;k<30;k++){
     const r = base({value:72,sampling:{fsHz:30,nSamples:300,windowStartS:100+k*0.5,windowEndS:110+k*0.5}, sessionElapsedS:100+k*0.5})
     c.add(r,r.analyzedAtMs)
   }
   const ratio = summarizeSession(c.all()).densityRatio
   expect(ratio).not.toBeNull()
   expect(ratio as number).toBeLessThan(1.5)
   expect(summarizeSession(c.all()).unevenDensity).toBe(false)
 })
 it('flags a session where one stretch was analysed far more often',()=>{
   const c = new SessionCollector()
   // Dense 0-30 s, then sparse 30-90 s: the condition under which an equal-weight
   // mean over-weights the dense part (see research/session/aggregation_analysis.py).
   for(let k=0;k<60;k++){
     const r = base({value:70,sampling:{fsHz:30,nSamples:300,windowStartS:k*0.5,windowEndS:k*0.5+10}, sessionElapsedS:k*0.5})
     c.add(r,r.analyzedAtMs)
   }
   for(let k=0;k<15;k++){
     const t = 30+k*4
     const r = base({value:80,sampling:{fsHz:30,nSamples:300,windowStartS:t,windowEndS:t+10}, sessionElapsedS:t})
     c.add(r,r.analyzedAtMs)
   }
   const s = summarizeSession(c.all())
   expect(s.densityRatio as number).toBeGreaterThan(DEFAULT_CONFIG.densityRatioWarning)
   expect(s.unevenDensity).toBe(true)
 })
 it('returns null rather than a fake 1 when there is too little span to judge',()=>{
   expect(summarizeSession(collect([70]).all()).densityRatio).toBeNull()
 })
 it('does not change the mean: density is reported, never silently corrected',()=>{
   // The primary estimator stays the all-window mean. This test exists so a future
   // change that "fixes" density by silently switching estimator fails loudly.
   const c = collect([70,70,80,80,80])
   const s = summarizeSession(c.all())
   const hr = s.metrics.find(m=>m.metric==='heart_rate')!
   expect(hr.mean).toBe(76)   // arithmetic mean of all accepted readings
   expect(hr.verdict).toBe('available')
 })
})

describe('aggregate reason hygiene', () => {
  it('clears the placeholder reason once a metric is available', () => {
    // The experimental block renders `reason` verbatim next to the value, so an
    // available aggregate must not carry "No readings recorded for this metric".
    const collector = collect([70, 72, 74, 76, 78])
    const summary = summarizeSession(collector.all(), { lifecycle: 'running' })
    const hr = summary.metrics.find(m => m.metric === 'heart_rate')!
    expect(hr.verdict).toBe('available')
    expect(hr.reason).toBe('')
  })

  it('keeps a placeholder reason for a metric with no readings', () => {
    const collector = collect([72])
    const summary = summarizeSession(collector.all(), { lifecycle: 'running' })
    const rr = summary.metrics.find(m => m.metric === 'respiratory_rate')!
    expect(rr.verdict).toBe('no_readings')
    expect(rr.reason).toMatch(/No readings recorded/)
  })
})

// ---------------------------------------------------------------------------
// Sprint 16: duplicate windows, outliers, variability, and session hygiene.
// These are the behaviours the session experience depends on; each has a
// corresponding Python test and, where it is a rule, a parity fixture case.
// ---------------------------------------------------------------------------
describe('duplicate windows are not new observations',()=>{
 it('counts a re-delivered window once and records the rest as duplicates',()=>{
   const c = new SessionCollector()
   for(let i=0;i<3;i++){
     const r = base({value:72,sampling:{fsHz:30,nSamples:300,windowStartS:0,windowEndS:10}})
     c.add(r,r.analyzedAtMs)
   }
   // The history stays complete: nothing is thrown away, it is refused.
   expect(c.all()).toHaveLength(3)
   expect(c.accepted()).toHaveLength(1)
   expect(c.rejected().map(r=>r.finalRejectionReason)).toEqual([DUPLICATE_WINDOW,DUPLICATE_WINDOW])
   const a = summarize(c.all(),'heart_rate')
   expect(a.nAccepted).toBe(1)
   expect(a.nDuplicateWindows).toBe(2)
   // rejected + accepted + duplicates accounts for every reading.
   expect(a.nAccepted + a.nRejected + a.nDuplicateWindows).toBe(a.nTotal)
 })

 it('does not let a duplicate move the mean',()=>{
   const c = new SessionCollector()
   // Bounds pinned explicitly: `base()` advances the clock, so relying on it would
   // produce five DIFFERENT windows and the test would prove nothing.
   for(let i=0;i<5;i++){
     const r = base({value:[70,72,74,76,78][i],sampling:{fsHz:30,nSamples:300,windowStartS:10*i,windowEndS:10*i+10}})
     c.add(r,r.analyzedAtMs)
   }
   const clean = summarize(c.all(),'heart_rate')
   // Re-submit the first window four more times: a naive count would weight it 5x.
   for(let i=0;i<4;i++){
     const r = base({value:70,sampling:{fsHz:30,nSamples:300,windowStartS:0,windowEndS:10}})
     c.add(r,r.analyzedAtMs)
   }
   const after = summarize(c.all(),'heart_rate')
   expect(after.mean).toBe(clean.mean)
   expect(after.nDuplicateWindows).toBe(4)
 })

 it('never treats unknown window bounds as duplicates',()=>{
   // "I do not know the window" is not evidence that it repeats one.
   const c = new SessionCollector()
   for(let i=0;i<3;i++){
     const r = base({value:72,sampling:{fsHz:30,nSamples:300,windowStartS:null,windowEndS:null}})
     c.add(r,r.analyzedAtMs)
   }
   expect(c.accepted()).toHaveLength(3)
   expect(summarize(c.all(),'heart_rate').nDuplicateWindows).toBe(0)
 })

 it('distinguishes metrics and algorithms when matching windows',()=>{
   const c = new SessionCollector()
   const s = {fsHz:30,nSamples:300,windowStartS:0,windowEndS:10}
   const hr = base({value:72,sampling:s}); c.add(hr,hr.analyzedAtMs)
   const rr = base({metric:'respiratory_rate',value:14,sampling:s}); c.add(rr,rr.analyzedAtMs)
   const green = base({value:71,algorithm:'green',sampling:s}); c.add(green,green.analyzedAtMs)
   // Same bounds, three genuinely different series: all three are new observations.
   expect(c.accepted()).toHaveLength(3)
 })

 it('can be switched off for diagnostics without changing anything else',()=>{
   const c = new SessionCollector({suppressDuplicateWindows:false})
   for(let i=0;i<3;i++){
     const r = base({value:72,sampling:{fsHz:30,nSamples:300,windowStartS:0,windowEndS:10}})
     c.add(r,r.analyzedAtMs)
   }
   expect(c.accepted()).toHaveLength(3)
 })
})

describe('outliers are disclosed, never removed',()=>{
 it('flags a wild reading and still includes it in every statistic',()=>{
   const c = collect([70,71,72,71,70,155])
   const a = summarize(c.all(),'heart_rate')
   expect(a.nAccepted).toBe(6)               // nothing was dropped
   expect(a.nFlaggedOutliers).toBe(1)
   expect(a.flaggedOutlierIds).toHaveLength(1)
   // The mean is the all-in mean: if 155 had been trimmed it would be ~70.8.
   expect(a.mean).toBeGreaterThan(80)
   expect(a.median).toBeLessThan(80)         // the robust statistic shrugs it off
   expect(a.variable).toBe(true)
 })

 it('does not let an outlier hide itself by inflating the spread',()=>{
   // The naive test compares a reading with an SD that includes it: with
   // [70,71,72,71,70,155] that SD is 34, so a 2.5 SD limit is 86 and 155 passes.
   // The flag must therefore use a leave-one-out baseline.
   const c = collect([70,71,72,71,70,155])
   expect(summarize(c.all(),'heart_rate').nFlaggedOutliers).toBe(1)
 })

 it('flags nothing in a steady session',()=>{
   // Six windows agreeing to within 1.4 BPM are not an outlier problem. A purely
   // statistical test would flag them; the materiality floor prevents that.
   const c = collect([72,73,72,71,73,72])
   const a = summarize(c.all(),'heart_rate')
   expect(a.nFlaggedOutliers).toBe(0)
   expect(a.variable).toBe(false)
 })

 it('reports the spread that drives the variability warning',()=>{
   const steady = summarize(collect([72,73,72,71]).all(),'heart_rate')
   expect(steady.variable).toBe(false)
   const varies = summarize(collect([55,95,60,100,70,85]).all(),'heart_rate')
   expect(varies.variable).toBe(true)
 })
})

describe('empty and insufficient sessions',()=>{
 it('reports no readings without inventing a number or a zero',()=>{
   const a = summarize([],'heart_rate')
   expect(a.verdict).toBe('no_readings')
   expect(a.mean).toBeNull()
   expect(a.median).toBeNull()
   expect(a.nDuplicateWindows).toBe(0)
   expect(a.nFlaggedOutliers).toBe(0)
 })

 it('explains a session that is entirely duplicates',()=>{
   const c = new SessionCollector()
   for(let i=0;i<4;i++){
     const r = base({value:72,sampling:{fsHz:30,nSamples:300,windowStartS:0,windowEndS:10}})
     c.add(r,r.analyzedAtMs)
   }
   const a = summarize(c.all(),'heart_rate')
   // One accepted, three duplicates: insufficient for a session average, and the
   // reason names duplicates rather than blaming the signal.
   expect(a.verdict).toBe('insufficient')
   expect(a.reason).toMatch(/at least 5/)
   expect(a.nDuplicateWindows).toBe(3)
 })
})

describe('session summary carries the new disclosure fields',()=>{
 it('exposes duplicate and outlier counts at session level',()=>{
   const c = collect([70,71,72,71,70,155])
   const s = summarizeSession(c.all(),{lifecycle:'stopped'})
   expect(s.nDuplicateWindows).toBe(0)
   expect(s.nFlaggedOutliers).toBe(1)
   expect(s.variable).toBe(true)
 })

 it('keeps duplicates out of the rejected count',()=>{
   // "The signal was bad" and "this window was already counted" are different
   // messages; adding them together misreports the session.
   const c = new SessionCollector()
   for(let i=0;i<5;i++){
     const r = base({value:[70,72,74,76,78][i],sampling:{fsHz:30,nSamples:300,windowStartS:10*i,windowEndS:10*i+10}})
     c.add(r,r.analyzedAtMs)
   }
   for(let i=0;i<2;i++){
     const r = base({value:70,sampling:{fsHz:30,nSamples:300,windowStartS:0,windowEndS:10}})
     c.add(r,r.analyzedAtMs)
   }
   const s = summarizeSession(c.all(),{lifecycle:'stopped'})
   expect(s.nDuplicateWindows).toBe(2)
   expect(s.nRejectedTotal).toBe(0)
   expect(s.nAcceptedTotal).toBe(5)
 })
})

describe('session reset and interruption',()=>{
 it('leaves no reading, id or count behind after reset',()=>{
   const c = collect([70,72,74,76,78])
   expect(summarizeSession(c.all(),{lifecycle:'running'}).resultAvailable).toBe(true)
   c.reset()
   expect(c.all()).toHaveLength(0)
   const after = summarizeSession(c.all(),{lifecycle:'running'})
   expect(after.resultAvailable).toBe(false)
   expect(after.nAcceptedTotal).toBe(0)
   expect(after.nDuplicateWindows).toBe(0)
   expect(after.completion).toBe('initialising')
 })

 it('restarts ids so an old id can never match a new reading',()=>{
   const first = collect([70]); const oldId = first.all()[0].id
   first.reset()
   const second = collect([80]); const newId = second.all()[0].id
   expect(newId).toBe(oldId)                 // ids restart...
   expect(second.all()).toHaveLength(1)      // ...but nothing else survived
   expect(second.all()[0].value).toBe(80)
 })

 it('marks an interruption as interrupted, not as slow progress',()=>{
   const s = summarizeSession(collect([70,72]).all(),{lifecycle:'interrupted'})
   expect(s.completion).toBe('interrupted')
   expect(s.resultAvailable).toBe(false)
   expect(s.completionReason).not.toMatch(/you can stop/i)
 })

 it('does not record a window after the session is finished',()=>{
   // BrowserPulse refuses post-finish windows; the aggregate must also never show
   // a "completed" session that keeps growing.
   const c = collect([70,72,74,76,78])
   const frozen = summarizeSession(c.all(),{lifecycle:'stopped'})
   expect(frozen.completion).toBe('completed')
   expect(frozen.nAcceptedTotal).toBe(5)
 })
})
