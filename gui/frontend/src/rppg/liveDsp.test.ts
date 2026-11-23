import {describe,it,expect} from 'vitest'
import {analyzeSamples,resampleTrace,chromProjection,posProjection,type TraceSample} from './liveDsp'
function fixture(drop=false):TraceSample[]{const samples:TraceSample[]=[];for(let i=0;i<480;i++){const t=i/30;if(drop&&t>5&&t<6)continue;const p=Math.sin(2*Math.PI*1.2*t)*.02;const rois={} as TraceSample['rois'];for(const [name,k] of [['forehead',1],['left_cheek',.95],['right_cheek',1.05]] as const)rois[name]=[100*(1+p*k),120*(1-p*k),90*(1+p*k*.5)];samples.push({t,rois})}return samples}
describe('browser DSP safeguards',()=>{
 it('estimates known synthetic frequency in test-only traces',()=>{const a=analyzeSamples(fixture());expect(a.status).toBe('valid');expect(a.bpm).toBeGreaterThan(60);expect(a.bpm).toBeLessThan(84)})
 it('does not interpolate across a long timestamp gap',()=>{expect(resampleTrace(fixture(true),'forehead','g')).toBeNull()})
 it('excludes a dropped ROI without treating missing RGB as zero',()=>{const s=fixture();s.forEach(x=>x.rois.left_cheek=null);const a=analyzeSamples(s);expect(a.estimates.left_cheek_green).toBeUndefined();expect(a.estimates.forehead_green).toBeDefined()})
 it('returns unavailable during warmup',()=>{expect(analyzeSamples(fixture().slice(0,100)).bpm).toBeNull()})
})

// Sprint 8 regression coverage: separated quality concepts, ROI-union coverage
// gate, and explicit-unavailable estimator inputs. All traces are synthetic
// test fixtures; passing these tests is software verification, not validation.
describe('Sprint 8 quality concepts and coverage gate',()=>{
 it('reports six separated concepts and all-pass on a clean synthetic window',()=>{
   const a=analyzeSamples(fixture())
   expect(a.concepts).toBeDefined()
   expect(Object.keys(a.concepts!).sort()).toEqual(['algorithm_agreement','availability','face_tracking','pulse_signal','roi_extraction','temporal_acquisition'])
   expect(a.concepts!.availability).toBe('pass')
   expect(a.concepts!.pulse_signal).toBe('pass')
   expect(a.concepts!.roi_extraction).toBe('pass')
 })
 it('fails availability when union ROI coverage falls below 50%',()=>{
   const s=fixture();
   // Keep usable forehead on only 40% of samples; cheeks always lost.
   s.forEach((x,i)=>{ if(i%5>=2){ x.rois.forehead=null } x.rois.left_cheek=null; x.rois.right_cheek=null })
   const a=analyzeSamples(s)
   expect(a.concepts?.roi_extraction).toBe('fail')
   expect(a.status).not.toBe('valid')
   expect(a.bpm).toBeNull()
 })
 it('marks temporal_acquisition fail on timestamp gaps beyond 0.25 s',()=>{
   const a=analyzeSamples(fixture(true))
   expect(a.status).toBe('irregular_timestamps')
   expect(a.concepts?.temporal_acquisition).toBe('fail')
   expect(a.bpm).toBeNull()
 })
 it('yields explicit unavailable on near-flat (dc-only) RGB traces',()=>{
   const flat:TraceSample[]=[];
   for(let i=0;i<480;i++){const t=i/30;flat.push({t,rois:{forehead:[120,120,120],left_cheek:[120,120,120],right_cheek:[120,120,120]}})}
   const a=analyzeSamples(flat)
   expect(a.bpm).toBeNull()
   expect(a.concepts?.availability).toBe('fail')
 })
 it('yields explicit unavailable on zero (fully dark) RGB means',()=>{
   const dark:TraceSample[]=[];
   for(let i=0;i<480;i++){const t=i/30;dark.push({t,rois:{forehead:[0,0,0],left_cheek:[0,0,0],right_cheek:[0,0,0]}})}
   const a=analyzeSamples(dark)
   expect(a.bpm).toBeNull()
   expect(Object.keys(a.estimates).length).toBeGreaterThan(0) // estimators reported, all unavailable
   for(const v of Object.values(a.estimates)) expect(v).toBeNull()
 })
})
describe('Sprint 8 estimator input contracts',()=>{
 it('chromProjection rejects non-positive RGB means',()=>{
   expect(()=>chromProjection(Array.from({length:16},()=>[100,0,90]),30)).toThrow(/positive/)
 })
 it('chromProjection rejects fewer than 8 samples',()=>{
   expect(()=>chromProjection([[100,110,90],[101,111,91]],30)).toThrow(/at least 8/)
 })
 it('posProjection rejects non-finite means',()=>{
   expect(()=>posProjection(Array.from({length:16},()=>[Number.NaN,110,90]))).toThrow(/finite/)
 })
})
