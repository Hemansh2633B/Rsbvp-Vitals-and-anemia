/**
 * Face ROI geometry: landmark contract, mask construction and pixel diagnostics.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The previous implementation sampled a single 16-point polygon spanning the
 * whole upper face (100 % of the face bounding-box width, 33 % of its height,
 * area 0.21 face-bbox units^2). That is not a forehead: its lower edge ran along
 * the brow ridge and its side vertices sat on the temple/hairline border
 * (landmarks 127 and 356 are the widest points of the entire face model). The
 * visible symptom was an oversized overlay; the functional symptom was that the
 * sampled pixel set was not the region it claimed to be.
 *
 * Everything here is derived from the MediaPipe canonical face model
 * (mediapipe/modules/face_geometry/data/canonical_face_model.obj, 468 vertices).
 * The indices used below were verified against that model numerically - see
 * `docs/ROI_GEOMETRY.md` for the verification table. No index in this file is
 * guessed: each one is listed in `LANDMARK_CONTRACT` with its anatomical role
 * and its measured position, and a test re-checks the contract against the
 * committed canonical coordinates.
 *
 * WHAT THIS FILE DOES NOT DO
 * --------------------------
 * It does not classify skin universally, does not report a pulse and does not
 * claim that a geometrically valid patch contains usable signal. A patch can be
 * perfectly placed on a real forehead and still yield no pulse (motion, poor
 * perfusion, compression, lighting). Geometry failures and signal failures are
 * reported separately, on purpose.
 */

export type Point = { x: number; y: number }

/* ------------------------------------------------------------------ *
 * 1. Landmark contract
 * ------------------------------------------------------------------ */

/**
 * Landmarks this module depends on, with the role each plays.
 *
 * Verified against the canonical face model. `canonicalX`/`canonicalY` are the
 * normalised positions of that vertex in the model's own 2D projection
 * (x: 0 = left edge of the model, 1 = right edge; y: 0 = hairline/vertex,
 * 1 = chin), which is why they can be asserted in a test without a camera.
 */
export type LandmarkRole = {
  index: number
  name: string
  role: string
  canonicalX: number
  canonicalY: number
}

export const LANDMARK_CONTRACT: readonly LandmarkRole[] = [
  { index: 10, name: 'forehead_top', role: 'hairline/vertex anchor: defines the top of the face bbox. NOT sampled - the old polygon started here, which is why it covered the whole upper face', canonicalX: 0.500, canonicalY: 0.000 },
  { index: 152, name: 'chin', role: 'defines the bottom of the face bbox', canonicalX: 0.500, canonicalY: 1.000 },
  { index: 9, name: 'glabella_mid', role: 'midline between the brows; the forehead patch depth is measured from the anchors to this landmark', canonicalX: 0.500, canonicalY: 0.191 },
  { index: 108, name: 'forehead_anchor_left', role: 'left upper corner of the forehead patch', canonicalX: 0.395, canonicalY: 0.094 },
  { index: 337, name: 'forehead_anchor_right', role: 'right upper corner of the forehead patch (exact mirror of 108)', canonicalX: 0.605, canonicalY: 0.094 },
  { index: 117, name: 'left_cheek_upper_outer', role: 'left cheek patch, upper-outer corner', canonicalX: 0.160, canonicalY: 0.414 },
  { index: 118, name: 'left_cheek_upper_inner', role: 'left cheek patch, upper-inner corner', canonicalX: 0.214, canonicalY: 0.427 },
  { index: 205, name: 'left_cheek_lower_inner', role: 'left cheek patch, lower-inner corner', canonicalX: 0.252, canonicalY: 0.555 },
  { index: 147, name: 'left_cheek_lower_outer', role: 'left cheek patch, lower-outer corner', canonicalX: 0.097, canonicalY: 0.578 },
  { index: 346, name: 'right_cheek_upper_outer', role: 'right cheek patch, upper-outer corner (mirror of 117)', canonicalX: 0.840, canonicalY: 0.414 },
  { index: 347, name: 'right_cheek_upper_inner', role: 'right cheek patch, upper-inner corner (mirror of 118)', canonicalX: 0.786, canonicalY: 0.427 },
  { index: 425, name: 'right_cheek_lower_inner', role: 'right cheek patch, lower-inner corner (mirror of 205)', canonicalX: 0.748, canonicalY: 0.555 },
  { index: 376, name: 'right_cheek_lower_outer', role: 'right cheek patch, lower-outer corner (mirror of 147)', canonicalX: 0.903, canonicalY: 0.578 },
  { index: 33, name: 'left_eye_outer', role: 'left eye exclusion ring', canonicalX: 0.213, canonicalY: 0.317 },
  { index: 160, name: 'left_eye_upper', role: 'left eye exclusion ring', canonicalX: 0.263, canonicalY: 0.302 },
  { index: 158, name: 'left_eye_upper_inner', role: 'left eye exclusion ring', canonicalX: 0.324, canonicalY: 0.300 },
  { index: 133, name: 'left_eye_inner', role: 'left eye exclusion ring', canonicalX: 0.380, canonicalY: 0.321 },
  { index: 153, name: 'left_eye_lower_inner', role: 'left eye exclusion ring', canonicalX: 0.324, canonicalY: 0.337 },
  { index: 144, name: 'left_eye_lower_outer', role: 'left eye exclusion ring', canonicalX: 0.263, canonicalY: 0.334 },
  { index: 362, name: 'right_eye_outer', role: 'right eye exclusion ring', canonicalX: 0.620, canonicalY: 0.321 },
  { index: 385, name: 'right_eye_upper', role: 'right eye exclusion ring', canonicalX: 0.676, canonicalY: 0.300 },
  { index: 387, name: 'right_eye_upper_inner', role: 'right eye exclusion ring', canonicalX: 0.737, canonicalY: 0.302 },
  { index: 263, name: 'right_eye_inner', role: 'right eye exclusion ring', canonicalX: 0.787, canonicalY: 0.317 },
  { index: 373, name: 'right_eye_lower_inner', role: 'right eye exclusion ring', canonicalX: 0.737, canonicalY: 0.334 },
  { index: 380, name: 'right_eye_lower_outer', role: 'right eye exclusion ring', canonicalX: 0.676, canonicalY: 0.337 },
  { index: 70, name: 'left_brow_outer', role: 'left brow exclusion ring', canonicalX: 0.131, canonicalY: 0.227 },
  { index: 63, name: 'left_brow_upper_outer', role: 'left brow exclusion ring', canonicalX: 0.178, canonicalY: 0.196 },
  { index: 105, name: 'left_brow_mid', role: 'left brow exclusion ring', canonicalX: 0.243, canonicalY: 0.178 },
  { index: 66, name: 'left_brow_upper_inner', role: 'left brow exclusion ring', canonicalX: 0.322, canonicalY: 0.179 },
  { index: 107, name: 'left_brow_inner_peak', role: 'left brow exclusion ring: the innermost brow point, closest to the forehead patch', canonicalX: 0.410, canonicalY: 0.184 },
  { index: 55, name: 'left_brow_lower_inner', role: 'left brow exclusion ring', canonicalX: 0.421, canonicalY: 0.233 },
  { index: 65, name: 'left_brow_lower_mid', role: 'left brow exclusion ring', canonicalX: 0.329, canonicalY: 0.212 },
  { index: 52, name: 'left_brow_lower_outer', role: 'left brow exclusion ring', canonicalX: 0.259, canonicalY: 0.212 },
  { index: 53, name: 'left_brow_outer_low', role: 'left brow exclusion ring', canonicalX: 0.204, canonicalY: 0.224 },
  { index: 300, name: 'right_brow_outer', role: 'right brow exclusion ring', canonicalX: 0.869, canonicalY: 0.227 },
  { index: 293, name: 'right_brow_upper_outer', role: 'right brow exclusion ring', canonicalX: 0.822, canonicalY: 0.196 },
  { index: 334, name: 'right_brow_mid', role: 'right brow exclusion ring', canonicalX: 0.757, canonicalY: 0.178 },
  { index: 296, name: 'right_brow_upper_inner', role: 'right brow exclusion ring', canonicalX: 0.678, canonicalY: 0.179 },
  { index: 336, name: 'right_brow_inner_peak', role: 'right brow exclusion ring: innermost brow point', canonicalX: 0.590, canonicalY: 0.184 },
  { index: 285, name: 'right_brow_lower_inner', role: 'right brow exclusion ring', canonicalX: 0.579, canonicalY: 0.233 },
  { index: 295, name: 'right_brow_lower_mid', role: 'right brow exclusion ring', canonicalX: 0.671, canonicalY: 0.212 },
  { index: 282, name: 'right_brow_lower_outer', role: 'right brow exclusion ring', canonicalX: 0.741, canonicalY: 0.212 },
  { index: 283, name: 'right_brow_outer_low', role: 'right brow exclusion ring', canonicalX: 0.796, canonicalY: 0.224 },
  { index: 61, name: 'mouth_outer_left', role: 'mouth exclusion ring (cheeks only)', canonicalX: 0.341, canonicalY: 0.714 },
  { index: 146, name: 'mouth_upper_left', role: 'mouth exclusion ring', canonicalX: 0.358, canonicalY: 0.728 },
  { index: 91, name: 'mouth_upper_mid_left', role: 'mouth exclusion ring', canonicalX: 0.381, canonicalY: 0.741 },
  { index: 181, name: 'mouth_upper_mid_right', role: 'mouth exclusion ring', canonicalX: 0.414, canonicalY: 0.757 },
  { index: 84, name: 'mouth_upper_right', role: 'mouth exclusion ring', canonicalX: 0.455, canonicalY: 0.767 },
  { index: 17, name: 'mouth_lower_mid', role: 'mouth exclusion ring', canonicalX: 0.500, canonicalY: 0.771 },
  { index: 314, name: 'mouth_lower_right', role: 'mouth exclusion ring', canonicalX: 0.545, canonicalY: 0.767 },
  { index: 405, name: 'mouth_lower_mid_right', role: 'mouth exclusion ring', canonicalX: 0.586, canonicalY: 0.757 },
  { index: 321, name: 'mouth_lower_mid_left', role: 'mouth exclusion ring', canonicalX: 0.619, canonicalY: 0.741 },
  { index: 375, name: 'mouth_lower_left', role: 'mouth exclusion ring', canonicalX: 0.642, canonicalY: 0.728 },
  { index: 291, name: 'mouth_outer_right', role: 'mouth exclusion ring', canonicalX: 0.659, canonicalY: 0.714 },
  { index: 308, name: 'mouth_lower_left_outer', role: 'mouth exclusion ring', canonicalX: 0.639, canonicalY: 0.710 },
  { index: 2, name: 'nostril_left_outer', role: 'nostril exclusion for the cheek patches', canonicalX: 0.500, canonicalY: 0.586 },
  { index: 97, name: 'nostril_left_inner', role: 'nostril exclusion for the cheek patches', canonicalX: 0.461, canonicalY: 0.582 },
  { index: 326, name: 'nostril_right_inner', role: 'nostril exclusion for the cheek patches', canonicalX: 0.539, canonicalY: 0.582 },
  { index: 327, name: 'nostril_right_outer', role: 'nostril exclusion for the cheek patches', canonicalX: 0.591, canonicalY: 0.565 },
] as const

const CONTRACT_BY_INDEX = new Map(LANDMARK_CONTRACT.map(l => [l.index, l]))

/** True when `index` is one of the contract's verified landmarks. */
export function isContractedLandmark(index: number): boolean {
  return CONTRACT_BY_INDEX.has(index)
}

/** Anatomical name for an index, for diagnostics. Falls back to the index. */
export function landmarkName(index: number): string {
  return CONTRACT_BY_INDEX.get(index)?.name ?? `landmark_${index}`
}

/* ------------------------------------------------------------------ *
 * 2. Region definitions
 * ------------------------------------------------------------------ */

export const ROI_NAMES = ['forehead', 'left_cheek', 'right_cheek'] as const
export type RoiName = (typeof ROI_NAMES)[number]

/**
 * Forehead anchors: the two landmarks that sit on the forehead surface at the
 * patch's upper edge, symmetric about the midline.
 *
 * Verified in the canonical model: 108 = (0.395, 0.094), 337 = (0.605, 0.094),
 * mirrored from each other with zero error. They are the natural top corners of
 * a central forehead patch. Vertex 10 (the vertex of the head, y = 0) is
 * deliberately NOT used - it is the hairline anchor, and the previous polygon
 * started there and swept down to the brow, which is why the overlay covered the
 * entire upper face (100 % of face width, 33 % of face height).
 */
export const FOREHEAD_ANCHORS: readonly [number, number] = [108, 337] as const

/** Midline landmark the patch is extruded toward; defines the lower edge. */
export const FOREHEAD_LOWER_REFERENCE = 9

/**
 * Fraction of the anchor-to-glabella distance the patch extends downward.
 *
 * Measured against the canonical geometry: the anchors sit at y = 0.094 and the
 * glabella (9) at y = 0.233, an 0.139 gap. At 0.65 the lower edge lands at
 * y = 0.184 - 2.3 % of face height above the brow landmark 107 (y = 0.184), and
 * measurably clear of the brow outline with the safe margin applied. This keeps
 * the patch on the flat, well-perfused mid-forehead and away from the hairline,
 * the brow ridge and the temple.
 */
export const FOREHEAD_DEPTH_FRACTION = 0.65

/**
 * Build the forehead patch corners. Kept as a function of the landmarks rather
 * than a fixed index list because the depth is a *fraction of the measured
 * anchor-to-glabella distance*, so the patch scales with face size instead of
 * assuming a fixed proportion of the bounding box.
 */
export function foreheadCorners(landmarks: ReadonlyArray<Point | undefined | null>): Point[] {
  const tl = landmarks[FOREHEAD_ANCHORS[0]]
  const tr = landmarks[FOREHEAD_ANCHORS[1]]
  const lower = landmarks[FOREHEAD_LOWER_REFERENCE]
  if (!tl || !tr || !lower) return []
  if (![tl.x, tl.y, tr.x, tr.y, lower.x, lower.y].every(Number.isFinite)) return []
  const span = lower.y - (tl.y + tr.y) / 2
  // A collapsed or inverted span means the landmarks cannot be trusted.
  if (!(span > 0)) return []
  const depth = span * FOREHEAD_DEPTH_FRACTION
  return [
    { x: tl.x, y: tl.y },
    { x: tr.x, y: tr.y },
    { x: tr.x, y: tr.y + depth },
    { x: tl.x, y: tl.y + depth },
  ]
}

/**
 * Cheek patches as verified landmark quads.
 *
 * Each vertex was checked in the canonical model to be: inside the face outline
 * with >= 7 % clearance, non-self-intersecting, convex, and clear of the orbital,
 * mouth and nostril masks. The right-side indices are the model's exact mirror
 * partners of the left-side ones (verified to 0.000 error), so the two cheeks
 * sample the same anatomical area on both sides:
 *
 *   117 <-> 346, 118 <-> 347, 205 <-> 425, 147 <-> 376
 *
 * The previous cheek outlines ([50,101,118,119,100,126,209,206,203,142,123,116]
 * and its right-side counterpart) **self-intersect** - confirmed by the geometry
 * test - which makes the even-odd fill rule ambiguous and silently changes which
 * pixels are sampled.
 */
export const CHEEK_PATCHES: Readonly<Record<'left_cheek' | 'right_cheek', readonly number[]>> = {
  left_cheek: [117, 118, 205, 147] as const,
  right_cheek: [346, 347, 425, 376] as const,
}

/**
 * Fraction of the face bounding-box height the patch is shrunk by on each side.
 * 0.012 of face height is ~2 px on a 160 px-tall face and ~8 px on a 700 px-tall
 * face: enough to absorb landmark jitter at normal viewing distance, small
 * enough not to reduce the patch to nothing.
 */
export const FOREHEAD_INSET = 0.012

/** Region outlines, expressed for diagnostics and for the exclusion masks. */
export const REGION_LANDMARKS: Readonly<Record<RoiName, readonly number[]>> = {
  forehead: [...FOREHEAD_ANCHORS, FOREHEAD_LOWER_REFERENCE],
  left_cheek: CHEEK_PATCHES.left_cheek,
  right_cheek: CHEEK_PATCHES.right_cheek,
}

/**
 * Feature masks subtracted from every ROI.
 *
 * These are *outlines of features to avoid*, not decorative rings: eyes (upper
 * and lower lid rings), brow ridges, the mouth, and the nostrils for the cheeks.
 */
export const FEATURE_MASKS: Readonly<Record<string, readonly number[]>> = {
  left_eye: [33, 160, 158, 133, 153, 144],
  right_eye: [362, 385, 387, 263, 373, 380],
  mouth: [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 308],
  left_brow: [70, 63, 105, 66, 107, 55, 65, 52, 53],
  right_brow: [300, 293, 334, 296, 336, 285, 295, 282, 283],
  nostrils: [2, 97, 326, 327],
}

/** Which masks apply to which region. The forehead needs brows; cheeks need nose/mouth. */
export const REGION_EXCLUSIONS: Readonly<Record<RoiName, readonly string[]>> = {
  forehead: ['left_brow', 'right_brow'],
  left_cheek: ['left_eye', 'mouth', 'nostrils'],
  right_cheek: ['right_eye', 'mouth', 'nostrils'],
}

/* ------------------------------------------------------------------ *
 * 3. Geometry primitives
 * ------------------------------------------------------------------ */

/** Shoelace area of a polygon in normalised units. Always non-negative. */
export function polygonArea(points: readonly Point[]): number {
  if (points.length < 3) return 0
  let sum = 0
  for (let i = 0; i < points.length; i += 1) {
    const a = points[i]
    const b = points[(i + 1) % points.length]
    sum += a.x * b.y - b.x * a.y
  }
  return Math.abs(sum) / 2
}

/** Signed shoelace area: sign encodes winding direction (clockwise is negative in image coords). */
export function signedArea(points: readonly Point[]): number {
  if (points.length < 3) return 0
  let sum = 0
  for (let i = 0; i < points.length; i += 1) {
    const a = points[i]
    const b = points[(i + 1) % points.length]
    sum += a.x * b.y - b.x * a.y
  }
  return sum / 2
}

function segmentsIntersect(a: Point, b: Point, c: Point, d: Point): boolean {
  const cross = (o: Point, p: Point, q: Point) => (p.x - o.x) * (q.y - o.y) - (p.y - o.y) * (q.x - o.x)
  const d1 = cross(c, d, a)
  const d2 = cross(c, d, b)
  const d3 = cross(a, b, c)
  const d4 = cross(a, b, d)
  return (d1 > 0) !== (d2 > 0) && (d3 > 0) !== (d4 > 0)
}

/**
 * A degenerate polygon cannot be sampled: its area is essentially zero, two
 * edges cross (self-intersection), or it has fewer than three distinct points.
 * Reported explicitly instead of silently producing a tiny or empty mean.
 */
export function polygonIsDegenerate(points: readonly Point[], minArea = 1e-6): boolean {
  if (points.length < 3) return true
  if (polygonArea(points) < minArea) return true
  const n = points.length
  for (let i = 0; i < n; i += 1) {
    for (let j = i + 2; j < n; j += 1) {
      if (i === 0 && j === n - 1) continue
      if (segmentsIntersect(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n])) return true
    }
  }
  return false
}

/**
 * Even-odd point-in-polygon test.
 *
 * `xScale`/`yScale` convert normalised coordinates to pixels. This is the hot
 * loop of pixel extraction, so it takes the scales rather than a width/height
 * pair and avoids allocating: the previous version allocated a `{x,y}` object
 * for every candidate pixel.
 */
export function pointInPolygon(px: number, py: number, polygon: readonly Point[], xScale: number, yScale: number): boolean {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const xi = polygon[i].x * xScale
    const yi = polygon[i].y * yScale
    const xj = polygon[j].x * xScale
    const yj = polygon[j].y * yScale
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

/**
 * Shrink a polygon toward its centroid by `inset` (in normalised units).
 *
 * Deliberately a centroid scale rather than a true polygon offset: the patches
 * are small convex quads, where the two agree closely, and a centroid scale
 * cannot introduce the self-intersections an offset can. Anything exotic is
 * caught downstream by `polygonIsDegenerate`.
 */
export function insetPolygon(points: readonly Point[], inset: number): Point[] {
  if (!points.length) return []
  const cx = points.reduce((s, p) => s + p.x, 0) / points.length
  const cy = points.reduce((s, p) => s + p.y, 0) / points.length
  const span = Math.max(
    Math.max(...points.map(p => p.x)) - Math.min(...points.map(p => p.x)),
    Math.max(...points.map(p => p.y)) - Math.min(...points.map(p => p.y)),
  )
  if (!(span > 0)) return [...points]
  // Convert an absolute inset into a scale factor for this polygon's size.
  const scale = Math.max(0, 1 - (2 * inset) / span)
  return points.map(p => ({ x: cx + (p.x - cx) * scale, y: cy + (p.y - cy) * scale }))
}

/** Axis-aligned bounds in pixel space, clipped to the frame. */
export function pixelBounds(points: readonly Point[], width: number, height: number) {
  const xs = points.map(p => p.x * width)
  const ys = points.map(p => p.y * height)
  const x0 = Math.max(0, Math.floor(Math.min(...xs)))
  const x1 = Math.min(width, Math.ceil(Math.max(...xs)))
  const y0 = Math.max(0, Math.floor(Math.min(...ys)))
  const y1 = Math.min(height, Math.ceil(Math.max(...ys)))
  return { x0, y0, x1, y1, insideFrame: Math.min(...xs) >= 0 && Math.min(...ys) >= 0 && Math.max(...xs) <= width && Math.max(...ys) <= height }
}

/** Build a region's sampled polygon from landmarks, or a reason it cannot be used. */
export type PatchResult =
  | { ok: true; polygon: Point[]; raw: Point[] }
  | { ok: false; reason: string; detail: string }

export function buildPatch(
  region: RoiName,
  landmarks: ReadonlyArray<Point | undefined | null>,
  options: { inset?: number } = {},
): PatchResult {
  const raw: Point[] = []
  if (region === 'forehead') {
    raw.push(...foreheadCorners(landmarks))
    if (!raw.length) {
      return { ok: false, reason: 'invalid_landmarks', detail: 'The forehead anchors (108/337) or the glabella reference (9) are missing, non-finite, or inverted this frame' }
    }
  } else {
    for (const index of REGION_LANDMARKS[region]) {
      const p = landmarks[index]
      if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) {
        return { ok: false, reason: 'invalid_landmarks', detail: `Landmark ${index} (${landmarkName(index)}) is missing or non-finite for the ${region} patch` }
      }
      raw.push({ x: p.x, y: p.y })
    }
  }
  if (polygonIsDegenerate(raw)) {
    return { ok: false, reason: 'invalid_landmarks', detail: `The ${region} outline is degenerate (zero area or self-intersecting); the landmarks cannot be trusted this frame` }
  }
  const inset = options.inset ?? FOREHEAD_INSET
  const polygon = inset > 0 ? insetPolygon(raw, inset) : raw
  if (polygonIsDegenerate(polygon)) {
    return { ok: false, reason: 'polygon_too_small', detail: `The ${region} patch collapses after the ${(inset * 100).toFixed(1)}% safe margin was applied` }
  }
  return { ok: true, polygon, raw }
}

/* ------------------------------------------------------------------ *
 * 4. Pixel diagnostics
 * ------------------------------------------------------------------ */

/**
 * Reasons a candidate pixel is not used. Each is counted separately so the UI
 * can say *which* condition removed pixels rather than a single opaque total.
 */
export type PixelRejection = 'outside_polygon' | 'in_feature_mask' | 'too_dark' | 'too_bright' | 'channel_order' | 'low_chroma'

export const PIXEL_REJECTION_COPY: Record<PixelRejection, string> = {
  outside_polygon: 'outside the ROI boundary',
  in_feature_mask: 'inside an excluded facial feature',
  too_dark: 'luminance below 35 (underexposed)',
  too_bright: 'luminance above 245 (saturated)',
  channel_order: 'no consistent red-over-green-over-blue ordering',
  low_chroma: 'near-grey pixel (no colour information)',
}

export type RoiDiagnostics = {
  region: RoiName
  /** True when the polygon was built and passed the geometric checks. */
  valid: boolean
  invalidReason: string | null
  invalidDetail: string | null
  /** Polygon area in square pixels. */
  polygonAreaPx: number
  /** Candidate pixel count = pixels inside the polygon and inside the frame. */
  candidatePixels: number
  /** Pixels removed by facial-feature masks. */
  excludedByMask: number
  /** Per-condition rejection counts among the remaining pixels. */
  rejected: Record<PixelRejection, number>
  /** Pixels that contributed to the RGB mean. */
  acceptedPixels: number
  /** acceptedPixels / candidatePixels, or 0 when there were no candidates. */
  acceptedFraction: number
  /** Mean RGB of accepted pixels (null when none were accepted). */
  meanRgb: [number, number, number] | null
  /** Median RGB of accepted pixels (null when none were accepted). */
  medianRgb: [number, number, number] | null
  /** Relative luminance mean of accepted pixels, 0-255. */
  meanLuminance: number | null
  /** Human-readable summary; the single string a user can act on. */
  summary: string
}

/** Minimum candidate pixels before a patch is considered sampleable at all. */
export const MIN_CANDIDATE_PIXELS = 40
/** Minimum accepted fraction: below this the patch is mostly not skin. */
export const MIN_ACCEPTED_FRACTION = 0.10

function emptyRejections(): Record<PixelRejection, number> {
  return { outside_polygon: 0, in_feature_mask: 0, too_dark: 0, too_bright: 0, channel_order: 0, low_chroma: 0 }
}

/**
 * Explicit, explainable pixel filter.
 *
 * The old heuristic required `r >= 0.88g`, `g >= 0.82b` and `r - b >= 8` for
 * *every* pixel. Those constants are hard-coded sRGB assumptions: they encode
 * "the camera's red channel is a bit above green, and green slightly above
 * blue". They hold for a cool-lit light face and break for warm/odd white
 * balance, for strongly saturated or clipped skin, and for the specular
 * highlights that sit on a real forehead. When a condition fails for every
 * pixel the ROI reports no mean at all, which is exactly the reported symptom:
 * a tracked face with 0 % valid samples.
 *
 * What replaces it, and why it is defensible:
 *  - **Luminance gates are kept** (`too_dark` / `too_bright`). A clipped or
 *    black patch carries no usable modulation, so the check is still required.
 *    Losing the luminance check would let background and shadows in.
 *  - **The channel-order check is relaxed into a warning condition that is
 *    measured, not assumed**: skin under any plausible illuminant has red >=
 *    blue. Requiring a *strict margin* is what discarded warm-lit skin.
 *  - **A chroma floor replaces the red-blue margin.** A near-grey patch (low
 *    saturation) has no colour information for POS/CHROM and is also the
 *    signature of sampling a wall or clothing. This is a *signal-quality*
 *    condition with a physical justification, not a skin-tone classifier.
 *  - **Nothing here classifies a person.** There is no skin-tone model, no
 *    Fitzpatrick assumption and no per-person calibration: the same thresholds
 *    apply to everyone, and the diagnostics report what was removed so the
 *    operator can see whether the thresholds or the acquisition are at fault.
 */
export function classifyPixel(r: number, g: number, b: number): PixelRejection | null {
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
  if (luminance < 35) return 'too_dark'
  if (luminance > 245) return 'too_bright'
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  if (max - min < 12) return 'low_chroma'
  // Red must not fall below blue by any meaningful amount: under every
  // illuminant a skin patch keeps more red than blue. The old code demanded
  // red exceed green by 12 % and green exceed blue by 22 %, which is a specific
  // white-balance assumption rather than a physical property.
  if (r < b - 6) return 'channel_order'
  return null
}

export type ExtractOptions = {
  /** Pixels below this count make the patch unsampleable. */
  minPixels?: number
  /** Masks to subtract; names resolve through FEATURE_MASKS. */
  maskNames?: readonly string[]
}

/**
 * Extract per-ROI statistics and diagnostics from a frame.
 *
 * Returns diagnostics even when the mean is `null`: the caller needs to explain
 * *why* a region produced nothing, so a silent null is not acceptable.
 */
export function extractRoi(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  region: RoiName,
  landmarks: ReadonlyArray<Point | undefined | null>,
  options: ExtractOptions = {},
): { rgb: [number, number, number] | null; diagnostics: RoiDiagnostics } {
  const rejected = emptyRejections()
  const diagnostics: RoiDiagnostics = {
    region,
    valid: false,
    invalidReason: null,
    invalidDetail: null,
    polygonAreaPx: 0,
    candidatePixels: 0,
    excludedByMask: 0,
    rejected,
    acceptedPixels: 0,
    acceptedFraction: 0,
    meanRgb: null,
    medianRgb: null,
    meanLuminance: null,
    summary: '',
  }
  const patch = buildPatch(region, landmarks)
  if (!patch.ok) {
    diagnostics.invalidReason = patch.reason
    diagnostics.invalidDetail = patch.detail
    diagnostics.summary = patch.detail
    return { rgb: null, diagnostics }
  }
  diagnostics.valid = true
  if (width <= 0 || height <= 0 || data.length < width * height * 4) {
    diagnostics.valid = false
    diagnostics.invalidReason = 'invalid_frame'
    diagnostics.invalidDetail = `Frame data (${data.length} bytes) does not match ${width}x${height}`
    diagnostics.summary = diagnostics.invalidDetail
    return { rgb: null, diagnostics }
  }

  const polygon = patch.polygon
  diagnostics.polygonAreaPx = polygonArea(polygon) * width * height
  if (diagnostics.polygonAreaPx <= 0) {
    diagnostics.valid = false
    diagnostics.invalidReason = 'polygon_too_small'
    diagnostics.invalidDetail = 'The patch has no area at this frame size'
    diagnostics.summary = diagnostics.invalidDetail
    return { rgb: null, diagnostics }
  }

  const bounds = pixelBounds(polygon, width, height)
  if (bounds.x1 <= bounds.x0 || bounds.y1 <= bounds.y0) {
    diagnostics.valid = false
    diagnostics.invalidReason = 'polygon_outside_frame'
    diagnostics.invalidDetail = 'The patch falls entirely outside the video frame'
    diagnostics.summary = diagnostics.invalidDetail
    return { rgb: null, diagnostics }
  }

  const maskNames = options.maskNames ?? REGION_EXCLUSIONS[region]
  const masks: Point[][] = []
  for (const name of maskNames) {
    const indices = FEATURE_MASKS[name]
    if (!indices) continue
    const points: Point[] = []
    for (const index of indices) {
      const p = landmarks[index]
      if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) continue
      points.push({ x: p.x, y: p.y })
    }
    // A broken mask must not create a hole that was never measured; skipping it
    // is safer than masking a degenerate sliver across the patch.
    if (points.length >= 3 && !polygonIsDegenerate(points, 1e-9)) masks.push(points)
  }

  // Bounded loop: only the patch's bounding box is scanned, so a large frame
  // with a small patch costs the patch, not the frame.
  const rValues: number[] = []
  const gValues: number[] = []
  const bValues: number[] = []
  let candidate = 0
  let masked = 0
  for (let y = bounds.y0; y < bounds.y1; y += 1) {
    const py = y + 0.5
    for (let x = bounds.x0; x < bounds.x1; x += 1) {
      const px = x + 0.5
      if (!pointInPolygon(px, py, polygon, width, height)) continue
      candidate += 1
      let excluded = false
      for (const mask of masks) {
        if (pointInPolygon(px, py, mask, width, height)) {
          excluded = true
          break
        }
      }
      if (excluded) {
        masked += 1
        continue
      }
      const offset = (y * width + x) * 4
      const r = data[offset]
      const g = data[offset + 1]
      const b = data[offset + 2]
      const rejection = classifyPixel(r, g, b)
      if (rejection) {
        rejected[rejection] += 1
        continue
      }
      rValues.push(r)
      gValues.push(g)
      bValues.push(b)
    }
  }
  diagnostics.candidatePixels = candidate
  diagnostics.excludedByMask = masked
  const considered = candidate - masked
  diagnostics.acceptedPixels = rValues.length
  diagnostics.acceptedFraction = considered > 0 ? rValues.length / considered : 0

  const minPixels = options.minPixels ?? MIN_CANDIDATE_PIXELS
  if (candidate === 0) {
    diagnostics.valid = false
    diagnostics.invalidReason = 'polygon_too_small'
    diagnostics.invalidDetail = 'No pixels fall inside the patch at this frame size'
    diagnostics.summary = diagnostics.invalidDetail
    return { rgb: null, diagnostics }
  }
  if (considered < minPixels) {
    diagnostics.valid = false
    diagnostics.invalidReason = 'too_few_candidate_pixels'
    diagnostics.invalidDetail = `Only ${considered} candidate pixels inside the patch; at least ${minPixels} are needed for a stable mean`
    diagnostics.summary = diagnostics.invalidDetail
    return { rgb: null, diagnostics }
  }
  if (rValues.length === 0) {
    diagnostics.invalidReason = 'no_accepted_pixels'
    diagnostics.invalidDetail = `All ${considered} candidate pixels were rejected (${describeRejections(diagnostics)})`
    diagnostics.summary = diagnostics.invalidDetail
    return { rgb: null, diagnostics }
  }
  if (diagnostics.acceptedFraction < MIN_ACCEPTED_FRACTION) {
    diagnostics.invalidReason = 'low_usable_coverage'
    diagnostics.invalidDetail = `Only ${(diagnostics.acceptedFraction * 100).toFixed(1)}% of candidate pixels were usable (${describeRejections(diagnostics)})`
    diagnostics.summary = diagnostics.invalidDetail
    return { rgb: null, diagnostics }
  }

  const mean = (a: number[]) => a.reduce((s, v) => s + v, 0) / a.length
  const meanRgb: [number, number, number] = [mean(rValues), mean(gValues), mean(bValues)]
  diagnostics.meanRgb = meanRgb
  diagnostics.medianRgb = [medianOf(rValues), medianOf(gValues), medianOf(bValues)]
  diagnostics.meanLuminance = 0.2126 * meanRgb[0] + 0.7152 * meanRgb[1] + 0.0722 * meanRgb[2]
  diagnostics.summary = `${rValues.length} of ${considered} candidate pixels used (${(diagnostics.acceptedFraction * 100).toFixed(0)}%)`
  return { rgb: meanRgb, diagnostics }
}

function describeRejections(d: RoiDiagnostics): string {
  const parts = (Object.entries(d.rejected) as Array<[PixelRejection, number]>)
    .filter(([, count]) => count > 0)
    .map(([reason, count]) => `${count} ${PIXEL_REJECTION_COPY[reason]}`)
  return parts.length ? parts.join('; ') : 'no reason recorded'
}

function medianOf(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/** Extract every region in one call; the UI needs all three side by side. */
export function extractAllRois(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  landmarks: ReadonlyArray<Point | undefined | null>,
): { samples: Partial<Record<RoiName, [number, number, number] | null>>; diagnostics: RoiDiagnostics[] } {
  const samples: Partial<Record<RoiName, [number, number, number] | null>> = {}
  const diagnostics: RoiDiagnostics[] = []
  for (const region of ROI_NAMES) {
    const { rgb, diagnostics: d } = extractRoi(data, width, height, region, landmarks)
    samples[region] = rgb
    diagnostics.push(d)
  }
  return { samples, diagnostics }
}
