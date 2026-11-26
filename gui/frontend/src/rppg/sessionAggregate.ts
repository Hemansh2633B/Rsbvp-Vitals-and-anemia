// Session-level measurement collection and aggregation.
//
// Why this exists: every analysis window can produce a slightly different
// estimate, so the live number jumps around. A session result must be computed
// from the readings that actually passed the *existing* quality gates, and it
// must be honest about how much evidence it rests on.
//
// Design rules enforced here (each has a test):
//   * Readings are append-only. The aggregate never overwrites history.
//   * A reading is accepted only if the existing verdict is `valid`, the value
//     is finite and inside a wide plausibility window for its metric.
//   * Different metrics and different units are never combined.
//   * Different algorithms are never averaged together: a series is computed per
//     algorithm, and a mixed set is refused rather than averaged.
//   * Overlapping windows are not independent observations, so the standard
//     error uses a non-overlapping subset count, never the raw reading count.
//   * Insufficient evidence yields an explicit insufficient state, never a
//     number and never a fabricated confidence score.

/** Metrics this session layer knows how to aggregate. */
export type MetricId = 'heart_rate' | 'respiratory_rate'

export interface MetricSpec {
  id: MetricId
  label: string
  shortLabel: string
  unit: string
  decimals: number
  /**
   * Data-hygiene plausibility bounds. These exist to catch unit mix-ups and
   * lost/garbage estimates (e.g. 0, 3, 900). They are NOT healthy ranges and
   * carry no clinical meaning.
   */
  plausibleMin: number
  plausibleMax: number
  /** Shown next to the result so the number is never mistaken for a diagnosis. */
  note: string
  /**
   * True when this metric may occupy the headline position. A metric must be
   * independently validated before it does; respiratory rate here is inferred
   * from beat-to-beat interval variability, so it stays in advanced details.
   */
  primary: boolean
  /** True when the estimator is experimental and must be labelled as such. */
  experimental: boolean
}

export const METRICS: Record<MetricId, MetricSpec> = {
  heart_rate: {
    id: 'heart_rate',
    label: 'Heart rate',
    shortLabel: 'Pulse',
    unit: 'BPM',
    decimals: 1,
    plausibleMin: 30,
    plausibleMax: 220,
    note: 'Estimate from accepted camera readings, not a medical measurement.',
    primary: true,
    experimental: false,
  },
  respiratory_rate: {
    id: 'respiratory_rate',
    label: 'Respiratory rate',
    shortLabel: 'Breathing',
    unit: 'br/min',
    decimals: 1,
    plausibleMin: 4,
    plausibleMax: 60,
    // Not a direct breathing measurement: this is inferred from pulse-to-pulse
    // interval variability (respiratory sinus arrhythmia), has no independent
    // reference validation in this project, and is heavily confounded by motion
    // and by the pulse estimate itself. It is therefore never a headline result.
    note:
      'Experimental. Inferred from beat-to-beat pulse-interval variability, not from a ' +
      'breathing measurement; unvalidated against a respiratory reference.',
    primary: false,
    experimental: true,
  },
}

export const METRIC_IDS = Object.keys(METRICS) as MetricId[]

/** Metrics eligible for the headline position (independently substantiated only). */
export const PRIMARY_METRIC_IDS = METRIC_IDS.filter(id => METRICS[id].primary)

/**
 * Metrics that are deliberately NOT aggregatable here. Keeping the list explicit
 * means a future contributor cannot quietly average them into a session result.
 */
export const NOT_AGGREGATED: Record<string, string> = {
  rmssd: 'Requires beat-to-beat pulse timing with independent reference validation; not available.',
  sdnn: 'Requires beat-to-beat pulse timing with independent reference validation; not available.',
  pnn50: 'Requires beat-to-beat pulse timing with independent reference validation; not available.',
  spo2: 'Not measurable from consumer RGB video; no validated estimator exists in this project.',
  blood_pressure: 'Not measurable from this method; deliberately absent.',
  hemoglobin: 'Anemia image features stay in a separate, non-cardiovascular pathway; no model exists.',
  conjunctiva_pallor: 'Image colour features are not a hemoglobin measurement and are never averaged here.',
}

/** The algorithm label used for the per-window consensus estimate (primary series). */
export const CONSENSUS = 'consensus'

export interface ReadingInput {
  metric: MetricId
  /** Raw estimate; null when the estimator produced nothing for this window. */
  value: number | null
  /** `consensus` for the per-window agreement-checked estimate, else green/pos/chrom. */
  algorithm: string
  /** ROI the estimate came from, or `all` for a consensus across ROIs. */
  roi: string
  /** Existing spectral-concentration score (0-1). Not a probability. */
  qualityScore: number | null
  /** Existing composite verdict token (valid, low_signal_quality, ...). */
  qualityVerdict: string
  sampling: {
    fsHz: number | null
    nSamples: number | null
    /** Window bounds on the session clock; null when unknown, never invented. */
    windowStartS: number | null
    windowEndS: number | null
  }
  rejectionReason: string | null
  /** Wall-clock time the analysis finished (epoch ms). */
  analyzedAtMs: number
  /** Seconds since capture began, for ordering and display. */
  sessionElapsedS: number | null
  windowIndex: number | null
}

export interface Measurement extends ReadingInput {
  id: number
  recordedUtc: string
  accepted: boolean
  /** Null iff accepted. Explains exactly why a reading was left out. */
  finalRejectionReason: string | null
}

export interface AggregationConfig {
  /** Accepted readings needed before a session average is shown at all. */
  minAcceptedReadings: number
  /** Accepted *non-overlapping* windows needed before the average is shown. */
  minIndependentWindows: number
  /** Accepted readings that mark a session as complete for the UI. */
  targetAcceptedReadings: number
  /** A result older than this is stale and never counted as current. */
  staleAfterMs: number
  /**
   * Above this ratio of densest to sparsest analysis density the session result
   * is flagged as potentially density-biased. Not a quality gate: the gates are
   * unchanged, this only reports a property of the accepted readings.
   */
  densityRatioWarning: number
  plausible: Record<MetricId, { min: number; max: number }>
}

export const DEFAULT_CONFIG: AggregationConfig = {
  // Five accepted windows is a low bar deliberately: each one already had to
  // pass the existing spectral, agreement, coverage and timing gates. Raising it
  // would not make the estimate more accurate, only slower to appear.
  minAcceptedReadings: 5,
  // Two non-overlapping windows, so a session average is never a single moment
  // re-counted. Independent windows grow slowly under sliding-window analysis
  // (~1 per window length), which is exactly why this is stated in the UI.
  minIndependentWindows: 2,
  targetAcceptedReadings: 8,
  staleAfterMs: 5000,
  densityRatioWarning: 3,
  plausible: {
    heart_rate: { min: METRICS.heart_rate.plausibleMin, max: METRICS.heart_rate.plausibleMax },
    respiratory_rate: { min: METRICS.respiratory_rate.plausibleMin, max: METRICS.respiratory_rate.plausibleMax },
  },
}

/** Acceptance-band cut-offs for the plain-language quality indicator. */
export const ACCEPTANCE_BANDS = { good: 70, fair: 40 } as const

function isMetricId(value: string): value is MetricId {
  return Object.prototype.hasOwnProperty.call(METRICS, value)
}

/**
 * Decide whether one raw estimate may contribute to a session average.
 * Returns the reason when it may not, so nothing is dropped silently.
 */
export function classifyReading(
  input: ReadingInput,
  config: AggregationConfig,
  nowMs: number,
): { accepted: boolean; reason: string | null } {
  if (!isMetricId(input.metric)) return { accepted: false, reason: `unsupported_metric:${input.metric}` }
  if (nowMs - input.analyzedAtMs > config.staleAfterMs) {
    // The pipeline re-reported an old analysis: it describes a moment that has
    // passed, so it must not be counted as a current observation.
    return { accepted: false, reason: 'stale_reading' }
  }
  // The pipeline's own verdict takes precedence over the missing value: "ROIs
  // lost" is more useful to a reader than "no estimate", and the verdict is what
  // the existing gates decided. Reporting the wrong reason is how a rejection
  // log becomes useless.
  if (input.qualityVerdict !== 'valid') {
    return { accepted: false, reason: input.rejectionReason ?? input.qualityVerdict }
  }
  if (input.value === null || !Number.isFinite(input.value)) {
    // A `valid` verdict with no number would be a contract violation upstream.
    // Name it, so it is visible rather than silently counted as a bad reading.
    return { accepted: false, reason: 'valid_verdict_without_estimate' }
  }
  const bounds = config.plausible[input.metric]
  if (input.value < bounds.min || input.value > bounds.max) {
    return {
      accepted: false,
      reason: `implausible_value_${input.value.toFixed(1)}_outside_${bounds.min}-${bounds.max}`,
    }
  }
  return { accepted: true, reason: null }
}

/**
 * Append-only collection of every reading produced during one session.
 *
 * Both live pathways feed this (browser DSP in BrowserPulse, server DSP in
 * Live). There is deliberately only one implementation: duplicating the
 * statistics language-by-language is how two UIs end up disagreeing.
 */
export class SessionCollector {
  private readings: Measurement[] = []
  private nextId = 1
  private config: AggregationConfig

  constructor(config: Partial<AggregationConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config, plausible: { ...DEFAULT_CONFIG.plausible, ...(config.plausible ?? {}) } }
  }

  setConfig(config: Partial<AggregationConfig>) {
    this.config = { ...this.config, ...config, plausible: { ...this.config.plausible, ...(config.plausible ?? {}) } }
  }

  getConfig(): AggregationConfig {
    return JSON.parse(JSON.stringify(this.config)) as AggregationConfig
  }

  add(input: ReadingInput, nowMs: number = Date.now()): Measurement {
    const { accepted, reason } = classifyReading(input, this.config, nowMs)
    const reading: Measurement = {
      ...input,
      id: this.nextId++,
      recordedUtc: new Date(input.analyzedAtMs).toISOString(),
      accepted,
      finalRejectionReason: accepted ? null : reason,
    }
    this.readings.push(reading)
    return reading
  }

  /** Every reading ever recorded this session, accepted or not. */
  all(): Measurement[] {
    return this.readings.slice()
  }

  accepted(metric?: MetricId): Measurement[] {
    return this.readings.filter(r => r.accepted && (metric === undefined || r.metric === metric))
  }

  rejected(metric?: MetricId): Measurement[] {
    return this.readings.filter(r => !r.accepted && (metric === undefined || r.metric === metric))
  }

  /** Drop all readings (new session). Ids restart; nothing is reused across sessions. */
  reset() {
    this.readings = []
    this.nextId = 1
  }

  get size(): number {
    return this.readings.length
  }
}

export type AggregateVerdict = 'available' | 'insufficient' | 'no_readings'

export interface MetricAggregate {
  metric: MetricId
  label: string
  unit: string
  decimals: number
  note: string
  algorithm: string
  verdict: AggregateVerdict
  /** Why the verdict is not `available`; empty string when available. */
  reason: string
  nAccepted: number
  nRejected: number
  nTotal: number
  /** Accepted share of all readings for this metric, 0-100, or null when none. */
  acceptancePct: number | null
  mean: number | null
  median: number | null
  min: number | null
  max: number | null
  sd: number | null
  range: number | null
  /**
   * Accepted readings whose analysis windows do not overlap, i.e. the number of
   * genuinely distinct observations. Null when window bounds were unavailable.
   */
  nIndependentAccepted: number | null
  /** nAccepted / nIndependentAccepted; 1 means no overlap. Null when unknown. */
  overlapFactor: number | null
  /**
   * Standard error of the mean from the *independent* subset only. Null when
   * fewer than three independent windows exist: with overlap it is not
   * estimable, and inventing it would overstate precision.
   */
  standardError: number | null
  firstAcceptedUtc: string | null
  lastAcceptedUtc: string | null
  medianQuality: number | null
  /** Distinct algorithms present for this metric across the whole session. */
  algorithmsSeen: string[]
  /**
   * True when this metric has more than one algorithm series. They are never
   * averaged together: each series is summarised on its own, and only the
   * agreement-checked consensus is presented as the session result.
   */
  multipleAlgorithmSeries: boolean
}

function mean(values: number[]): number | null {
  if (!values.length) return null
  return values.reduce((a, b) => a + b, 0) / values.length
}

function sampleSd(values: number[]): number | null {
  if (values.length < 2) return null
  const m = mean(values) as number
  const variance = values.reduce((acc, v) => acc + (v - m) ** 2, 0) / (values.length - 1)
  return Math.sqrt(variance)
}

/** Median of a numeric list; null for an empty list (never 0). */
export function median(values: number[]): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/**
 * Count readings whose windows do not overlap each other.
 *
 * Greedy interval scheduling by end time: for sliding-window analysis (the
 * browser re-analyses every 500 ms over a 10 s window) almost every pair
 * overlaps, so the raw count hugely overstates how many independent
 * observations a session contains. Reporting that count is the point.
 */
export function countIndependentWindows(readings: Measurement[]): number | null {
  const bounded = readings.filter(
    r => r.sampling.windowStartS !== null && r.sampling.windowEndS !== null,
  )
  if (!bounded.length) return null
  const sorted = [...bounded].sort(
    (a, b) =>
      (a.sampling.windowEndS as number) - (b.sampling.windowEndS as number) ||
      (a.sampling.windowStartS as number) - (b.sampling.windowStartS as number),
  )
  let count = 0
  let lastEnd = -Infinity
  for (const r of sorted) {
    const start = r.sampling.windowStartS as number
    // Touching windows (start == lastEnd) are adjacent, not overlapping.
    if (start >= lastEnd) {
      count += 1
      lastEnd = r.sampling.windowEndS as number
    }
  }
  return count
}

function emptyAggregate(metric: MetricId, algorithm: string): MetricAggregate {
  const spec = METRICS[metric]
  return {
    metric,
    label: spec.label,
    unit: spec.unit,
    decimals: spec.decimals,
    note: spec.note,
    algorithm,
    verdict: 'no_readings',
    reason: 'No readings recorded for this metric in this session',
    nAccepted: 0,
    nRejected: 0,
    nTotal: 0,
    acceptancePct: null,
    mean: null,
    median: null,
    min: null,
    max: null,
    sd: null,
    range: null,
    nIndependentAccepted: null,
    overlapFactor: null,
    standardError: null,
    firstAcceptedUtc: null,
    lastAcceptedUtc: null,
    medianQuality: null,
    algorithmsSeen: [],
    multipleAlgorithmSeries: false,
  }
}

export interface SummarizeOptions {
  /** Which algorithm series to summarise. Defaults to the per-window consensus. */
  algorithm?: string
  config?: AggregationConfig
}

/**
 * Summarise one metric for one algorithm series.
 *
 * A mixed-algorithm series is *refused* (`insufficient`, reason `mixed_algorithms`)
 * rather than averaged: GREEN, POS and CHROM are not interchangeable estimators,
 * and only the per-window consensus has had its estimator spread checked against
 * the agreement gate.
 */
export function summarize(
  readings: Measurement[],
  metric: MetricId,
  options: SummarizeOptions = {},
): MetricAggregate {
  const config = options.config ?? DEFAULT_CONFIG
  const algorithm = options.algorithm ?? CONSENSUS
  if (!isMetricId(metric)) {
    const fallback = emptyAggregate('heart_rate', algorithm)
    return { ...fallback, verdict: 'insufficient', reason: `unsupported_metric:${metric}` }
  }
  const forMetric = readings.filter(r => r.metric === metric)
  if (!forMetric.length) return emptyAggregate(metric, algorithm)

  const algorithmsSeen = [...new Set(forMetric.map(r => r.algorithm))].sort()
  const series = forMetric.filter(r => r.algorithm === algorithm)
  const base = emptyAggregate(metric, algorithm)
  const result: MetricAggregate = {
    ...base,
    nTotal: series.length,
    nRejected: series.length - series.filter(r => r.accepted).length,
    algorithmsSeen,
    multipleAlgorithmSeries: algorithmsSeen.length > 1,
  }
  const accepted = series.filter(r => r.accepted)
  const values = accepted.map(r => r.value as number)

  result.nAccepted = accepted.length
  result.nRejected = series.length - accepted.length
  result.acceptancePct = series.length ? (accepted.length / series.length) * 100 : null
  result.nIndependentAccepted = countIndependentWindows(accepted)
  result.overlapFactor =
    result.nIndependentAccepted && result.nIndependentAccepted > 0
      ? accepted.length / result.nIndependentAccepted
      : null

  // A single series can only ever contain one algorithm label by construction:
  // separation happens by filtering, so there is nothing to average across.
  // Assert it rather than trust it.
  if (new Set(series.map(r => r.algorithm)).size > 1) {
    result.verdict = 'insufficient'
    result.reason = 'Series mixes several algorithms; they are not interchangeable and were not averaged'
    return result
  }
  if (!values.length) {
    result.verdict = 'insufficient'
    result.reason =
      series.length > 0
        ? `No accepted readings (${result.nRejected} rejected by the quality gates)`
        : 'No readings for this algorithm in this session'
    return result
  }

  result.mean = mean(values)
  result.median = median(values)
  result.min = Math.min(...values)
  result.max = Math.max(...values)
  result.sd = sampleSd(values)
  result.range = (result.max as number) - (result.min as number)
  const qualities = accepted.map(r => r.qualityScore).filter((q): q is number => q !== null && Number.isFinite(q))
  result.medianQuality = median(qualities)
  result.firstAcceptedUtc = accepted[0]?.recordedUtc ?? null
  result.lastAcceptedUtc = accepted[accepted.length - 1]?.recordedUtc ?? null

  if (result.nIndependentAccepted !== null && result.nIndependentAccepted >= 3 && result.sd !== null) {
    result.standardError = result.sd / Math.sqrt(result.nIndependentAccepted)
  }

  if (values.length < config.minAcceptedReadings) {
    result.verdict = 'insufficient'
    result.reason = `Only ${values.length} accepted reading${values.length === 1 ? '' : 's'}; at least ${config.minAcceptedReadings} are needed for a session average`
    return result
  }
  if (
    result.nIndependentAccepted !== null &&
    result.nIndependentAccepted < config.minIndependentWindows
  ) {
    result.verdict = 'insufficient'
    result.reason = `Only ${result.nIndependentAccepted} independent (non-overlapping) window${result.nIndependentAccepted === 1 ? '' : 's'}; at least ${config.minIndependentWindows} are needed`
    return result
  }
  result.verdict = 'available'
  // An available aggregate has no shortfall to explain. Leaving the placeholder
  // reason from emptyAggregate in place produced "available" blocks carrying
  // "No readings recorded for this metric", and the experimental block renders
  // that text verbatim. Python already cleared it; this keeps the two identical.
  result.reason = ''
  return result
}

/**
 * What the *capture* is doing, supplied by the caller.
 *
 * Completion is not derivable from the readings alone: the same set of accepted
 * readings means "keep going" while the camera runs and "this is all there is"
 * once it stops. Conflating the two is what let the previous implementation tell
 * a user to stop a session whose aggregate was still insufficient.
 */
export type SessionLifecycle = 'running' | 'stopped' | 'interrupted'

/**
 * Distinct, non-overlapping session states.
 *
 * `completed` and `available` both require a genuinely available aggregate;
 * there is no state that invites the user to stop while the result is
 * insufficient.
 */
export type CompletionState =
  | 'idle'
  | 'initialising'
  | 'collecting'
  | 'insufficient'
  | 'available'
  | 'interrupted'
  | 'completed'

export interface SessionSummary {
  metrics: MetricAggregate[]
  /** Aggregates of every non-consensus algorithm, for the advanced details view. */
  perAlgorithm: MetricAggregate[]
  /** Every reading recorded, including per-estimator series. Used for export. */
  readings: Measurement[]
  /**
   * One reading per analysed window (the agreement-checked consensus series).
   * This is what the interface counts and lists: a user thinks in windows, and
   * counting the six per-estimator series of one window as six "readings" would
   * overstate both the evidence and the amount of work the session did.
   */
  primaryReadings: Measurement[]
  nAcceptedTotal: number
  nRejectedTotal: number
  acceptancePct: number | null
  /** Plain-language band derived from the observed acceptance rate only. */
  acceptanceBand: 'good' | 'fair' | 'poor' | null
  completion: CompletionState
  completionReason: string
  /** True when the aggregate is available (the only condition for a headline number). */
  resultAvailable: boolean
  /**
   * Readings per unit time in the densest part of the session divided by the
   * sparsest. Around 1 means the session was analysed evenly. Large values mean
   * some stretch contributed many more readings than another, which is the
   * condition under which the all-window mean can be biased (see
   * docs/SESSION_AGGREGATION.md and research/session/aggregation_analysis.py).
   */
  densityRatio: number | null
  /** True when densityRatio exceeds the configured warning threshold. */
  unevenDensity: boolean
  /** True when at least one metric has a presentable average. */
  hasResult: boolean
  config: AggregationConfig
}

/**
 * Ratio of the densest to the sparsest analysis density across the session.
 *
 * Density is measured in readings per second over the span the readings cover.
 * It is split into thirds and the busiest third compared with the quietest, so a
 * single short burst does not dominate. `null` when there is too little span to
 * judge, rather than guessing 1.
 */
export function densityRatio(readings: Measurement[]): number | null {
  const times = readings
    .map(r => r.sessionElapsedS)
    .filter((t): t is number => t !== null && Number.isFinite(t))
  if (times.length < 4) return null
  const ordered = [...times].sort((a, b) => a - b)
  const span = ordered[ordered.length - 1] - ordered[0]
  if (!(span > 0)) return null
  const third = span / 3
  if (third <= 0) return null
  const start = ordered[0]
  const counts = [0, 0, 0]
  for (const t of ordered) {
    const bucket = Math.min(2, Math.floor((t - start) / third))
    counts[bucket] += 1
  }
  const nonZero = counts.filter(c => c > 0)
  if (!nonZero.length) return null
  const densest = Math.max(...nonZero)
  const sparsest = Math.min(...nonZero)
  if (sparsest === 0) return null
  return densest / sparsest
}

export interface SummarizeSessionOptions {
  config?: AggregationConfig
  /** What the capture is doing. Defaults to `stopped`: a summary nobody is feeding. */
  lifecycle?: SessionLifecycle
}

/**
 * Session summary: per-metric aggregates, completion state, and whether a
 * headline result may be shown.
 *
 * The single rule this function exists to enforce: `completed` (an invitation to
 * stop) and `available` (a headline number) both require the aggregate verdict to
 * actually be `available`. A count of accepted readings is progress, never
 * permission to stop.
 */
export function summarizeSession(
  readings: Measurement[],
  configOrOptions: AggregationConfig | SummarizeSessionOptions = DEFAULT_CONFIG,
): SessionSummary {
  const options: SummarizeSessionOptions =
    'minAcceptedReadings' in (configOrOptions as AggregationConfig)
      ? { config: configOrOptions as AggregationConfig }
      : (configOrOptions as SummarizeSessionOptions)
  const config = options.config ?? DEFAULT_CONFIG
  const lifecycle: SessionLifecycle = options.lifecycle ?? 'stopped'
  const metrics = METRIC_IDS.map(m => summarize(readings, m, { config }))
  const perAlgorithm: MetricAggregate[] = []
  for (const metric of METRIC_IDS) {
    const algs = [...new Set(readings.filter(r => r.metric === metric).map(r => r.algorithm))].sort()
    for (const algorithm of algs) {
      if (algorithm === CONSENSUS) continue
      perAlgorithm.push(summarize(readings, metric, { algorithm, config }))
    }
  }
  const primaryReadings = readings.filter(r => r.algorithm === CONSENSUS)
  const nAcceptedTotal = primaryReadings.filter(r => r.accepted).length
  const nRejectedTotal = primaryReadings.length - nAcceptedTotal
  const acceptancePct = primaryReadings.length ? (nAcceptedTotal / primaryReadings.length) * 100 : null
  const acceptanceBand =
    acceptancePct === null
      ? null
      : acceptancePct >= ACCEPTANCE_BANDS.good
        ? 'good'
        : acceptancePct >= ACCEPTANCE_BANDS.fair
          ? 'fair'
          : 'poor'

  const presentable = metrics.filter(m => m.verdict === 'available')
  // Completion follows the metric the interface headlines: heart rate. A session
  // is not "available" because a secondary metric has enough readings.
  const primaryAggregate = metrics.find(m => m.metric === 'heart_rate') ?? metrics[0]
  const resultAvailable = primaryAggregate?.verdict === 'available'
  const needed = config.minAcceptedReadings
  const progressMetric = primaryAggregate

  // Density flag uses the consensus series only: the per-estimator readings are
  // recorded at the same moments, so including them would divide out.
  const density = densityRatio(primaryReadings)
  const unevenDensity = density !== null && density > config.densityRatioWarning

  let completion: CompletionState
  let completionReason: string
  if (!primaryReadings.length) {
    if (lifecycle === 'interrupted') {
      completion = 'interrupted'
      completionReason = 'Capture was interrupted before any window was analysed'
    } else if (lifecycle === 'stopped') {
      // No session exists yet. Calling an idle page "initialising" would imply
      // work is happening when none is.
      completion = 'idle'
      completionReason = 'No session yet: press Start to begin collecting readings'
    } else {
      completion = 'initialising'
      completionReason = 'Waiting for the first analysable window'
    }
  } else if (resultAvailable) {
    completion = lifecycle === 'running' ? 'available' : 'completed'
    completionReason =
      lifecycle === 'running'
        ? `Session average available from ${progressMetric.nAccepted} accepted readings; you can stop the camera`
        : `Session complete: ${progressMetric.nAccepted} accepted readings`
  } else if (lifecycle === 'interrupted') {
    // Same evidence, different meaning: capture stopped by an interruption, so
    // the shortfall is not something the user can fix by holding still.
    completion = 'interrupted'
    completionReason = `Capture interrupted with ${progressMetric?.nAccepted ?? 0} accepted readings - not enough for a session average`
  } else if (lifecycle === 'running') {
    // Still capturing: the shortfall is provisional and the user can act on it.
    // Name whichever condition is actually blocking, so "collecting" is never a
    // vague reassurance when the real problem is overlap rather than a low count.
    completion = 'collecting'
    const accepted = progressMetric?.nAccepted ?? 0
    const independent = progressMetric?.nIndependentAccepted ?? null
    completionReason =
      accepted < needed
        ? `Collecting: ${accepted} of ${needed} accepted readings`
        : independent !== null && independent < config.minIndependentWindows
          ? `Collecting: ${accepted} accepted readings, but they overlap (${independent} independent window${independent === 1 ? '' : 's'}); keep capturing`
          : `Collecting: ${accepted} accepted readings; waiting for the aggregate to become available`
  } else {
    // Capture finished (or never started) without enough evidence. This is a
    // final state, not a progress report, and it never says "you can stop".
    completion = 'insufficient'
    completionReason = progressMetric?.reason ?? 'Not enough accepted readings for a session average'
  }

  return {
    metrics,
    perAlgorithm,
    readings,
    primaryReadings,
    nAcceptedTotal,
    nRejectedTotal,
    acceptancePct,
    acceptanceBand,
    completion,
    completionReason,
    resultAvailable,
    densityRatio: density,
    unevenDensity,
    hasResult: presentable.length > 0,
    config,
  }
}

export function formatValue(value: number | null, metric: MetricId): string {
  if (value === null || !Number.isFinite(value)) return '—'
  const spec = METRICS[metric]
  return `${value.toFixed(spec.decimals)} ${spec.unit}`
}

export interface SessionExportInput {
  sessionId: string
  createdUtc: string
  readings: Measurement[]
  summary: SessionSummary
  capture: {
    algorithms: string[]
    rois: string[]
    passbandHz: readonly [number, number]
    requiredSeconds: number
    backend: string
    cameraLabel: string | null
    samplingRateHz: number | null
  }
}

/**
 * Machine-readable session aggregate. Deliberately carries the independence
 * caveat next to the statistics so a reader cannot take the mean of 400
 * overlapping windows as 400 observations.
 */
export function buildSessionAggregateExport(input: SessionExportInput) {
  const { summary } = input
  const metricBlock = (a: MetricAggregate) => ({
    metric: a.metric,
    label: a.label,
    unit: a.unit,
    algorithm: a.algorithm,
    verdict: a.verdict,
    reason: a.reason,
    experimental: METRICS[a.metric]?.experimental ?? true,
    primary: METRICS[a.metric]?.primary ?? false,
    accepted_readings: a.nAccepted,
    rejected_readings: a.nRejected,
    total_readings: a.nTotal,
    acceptance_pct: a.acceptancePct,
    mean: a.mean,
    median: a.median,
    min: a.min,
    max: a.max,
    sd: a.sd,
    range: a.range,
    independent_windows: a.nIndependentAccepted,
    overlap_factor: a.overlapFactor,
    standard_error: a.standardError,
    median_quality_score: a.medianQuality,
    first_accepted_utc: a.firstAcceptedUtc,
    last_accepted_utc: a.lastAcceptedUtc,
  })
  return {
    schema: SESSION_SCHEMA,
    created_utc: input.createdUtc,
    capture_session_id: input.sessionId,
    primary_series: CONSENSUS,
    metrics: summary.metrics.map(metricBlock),
    per_estimator: summary.perAlgorithm.map(metricBlock),
    // Counts are per analysed window (consensus series); the per-estimator series
    // are listed separately so a reader cannot mistake them for extra evidence.
    windows_total: summary.primaryReadings.length,
    windows_accepted: summary.nAcceptedTotal,
    windows_rejected: summary.nRejectedTotal,
    readings_total: summary.readings.length,
    acceptance_pct: summary.acceptancePct,
    acceptance_band: summary.acceptanceBand,
    acceptance_band_note:
      'Band derived from the observed acceptance rate only. It is not a confidence score and says nothing about accuracy.',
    completion_state: summary.completion,
    result_available: summary.resultAvailable,
    density_ratio: summary.densityRatio,
    uneven_density: summary.unevenDensity,
    aggregation_config: {
      min_accepted_readings: summary.config.minAcceptedReadings,
      min_independent_windows: summary.config.minIndependentWindows,
      target_accepted_readings: summary.config.targetAcceptedReadings,
      stale_after_ms: summary.config.staleAfterMs,
      plausible_bounds: summary.config.plausible,
    },
    acquisition: {
      backend: input.capture.backend,
      algorithms: input.capture.algorithms,
      rois: input.capture.rois,
      passband_hz: [...input.capture.passbandHz],
      required_seconds: input.capture.requiredSeconds,
      camera_label: input.capture.cameraLabel,
      sampling_rate_hz: input.capture.samplingRateHz,
    },
    statistics_notes: [
      'The mean is the arithmetic mean of accepted readings only; rejected readings are counted but never averaged.',
      'Readings come from overlapping analysis windows, so independent_windows is the number of non-overlapping observations and the only basis used for the standard error.',
      'standard_error is null when fewer than three independent windows exist, rather than being estimated from overlapping samples.',
      'Averaging readings reduces random variation; it does not establish physiological accuracy and this is not a medical measurement.',
    ],
    frames_images_included: false,
    frames_uploaded: false,
  }
}

export const SESSION_SCHEMA = 'rsbvp.session-aggregate.v1'

export const SESSION_READINGS_CSV_HEADER = [
  'reading_id',
  'metric',
  'unit',
  'value',
  'algorithm',
  'roi',
  'accepted',
  'rejection_reason',
  'quality_score',
  'quality_verdict',
  'sampling_rate_hz',
  'n_samples',
  'window_start_s',
  'window_end_s',
  'session_elapsed_s',
  'window_index',
  'recorded_utc',
] as const

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = String(value)
  // Quote only when necessary; never invent a placeholder for a missing value.
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

/** One row per reading, accepted and rejected alike, so nothing is hidden. */
export function buildSessionReadingsCsv(readings: Measurement[]): string {
  const lines = [SESSION_READINGS_CSV_HEADER.join(',')]
  for (const r of readings) {
    lines.push(
      [
        r.id,
        r.metric,
        METRICS[r.metric]?.unit ?? '',
        r.value,
        r.algorithm,
        r.roi,
        r.accepted ? 'true' : 'false',
        r.finalRejectionReason,
        r.qualityScore,
        r.qualityVerdict,
        r.sampling.fsHz,
        r.sampling.nSamples,
        r.sampling.windowStartS,
        r.sampling.windowEndS,
        r.sessionElapsedS,
        r.windowIndex,
        r.recordedUtc,
      ]
        .map(csvCell)
        .join(','),
    )
  }
  return lines.join('\n')
}
