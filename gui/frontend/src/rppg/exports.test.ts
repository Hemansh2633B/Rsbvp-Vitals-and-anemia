import {describe,it,expect} from 'vitest'
import {buildTraceCsv,buildTraceMetadata,buildWindowRecord,buildWindowsExport,TRACE_SCHEMA,WINDOWS_SCHEMA} from './exports'
import {SOFTWARE_VERSION} from './provenance'

const sample = (t:number, forehead:[number,number,number]|null) => ({t, rois:{forehead, left_cheek:null, right_cheek:null as [number,number,number]|null}})
const metaArgs = () => ({
  createdUtc:'2026-11-24T00:00:00.000Z', sessionId:'sess-test123', sampleCount:2, earlierSamplesDropped:0,
  traceStartTs:0, traceEndTs:0.05, acquisitionDurationS:10, cameraFps:30, sampleRateMedianHz:20,
  droppedIntervalFraction:0, analysisStatus:'low_signal_quality', analysisReason:'test reason',
  estimatesBpm:{forehead_green:70, forehead_pos:null}, validConsensusBpm:null,
  qualityConcepts:{availability:'fail'}, roiCoverage:{forehead:1,left_cheek:0,right_cheek:0}, roiCoverageOverall:0.4,
  userAgent:'vitest',
})

describe('rsbvp.rgb-trace.v1 export builder',()=>{
 it('emits the documented header and empty cells (never zero) for missing ROIs',()=>{
   const csv = buildTraceCsv([sample(0,[100,120,90]), sample(0.05,null)])
   const lines = csv.split('\n')
   expect(lines[0]).toBe('timestamp_s,forehead_r,forehead_g,forehead_b,left_cheek_r,left_cheek_g,left_cheek_b,right_cheek_r,right_cheek_g,right_cheek_b')
   expect(lines[1]).toBe(['0','100','120','90','','','','','',''].join(','))
   expect(lines[2]).toBe(['0.05','','','','','','','','',''].join(','))  // absent ROI => empty cell, never zero
 })
 it('metadata carries full provenance and honesty fields',()=>{
   const m = buildTraceMetadata(metaArgs())
   expect(m.schema).toBe(TRACE_SCHEMA)
   expect(m.software.name).toBe('RSBVP')
   expect(m.software.version).toBe(SOFTWARE_VERSION)
   expect(m.software.commit).toBeTruthy()
   expect(m.capture_session_id).toBe('sess-test123')
   expect(m.frame_images_included).toBe(false)
   expect(m.frames_uploaded).toBe(false)
   expect(m.estimates_bpm.forehead_pos).toBeNull()     // unavailable stays null
   expect(m.valid_consensus_bpm).toBeNull()            // never a fallback number
   expect(m.passband_hz).toEqual([0.7,3.5])
   expect(m.analysis_config.backend).toBe('rsbvp-browser-liveDsp')
 })
})
describe('rsbvp.window-analysis.v1 export builder',()=>{
 const win = {start_s:0, end_s:10, n_samples:200}
 const scores = {fsHz:20, durationS:10, maxGapS:0.05, peakFraction:0.3, snrDb:5, separationRatio:2, roiCoverage:{forehead:1}, roiCoverageOverall:1}
 const rec = (over:Partial<Parameters<typeof buildWindowRecord>[0]>={}) => buildWindowRecord({windowIndex:4, analyzedUtc:'2026-11-24T00:00:01.000Z', pendingWindow:win, fs:20, consensusBpm:null, estimates:{forehead_green:72}, qualityScore:0.3, consistencyBpm:3, availabilityStatus:'low_signal_quality', rejectionReason:'estimator disagreement exceeds 12 BPM', scores, concepts:{algorithm_agreement:'fail'}, selectedAlgorithm:'chrom', ...over})
 it('window records trace to software, backend, config and window bounds',()=>{
   const r = rec()
   expect(r.window_index).toBe(4)
   expect(r.software.version).toBe(SOFTWARE_VERSION)
   expect(r.backend).toBe('rsbvp-browser-liveDsp')
   expect(r.analysis_config.min_roi_coverage).toBe(0.5)
   expect(r.window_start_s).toBe(0); expect(r.window_end_s).toBe(10); expect(r.n_samples).toBe(200)
   expect(r.quality_concepts).toEqual({algorithm_agreement:'fail'})
   expect(r.roi_coverage_overall).toBe(1)
 })
 it('rejection_reason is null exactly when status is valid',()=>{
   expect(rec({availabilityStatus:'valid', rejectionReason:null, consensusBpm:72}).rejection_reason).toBeNull()
   expect(rec().rejection_reason).toBeTruthy()
 })
 it('missing window bounds remain null, never fabricated',()=>{
   const r = rec({pendingWindow:null})
   expect(r.window_start_s).toBeNull(); expect(r.window_end_s).toBeNull(); expect(r.n_samples).toBeNull()
 })
 it('windows export wrapper carries schema, session and provenance',()=>{
   const w = buildWindowsExport([rec() as unknown as Record<string,unknown>], 2, '2026-11-24T00:00:02.000Z', 'sess-test123')
   expect(w.schema).toBe(WINDOWS_SCHEMA)
   expect(w.capture_session_id).toBe('sess-test123')
   expect(w.software.version).toBe(SOFTWARE_VERSION)
   expect(w.dropped_windows_due_to_buffer_limit).toBe(2)
   expect(w.frames_images_included).toBe(false)
   expect(w.window_count).toBe(1)
 })
})
