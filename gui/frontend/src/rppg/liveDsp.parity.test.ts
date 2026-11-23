import {describe,it,expect} from 'vitest'
import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {analyzeSamples,spectralDiagnostics,posProjection,chromProjection,type TraceSample} from './liveDsp'

function fixture():TraceSample[]{
  const text=readFileSync(resolve(process.cwd(),'../../tests/fixtures/rppg_rgb_fixture.csv'),'utf8').trim().split(/\r?\n/)
  const headers=text[0].split(',')
  return text.slice(1).map(line=>{const row=Object.fromEntries(line.split(',').map((v,i)=>[headers[i],v]));return{t:Number(row.timestamp_s),rois:{forehead:[Number(row.forehead_r),Number(row.forehead_g),Number(row.forehead_b)] as TraceSample['rois']['forehead'],left_cheek:[Number(row.left_cheek_r),Number(row.left_cheek_g),Number(row.left_cheek_b)] as TraceSample['rois']['left_cheek'],right_cheek:[Number(row.right_cheek_r),Number(row.right_cheek_g),Number(row.right_cheek_b)] as TraceSample['rois']['right_cheek']}} as TraceSample})
}
function window240(){const samples=fixture().filter(s=>s.t<12);return samples.map(s=>s.rois.forehead!)}
function measuredFs(samples:TraceSample[]){const d=samples.slice(1).map((s,i)=>s.t-samples[i].t).filter(x=>x>0).sort((a,b)=>a-b);return 1/d[Math.floor(d.length/2)]}

// These assertions compare the TypeScript implementation against an independent
// Python reimplementation of the same projections and Hann-periodogram estimator
// (tests/fixtures/generate_rppg_rgb_fixture_expected.py). They verify software
// parity on one synthetic fixture. They are NOT evidence that browser and
// Python agree on real cameras, real skin optics, or clinical accuracy.
describe('shared Python/TypeScript DSP fixture',()=>{
  it('matches the Python frequency-bin reference on identical synthetic samples',()=>{
    const samples=fixture().filter(s=>s.t<12)
    const expected=JSON.parse(readFileSync(resolve(process.cwd(),'../../tests/fixtures/rppg_rgb_fixture_expected.json'),'utf8')).reference_free_expected_python_estimates_bpm
    const result=analyzeSamples(samples)
    expect(result.status).toBe('valid')
    for(const key of ['forehead_green','forehead_pos','forehead_chrom'])expect(result.estimates[key]).toBeCloseTo(expected[key],1)
  })
  it('spectral diagnostics match the independent Python reimplementation',()=>{
    const samples=fixture().filter(s=>s.t<12)
    const fs=measuredFs(samples)
    const forehead=window240()
    const py=JSON.parse(readFileSync(resolve(process.cwd(),'../../tests/fixtures/rppg_rgb_fixture_expected.json'),'utf8')).python_spectral_diagnostics_first_12_seconds
    const projections:Record<string,number[]>={
      forehead_green:forehead.map(v=>v[1]),
      forehead_pos:posProjection(forehead),
      forehead_chrom:chromProjection(forehead,fs),
    }
    for(const key of ['forehead_green','forehead_pos','forehead_chrom'] as const){
      const ts=spectralDiagnostics(projections[key],fs)
      const p=py[key]
      expect(ts.bpm,`${key} bpm`).toBeCloseTo(p.bpm,6)
      expect(ts.quality,`${key} peak fraction`).toBeCloseTo(p.peak_fraction,6)
      expect(ts.snrDb,`${key} snr dB`).toBeCloseTo(p.snr_db,3)
      expect(ts.separationRatio,`${key} separation`).toBe(p.separation_ratio)
    }
  })
  it('reports the same effective sampling rate the Python reimplementation measured',()=>{
    const samples=fixture().filter(s=>s.t<12)
    const fs=measuredFs(samples)
    const py=JSON.parse(readFileSync(resolve(process.cwd(),'../../tests/fixtures/rppg_rgb_fixture_expected.json'),'utf8')).python_spectral_diagnostics_first_12_seconds
    expect(fs).toBeCloseTo(py.fs_hz,6)
    expect(py.n_samples).toBe(240)
  })
})
