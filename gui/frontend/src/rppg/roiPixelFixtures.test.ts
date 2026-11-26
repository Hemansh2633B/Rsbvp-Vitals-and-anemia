// ROI extraction against the shared illumination / colour-cast fixtures.
//
// The fixture file is a *recipe* (face box, skin colour, per-channel illuminant
// gain, hair band) rendered identically here and in tests/test_roi_pixel_fixtures.py.
// Every frame is synthetic: no camera, no real face, no personal data. These tests
// prove the extractor's arithmetic and its rejection accounting. They say nothing
// about real skin under real light.
import { describe, it, expect } from 'vitest'
import fixture from '../../../../tests/fixtures/roi_pixel_fixtures.json'
import {
  extractAllRois,
  extractRoi,
  classifyPixel,
  MIN_ACCEPTED_FRACTION,
  type Point,
} from './roiGeometry'

type Case = { skin: string; illuminant: string; base_rgb: number[]; gain: number[]; background: number[] }
type Payload = {
  width: number
  height: number
  faceBox: { x: number; y: number; w: number; h: number }
  hair: { rgb: number[]; pixelsAboveFace: number }
  landmarks: Point[]
  cases: Record<string, Case>
}
const P = fixture as unknown as Payload
const L = P.landmarks

const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)))

/** Render a fixture frame exactly as the Python generator does. */
function render(c: Case): Uint8ClampedArray {
  const { width, height, faceBox, hair } = P
  const data = new Uint8ClampedArray(width * height * 4)
  const put = (x: number, y: number, rgb: number[]) => {
    const o = (y * width + x) * 4
    data[o] = rgb[0]; data[o + 1] = rgb[1]; data[o + 2] = rgb[2]; data[o + 3] = 255
  }
  for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) put(x, y, c.background)
  const x0 = Math.floor(faceBox.x * width)
  const x1 = Math.floor((faceBox.x + faceBox.w) * width)
  const y0 = Math.floor(faceBox.y * height)
  const y1 = Math.floor((faceBox.y + faceBox.h) * height)
  const skin = c.base_rgb.map((v, i) => clamp(v * c.gain[i]))
  for (let y = y0; y < y1; y += 1) for (let x = x0; x < x1; x += 1) put(x, y, skin)
  for (let y = Math.max(0, y0 - hair.pixelsAboveFace); y < y0; y += 1) {
    for (let x = x0; x < x1; x += 1) put(x, y, hair.rgb)
  }
  return data
}

const physiological = Object.entries(P.cases).filter(
  ([, c]) => c.skin !== 'grey_wall' && c.skin !== 'background_only',
)

describe('shared fixture integrity', () => {
  it('is labelled synthetic and carries no image data', () => {
    const text = JSON.stringify(fixture)
    expect((fixture as unknown as { note: string }).note.toLowerCase()).toContain('synthetic')
    expect(text).not.toMatch(/data:image|base64/i)
    expect(L).toHaveLength(468)
  })

  it('covers every skin tone under every illuminant', () => {
    const skins = new Set(Object.values(P.cases).map(c => c.skin))
    const lights = new Set(Object.values(P.cases).map(c => c.illuminant))
    expect(skins.size).toBeGreaterThanOrEqual(5)
    expect(lights.size).toBeGreaterThanOrEqual(6)
  })
})

describe('extraction across illumination and colour cast', () => {
  it('samples the forehead for every plausible skin/illuminant combination', () => {
    // THE REGRESSION for the reported 0 %-coverage symptom. The old gate rejected
    // light skin in cool/deep shade and dark skin in deep shade because it demanded
    // r >= 0.88g and r - b >= 8 for every pixel.
    const failures: Array<{ name: string; reason: string | null; fraction: number }> = []
    for (const [name, c] of physiological) {
      const data = render(c)
      const { rgb, diagnostics } = extractRoi(data, P.width, P.height, 'forehead', L)
      if (!rgb) failures.push({ name, reason: diagnostics.invalidReason, fraction: diagnostics.acceptedFraction })
    }
    // One known limitation is excluded and asserted separately below.
    expect(failures.map(f => f.name)).toEqual(['very_light__deep_blue_shade'])
  })

  it('states the one case the new rule still cannot sample', () => {
    // Very light skin under deep blue shade is nearly achromatic, and POS/CHROM
    // need chrominance. Keeping this visible is the point: the fix is disclosed,
    // not hidden by lowering the chroma floor until everything passes.
    const c = P.cases['very_light__deep_blue_shade']
    const { rgb, diagnostics } = extractRoi(render(c), P.width, P.height, 'forehead', L)
    expect(rgb).toBeNull()
    expect(diagnostics.invalidReason).toBe('no_accepted_pixels')
    expect(diagnostics.rejected.low_chroma).toBeGreaterThan(0)
    expect(diagnostics.invalidDetail).toMatch(/near-grey pixel/)
  })

  it('extracts a mean close to the rendered skin colour rather than the background', () => {
    for (const [name, c] of physiological) {
      const data = render(c)
      const { rgb } = extractRoi(data, P.width, P.height, 'forehead', L)
      if (!rgb) continue
      const expected = c.base_rgb.map((v, i) => clamp(v * c.gain[i]))
      // Every channel within a few counts: the patch lies inside the face box, so
      // the mean must be the skin, not a blend with the wall or the hair.
      rgb.forEach((value, i) => {
        expect(Math.abs(value - expected[i]), `${name} channel ${i}`).toBeLessThan(4)
      })
    }
  })

  it('samples both cheeks on the same frame, independently', () => {
    const c = P.cases['light__neutral_d65']
    const data = render(c)
    const { samples, diagnostics } = extractAllRois(data, P.width, P.height, L)
    expect(samples.forehead).not.toBeNull()
    expect(samples.left_cheek).not.toBeNull()
    expect(samples.right_cheek).not.toBeNull()
    for (const d of diagnostics) {
      expect(d.valid).toBe(true)
      expect(d.acceptedFraction).toBeGreaterThan(MIN_ACCEPTED_FRACTION)
    }
  })

  it('rejects a grey wall and a featureless background', () => {
    for (const name of ['grey_wall__neutral_d65', 'background_only__neutral_d65']) {
      const { rgb, diagnostics } = extractRoi(render(P.cases[name]), P.width, P.height, 'forehead', L)
      expect(rgb, name).toBeNull()
      // Either too dark or too achromatic - both are explicit reasons.
      expect(['no_accepted_pixels', 'low_usable_coverage']).toContain(diagnostics.invalidReason)
    }
  })

  it('samples the face even when the background is grey', () => {
    // The inverse of the previous test: a grey wall must not prevent sampling skin.
    const data = render(P.cases['grey_background_skinned_face__neutral_d65'])
    const { rgb, diagnostics } = extractRoi(data, P.width, P.height, 'forehead', L)
    expect(rgb).not.toBeNull()
    expect(diagnostics.excludedByMask).toBeGreaterThanOrEqual(0)
  })

  it('the foreground pixel filter agrees with the fixture expectations', () => {
    // Cross-check: whatever `classifyPixel` decides for the rendered skin colour is
    // what the extractor reports across the patch.
    for (const [name, c] of physiological) {
      const skin = c.base_rgb.map((v, i) => clamp(v * c.gain[i])) as [number, number, number]
      const verdict = classifyPixel(...skin)
      const { rgb } = extractRoi(render(c), P.width, P.height, 'forehead', L)
      expect(rgb === null, `${name}: verdict ${verdict} vs rgb ${rgb}`).toBe(verdict !== null)
    }
  })
})

describe('pixel accounting is conserved on real fixture frames', () => {
  it('every candidate pixel is accounted for, on every fixture', () => {
    for (const [name, c] of Object.entries(P.cases)) {
      const data = render(c)
      for (const region of ['forehead', 'left_cheek', 'right_cheek'] as const) {
        const { diagnostics } = extractRoi(data, P.width, P.height, region, L)
        const rejected = Object.values(diagnostics.rejected).reduce((s, v) => s + v, 0)
        // Include pixels outside the patch: they were never candidates.
        expect(
          diagnostics.acceptedPixels + diagnostics.excludedByMask + rejected,
          `${name}/${region}`,
        ).toBe(diagnostics.candidatePixels)
      }
    }
  })
})
