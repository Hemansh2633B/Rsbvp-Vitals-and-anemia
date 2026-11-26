import {describe,it,expect} from 'vitest'
import {SessionCollector,DEFAULT_CONFIG,CONSENSUS,classifyReading,summarize,summarizeSession,countIndependentWindows,buildSessionReadingsCsv,buildSessionAggregateExport,SESSION_SCHEMA} from './sessionAggregate'
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
   for(let i=0;i<6;i++) c.add(base({value:72, sampling:{fsHz:30,nSamples:300,windowStartS:100,windowEndS:110}}), NOW+i*1000)
   const a = summarize(c.all(),'heart_rate')
   expect(a.nAccepted).toBe(6)
   expect(a.nIndependentAccepted).toBe(1)
   expect(a.verdict).toBe('insufficient')
   expect(a.reason).toContain('independent')
 })
 it('marks a session complete once the target is reached, and not before',()=>{
   const short = summarizeSession(collect([72,72,72,72]).all())
   expect(short.completion).toBe('collecting')
   const long = summarizeSession(collect(Array.from({length:DEFAULT_CONFIG.targetAcceptedReadings},()=>72)).all())
   expect(long.completion).toBe('complete')
 })
 it('counts accepted readings below the average threshold instead of denying they passed',()=>{
   // Regression: 2 accepted readings used to report "Waiting for readings that
   // pass the quality checks", which was untrue - they had passed.
   const s = summarizeSession(collect([72,73]).all())
   expect(s.completion).toBe('collecting')
   expect(s.completionReason).toBe('2 of 8 accepted readings collected')
 })
 it('is honest when every reading was rejected',()=>{
   const c = new SessionCollector()
   for(let i=0;i<3;i++){ const r = base({value:null,qualityVerdict:'roi_lost',rejectionReason:'All skin ROIs are lost'}); c.add(r,r.analyzedAtMs) }
   expect(summarizeSession(c.all()).completionReason).toContain('No readings accepted yet (3 rejected')
 })
 it('starts from an empty reported state before any reading exists',()=>{
   const s = summarizeSession([])
   expect(s.completion).toBe('idle'); expect(s.hasResult).toBe(false)
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
