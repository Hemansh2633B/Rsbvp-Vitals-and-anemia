/**
 * Camera acquisition integrity: what the browser actually delivered, measured.
 *
 * Why this is separate from the DSP
 * ---------------------------------
 * The rPPG estimators assume "one RGB sample every 1/fs seconds". A real camera
 * does not deliver that. It duplicates frames (`requestAnimationFrame` fires
 * faster than the sensor), stalls (tab throttling, GC), drops frames (thermal
 * throttling on phones) and recovers after interruptions. When those facts are
 * hidden, a plausible-looking BPM can be produced from a signal whose sampling
 * rate is not what the estimator believes.
 *
 * This module answers three questions with evidence, not guesses:
 *
 *  1. What was the *effective* sampling rate, from the timestamps themselves?
 *  2. Did the same camera frame get sampled twice (duplicate sample)?
 *  3. How much of the capture was lost to gaps, and was the rate high enough?
 *
 * It deliberately does not decide availability - that stays with `liveDsp.ts`,
 * which consumes these numbers through `scores`/`concepts`.
 */

/** Exported for display and tests: the lowest frame rate the estimators accept. */
export const MIN_USABLE_FS_HZ = 12
const DUPLICATE_EPSILON_S = 0.001
const MEDIAN_INTERVAL_MULTIPLE = 1.5
/** A single interval this many times the median is a stall, whatever the CV says. */
const STALL_INTERVAL_MULTIPLE = 2.5

export interface CaptureTimestamps {
  /** Monotonic seconds per accepted sample, ascending. */
  times: number[]
  /**
   * Camera frame identity per sample when the browser exposes it
   * (`HTMLVideoElement.getVideoPlaybackQuality().totalVideoFrames` or
   * `requestVideoFrameCallback` metadata). Optional: without it duplicate
   * detection falls back to identical timestamps only.
   */
  frameIds?: Array<number | null>
}

export interface CaptureIntegrity {
  /** Number of samples examined. */
  nSamples: number
  /** Span of the capture in seconds (last - first timestamp). */
  durationS: number
  /** Effective rate from the median inter-sample interval; null if unusable. */
  medianFsHz: number | null
  /** Rate from the mean interval - differs from the median when there are gaps. */
  meanFsHz: number | null
  /** Median inter-sample interval in seconds. */
  medianIntervalS: number | null
  /** Largest inter-sample gap in seconds; null with fewer than two samples. */
  maxGapS: number | null
  /** Fraction of intervals longer than 1.5x the median (dropped/stalled frames). */
  droppedIntervalFraction: number | null
  /** Fraction of intervals shorter than ~1 ms (the loop outran the sensor). */
  duplicateIntervalFraction: number | null
  /** Samples whose camera frame id equals the previous sample's frame id. */
  duplicateFrameFraction: number | null
  /** Coefficient of variation of the intervals: 0 = perfectly regular. */
  intervalJitterCv: number | null
  /** Median rate is below the rate the estimators need. */
  insufficientSamplingRate: boolean
  /** Any single gap exceeded 0.25 s (the window-level gap gate in liveDsp). */
  hasLargeGap: boolean
  /** Duplicate or sub-millisecond intervals are common enough to matter (>2%). */
  hasDuplicateSamples: boolean
  /** Interval jitter above 25% of the median interval. */
  hasIrregularTiming: boolean
  /** True when none of the timing problems above is present. */
  regular: boolean
}

export function median(values: number[]): number {
  if (!values.length) return Number.NaN
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/**
 * Describe the timing of what the camera delivered.
 *
 * Non-finite or non-ascending timestamps are dropped rather than repaired: a
 * clock that goes backwards is a defect to report, not something to smooth over.
 */
export function captureIntegrity(input: CaptureTimestamps): CaptureIntegrity {
  const empty: CaptureIntegrity = {
    nSamples: 0,
    durationS: 0,
    medianFsHz: null,
    meanFsHz: null,
    medianIntervalS: null,
    maxGapS: null,
    droppedIntervalFraction: null,
    duplicateIntervalFraction: null,
    duplicateFrameFraction: null,
    intervalJitterCv: null,
    insufficientSamplingRate: true,
    hasLargeGap: false,
    hasDuplicateSamples: false,
    hasIrregularTiming: false,
    regular: false,
  }

  const pairs: Array<{ t: number; id: number | null }> = []
  for (let i = 0; i < input.times.length; i += 1) {
    const t = input.times[i]
    if (!Number.isFinite(t)) continue
    if (pairs.length && t < pairs[pairs.length - 1].t) continue // clock went backwards
    const id = input.frameIds?.[i]
    pairs.push({ t, id: typeof id === 'number' && Number.isFinite(id) ? id : null })
  }
  if (pairs.length < 2) return { ...empty, nSamples: pairs.length }

  const intervals: number[] = []
  for (let i = 1; i < pairs.length; i += 1) intervals.push(pairs[i].t - pairs[i - 1].t)

  // The rate must come from intervals that represent *new* sensor frames. If the
  // read loop outran the camera, many intervals are ~0; including them would
  // drag the median to zero and make the rate look unknown instead of reporting
  // the real frame rate next to a duplicate warning.
  const distinct = intervals.filter((d) => d > DUPLICATE_EPSILON_S)
  const rateBasis = distinct.length ? distinct : intervals
  const med = median(rateBasis)
  const mean = rateBasis.reduce((a, b) => a + b, 0) / rateBasis.length
  const durationS = pairs[pairs.length - 1].t - pairs[0].t

  const medianFsHz = med > 0 ? 1 / med : null
  const meanFsHz = mean > 0 ? 1 / mean : null
  const maxGapS = Math.max(...intervals)

  const dropped = intervals.filter((d) => d > MEDIAN_INTERVAL_MULTIPLE * med).length / intervals.length
  const duplicates = intervals.filter((d) => d <= DUPLICATE_EPSILON_S).length / intervals.length

  let duplicateFrames: number | null = null
  const ids = pairs.map((p) => p.id)
  if (ids.some((id) => id !== null)) {
    let repeats = 0
    let comparable = 0
    for (let i = 1; i < ids.length; i += 1) {
      if (ids[i] === null || ids[i - 1] === null) continue
      comparable += 1
      if (ids[i] === ids[i - 1]) repeats += 1
    }
    duplicateFrames = comparable ? repeats / comparable : null
  }

  const jitterCv = med > 0
    ? Math.sqrt(rateBasis.reduce((a, d) => a + (d - med) ** 2, 0) / rateBasis.length) / med
    : null

  const insufficientSamplingRate = medianFsHz === null || medianFsHz < MIN_USABLE_FS_HZ
  const hasLargeGap = maxGapS > 0.25
  const hasDuplicateSamples = duplicates > 0.02 || (duplicateFrames !== null && duplicateFrames > 0.02)
  // Jitter alone is a poor detector: one 120 ms stall in 300 samples barely moves
  // the coefficient of variation but does break the "uniform sampling" premise.
  // Flag either a large CV or a single interval far beyond the typical one.
  const hasStall = med > 0 && distinct.some((d) => d > STALL_INTERVAL_MULTIPLE * med)
  const hasIrregularTiming = (jitterCv !== null && jitterCv > 0.25) || hasStall

  return {
    nSamples: pairs.length,
    durationS,
    medianFsHz,
    meanFsHz,
    medianIntervalS: med,
    maxGapS,
    droppedIntervalFraction: dropped,
    duplicateIntervalFraction: duplicates,
    duplicateFrameFraction: duplicateFrames,
    intervalJitterCv: jitterCv,
    insufficientSamplingRate,
    hasLargeGap,
    hasDuplicateSamples,
    hasIrregularTiming,
    regular: !insufficientSamplingRate && !hasLargeGap && !hasDuplicateSamples && !hasIrregularTiming,
  }
}

/**
 * A specific, user-readable reason for the first timing problem found, or null
 * when the capture is clean. Ordered by how badly each one breaks the estimate.
 */
export function integrityReason(report: CaptureIntegrity): string | null {
  if (report.nSamples < 2) return 'Not enough frames yet'
  if (report.insufficientSamplingRate) {
    const rate = report.medianFsHz === null ? 'unknown' : report.medianFsHz.toFixed(1)
    return `Camera delivered ${rate} fps; at least ${MIN_USABLE_FS_HZ} fps is needed for pulse analysis`
  }
  if (report.hasLargeGap && report.maxGapS !== null) {
    return `Frame gap of ${report.maxGapS.toFixed(2)} s (dropped frames or tab throttling)`
  }
  if (report.hasDuplicateSamples) {
    const frac = report.duplicateFrameFraction ?? report.duplicateIntervalFraction ?? 0
    return `${(frac * 100).toFixed(0)}% of samples repeated the same camera frame`
  }
  if (report.hasIrregularTiming && report.intervalJitterCv !== null) {
    return `Irregular frame timing (jitter ${(report.intervalJitterCv * 100).toFixed(0)}% of the frame interval)`
  }
  return null
}

/**
 * How long to wait before reopening a camera after it fails, in milliseconds.
 *
 * A camera that fails immediately must not be retried in a tight loop (it drains
 * the battery and spams the permission prompt on some phones). Backoff is
 * exponential from 1 s, capped at 30 s, and stops after `maxAttempts`.
 */
export function recoveryDelayMs(attempt: number, maxAttempts = 4): number | null {
  if (attempt < 0 || attempt >= maxAttempts) return null
  return Math.min(30_000, 1_000 * 2 ** attempt)
}
