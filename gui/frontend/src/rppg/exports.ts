// Pure builders for the browser-local research export (`rsbvp.rgb-trace.v1`
// and `rsbvp.window-analysis.v1`). BrowserPulse.tsx wires these to the
// download UI; keeping them pure makes provenance requirements testable.
import { softwareBlock } from './provenance'
export const TRACE_SCHEMA = 'rsbvp.rgb-trace.v1'
export const WINDOWS_SCHEMA = 'rsbvp.window-analysis.v1'
export const ANALYSIS_CONFIG = {
  backend: 'rsbvp-browser-liveDsp',
  passband_hz: [0.7, 3.5] as const,
  required_seconds: 10,
  min_roi_coverage: 0.5,
  spectrum: 'hann-periodogram-v1',
  roi_method: 'MediaPipe Face Landmarker polygons + eye/lip/brow exclusion + RGB skin heuristic',
  algorithms: ['Green', 'POS (window projection)', 'CHROM'] as const,
} as const

const REGIONS = ['forehead', 'left_cheek', 'right_cheek'] as const
export type RegionName = typeof REGIONS[number]
type RGBish = [number, number, number] | null | undefined
export type ExportSample = { t: number; rois: Partial<Record<RegionName, RGBish>> }

export function traceCsvHeader(): string {
  return ['timestamp_s', ...REGIONS.flatMap(name => ['r', 'g', 'b'].map(c => `${name}_${c}`))].join(',')
}

export function buildTraceCsv(samples: ExportSample[]): string {
  const lines = [traceCsvHeader()]
  for (const s of samples) {
    const cells = [String(s.t), ...REGIONS.flatMap(name => {
      const v = s.rois[name]
      return v ? [String(v[0]), String(v[1]), String(v[2])] : ['', '', '']
    })]
    lines.push(cells.join(','))
  }
  return lines.join('\n')
}

type MetadataArgs = {
  createdUtc: string
  sessionId: string
  sampleCount: number
  earlierSamplesDropped: number
  traceStartTs: number | null
  traceEndTs: number | null
  acquisitionDurationS: number | null
  cameraFps: number | null
  sampleRateMedianHz: number | null
  droppedIntervalFraction: number | null
  analysisStatus: string
  analysisReason: string
  estimatesBpm: Record<string, number | null>
  validConsensusBpm: number | null
  qualityConcepts: Record<string, string> | null
  roiCoverage: Record<string, number> | null
  roiCoverageOverall: number | null
  userAgent: string
}

export function buildTraceMetadata(a: MetadataArgs) {
  return {
    schema: TRACE_SCHEMA,
    created_utc: a.createdUtc,
    capture_session_id: a.sessionId,
    software: softwareBlock(),
    sample_count: a.sampleCount,
    earlier_samples_dropped_due_to_buffer_limit: a.earlierSamplesDropped,
    trace_start_timestamp_s: a.traceStartTs,
    trace_end_timestamp_s: a.traceEndTs,
    acquisition_duration_seconds: a.acquisitionDurationS,
    camera_fps_reported: a.cameraFps,
    sample_rate_median_hz: a.sampleRateMedianHz,
    dropped_interval_fraction: a.droppedIntervalFraction,
    passband_hz: [...ANALYSIS_CONFIG.passband_hz],
    roi_method: ANALYSIS_CONFIG.roi_method,
    algorithms: [...ANALYSIS_CONFIG.algorithms],
    analysis_config: { ...ANALYSIS_CONFIG, passband_hz: [...ANALYSIS_CONFIG.passband_hz], algorithms: [...ANALYSIS_CONFIG.algorithms] },
    measurement_status: a.analysisStatus,
    measurement_reason: a.analysisReason,
    estimates_bpm: a.estimatesBpm,
    valid_consensus_bpm: a.validConsensusBpm,
    quality_concepts: a.qualityConcepts,
    roi_coverage: a.roiCoverage,
    roi_coverage_overall: a.roiCoverageOverall,
    browser: a.userAgent,
    frame_images_included: false,
    frames_uploaded: false,
    notes: 'Local exploratory signal output. Browser POS/CHROM variants are experimental; parity with Python is demonstrated on a shared synthetic fixture only.',
  }
}

type WindowRecordArgs = {
  windowIndex: number
  analyzedUtc: string
  pendingWindow: { start_s: number; end_s: number; n_samples: number } | null
  fs: number | null
  consensusBpm: number | null
  estimates: Record<string, number | null>
  qualityScore: number
  consistencyBpm: number | null
  availabilityStatus: string
  rejectionReason: string | null
  scores: { fsHz: number | null; durationS: number | null; maxGapS: number | null; peakFraction: number | null; snrDb: number | null; separationRatio: number | null; roiCoverage: Record<string, number> | null; roiCoverageOverall: number | null } | null
  concepts: Record<string, string> | null
  selectedAlgorithm: string
}

// One record per analyzed window; missing values stay null, never zero-filled.
export function buildWindowRecord(a: WindowRecordArgs) {
  return {
    window_index: a.windowIndex,
    window_start_s: a.pendingWindow?.start_s ?? null,
    window_end_s: a.pendingWindow?.end_s ?? null,
    n_samples: a.pendingWindow?.n_samples ?? null,
    analyzed_utc: a.analyzedUtc,
    software: softwareBlock(),
    backend: ANALYSIS_CONFIG.backend,
    analysis_config: { passband_hz: [...ANALYSIS_CONFIG.passband_hz], required_seconds: ANALYSIS_CONFIG.required_seconds, min_roi_coverage: ANALYSIS_CONFIG.min_roi_coverage, spectrum: ANALYSIS_CONFIG.spectrum },
    effective_sampling_rate_hz: a.fs,
    consensus_bpm: a.consensusBpm,
    per_estimator_bpm: a.estimates,
    quality_score: a.qualityScore,
    consistency_bpm: a.consistencyBpm,
    availability_status: a.availabilityStatus,
    rejection_reason: a.rejectionReason,
    spectral: a.scores ?? null,
    roi_coverage: a.scores?.roiCoverage ?? null,
    roi_coverage_overall: a.scores?.roiCoverageOverall ?? null,
    quality_concepts: a.concepts,
    selected_display_algorithm: a.selectedAlgorithm,
  }
}

export function buildWindowsExport(windowRecords: Array<Record<string, unknown>>, droppedWindows: number, createdUtc: string, sessionId: string) {
  return {
    schema: WINDOWS_SCHEMA,
    created_utc: createdUtc,
    capture_session_id: sessionId,
    software: softwareBlock(),
    window_count: windowRecords.length,
    dropped_windows_due_to_buffer_limit: droppedWindows,
    window_records: windowRecords,
    frames_images_included: false,
    frames_uploaded: false,
    notes: 'One record per analyzed window; availability_status is the composite verdict; rejection_reason repeats it for convenience. See docs/EXPORT_SCHEMA.md.',
  }
}
