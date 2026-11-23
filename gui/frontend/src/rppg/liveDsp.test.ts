import {describe,it,expect} from 'vitest'
import {analyzeSamples,resampleTrace,type TraceSample} from './liveDsp'
function fixture(drop=false):TraceSample[]{const samples:TraceSample[]=[];for(let i=0;i<480;i++){const t=i/30;if(drop&&t>5&&t<6)continue;const p=Math.sin(2*Math.PI*1.2*t)*.02;const rois={} as TraceSample['rois'];for(const [name,k] of [['forehead',1],['left_cheek',.95],['right_cheek',1.05]] as const)rois[name]=[100*(1+p*k),120*(1-p*k),90*(1+p*k*.5)];samples.push({t,rois})}return samples}
describe('browser DSP safeguards',()=>{
 it('estimates known synthetic frequency in test-only traces',()=>{const a=analyzeSamples(fixture());expect(a.status).toBe('valid');expect(a.bpm).toBeGreaterThan(60);expect(a.bpm).toBeLessThan(84)})
 it('does not interpolate across a long timestamp gap',()=>{expect(resampleTrace(fixture(true),'forehead','g')).toBeNull()})
 it('excludes a dropped ROI without treating missing RGB as zero',()=>{const s=fixture();s.forEach(x=>x.rois.left_cheek=null);const a=analyzeSamples(s);expect(a.estimates.left_cheek_green).toBeUndefined();expect(a.estimates.forehead_green).toBeDefined()})
 it('returns unavailable during warmup',()=>{expect(analyzeSamples(fixture().slice(0,100)).bpm).toBeNull()})
})
