// Overlay alignment: object-fit letterboxing, device pixel ratio, mirroring and
// portrait/landscape. Synthetic frames only - these tests prove the *mapping* is
// correct, not that a phone camera behaves the same way.
import { describe, it, expect } from 'vitest'
import canonical from './fixtures/faceCanonical2d.json'
import {
  ROI_COLORS,
  backingStoreSize,
  computeOverlayTransform,
  overlayState,
  shouldMirror,
  videoPointToOverlay,
  type OverlayRegion,
  type OverlayTransform,
} from './overlay'
import { buildPatch, foreheadCorners, type Point } from './roiGeometry'
import { drawRoiOverlay } from './overlay'

const L = canonical.landmarks as Point[]

/** Minimal 2D context recorder: enough to assert what was drawn and where. */
function recordingContext() {
  const calls: Array<{ op: string; args: number[] }> = []
  const ctx = {
    save() { calls.push({ op: 'save', args: [] }) },
    restore() { calls.push({ op: 'restore', args: [] }) },
    setTransform(...args: number[]) { calls.push({ op: 'setTransform', args }) },
    clearRect(...args: number[]) { calls.push({ op: 'clearRect', args }) },
    beginPath() { calls.push({ op: 'beginPath', args: [] }) },
    moveTo(...args: number[]) { calls.push({ op: 'moveTo', args }) },
    lineTo(...args: number[]) { calls.push({ op: 'lineTo', args }) },
    closePath() { calls.push({ op: 'closePath', args: [] }) },
    stroke() { calls.push({ op: 'stroke', args: [] }) },
    fillRect(...args: number[]) { calls.push({ op: 'fillRect', args }) },
    setLineDash(...args: unknown[]) { calls.push({ op: 'setLineDash', args: args as number[] }) },
    strokeStyle: '', fillStyle: '', lineWidth: 0, globalAlpha: 1,
  }
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls }
}

const transformFor = (vw: number, vh: number, ew: number, eh: number, mirrored = false): OverlayTransform =>
  computeOverlayTransform(vw, vh, ew, eh, { mirrored })!

describe('object-fit: contain mapping', () => {
  it('maps a 4:3 stream into a 4:3 box with no letterbox', () => {
    const t = transformFor(640, 480, 640, 480)
    expect(t.scale).toBe(1)
    expect(t.offsetX).toBe(0)
    expect(t.offsetY).toBe(0)
    expect(t.drawnWidth).toBe(640)
    expect(t.drawnHeight).toBe(480)
  })

  it('letterboxes a 16:9 stream inside a 4:3 box', () => {
    // 1280x720 drawn into 640x480: scale is 0.5 by width, so the drawn height is
    // 360 and 60 px of bars appear top and bottom. The old code ignored this and
    // drew ROIs 60 px too low.
    const t = transformFor(1280, 720, 640, 480)
    expect(t.scale).toBe(0.5)
    expect(t.drawnWidth).toBe(640)
    expect(t.drawnHeight).toBe(360)
    expect(t.offsetX).toBe(0)
    expect(t.offsetY).toBe(60)
  })

  it('pillarboxes a portrait stream inside a landscape box', () => {
    const t = transformFor(720, 1280, 640, 480)
    expect(t.drawnHeight).toBe(480)
    expect(t.drawnWidth).toBe(270)
    expect(t.offsetY).toBe(0)
    expect(t.offsetX).toBe((640 - 270) / 2)
  })

  it('is exact for an extreme aspect mismatch', () => {
    const t = transformFor(1000, 100, 200, 200)
    expect(t.drawnWidth).toBe(200)
    expect(t.drawnHeight).toBe(20)
    expect(t.offsetY).toBe(90)
  })

  it('returns null for degenerate inputs rather than dividing by zero', () => {
    expect(computeOverlayTransform(0, 480, 640, 480)).toBeNull()
    expect(computeOverlayTransform(640, 0, 640, 480)).toBeNull()
    expect(computeOverlayTransform(640, 480, 0, 480)).toBeNull()
    expect(computeOverlayTransform(640, 480, 640, 0)).toBeNull()
  })

  it('never stretches: scale is uniform on both axes', () => {
    for (const [vw, vh, ew, eh] of [[1280, 720, 640, 480], [720, 1280, 640, 480], [640, 480, 300, 300], [1080, 1920, 390, 844]]) {
      const t = transformFor(vw, vh, ew, eh)
      expect(t.drawnWidth / vw, `${vw}x${vh}`).toBeCloseTo(t.scale, 10)
      expect(t.drawnHeight / vh, `${vw}x${vh}`).toBeCloseTo(t.scale, 10)
      expect(t.drawnWidth).toBeLessThanOrEqual(ew + 1e-9)
      expect(t.drawnHeight).toBeLessThanOrEqual(eh + 1e-9)
    }
  })
})

describe('point mapping', () => {
  it('sends the video centre to the drawn-video centre', () => {
    const t = transformFor(1280, 720, 640, 480)
    const centre = videoPointToOverlay({ x: 0.5, y: 0.5 }, t)
    expect(centre.x).toBeCloseTo(320, 6)
    expect(centre.y).toBeCloseTo(60 + 180, 6)
  })

  it('mirrors about the video centre, not the element centre', () => {
    const t = transformFor(720, 1280, 640, 480, true)
    const left = videoPointToOverlay({ x: 0, y: 0.5 }, t)
    const right = videoPointToOverlay({ x: 1, y: 0.5 }, t)
    // symmetric about the pillarbox window
    expect(left.x + right.x).toBeCloseTo(2 * (t.offsetX + t.drawnWidth / 2), 6)
    expect(left.x).toBeCloseTo(t.offsetX + t.drawnWidth, 6)
  })

  it('leaves the vertical axis untouched when mirrored', () => {
    const mirrored = transformFor(1280, 720, 640, 480, true)
    const plain = transformFor(1280, 720, 640, 480, false)
    const a = videoPointToOverlay({ x: 0.3, y: 0.17 }, mirrored)
    const b = videoPointToOverlay({ x: 0.7, y: 0.17 }, plain)
    expect(a.x).toBeCloseTo(b.x, 9)
    expect(a.y).toBeCloseTo(b.y, 9)
  })

  it('keeps an off-centre face land in the same displayed place as the video', () => {
    // A face box at 30 % width must appear at 30 % of the drawn video, not 30 %
    // of the element.
    const t = transformFor(1280, 720, 640, 480)
    const p = videoPointToOverlay({ x: 0.3, y: 0.5 }, t)
    expect(p.x).toBeCloseTo(t.offsetX + 0.3 * t.drawnWidth, 9)
  })
})

describe('device pixel ratio', () => {
  it('sizes the backing store in device pixels', () => {
    expect(backingStoreSize(640, 480, 1)).toEqual({ width: 640, height: 480 })
    expect(backingStoreSize(640, 480, 2)).toEqual({ width: 1280, height: 960 })
    expect(backingStoreSize(390, 844, 3)).toEqual({ width: 1170, height: 2532 })
  })

  it('clamps a nonsense ratio instead of producing a huge canvas', () => {
    expect(backingStoreSize(100, 100, 0)).toEqual({ width: 100, height: 100 })
    expect(backingStoreSize(100, 100, Number.NaN)).toEqual({ width: 100, height: 100 })
  })

  it('scales drawing by the device ratio so CSS coordinates stay CSS coordinates', () => {
    const { ctx, calls } = recordingContext()
    const t = computeOverlayTransform(640, 480, 320, 240, { dpr: 2 })!
    const region: OverlayRegion = { roi: 'forehead', polygon: foreheadCorners(L)!, sampled: true }
    drawRoiOverlay(ctx, t, [region])
    const setTransform = calls.find(c => c.op === 'setTransform')
    expect(setTransform!.args).toEqual([2, 0, 0, 2, 0, 0])
    // Every drawn point is within the CSS box, not the doubled backing store.
    for (const call of calls.filter(c => c.op === 'moveTo' || c.op === 'lineTo')) {
      expect(call.args[0]).toBeGreaterThanOrEqual(-1)
      expect(call.args[0]).toBeLessThanOrEqual(321)
      expect(call.args[1]).toBeGreaterThanOrEqual(-1)
      expect(call.args[1]).toBeLessThanOrEqual(241)
    }
  })
})

describe('mirroring policy', () => {
  it('mirrors only a user-facing camera', () => {
    expect(shouldMirror('user')).toBe(true)
    expect(shouldMirror('environment')).toBe(false)
    expect(shouldMirror(undefined)).toBe(false)
    expect(shouldMirror(null)).toBe(false)
  })
})

describe('overlay draws the sampled polygon', () => {
  it('strokes exactly the ROI polygon that was sampled', () => {
    const { ctx, calls } = recordingContext()
    const t = transformFor(640, 480, 640, 480)
    const patch = buildPatch('forehead', L)
    expect(patch.ok).toBe(true)
    if (!patch.ok) return
    drawRoiOverlay(ctx, t, [{ roi: 'forehead', polygon: patch.polygon, sampled: true }])
    const drawn = calls.filter(c => c.op === 'moveTo' || c.op === 'lineTo').map(c => ({ x: c.args[0], y: c.args[1] }))
    expect(drawn).toHaveLength(patch.polygon.length)
    drawn.forEach((p, i) => {
      expect(p.x).toBeCloseTo(patch.polygon[i].x * 640, 6)
      expect(p.y).toBeCloseTo(patch.polygon[i].y * 480, 6)
    })
    // and only the patch is stroked - no bounding box, no second shape
    expect(calls.filter(c => c.op === 'stroke')).toHaveLength(1)
  })

  it('draws each ROI in its own colour', () => {
    const { ctx, calls } = recordingContext()
    const t = transformFor(640, 480, 640, 480)
    const regions: OverlayRegion[] = (['forehead', 'left_cheek', 'right_cheek'] as const).map(roi => ({
      roi,
      polygon: buildPatch(roi, L).ok ? (buildPatch(roi, L) as { ok: true; polygon: Point[] }).polygon : [],
      sampled: true,
    }))
    drawRoiOverlay(ctx, t, regions)
    expect(calls.filter(c => c.op === 'stroke')).toHaveLength(3)
    expect(new Set(Object.values(ROI_COLORS)).size).toBe(3)
  })

  it('marks a lost face with a cross instead of stale outlines', () => {
    const { ctx, calls } = recordingContext()
    const t = transformFor(640, 480, 640, 480)
    drawRoiOverlay(ctx, t, [], { lost: true })
    const lines = calls.filter(c => c.op === 'moveTo' || c.op === 'lineTo')
    // Two diagonals = four endpoints, no ROI polygon traced.
    expect(lines).toHaveLength(4)
    expect(calls.filter(c => c.op === 'stroke')).toHaveLength(1)
  })

  it('skips a region whose polygon could not be built', () => {
    const { ctx, calls } = recordingContext()
    const t = transformFor(640, 480, 640, 480)
    drawRoiOverlay(ctx, t, [{ roi: 'forehead', polygon: [], sampled: false }])
    expect(calls.filter(c => c.op === 'stroke')).toHaveLength(0)
  })
})

describe('overlay state legend', () => {
  it('distinguishes lost face from found face with unusable regions', () => {
    expect(overlayState(0, false)).toBe('no_face')
    expect(overlayState(0, true)).toBe('no_rois')
    expect(overlayState(1, true)).toBe('partial')
    expect(overlayState(3, true)).toBe('all')
  })
})

describe('portrait and landscape alignment', () => {
  const cases: Array<[string, number, number, number, number]> = [
    ['portrait phone, portrait container', 720, 1280, 390, 520],
    ['portrait phone, landscape container', 720, 1280, 640, 480],
    ['landscape phone, portrait container', 1280, 720, 390, 520],
    ['landscape phone, landscape container', 1280, 720, 640, 480],
  ]
  for (const [label, vw, vh, ew, eh] of cases) {
    it(`${label}: the forehead overlay lands in the upper half and inside the frame`, () => {
      const t = transformFor(vw, vh, ew, eh)
      const patch = foreheadCorners(L)!
      const drawn = patch.map(p => videoPointToOverlay(p, t))
      // inside the letterboxed window
      for (const p of drawn) {
        expect(p.x).toBeGreaterThanOrEqual(t.offsetX - 1e-9)
        expect(p.x).toBeLessThanOrEqual(t.offsetX + t.drawnWidth + 1e-9)
        expect(p.y).toBeGreaterThanOrEqual(t.offsetY - 1e-9)
        expect(p.y).toBeLessThanOrEqual(t.offsetY + t.drawnHeight + 1e-9)
      }
      // upper part of the drawn video
      const centreY = t.offsetY + t.drawnHeight / 2
      expect(Math.max(...drawn.map(p => p.y))).toBeLessThan(centreY)
    })
  }

  it('preserves relative distance between two ROIs under every container', () => {
    // The cheek-to-cheek separation must scale with the same factor as the frame;
    // if the overlay stretched on one axis, this ratio would drift.
    const left = { x: 0.2, y: 0.5 }
    const right = { x: 0.8, y: 0.5 }
    for (const [vw, vh, ew, eh] of [[640, 480, 640, 480], [1280, 720, 640, 480], [720, 1280, 390, 520]]) {
      const t = transformFor(vw, vh, ew, eh)
      const a = videoPointToOverlay(left, t)
      const b = videoPointToOverlay(right, t)
      expect(b.x - a.x).toBeCloseTo(0.6 * t.drawnWidth, 6)
    }
  })
})
