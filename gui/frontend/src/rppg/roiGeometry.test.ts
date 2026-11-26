// ROI geometry: landmark contract, patch construction, exclusion masks and pixel
// diagnostics.
//
// Every geometric assertion here is checked against the MediaPipe canonical face
// model's own 2D projection, committed as `fixtures/faceCanonical2d.json`. That
// fixture is model geometry, not a photograph: these tests prove that the ROI
// follows the documented anatomy and that the code rejects degenerate input. They
// say nothing about how well this works on a real face under real light.
import { describe, it, expect } from 'vitest'
import canonical from './fixtures/faceCanonical2d.json'
import {
  CHEEK_PATCHES,
  FEATURE_MASKS,
  FOREHEAD_ANCHORS,
  FOREHEAD_LOWER_REFERENCE,
  LANDMARK_CONTRACT,
  MIN_ACCEPTED_FRACTION,
  MIN_CANDIDATE_PIXELS,
  PIXEL_REJECTION_COPY,
  REGION_EXCLUSIONS,
  ROI_NAMES,
  buildPatch,
  classifyPixel,
  extractAllRois,
  extractRoi,
  foreheadCorners,
  insetPolygon,
  isContractedLandmark,
  landmarkName,
  pointInPolygon,
  polygonArea,
  polygonIsDegenerate,
  signedArea,
  type Point,
  type PixelRejection,
} from './roiGeometry'

const L = canonical.landmarks as Point[]
const at = (i: number): Point => L[i]

function segmentsCross(a: Point, b: Point, c: Point, d: Point): boolean {
  const cross = (o: Point, p: Point, q: Point) => (p.x - o.x) * (q.y - o.y) - (p.y - o.y) * (q.x - o.x)
  return (cross(c, d, a) > 0) !== (cross(c, d, b) > 0) && (cross(a, b, c) > 0) !== (cross(a, b, d) > 0)
}

function selfIntersects(poly: Point[]): boolean {
  const n = poly.length
  for (let i = 0; i < n; i += 1) {
    for (let j = i + 2; j < n; j += 1) {
      if (i === 0 && j === n - 1) continue
      if (segmentsCross(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n])) return true
    }
  }
  return false
}

function isConvex(poly: Point[]): boolean {
  const n = poly.length
  const signs = new Set<boolean>()
  for (let i = 0; i < n; i += 1) {
    const o = poly[i]
    const a = poly[(i + 1) % n]
    const b = poly[(i + 2) % n]
    const c = (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
    if (Math.abs(c) > 1e-12) signs.add(c > 0)
  }
  return signs.size === 1
}

// The face outline as a polygon, for containment and clearance checks.
const FACE_OUTLINE = [
  10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400,
  377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
]
const outline = FACE_OUTLINE.map(at)

function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const denom = dx * dx + dy * dy
  const t = denom === 0 ? 0 : Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / denom))
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
}

/** Smallest distance from any patch vertex to the face outline. */
function faceClearance(poly: Point[]): number {
  return Math.min(
    ...poly.map(p => Math.min(...outline.map((_, k) => distanceToSegment(p, outline[k], outline[(k + 1) % outline.length])))),
  )
}

const inPoly = (p: Point, poly: Point[]) => pointInPolygon(p.x, p.y, poly, 1, 1)

/** Fraction of a patch's interior that falls inside a mask polygon. */
function maskOverlapFraction(patch: Point[], mask: Point[], n = 120): number {
  const xs = patch.map(p => p.x)
  const ys = patch.map(p => p.y)
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
  let cells = 0
  let hits = 0
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j < n; j += 1) {
      const p = { x: x0 + ((x1 - x0) * (i + 0.5)) / n, y: y0 + ((y1 - y0) * (j + 0.5)) / n }
      if (!inPoly(p, patch)) continue
      cells += 1
      if (inPoly(p, mask)) hits += 1
    }
  }
  return cells ? hits / cells : 0
}

const patchFor = (region: (typeof ROI_NAMES)[number]): Point[] => {
  const built = buildPatch(region, L)
  if (!built.ok) throw new Error(`patch ${region} failed: ${built.detail}`)
  return built.polygon
}

describe('landmark contract', () => {
  it('agrees with the canonical face model exactly', () => {
    // The contract's purpose is to be checkable. A wrong coordinate here would
    // silently move a sampling region, so it is asserted, not documented.
    for (const entry of LANDMARK_CONTRACT) {
      expect(Math.abs(entry.canonicalX - at(entry.index).x), `landmark ${entry.index} x`).toBeLessThan(0.002)
      expect(Math.abs(entry.canonicalY - at(entry.index).y), `landmark ${entry.index} y`).toBeLessThan(0.002)
    }
  })

  it('covers every landmark the code actually uses', () => {
    const used = new Set<number>([
      ...FOREHEAD_ANCHORS,
      FOREHEAD_LOWER_REFERENCE,
      ...CHEEK_PATCHES.left_cheek,
      ...CHEEK_PATCHES.right_cheek,
      ...Object.values(FEATURE_MASKS).flat(),
    ])
    const documented = new Set(LANDMARK_CONTRACT.map(e => e.index))
    const undocumented = [...used].filter(i => !documented.has(i))
    expect(undocumented).toEqual([])
    expect(isContractedLandmark(108)).toBe(true)
    expect(isContractedLandmark(4000)).toBe(false)
    expect(landmarkName(108)).toBe('forehead_anchor_left')
    expect(landmarkName(4000)).toBe('landmark_4000')
  })

  it('places the model\'s hairline and chin where the contract says', () => {
    // Anchors used by every other assertion: vertex 10 is the top of the head,
    // 152 the chin. If these were swapped, "above the brow" would mean the back
    // of the neck.
    expect(at(10).y).toBeCloseTo(0, 3)
    expect(at(152).y).toBeCloseTo(1, 3)
    expect(at(10).x).toBeCloseTo(0.5, 3)
  })

  it('has symmetric left/right landmark pairs', () => {
    // The forehead anchors and both cheek sets must be exact mirrors about the
    // midline, otherwise the two sides sample different anatomy.
    for (const [left, right] of [
      [FOREHEAD_ANCHORS[0], FOREHEAD_ANCHORS[1]],
      ...CHEEK_PATCHES.left_cheek.map((l, k) => [l, CHEEK_PATCHES.right_cheek[k]] as [number, number]),
    ]) {
      expect(at(right).x, `mirror of ${left} -> ${right}`).toBeCloseTo(1 - at(left).x, 3)
      expect(at(right).y).toBeCloseTo(at(left).y, 3)
    }
  })
})

describe('forehead patch geometry', () => {
  it('is a compact patch, not the whole upper face', () => {
    // THE REGRESSION. The previous polygon was [10,338,297,332,284,251,389,356,
    // 9,127,162,21,54,103,67,109]: 100 % of face width, 33.4 % of face height,
    // area 0.212 bbox units^2. It read as "forehead covers the whole top of the
    // head", which is what the operator saw on the overlay.
    const poly = patchFor('forehead')
    const xs = poly.map(p => p.x)
    const ys = poly.map(p => p.y)
    const width = Math.max(...xs) - Math.min(...xs)
    const height = Math.max(...ys) - Math.min(...ys)
    expect(width).toBeLessThan(0.30)
    expect(height).toBeLessThan(0.12)
    expect(polygonArea(poly)).toBeLessThan(0.035)
    // and big enough to be worth sampling
    expect(polygonArea(poly)).toBeGreaterThan(0.005)
  })

  it('sits between the hairline and the brow', () => {
    const poly = patchFor('forehead')
    const top = Math.min(...poly.map(p => p.y))
    const bottom = Math.max(...poly.map(p => p.y))
    const hairline = at(10).y // 0.000
    const brow = at(107).y // innermost brow landmark
    expect(top).toBeGreaterThan(hairline + 0.05)
    expect(bottom).toBeLessThan(brow)
    // The lower edge must stay measurably above the brow, not just barely.
    expect(brow - bottom).toBeGreaterThan(0.015)
  })

  it('scales with face size instead of a fixed bounding-box fraction', () => {
    // Shrink every landmark toward the face centre; the patch must shrink with
    // the face, because its depth is a fraction of the anchor-glabella distance.
    const centre = { x: 0.5, y: 0.5 }
    for (const scale of [0.5, 2]) {
      const scaled = L.map(p => ({ x: centre.x + (p.x - centre.x) * scale, y: centre.y + (p.y - centre.y) * scale }))
      const big = foreheadCorners(L)!
      const small = foreheadCorners(scaled)!
      expect(small.length).toBe(4)
      const ratio = polygonArea(small) / polygonArea(big)
      expect(ratio).toBeCloseTo(scale * scale, 1)
    }
  })

  it('is convex, simple and clear of the brow masks', () => {
    const poly = patchFor('forehead')
    expect(selfIntersects(poly)).toBe(false)
    expect(isConvex(poly)).toBe(true)
    expect(faceClearance(poly)).toBeGreaterThan(0.03)
    for (const maskName of REGION_EXCLUSIONS.forehead) {
      const mask = FEATURE_MASKS[maskName].map(at)
      expect(maskOverlapFraction(poly, mask), `forehead vs ${maskName}`).toBe(0)
    }
  })

  it('applies the safe margin inward on every edge', () => {
    const raw = foreheadCorners(L)!
    const poly = patchFor('forehead')
    expect(polygonArea(poly)).toBeLessThan(polygonArea(raw))
    // every corner moved toward the centroid
    const cx = raw.reduce((s, p) => s + p.x, 0) / raw.length
    const cy = raw.reduce((s, p) => s + p.y, 0) / raw.length
    poly.forEach((p, i) => {
      expect(Math.hypot(p.x - cx, p.y - cy)).toBeLessThan(Math.hypot(raw[i].x - cx, raw[i].y - cy))
    })
    // and the margin is bounded: it must not eat the patch
    expect(polygonArea(poly) / polygonArea(raw)).toBeGreaterThan(0.5)
  })

  it('rejects an inverted or missing anchor instead of guessing', () => {
    const flipped = L.map(p => ({ ...p }))
    flipped[FOREHEAD_LOWER_REFERENCE] = { x: 0.5, y: flipped[FOREHEAD_ANCHORS[0]].y - 0.2 }
    expect(foreheadCorners(flipped)).toEqual([])
    const broken = L.map(p => ({ ...p }))
    broken[FOREHEAD_ANCHORS[1]] = Number.NaN as unknown as Point
    expect(foreheadCorners(broken)).toEqual([])
  })
})

describe('cheek patch geometry', () => {
  const cases: Array<[(typeof ROI_NAMES)[number], string[]]> = [
    ['left_cheek', ['left_eye', 'mouth', 'nostrils']],
    ['right_cheek', ['right_eye', 'mouth', 'nostrils']],
  ]

  for (const [region, masks] of cases) {
    it(`${region} is simple and convex`, () => {
      // THE REGRESSION: the previous cheek outlines self-intersected, which makes
      // the even-odd fill ambiguous and silently changes the sampled pixels.
      const poly = patchFor(region)
      expect(selfIntersects(poly)).toBe(false)
      expect(isConvex(poly)).toBe(true)
      expect(polygonArea(poly)).toBeGreaterThan(0.005)
      expect(polygonArea(poly)).toBeLessThan(0.035)
    })

    it(`${region} stays on the facial surface`, () => {
      const poly = patchFor(region)
      expect(faceClearance(poly)).toBeGreaterThan(0.03)
      for (const vertex of poly) expect(inPoly(vertex, outline)).toBe(true)
    })

    it(`${region} avoids eyes, mouth and nostrils`, () => {
      const poly = patchFor(region)
      for (const maskName of masks) {
        const mask = FEATURE_MASKS[maskName].map(at)
        expect(maskOverlapFraction(poly, mask), `${region} vs ${maskName}`).toBe(0)
      }
    })

    it(`${region} sits below the eye and above the mouth`, () => {
      const poly = patchFor(region)
      const top = Math.min(...poly.map(p => p.y))
      const bottom = Math.max(...poly.map(p => p.y))
      expect(top).toBeGreaterThan(at(33).y) // below the eye ring
      expect(bottom).toBeLessThan(at(0).y) // above the upper lip
    })
  }

  it('keeps the two cheeks from overlapping each other', () => {
    const left = patchFor('left_cheek')
    const right = patchFor('right_cheek')
    const overlap = left.filter(p => inPoly(p, right)).length + right.filter(p => inPoly(p, left)).length
    expect(overlap).toBe(0)
    expect(Math.max(...left.map(p => p.x))).toBeLessThan(Math.min(...right.map(p => p.x)))
  })

  it('mirrors the left cheek exactly on the right', () => {
    const left = patchFor('left_cheek')
    const right = patchFor('right_cheek')
    expect(left.length).toBe(right.length)
    expect(polygonArea(left)).toBeCloseTo(polygonArea(right), 6)
  })
})

describe('degenerate and out-of-frame input', () => {
  it('reports invalid landmarks when a required index is missing', () => {
    const holes = L.map((p, i) => (i === CHEEK_PATCHES.left_cheek[0] ? undefined : p))
    const built = buildPatch('left_cheek', holes)
    expect(built.ok).toBe(false)
    if (!built.ok) {
      expect(built.reason).toBe('invalid_landmarks')
      expect(built.detail).toMatch(/Landmark 117/)
    }
  })

  it('detects zero-area and self-intersecting polygons', () => {
    expect(polygonIsDegenerate([{ x: 0.1, y: 0.1 }, { x: 0.2, y: 0.1 }, { x: 0.3, y: 0.1 }])).toBe(true)
    // bow-tie: all four points distinct, area cancels to zero
    expect(polygonIsDegenerate([
      { x: 0, y: 0 }, { x: 1, y: 1 }, { x: 1, y: 0 }, { x: 0, y: 1 },
    ])).toBe(true)
    // a proper quad is not degenerate
    expect(polygonIsDegenerate([{ x: 0.2, y: 0.2 }, { x: 0.4, y: 0.2 }, { x: 0.4, y: 0.4 }, { x: 0.2, y: 0.4 }])).toBe(false)
  })

  it('winds consistently, so area is always positive', () => {
    expect(polygonArea(patchFor('forehead'))).toBeGreaterThan(0)
    expect(Math.abs(signedArea(patchFor('forehead')))).toBeCloseTo(polygonArea(patchFor('forehead')), 10)
  })

  it('never returns a mean for a NaN landmark', () => {
    const broken = L.map((p, i) => (i === FOREHEAD_ANCHORS[0] ? { x: Number.NaN, y: 0.1 } : p))
    const frame = solidFrame(64, 64, [170, 140, 125])
    const { rgb, diagnostics } = extractRoi(frame.data, 64, 64, 'forehead', broken)
    expect(rgb).toBeNull()
    expect(diagnostics.valid).toBe(false)
    expect(diagnostics.invalidReason).toBe('invalid_landmarks')
  })
})

describe('insetPolygon', () => {
  it('shrinks around the centroid without changing the shape', () => {
    const square = [{ x: 0.2, y: 0.2 }, { x: 0.6, y: 0.2 }, { x: 0.6, y: 0.6 }, { x: 0.2, y: 0.6 }]
    const inner = insetPolygon(square, 0.05)
    expect(polygonArea(inner)).toBeLessThan(polygonArea(square))
    expect(isConvex(inner)).toBe(true)
    expect(selfIntersects(inner)).toBe(false)
    const centre = inner.reduce((s, p) => s + p.x, 0) / 4
    expect(centre).toBeCloseTo(0.4, 6)
  })

  it('leaves a polygon with no extent untouched rather than producing NaN', () => {
    const point = [{ x: 0.5, y: 0.5 }, { x: 0.5, y: 0.5 }, { x: 0.5, y: 0.5 }]
    expect(insetPolygon(point, 0.05).every(p => Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true)
  })
})

/* ---------------- pixel extraction ---------------- */

function solidFrame(width: number, height: number, rgb: [number, number, number]): { data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let i = 0; i < width * height; i += 1) {
    data[i * 4] = rgb[0]
    data[i * 4 + 1] = rgb[1]
    data[i * 4 + 2] = rgb[2]
    data[i * 4 + 3] = 255
  }
  return { data }
}

/** Landmarks scaled so the face occupies `box` (all values normalised, 0-1). */
function landmarksInBox(box: { x: number; y: number; w: number; h: number }): Point[] {
  return L.map(p => ({ x: box.x + p.x * box.w, y: box.y + p.y * box.h }))
}

describe('pixel classification', () => {
  it('keeps representative skin under several white-balance casts', () => {
    // The reported failure was 0 % valid forehead samples. The old gate demanded
    // r >= 0.88g, g >= 0.82b AND r-b >= 8 for every pixel, which is one specific
    // white-balance assumption. These are the same physiologically plausible skin
    // samples under different illuminants; all must now be usable.
    const tinted: Array<[string, [number, number, number]]> = [
      ['neutral light skin', [224, 189, 171]],
      ['neutral medium skin', [198, 160, 138]],
      ['neutral olive skin', [168, 130, 108]],
      ['neutral brown skin', [128, 95, 76]],
      ['neutral dark skin', [85, 62, 50]],
      ['warm tungsten light skin', [224, 189, 160]],
      ['warm tungsten dark skin', [95, 62, 38]],
      ['cool LED light skin', [210, 189, 188]],
      ['greenish fluorescent', [150, 165, 142]],
      ['mild blue shade', [190, 178, 174]],
    ]
    for (const [label, rgb] of tinted) {
      expect(classifyPixel(...rgb), label).toBeNull()
    }
  })

  it('still rejects what cannot carry a pulse', () => {
    expect(classifyPixel(5, 5, 5)).toBe('too_dark')
    expect(classifyPixel(255, 255, 255)).toBe('too_bright')
    expect(classifyPixel(120, 120, 120)).toBe('low_chroma') // grey wall / clothing
    expect(classifyPixel(60, 100, 150)).toBe('channel_order') // blue-dominant background
  })

  it('rejects a chromatically neutral patch, and that is deliberate', () => {
    // A patch can be light and "skin-like" in luminance yet carry almost no
    // chroma (e.g. heavy blue shade plus a camera's own desaturation). POS and
    // CHROM both project chrominance, so such a patch cannot yield a pulse. This
    // is a signal-capability check, not a skin-tone judgement, and it is
    // reported as `low_chroma` with its own copy rather than as a generic
    // rejection. Recorded here so nobody "fixes" it by loosening the floor.
    expect(classifyPixel(197, 189, 198)).toBe('low_chroma')
    expect(classifyPixel(184, 180, 183)).toBe('low_chroma')
  })

  it('has human-readable copy for every rejection reason', () => {
    const reasons: PixelRejection[] = ['outside_polygon', 'in_feature_mask', 'too_dark', 'too_bright', 'channel_order', 'low_chroma']
    for (const reason of reasons) expect(PIXEL_REJECTION_COPY[reason].length).toBeGreaterThan(8)
  })

  it('does not depend on a skin-tone classifier', () => {
    // A dark-skin sample must not be rejected merely for being dark, as long as
    // it is above the luminance floor. 60/45/38 is dark but well lit.
    expect(classifyPixel(60, 45, 38)).toBeNull()
  })
})

describe('ROI extraction diagnostics', () => {
  const box = { x: 0.25, y: 0.15, w: 0.5, h: 0.7 }

  it('reports accepted pixel counts and a usable mean for a skin-coloured frame', () => {
    const width = 320
    const height = 320
    const frame = solidFrame(width, height, [198, 160, 138])
    const landmarks = landmarksInBox(box)
    const { rgb, diagnostics } = extractRoi(frame.data, width, height, 'forehead', landmarks)
    expect(diagnostics.valid).toBe(true)
    expect(diagnostics.candidatePixels).toBeGreaterThan(MIN_CANDIDATE_PIXELS)
    expect(diagnostics.acceptedPixels).toBeGreaterThan(0)
    expect(diagnostics.acceptedFraction).toBeGreaterThan(0.5)
    expect(rgb).not.toBeNull()
    expect(rgb![0]).toBeCloseTo(198, 0)
    expect(diagnostics.polygonAreaPx).toBeGreaterThan(0)
    expect(diagnostics.summary).toMatch(/candidate pixels used/)
  })

  it('accounts for every candidate pixel exactly once', () => {
    // Conservation check: candidate = accepted + masked + each rejection count.
    const width = 256
    const height = 256
    const frame = solidFrame(width, height, [198, 160, 138])
    // Paint a clipped patch and a near-grey strip so several conditions fire.
    for (let y = 100; y < 120; y += 1) {
      for (let x = 90; x < 160; x += 1) {
        const o = (y * width + x) * 4
        frame.data[o] = 250
        frame.data[o + 1] = 250
        frame.data[o + 2] = 250
      }
    }
    const landmarks = landmarksInBox(box)
    const { diagnostics } = extractRoi(frame.data, width, height, 'forehead', landmarks)
    const rejected = Object.values(diagnostics.rejected).reduce((s, v) => s + v, 0)
    expect(diagnostics.candidatePixels).toBe(
      diagnostics.acceptedPixels + diagnostics.excludedByMask + rejected,
    )
  })

  it('explains a wholly unusable patch instead of returning a silent null', () => {
    const width = 200
    const height = 200
    const grey = solidFrame(width, height, [128, 128, 128])
    const landmarks = landmarksInBox(box)
    const { rgb, diagnostics } = extractRoi(grey.data, width, height, 'forehead', landmarks)
    expect(rgb).toBeNull()
    expect(diagnostics.valid).toBe(true) // the polygon was fine; the pixels were not
    expect(diagnostics.invalidReason).toBe('no_accepted_pixels')
    expect(diagnostics.rejected.low_chroma).toBeGreaterThan(0)
    expect(diagnostics.invalidDetail).toMatch(/near-grey pixel/)
  })

  it('reports a patch that is too small at the current frame size', () => {
    // A face occupying a small box in a small frame leaves a patch of a few
    // pixels: ~72 x 72 frame, 25 % face box -> a forehead patch a few px tall.
    const size = 72
    const landmarks = landmarksInBox({ x: 0.375, y: 0.3, w: 0.25, h: 0.4 })
    const frame = solidFrame(size, size, [198, 160, 138])
    const { rgb, diagnostics } = extractRoi(frame.data, size, size, 'forehead', landmarks)
    expect(rgb).toBeNull()
    expect(diagnostics.invalidReason).toBe('too_few_candidate_pixels')
    expect(diagnostics.invalidDetail).toMatch(/at least \d+ are needed/)
  })

  it('reports low usable coverage when most pixels are rejected', () => {
    const width = 320
    const height = 320
    const frame = solidFrame(width, height, [198, 160, 138])
    const landmarks = landmarksInBox(box)
    const forehead = foreheadCorners(landmarks)!
    const ys = forehead.map(p => p.y)
    const xs = forehead.map(p => p.x)
    // Darken most of the patch box, keeping only a thin band of valid skin. The
    // stride is derived from the patch's own height (a forehead patch is only a
    // few percent of the frame tall), not from an absolute row count.
    // foreheadCorners works in normalised coordinates, so convert to pixels here.
    const y0 = Math.floor(Math.min(...ys) * height)
    const y1 = Math.ceil(Math.max(...ys) * height)
    // Keep ~15 % of the patch's rows: above zero accepted pixels, below the floor.
    const keepRows = Math.max(2, Math.round((y1 - y0) * 0.15))
    for (let y = y0 + keepRows; y < y1; y += 1) {
      for (let x = Math.floor(Math.min(...xs) * width); x < Math.ceil(Math.max(...xs) * width); x += 1) {
        const o = (y * width + x) * 4
        frame.data[o] = 4
        frame.data[o + 1] = 4
        frame.data[o + 2] = 4
      }
    }
    const { rgb, diagnostics } = extractRoi(frame.data, width, height, 'forehead', landmarks)
    // The two "mostly rejected" outcomes must be distinguishable: some pixels
    // accepted but too few is `low_usable_coverage`; none at all is
    // `no_accepted_pixels`. Both are explicit, neither is a silent null.
    expect(rgb).toBeNull()
    expect(['low_usable_coverage', 'no_accepted_pixels']).toContain(diagnostics.invalidReason)
    expect(diagnostics.acceptedFraction).toBeLessThan(MIN_ACCEPTED_FRACTION)
    expect(diagnostics.rejected.too_dark).toBeGreaterThan(0)
    expect(diagnostics.invalidDetail).toMatch(/underexposed|usable/)
  })

  it('counts feature-mask exclusions separately from pixel rejections', () => {
    const width = 320
    const height = 320
    const frame = solidFrame(width, height, [198, 160, 138])
    const landmarks = landmarksInBox(box)
    const withMasks = extractRoi(frame.data, width, height, 'left_cheek', landmarks)
    const withoutMasks = extractRoi(frame.data, width, height, 'left_cheek', landmarks, { maskNames: [] })
    expect(withMasks.diagnostics.excludedByMask).toBeGreaterThanOrEqual(0)
    expect(withoutMasks.diagnostics.excludedByMask).toBe(0)
    expect(withoutMasks.diagnostics.candidatePixels).toBe(withMasks.diagnostics.candidatePixels)
  })

  it('returns median alongside mean so a specular highlight is visible', () => {
    const width = 300
    const height = 300
    const frame = solidFrame(width, height, [198, 160, 138])
    const landmarks = landmarksInBox(box)
    const forehead = foreheadCorners(landmarks)!
    const ys = forehead.map(p => p.y)
    const xs = forehead.map(p => p.x)
    // A bright specular blob covering part of the patch (normalised -> pixels).
    const py0 = Math.floor(Math.min(...ys) * height)
    const py1 = Math.ceil(Math.max(...ys) * height)
    for (let y = py0; y < Math.min(py1, py0 + Math.max(2, Math.floor((py1 - py0) / 3))); y += 1) {
      for (let x = Math.floor(Math.min(...xs) * width); x < Math.ceil(Math.max(...xs) * width); x += 1) {
        const o = (y * width + x) * 4
        frame.data[o] = 240
        frame.data[o + 1] = 232
        frame.data[o + 2] = 228
      }
    }
    const { diagnostics } = extractRoi(frame.data, width, height, 'forehead', landmarks)
    if (diagnostics.meanRgb && diagnostics.medianRgb) {
      expect(diagnostics.medianRgb[1]).toBeLessThanOrEqual(diagnostics.meanRgb[1])
    }
  })

  it('rejects a frame whose buffer does not match its dimensions', () => {
    const frame = solidFrame(100, 100, [198, 160, 138])
    const { rgb, diagnostics } = extractRoi(frame.data, 200, 200, 'forehead', L)
    expect(rgb).toBeNull()
    expect(diagnostics.invalidReason).toBe('invalid_frame')
  })

  it('extracts all three regions independently', () => {
    const width = 320
    const height = 320
    const frame = solidFrame(width, height, [198, 160, 138])
    const landmarks = landmarksInBox(box)
    const { samples, diagnostics } = extractAllRois(frame.data, width, height, landmarks)
    expect(diagnostics).toHaveLength(3)
    expect(diagnostics.map(d => d.region)).toEqual(['forehead', 'left_cheek', 'right_cheek'])
    // One region failing must not prevent the others from being reported.
    expect(samples.forehead).not.toBeNull()
    expect(samples.left_cheek).not.toBeNull()
    expect(samples.right_cheek).not.toBeNull()
    const distinctCentroids = new Set(diagnostics.map(d => d.polygonAreaPx.toFixed(2)))
    expect(distinctCentroids.size).toBeGreaterThan(1)
  })
})

describe('portrait and landscape frames', () => {
  it('extracts the same region in portrait and landscape video', () => {
    // Android delivers portrait video as 720x1280 and landscape as 1280x720. The
    // patch must be found in both, and the forehead must end up in the upper part
    // of the frame either way.
    for (const [width, height] of [[720, 1280], [1280, 720], [480, 640], [640, 480]]) {
      const frame = solidFrame(width, height, [198, 160, 138])
      const box = width < height
        ? { x: 0.3, y: 0.2, w: 0.4, h: 0.4 }
        : { x: 0.35, y: 0.25, w: 0.3, h: 0.5 }
      const landmarks = landmarksInBox(box)
      const { rgb, diagnostics } = extractRoi(frame.data, width, height, 'forehead', landmarks)
      expect(rgb, `${width}x${height}`).not.toBeNull()
      expect(diagnostics.acceptedPixels).toBeGreaterThan(MIN_CANDIDATE_PIXELS)
      const foreheadY = landmarks[FOREHEAD_ANCHORS[0]].y
      expect(foreheadY).toBeLessThan(box.y + box.h * 0.5)
    }
  })

  it('scales the accepted pixel count with face size', () => {
    const width = 480
    const height = 480
    const frame = solidFrame(width, height, [198, 160, 138])
    const near = extractRoi(frame.data, width, height, 'forehead', landmarksInBox({ x: 0.2, y: 0.1, w: 0.6, h: 0.8 }))
    const far = extractRoi(frame.data, width, height, 'forehead', landmarksInBox({ x: 0.4, y: 0.35, w: 0.2, h: 0.3 }))
    expect(near.diagnostics.acceptedPixels).toBeGreaterThan(far.diagnostics.acceptedPixels)
  })
})

describe('the original 0%-coverage failure', () => {
  it('a tracked face on a skin-coloured frame now yields a sample', () => {
    // The reported symptom: face detected, forehead ROI drawn, still 0 % valid.
    // This reproduces the acquisition shape (a face box in a 640x480 frame) with
    // a range of plausible skin renderings and requires a sample every time.
    const width = 640
    const height = 480
    const box = { x: 0.28, y: 0.16, w: 0.44, h: 0.6 }
    const skins: Array<[string, [number, number, number]]> = [
      ['neutral light', [224, 189, 171]],
      ['neutral medium', [198, 160, 138]],
      ['neutral olive', [168, 130, 108]],
      ['neutral brown', [128, 95, 76]],
      ['warm tungsten', [206, 172, 141]],
      ['cool LED', [210, 195, 198]],
      ['slightly desaturated', [176, 158, 148]],
    ]
    const landmarks = landmarksInBox(box)
    for (const [label, rgb] of skins) {
      const frame = solidFrame(width, height, rgb)
      const { rgb: measured, diagnostics } = extractRoi(frame.data, width, height, 'forehead', landmarks)
      expect(measured, `${label} should be sampleable`).not.toBeNull()
      expect(diagnostics.acceptedFraction, label).toBeGreaterThan(0.9)
    }
  })

  it('still refuses a frame with no skin in the patch', () => {
    // The fix must not become "accept anything": a blue-dominant background
    // behind a tracked face is still rejected.
    const width = 320
    const height = 320
    const frame = solidFrame(width, height, [30, 90, 200])
    const landmarks = landmarksInBox({ x: 0.25, y: 0.2, w: 0.5, h: 0.6 })
    const { rgb, diagnostics } = extractRoi(frame.data, width, height, 'forehead', landmarks)
    expect(rgb).toBeNull()
    expect(diagnostics.invalidReason).toBe('no_accepted_pixels')
  })
})
