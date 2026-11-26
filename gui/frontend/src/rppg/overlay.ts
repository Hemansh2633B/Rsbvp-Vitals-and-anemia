/**
 * Overlay geometry: map normalised ROI polygons onto the *displayed* video.
 *
 * WHY THIS IS A MODULE
 * --------------------
 * The overlay canvas was sized to the video element's CSS box and drawn with
 * `x * videoWidth`, `y * videoHeight`. That is only correct when the video is
 * displayed at exactly its intrinsic aspect ratio with no letterboxing. In
 * practice:
 *
 *  - the preview sits in a container with a fixed `aspect-ratio: 4/3` and
 *    `object-fit: contain`, so a 640x480 stream (4:3) fits, but a modern phone
 *    delivers 1280x720 (16:9) or portrait 720x1280 (9:16) - both letterboxed,
 *    so every polygon was drawn offset and scaled by the wrong factor;
 *  - the overlay canvas has no width/height attributes in React, so its backing
 *    store defaults to 300x150 and is then stretched by CSS, blurring and
 *    distorting the outlines further;
 *  - front cameras are commonly mirrored by the browser (or by CSS), so a
 *    correct-in-image-space polygon appears on the wrong cheek.
 *
 * `computeOverlayTransform` returns exactly the mapping needed, and
 * `drawRoiOverlay` uses it. Both are testable without a camera because they are
 * pure functions of the frame size, the element size and the flip flag.
 */

import type { Point } from './roiGeometry'

export type OverlayTransform = {
  /** Scale from video pixels to CSS pixels (uniform, from object-fit: contain). */
  scale: number
  /** Letterbox offset in CSS pixels: left edge of the drawn video. */
  offsetX: number
  /** Letterbox offset in CSS pixels: top edge of the drawn video. */
  offsetY: number
  /** Device-pixel ratio used for the canvas backing store. */
  dpr: number
  /** Width/height of the drawn video in CSS pixels. */
  drawnWidth: number
  drawnHeight: number
  /** True when a horizontal flip is applied (front camera mirroring). */
  mirrored: boolean
}

/**
 * Compute the mapping from video pixel space to overlay CSS space.
 *
 * `object-fit: contain` scales the video uniformly to fit inside the element and
 * centres it, leaving letterbox bars on the excess axis. The overlay must use the
 * same mapping, or the drawn ROI will not sit on the pixels it describes.
 */
export function computeOverlayTransform(
  videoWidth: number,
  videoHeight: number,
  elementWidth: number,
  elementHeight: number,
  options: { mirrored?: boolean; dpr?: number } = {},
): OverlayTransform | null {
  if (!(videoWidth > 0) || !(videoHeight > 0) || !(elementWidth > 0) || !(elementHeight > 0)) return null
  const scale = Math.min(elementWidth / videoWidth, elementHeight / videoHeight)
  const drawnWidth = videoWidth * scale
  const drawnHeight = videoHeight * scale
  return {
    scale,
    offsetX: (elementWidth - drawnWidth) / 2,
    offsetY: (elementHeight - drawnHeight) / 2,
    dpr: Math.max(1, options.dpr ?? 1),
    drawnWidth,
    drawnHeight,
    mirrored: Boolean(options.mirrored),
  }
}

/** Map a normalised video coordinate to CSS pixels in the overlay element. */
export function videoPointToOverlay(point: Point, transform: OverlayTransform): Point {
  // Mirroring is applied about the *video's* horizontal centre, not the
  // element's, so a letterboxed portrait stream mirrors correctly.
  const x = transform.mirrored ? 1 - point.x : point.x
  return {
    x: transform.offsetX + x * transform.drawnWidth,
    y: transform.offsetY + point.y * transform.drawnHeight,
  }
}

/** Canvas backing-store size for a given CSS box, accounting for device pixels. */
export function backingStoreSize(elementWidth: number, elementHeight: number, dpr: number) {
  // Guard explicitly: Math.max(1, NaN) is NaN, which would propagate into the
  // canvas dimensions and blank the overlay.
  const ratio = Number.isFinite(dpr) && dpr > 0 ? Math.max(1, dpr) : 1
  return { width: Math.round(elementWidth * ratio), height: Math.round(elementHeight * ratio) }
}

/** Colours per ROI: distinct, and consistent between the overlay and the cards. */
export const ROI_COLORS: Record<string, string> = {
  forehead: '#58dfba',
  left_cheek: '#5aa9ff',
  right_cheek: '#c78bff',
}

/** Colour used when a region is tracked but produced no usable sample. */
export const ROI_INVALID_COLOR = '#ffb547'
/** Colour used when the face itself was lost. */
export const ROI_LOST_COLOR = '#ff6b6b'

export type OverlayRegion = {
  roi: string
  /** Sampled polygon in normalised video coordinates. */
  polygon: Point[]
  /** Exclusion masks in normalised video coordinates. */
  masks?: Point[][]
  /** True when this region contributed a sample this frame. */
  sampled: boolean
  /** Bounding box of accepted pixels in normalised coordinates, when known. */
  acceptedBox?: { x0: number; y0: number; x1: number; y1: number } | null
}

/**
 * Draw the ROI overlay.
 *
 * Draws, in order: the excluded feature masks (hatched outline), the accepted
 * pixel box (a faint fill showing which pixels actually contributed), then the
 * ROI boundary. The boundary is the actual sampled polygon - the same points
 * passed to `extractRoi` - so what is drawn is what was measured.
 */
export function drawRoiOverlay(
  ctx: CanvasRenderingContext2D,
  transform: OverlayTransform,
  regions: OverlayRegion[],
  options: { lost?: boolean } = {},
): void {
  ctx.save()
  // Work in CSS pixels regardless of the backing store's device-pixel scale.
  ctx.setTransform(transform.dpr, 0, 0, transform.dpr, 0, 0)
  ctx.clearRect(0, 0, transform.offsetX * 2 + transform.drawnWidth, transform.offsetY * 2 + transform.drawnHeight)

  if (options.lost) {
    ctx.strokeStyle = ROI_LOST_COLOR
    ctx.lineWidth = 2
    ctx.setLineDash([8, 6])
    const p0 = { x: transform.offsetX, y: transform.offsetY }
    const p1 = { x: transform.offsetX + transform.drawnWidth, y: transform.offsetY + transform.drawnHeight }
    ctx.beginPath()
    ctx.moveTo(p0.x, p0.y)
    ctx.lineTo(p1.x, p1.y)
    ctx.moveTo(p1.x, p0.y)
    ctx.lineTo(p0.x, p1.y)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.restore()
    return
  }

  for (const region of regions) {
    const colour = region.sampled ? (ROI_COLORS[region.roi] ?? '#58dfba') : ROI_INVALID_COLOR
    if (region.polygon.length < 3) continue

    // 1. Accepted pixel area: a faint fill so the operator can see which pixels
    //    actually contributed to the mean, not just the geometric outline.
    if (region.sampled && region.acceptedBox) {
      const a = videoPointToOverlay({ x: region.acceptedBox.x0, y: region.acceptedBox.y0 }, transform)
      const b = videoPointToOverlay({ x: region.acceptedBox.x1, y: region.acceptedBox.y1 }, transform)
      ctx.fillStyle = colour
      ctx.globalAlpha = 0.12
      ctx.fillRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y))
      ctx.globalAlpha = 1
    }

    // 2. Excluded facial features, dashed, so an overlap is visible rather than
    //    implied.
    if (region.masks?.length) {
      ctx.strokeStyle = 'rgba(255, 107, 107, 0.55)'
      ctx.lineWidth = 1
      ctx.setLineDash([3, 3])
      for (const mask of region.masks) {
        if (mask.length < 3) continue
        tracePath(ctx, mask, transform)
        ctx.stroke()
      }
      ctx.setLineDash([])
    }

    // 3. The ROI boundary itself.
    ctx.strokeStyle = colour
    ctx.lineWidth = 2
    tracePath(ctx, region.polygon, transform)
    ctx.stroke()
  }
  ctx.restore()
}

function tracePath(ctx: CanvasRenderingContext2D, polygon: Point[], transform: OverlayTransform): void {
  const first = videoPointToOverlay(polygon[0], transform)
  ctx.beginPath()
  ctx.moveTo(first.x, first.y)
  for (let i = 1; i < polygon.length; i += 1) {
    const p = videoPointToOverlay(polygon[i], transform)
    ctx.lineTo(p.x, p.y)
  }
  ctx.closePath()
}

/**
 * Whether the browser is likely mirroring the preview.
 *
 * A front-facing camera gives the user a mirror view by convention, but the
 * *pixels* fed to the landmarker are not mirrored. The overlay therefore needs
 * the same flip as the displayed video. We derive it from the track settings
 * rather than assuming, because a rear camera must not be flipped.
 */
export function shouldMirror(facingMode: string | undefined | null): boolean {
  return facingMode === 'user'
}

/**
 * Human-readable state for the overlay legend.
 *
 * Deliberately distinguishes "face found, region not sampleable" from "face
 * lost": the first is a geometry/lighting problem the operator can act on, the
 * second is a framing problem.
 */
export type OverlayState = 'no_face' | 'no_rois' | 'partial' | 'all'
export function overlayState(sampledCount: number, faceDetected: boolean): OverlayState {
  if (!faceDetected) return 'no_face'
  if (sampledCount === 0) return 'no_rois'
  if (sampledCount < 3) return 'partial'
  return 'all'
}
